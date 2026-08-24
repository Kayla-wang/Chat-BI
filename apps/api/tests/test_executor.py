"""执行器的四条路径与注册表清理（P3b 设计 §1、§4、§10）。

假驱动只实现 execute 与 cancel——缺 probe / reflect 是**故意**的：执行器若调了它不该调的
方法会以 AttributeError 暴露（与 P2b /test、P2c /schema 的假驱动同形）。
"""

import asyncio
import threading
import uuid

import pytest
from chatbi.execution.executor import execute_approved

from chatbi.datasources.drivers.base import (
    ColumnSchema,
    ConnectionFailed,
    ConnectionInfo,
    QueryCancelled,
    QueryFailed,
    QueryHandle,
    QueryResult,
    QueryTimeout,
)
from chatbi.execution import registry


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def _info() -> ConnectionInfo:
    return ConnectionInfo(kind="fake", host="h", port=1, database="d", username="u", password="p")


_RESULT = QueryResult(
    columns=(ColumnSchema(name="n", data_type="integer", is_numeric=True),),
    rows=((1,),),
    row_count=1,
    truncated=False,
)


class _FakeDriver:
    """四种行为：正常返回、抛超时、抛失败、**阻塞直到被 cancel**。

    第四种是取消路径的关键——它必须真的在线程里阻塞，否则测不到「to_thread 还没返回时取消
    进来了」这个时序。用 threading.Event 而不是 sleep：sleep 会让测试变慢且时序不确定。
    """

    kind = "fake"

    def __init__(self, *, raises: type[Exception] | None = None, block: bool = False) -> None:
        self._raises = raises
        self._block = block
        self._released = threading.Event()
        self.started = threading.Event()
        self.cancelled: list[str] = []
        self.executed: list[str] = []

    def execute(self, info, sql, *, timeout_seconds, max_rows, on_start=None):
        self.executed.append(sql)
        if self._raises is ConnectionFailed:
            # 连不上时 on_start **不会**被调用（P2b 的驱动在 _connect 阶段就抛了）。
            # 这条路径要验的正是「还没 register 就失败」时 finally 里的 unregister 也安全。
            raise ConnectionFailed()
        if on_start is not None:
            on_start(QueryHandle(token="tok-1"))
        self.started.set()
        if self._raises is not None:
            raise self._raises("boom")
        if self._block:
            self._released.wait(timeout=10)
            raise QueryCancelled("查询已取消")
        return _RESULT

    def cancel(self, info, handle) -> None:
        self.cancelled.append(handle.token)
        self._released.set()


@pytest.mark.asyncio
async def test_a_successful_execution_returns_the_result() -> None:
    driver = _FakeDriver()

    result = await execute_approved(
        driver,
        _info(),
        run_id=uuid.uuid4(),
        effective_sql="select 1",
        timeout_seconds=60,
        max_rows=1000,
    )

    assert result is _RESULT
    assert driver.executed == ["select 1"]


@pytest.mark.asyncio
async def test_the_registry_is_cleared_after_a_successful_execution() -> None:
    """注册表在 on_start 回调里登记（那是 QueryHandle 唯一的来源），在 finally 里清。"""
    run_id = uuid.uuid4()

    await execute_approved(
        _FakeDriver(),
        _info(),
        run_id=run_id,
        effective_sql="select 1",
        timeout_seconds=60,
        max_rows=1000,
    )

    assert registry.is_running(run_id) is False, "执行结束后注册表必须清干净"


@pytest.mark.parametrize("raises", [QueryTimeout, QueryFailed, ConnectionFailed, QueryCancelled])
@pytest.mark.asyncio
async def test_driver_exceptions_propagate(raises) -> None:
    """执行器**不翻译异常**——P2b 的四个异常直接往上抛，由 p3b2 的流映射成错误码。

    在这里翻译会让执行器同时认识 HTTP 错误码，而它是领域层。
    """
    with pytest.raises(raises):
        await execute_approved(
            _FakeDriver(raises=raises),
            _info(),
            run_id=uuid.uuid4(),
            effective_sql="select 1",
            timeout_seconds=60,
            max_rows=1000,
        )


@pytest.mark.parametrize("raises", [QueryTimeout, QueryFailed, ConnectionFailed, QueryCancelled])
@pytest.mark.asyncio
async def test_the_registry_is_cleared_on_every_failure_path(raises) -> None:
    """**`unregister` 必须在 finally 里**（设计 §1.4）。

    留下陈旧的 handle 会让后续的 cancel 掐掉**别人的**查询——Postgres 的 backend pid 会被
    复用。四种异常各验一次，因为 ConnectionFailed 那条**在 register 之前就抛了**（还没拿到
    handle），它验的是「unregister 对未登记的 run 也安全」。
    """
    run_id = uuid.uuid4()
    with pytest.raises(raises):
        await execute_approved(
            _FakeDriver(raises=raises),
            _info(),
            run_id=run_id,
            effective_sql="select 1",
            timeout_seconds=60,
            max_rows=1000,
        )

    assert registry.is_running(run_id) is False


@pytest.mark.asyncio
async def test_a_blocked_execution_can_be_cancelled_through_the_registry() -> None:
    """**取消路径的完整时序**：执行器在线程里阻塞 → 注册表里有它 → 掐掉 → 驱动抛
    QueryCancelled → await 处抛出来。

    这条证明的是「注册表登记发生在语句下发之前」——若 register 在 execute 返回之后才做，
    取消时会找不到这条 run。
    """
    driver = _FakeDriver(block=True)
    run_id = uuid.uuid4()

    task = asyncio.create_task(
        execute_approved(
            driver,
            _info(),
            run_id=run_id,
            effective_sql="select pg_sleep(30)",
            timeout_seconds=60,
            max_rows=1000,
        )
    )
    await asyncio.to_thread(driver.started.wait, 5)
    await asyncio.sleep(0.05)  # 让 on_start 的登记落地

    assert registry.is_running(run_id) is True

    # 直接用注册表里的 driver.cancel，不经过 cancel_run（那条在 Task 1 测过，且它要写 DB，
    # 本条测试不需要一个真的 run 行）
    # 直接读私有字典是有意的：这条测的是登记时序，不是封装
    running = registry._RUNNING[run_id]
    running.driver.cancel(running.info, running.handle)

    with pytest.raises(QueryCancelled):
        await task
    assert driver.cancelled == ["tok-1"]
    assert registry.is_running(run_id) is False
