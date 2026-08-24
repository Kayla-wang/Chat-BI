"""执行器对真 Postgres 的验收（设计 §11.2）。**本份的退出标准。**

假驱动能证明「执行器调了 driver.cancel」，但证明不了**库侧的查询真的死了**。而后者
才是上游 spec §4.3 闸 4 的承诺（「私有化部署里一条跑飞的查询能拖垮用户的生产库」）。

用本机原生 Postgres（TEST_DATABASE_URL 指的那个库）。**不 skip**：这不是需要 Docker 的
契约测。
"""

import asyncio
import os
import time
import uuid

import psycopg
import pytest

from chatbi.datasources.drivers.base import ConnectionInfo, QueryTimeout
from chatbi.datasources.registry import get_driver
from chatbi.execution import registry
from chatbi.execution.executor import execute_approved

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


@pytest.fixture
def pg_info(_test_env: None) -> ConnectionInfo:
    """从 TEST_DATABASE_URL 拼一个 ConnectionInfo。

    用 TEST_DATABASE_URL 而不是 CHATBI_TEST_PG_DSN：后者是契约测用的，允许缺失；
    前者是应用库，外层 conftest 保证它存在（缺了就 pytest.fail，spec §5.1）。
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(os.environ["TEST_DATABASE_URL"].replace("postgresql+psycopg", "postgresql"))
    return ConnectionInfo(
        kind="postgres",
        host=parsed.hostname,
        port=parsed.port,
        database=parsed.path.lstrip("/"),
        username=unquote(parsed.username or ""),
        password=unquote(parsed.password) if parsed.password else None,
    )


def _active_sleep_count(info: ConnectionInfo, pid: int) -> int:
    """在**另一条连接**上问：那个 backend 还在跑 pg_sleep 吗？

    必须另开连接——被取消的那条正被查询占住。这是「真取消」唯一的直接证据：
    流结束了不算，因为 task.cancel() 单独就能让流结束而查询继续跑（设计 §1.1）。
    """
    dsn = f"postgresql://{info.username}:{info.password}@{info.host}:{info.port}/{info.database}"
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "select count(*) from pg_stat_activity "
            "where pid = %s and state = 'active' and query like %s",
            (pid, "%pg_sleep%"),
        ).fetchone()
    return row[0]


async def test_a_real_query_runs(pg_info) -> None:
    """先证明这条路是通的，否则下面两条的红没法区分「取消生效」与「根本连不上」。"""
    result = await execute_approved(
        get_driver("postgres"),
        pg_info,
        run_id=uuid.uuid4(),
        effective_sql="select count(*) from demo_sales.orders",
        timeout_seconds=30,
        max_rows=1000,
    )

    assert result.row_count == 1
    assert result.rows[0][0] > 0  # demo_sales 有 240 行订单（P2b 灌的）


async def test_the_database_side_timeout_really_fires(pg_info) -> None:
    """**真超时**。闸 4 只靠库侧机制（设计 §3）。

    断言总耗时 < 8 秒才是关键：它证明**是库侧的 statement_timeout 掐了它**，而不是
    等 pg_sleep(30) 自己跑完。只断言「抛了 QueryTimeout」的话，一个「等 30 秒然后
    抛超时」的实现也能通过。
    """
    started = time.monotonic()

    with pytest.raises(QueryTimeout):
        await execute_approved(
            get_driver("postgres"),
            pg_info,
            run_id=uuid.uuid4(),
            effective_sql="select pg_sleep(30)",
            timeout_seconds=2,
            max_rows=10,
        )

    elapsed = time.monotonic() - started
    assert elapsed < 8, f"耗时 {elapsed:.1f}s——库侧超时没生效，是等查询自己跑完的"


async def test_cancelling_really_kills_the_backend_query(pg_info, db_session) -> None:
    """**真取消——本份最重要的一条。**

    只断言「流以 QueryCancelled 结束」证明不了取消：task.cancel() 单独就能让 await 处
    抛异常，而查询还在库上跑（设计 §1.1 的实测）。所以这里去 pg_stat_activity 里看。

    时序：起执行 → 等注册表登记（那时语句已下发）→ 确认库里**有**这条 pg_sleep →
    cancel_run() → 确认库里**没有**了。
    """
    run_id = uuid.uuid4()
    task = asyncio.create_task(
        execute_approved(
            get_driver("postgres"),
            pg_info,
            run_id=run_id,
            effective_sql="select pg_sleep(30)",
            timeout_seconds=60,
            max_rows=10,
        )
    )

    for _ in range(100):  # 等 on_start 登记，最多 5 秒
        if registry.is_running(run_id):
            break
        await asyncio.sleep(0.05)
    assert registry.is_running(run_id), "on_start 没登记——取消能力没有入口"

    # 直接读私有字典是有意的：要的是 backend pid，而那是「真取消」唯一的直接证据来源
    pid = int(registry._RUNNING[run_id].handle.token)
    await asyncio.sleep(0.5)  # 让语句真的开始跑
    assert await asyncio.to_thread(_active_sleep_count, pg_info, pid) == 1, (
        "取消前库里就没有这条 pg_sleep——这条测试证明不了任何事，先查环境"
    )

    assert await asyncio.to_thread(registry.cancel_run, db_session, run_id) is True

    # **经 cancel_run 取消时 await 处抛的是 CancelledError，不是 QueryCancelled。**
    # cancel_run 的第 2 步 task.cancel() 与第 1 步之间没有 await，所以外层 task 必然以
    # CancelledError 恢复（_fut_waiter.cancel() 或 _must_cancel 两条路都是），驱动线程稍后
    # 抛的 QueryCancelled 到不了这里。这不是竞态，是确定的——task.cancel() 总是赢。
    # 假驱动那条（test_executor.py）看到的是 QueryCancelled，因为它**绕过 cancel_run**
    # 直接调 driver.cancel，没有第 2 步。
    # p3b2 的执行流因此两个都要兜：CancelledError 走取消路径（点了 DELETE 或客户端断开），
    # QueryCancelled 走「查询被别人在库上掐了」那条。
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.3)  # 给 backend 一点时间退出
    assert await asyncio.to_thread(_active_sleep_count, pg_info, pid) == 0, (
        "**查询还在库上跑**——只关了流没掐库侧，这是 spec §4.3 点名的错误"
    )
