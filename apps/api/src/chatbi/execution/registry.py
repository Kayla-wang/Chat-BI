"""正在跑的查询的进程内注册表，与取消的唯一入口。

**这张表成立的唯一前提是单进程部署。** 上游 spec §7.2 明确不做连接池、不做多进程扩展
（单机私有化部署），所以一个模块级 dict 是当前架构下正确的成本。

但它是一条**真实的架构约束**，不是实现细节：将来上多 worker（`uvicorn --workers N`）时，
DELETE 请求会有 (N-1)/N 的概率打到没有那条 run 的进程上，**取消静默失效**——用户点了
取消、界面显示已取消、而查询还在库上跑。要上多 worker 就得把这张表换成共享存储
（Redis 或一张表）并让 cancel 跨进程投递。

不 import fastapi：取消要能脱离 HTTP 测（设计 §10.3）。
"""

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from chatbi.datasources.drivers.base import ConnectionInfo, Driver, QueryHandle
from chatbi.db.models import Run
from chatbi.errors import QUERY_CANCELLED
from chatbi.runs.repository import append_event, next_seq


@dataclass(frozen=True)
class RunningQuery:
    """取消一条正在跑的查询所需的全部东西。

    driver 与 info 都要存：cancel 必须另开一条连接发出（原连接正被查询占住），所以它需要
    完整的连接信息，不只是 handle。
    """

    handle: QueryHandle
    task: asyncio.Task | None
    info: ConnectionInfo
    driver: Driver


_RUNNING: dict[uuid.UUID, RunningQuery] = {}


def register(
    run_id: uuid.UUID,
    *,
    handle: QueryHandle,
    task: asyncio.Task | None,
    info: ConnectionInfo,
    driver: Driver,
) -> None:
    """登记一条正在跑的查询。由执行器在 driver 的 on_start 回调里调用——那是 QueryHandle
    唯一的来源，且它在语句真正下发**之前**触发（P2b 的协议）。
    """
    _RUNNING[run_id] = RunningQuery(handle=handle, task=task, info=info, driver=driver)


def unregister(run_id: uuid.UUID) -> None:
    """清掉登记。**必须在 finally 里调**：正常结束、失败、被取消都要清。

    留下陈旧的 handle 会让后续的 cancel 掐掉**别人的**查询——Postgres 的 backend pid 会被
    复用，MySQL 的 connection id 也会。

    对未登记的 run 静默返回：finally 也会在「还没 register 就失败了」时跑到（例如连接阶段
    就抛了 ConnectionFailed），抛 KeyError 会把真正的异常盖掉。
    """
    _RUNNING.pop(run_id, None)


def is_running(run_id: uuid.UUID) -> bool:
    return run_id in _RUNNING


def clear() -> None:
    """只给测试用：它是模块级状态，测试之间必须隔离。"""
    _RUNNING.clear()


def cancel_run(session: Session, run_id: uuid.UUID) -> bool:
    """取消一条正在跑的查询。返回是否真的取消了。

    **这是唯一的取消入口。** DELETE 端点与客户端断开检测都只调它，自己不做任何取消
    动作——那样它本身能被直接测，而那是必需的：客户端断开那条触发器无法用 TestClient 验
    （设计 §11.3），它那一侧只剩「调了这个函数」一行代码。

    三件事，**顺序固定**（设计 §1.2）：

    1. driver.cancel() 掐库侧。**这一步不能省**——实测 asyncio.to_thread 的 task 被 cancel
       后线程会继续跑到底，所以只做第 2 步等于关掉流然后让查询继续跑在用户的生产库上，
       那是上游 spec §4.3 点名的错误。
    2. task.cancel() 让 SSE 流停止等待，不必等驱动抛异常绕回来。
    3. 写状态与事件并**显式 commit**——本函数可能跑在一个被取消的请求上下文里，那时
       get_db 会回滚（设计 §2 的实测）。

    先掐库侧再关流：反过来的话 task.cancel() 之后生成器可能已经退出，而退出路径上如果
    没兜住 CancelledError 就走不到第 1 步，查询就漏了。

    返回 False 的两种情况都不是错误，所以不抛：查询已经结束（注册表里没有），或者还在
    连接阶段（那时没有 QueryHandle，设计 §3 末）。「取消一个已结束的查询」是幂等的
    正常情况。
    """
    running = _RUNNING.pop(run_id, None)
    if running is None:
        return False

    # 1. 库侧。**同步调用**：本函数的调用方（DELETE 端点）要负责把它放进 to_thread，
    #    因为那里的事件循环不能被一次另开连接的往返卡住（设计 §4）。
    running.driver.cancel(running.info, running.handle)

    # 2. 流
    if running.task is not None:
        running.task.cancel()

    # 3. 审计
    run = session.get(Run, run_id)
    if run is not None:
        run.status = "cancelled"
        run.error_code = QUERY_CANCELLED[0]
        append_event(
            session,
            run_id=run_id,
            seq=next_seq(session, run_id),
            step="execute",
            status="cancelled",
        )
    session.commit()
    return True
