"""三个驱动共用的契约用例（spec §5.1）。

覆盖：连通性、schema 反射、类型映射、语句超时、真取消、行截断。
新增驱动**不改本文件**——只往 conftest 的 CONTRACT_KINDS 与 DIALECTS 各加一项。
如果某个驱动需要在这里加 if 分支，说明协议没抽对，回去改协议。
"""

import threading
from dataclasses import replace

import pytest

from chatbi.datasources.drivers.base import (
    ConnectionFailed,
    QueryCancelled,
    QueryFailed,
    QueryHandle,
    QueryTimeout,
)


def test_probe_reports_reachable_and_a_version(driver_target) -> None:
    driver, info, _ = driver_target

    result = driver.probe(info)

    assert result.reachable is True
    assert result.server_version  # 非空——排障时要知道对面是什么版本


def test_probe_detects_a_writable_account(driver_target) -> None:
    """契约测用的账号是库主，所以 can_write 必须是 True。

    这条不是「希望账号可写」，而是钉住探测**真的在探**：一个恒返回 False 的实现
    在只读账号上看起来完全正确，只有拿一个已知可写的账号才能证伪它。
    spec §4.3 闸 1 的告警完全依赖这个判断，它错了用户会以为自己配了只读账号。
    """
    driver, info, _ = driver_target

    assert driver.probe(info).can_write is True


def test_probe_does_not_write_anything(driver_target, seeded_table) -> None:
    """探测必须是只读的——不能真去建一张表试试。

    这种实现会在用户的生产库里攒垃圾表，而且在只读账号上会把「探测失败」
    误报成「账号不可写」。
    """
    driver, info, _ = driver_target
    count_sql = f"select count(*) from {seeded_table}"
    before = driver.execute(info, count_sql, timeout_seconds=30, max_rows=10)

    driver.probe(info)

    after = driver.execute(info, count_sql, timeout_seconds=30, max_rows=10)
    assert before.rows == after.rows


def test_wrong_password_raises_connection_failed(driver_target) -> None:
    """并且异常里不能带地址、端口、密码（spec §4.4）。"""
    driver, info, _ = driver_target
    if info.password is None:
        pytest.skip("该 DSN 未带密码（trust 认证），无法构造「密码错误」")
    bad = replace(info, password="definitely-not-the-password")

    with pytest.raises(ConnectionFailed) as exc_info:
        driver.probe(bad)

    text = str(exc_info.value)
    assert info.host not in text
    assert str(info.port) not in text
    assert "definitely-not-the-password" not in text


def test_reflect_finds_the_seeded_table(driver_target, seeded_table) -> None:
    driver, info, _ = driver_target

    snapshot = driver.reflect(info)

    assert seeded_table in {table.name for table in snapshot.tables}


def test_reflect_describes_the_seeded_columns(driver_target, seeded_table) -> None:
    """列名、可空性、数值性三项都要对。

    is_numeric 决定前端能不能给这列画柱状图（spec §2.3 的 result 事件），
    错了表现是「图表选项里少了一列」，很难追到驱动这一层。
    """
    driver, info, _ = driver_target

    table = next(t for t in driver.reflect(info).tables if t.name == seeded_table)
    columns = {column.name: column for column in table.columns}

    assert set(columns) == {"id", "label", "amount"}
    assert columns["id"].is_nullable is False
    assert columns["label"].is_nullable is True
    assert columns["id"].is_numeric is True
    assert columns["amount"].is_numeric is True
    assert columns["label"].is_numeric is False
    assert columns["id"].data_type  # 原始类型名原样保留，P2c 的注释 UI 要显示


def test_execute_returns_columns_and_rows(driver_target, seeded_table) -> None:
    driver, info, _ = driver_target

    result = driver.execute(
        info, f"select id, label, amount from {seeded_table}", timeout_seconds=30, max_rows=100
    )

    assert [column.name for column in result.columns] == ["id", "label", "amount"]
    assert result.row_count == 1
    assert result.truncated is False
    assert result.rows[0][0] == 1
    assert result.rows[0][1] == "甲"  # 非 ASCII 往返：编码配错时这里先炸


def test_execute_truncates_at_max_rows(driver_target) -> None:
    driver, info, dialect = driver_target

    result = driver.execute(info, dialect.rows_sql.format(n=50), timeout_seconds=30, max_rows=10)

    assert len(result.rows) == 10
    assert result.row_count == 10
    assert result.truncated is True


def test_execute_does_not_report_truncation_when_the_result_fits_exactly(driver_target) -> None:
    """结果恰好等于上限时不能报截断。只有「多取一行」的实现过得了这条。"""
    driver, info, dialect = driver_target

    result = driver.execute(info, dialect.rows_sql.format(n=10), timeout_seconds=30, max_rows=10)

    assert len(result.rows) == 10
    assert result.truncated is False


def test_execute_raises_query_failed_on_a_bad_statement(driver_target) -> None:
    driver, info, _ = driver_target

    with pytest.raises(QueryFailed):
        driver.execute(
            info, "select * from a_table_that_does_not_exist_x9", timeout_seconds=30, max_rows=10
        )


def test_execute_raises_query_timeout(driver_target) -> None:
    """超时必须由**库侧**生效（statement_timeout / MAX_EXECUTION_TIME /
    max_execution_time），不是客户端等够了就断开连接——只断开的话查询还在对面
    继续跑，而 spec §4.3 闸 4 要的正是「别把用户的生产库拖垮」。
    """
    driver, info, dialect = driver_target

    with pytest.raises(QueryTimeout):
        driver.execute(info, dialect.sleep_sql, timeout_seconds=1, max_rows=10)


def test_cancel_stops_a_running_query(driver_target) -> None:
    """spec §2.3：只关流不取消后端查询是错的。

    在线程里跑一条长语句，从 on_start 拿到 handle，主线程调 cancel。
    """
    driver, info, dialect = driver_target
    handles: list[QueryHandle] = []
    started = threading.Event()
    outcome: list[BaseException | None] = []

    def run() -> None:
        def on_start(handle: QueryHandle) -> None:
            handles.append(handle)
            started.set()

        try:
            driver.execute(
                info,
                dialect.sleep_sql,
                timeout_seconds=60,
                max_rows=10,
                on_start=on_start,
            )
            outcome.append(None)
        except BaseException as exc:  # noqa: BLE001 —— 要看清到底抛了什么
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    assert started.wait(timeout=10), "on_start 未在 10s 内被调用——取消能力没有入口"

    driver.cancel(info, handles[0])
    worker.join(timeout=20)

    assert not worker.is_alive(), "cancel 之后查询仍在跑"
    assert isinstance(outcome[0], QueryCancelled), f"期望 QueryCancelled，实际 {outcome[0]!r}"


def test_cancel_is_idempotent_after_the_query_finished(driver_target, seeded_table) -> None:
    """查询早已结束时再取消必须静默返回。

    执行器在「客户端断开」时会无条件调一次 cancel，那一刻查询可能刚好跑完；
    这里抛异常会把一次正常完成变成一条错误日志，还会盖掉真正的结果。
    """
    driver, info, _ = driver_target
    handles: list[QueryHandle] = []

    driver.execute(
        info,
        f"select 1 from {seeded_table}",
        timeout_seconds=30,
        max_rows=10,
        on_start=handles.append,
    )

    driver.cancel(info, handles[0])  # 不抛异常就算通过
