"""进程内运行注册表与 cancel_run()（P3b 设计 §1）。

cancel_run() 是**唯一**的取消入口。p3b2 的两个触发器都只调它，所以这个文件的覆盖决定了
「取消」这件事的可信度——其中一个触发器（客户端断开）无法用 TestClient 验（设计 §11.3），
它那一侧只剩「调了这个函数」一行代码。
"""

import asyncio
import uuid

import pytest
import sqlalchemy as sa

from chatbi.datasources.drivers.base import ConnectionInfo, QueryHandle
from chatbi.db.models import Conversation, Run, RunEvent
from chatbi.execution import registry


@pytest.fixture(autouse=True)
def _clean_registry():
    """每条测试跑在干净的注册表上，且**跑完清干净**。

    它是模块级状态——不清的话一条测试的残留会让下一条看到一个不存在的 run 在跑，而那种
    失败极难定位（测试单独跑绿、一起跑红）。
    """
    registry.clear()
    yield
    registry.clear()


class _FakeDriver:
    """只实现 cancel——cancel_run() 只调它。缺 execute/probe/reflect 是**故意**的：若
    cancel_run 调了它不该调的方法会以 AttributeError 暴露。
    """

    kind = "fake"

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def cancel(self, info: ConnectionInfo, handle: QueryHandle) -> None:
        self.cancelled.append(handle.token)


def _info() -> ConnectionInfo:
    return ConnectionInfo(kind="fake", host="h", port=1, database="d", username="u", password="p")


@pytest.fixture
def run(db_session, make_user, make_datasource) -> Run:
    user, datasource = make_user(), make_datasource()
    conversation = Conversation(
        id=uuid.uuid4(), user_id=user.id, datasource_id=datasource.id, title="t"
    )
    db_session.add(conversation)
    db_session.flush()
    record = Run(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        user_id=user.id,
        datasource_id=datasource.id,
        question="q",
        status="running",  # 只有 running 的 run 会被取消
    )
    db_session.add(record)
    db_session.flush()
    return record


async def _idle_task() -> None:
    """一个能被 cancel 的 task，替代真的执行 task。"""
    await asyncio.sleep(60)


def test_an_unregistered_run_is_not_running() -> None:
    assert registry.is_running(uuid.uuid4()) is False


def test_cancel_run_returns_false_for_an_unknown_run(db_session) -> None:
    """不在注册表里 = 没有查询在跑。**不抛异常**：DELETE 端点会拿这个返回值决定响应，
    而「取消一个已经结束的查询」是幂等的正常情况，不是错误。

    也覆盖设计 §3 末那个连接阶段的 10 秒窗口：那时还没有 QueryHandle，注册表里没有这条
    run，取消返回 False。
    """
    assert registry.cancel_run(db_session, uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_cancel_run_cancels_the_driver_first_then_the_task(db_session, run) -> None:
    """**顺序是有意的**（设计 §1.2）：先掐库侧、再关流。

    反过来的话 task.cancel() 之后生成器可能已经退出，而退出路径上如果没兜住
    CancelledError 就走不到 driver.cancel()——查询就漏了。
    """
    driver = _FakeDriver()
    task = asyncio.create_task(_idle_task())
    registry.register(
        run.id, handle=QueryHandle(token="12345"), task=task, info=_info(), driver=driver
    )

    assert registry.cancel_run(db_session, run.id) is True

    assert driver.cancelled == ["12345"], "driver.cancel 没被调——只关流是 spec §4.3 点名的错误"
    assert task.cancelled() or task.cancelling() > 0, "task 没被 cancel"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancel_run_records_the_cancellation(db_session, run) -> None:
    """状态与事件必须落库并**显式 commit**（设计 §2）：cancel_run 可能跑在一个被取消的
    请求上下文里，那时 get_db 会回滚。
    """
    task = asyncio.create_task(_idle_task())
    registry.register(
        run.id, handle=QueryHandle(token="1"), task=task, info=_info(), driver=_FakeDriver()
    )

    registry.cancel_run(db_session, run.id)
    task.cancel()

    db_session.expire_all()  # 不能靠 identity map 验 DB 侧的事实
    refreshed = db_session.get(Run, run.id)
    assert refreshed.status == "cancelled"
    assert refreshed.error_code == "QUERY_CANCELLED"
    events = db_session.scalars(sa.select(RunEvent).where(RunEvent.run_id == run.id)).all()
    assert [e.status for e in events] == ["cancelled"]


@pytest.mark.asyncio
async def test_cancel_run_is_idempotent(db_session, run) -> None:
    """第二次调返回 False：第一次已经 unregister 了。

    幂等性是必需的——客户端断开与 DELETE 可能几乎同时到达，两者都调 cancel_run。
    """
    task = asyncio.create_task(_idle_task())
    registry.register(
        run.id, handle=QueryHandle(token="1"), task=task, info=_info(), driver=_FakeDriver()
    )

    assert registry.cancel_run(db_session, run.id) is True
    assert registry.cancel_run(db_session, run.id) is False
    task.cancel()


def test_unregister_removes_the_entry(db_session) -> None:
    run_id = uuid.uuid4()
    registry.register(
        run_id, handle=QueryHandle(token="1"), task=None, info=_info(), driver=_FakeDriver()
    )
    assert registry.is_running(run_id) is True

    registry.unregister(run_id)

    assert registry.is_running(run_id) is False


def test_unregister_is_safe_for_an_unknown_run() -> None:
    """执行器在 finally 里调它，而 finally 也会在「还没 register 就失败了」时跑到（比如
    连接阶段就抛了 ConnectionFailed）。抛 KeyError 会把真正的异常盖掉。
    """
    registry.unregister(uuid.uuid4())  # 不该抛
