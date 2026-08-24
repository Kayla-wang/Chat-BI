"""执行一条**已被 guard 批准**的语句（上游 spec §2.3、§4.3 闸 4）。

**这是安全红线代码**，保持在 200 行以内、只做这一件事（spec §1.4，与 guard/validator.py
并列点名）。不 import fastapi：取消与执行要能脱离 HTTP 测。

这里不做任何 SQL 检查：闸 2 与闸 3 在 guard，重复校验只会让人以为执行器也是一道防线，
从而放松那一道（与 P2b 驱动 execute() 的文件头同一条约定）。

**不加 asyncio 层的超时兜底**（设计 §3）。闸 4 的超时只靠驱动的库侧机制
（statement_timeout / MAX_EXECUTION_TIME / max_execution_time，P2b 三个驱动都实现了）。
理由：asyncio.wait_for 超时后 cancel 的是 to_thread task，而**实测 to_thread 的 task
被 cancel 后线程会继续跑到底**——加了之后的行为是「流提前结束、查询继续跑」，正是闸 4
要防的事。一层停不住东西的超时比没有超时更糟，因为它让人以为有保护。库侧超时失效是
驱动层的 bug，该由契约测（P2b 的 test_execute_raises_query_timeout）抓。
"""

import asyncio
import uuid

from chatbi.datasources.drivers.base import (
    ConnectionInfo,
    Driver,
    QueryHandle,
    QueryResult,
)
from chatbi.execution import registry


async def execute_approved(
    driver: Driver,
    info: ConnectionInfo,
    *,
    run_id: uuid.UUID,
    effective_sql: str,
    timeout_seconds: int,
    max_rows: int,
) -> QueryResult:
    """跑一条已批准的语句，并让它在执行期间可被取消。

    **驱动调用必须在 to_thread 里**（设计 §4）：它可能几十秒，而阻塞事件循环会让同一个
    进程里所有其他请求——**包括 DELETE 取消**——全部卡死。那会让取消功能在最需要它的
    时候不可用。

    异常**不翻译**：P2b 的 QueryTimeout / QueryCancelled / QueryFailed / ConnectionFailed
    直接往上抛，由 p3b2 的执行流映射成错误码。在这里翻译会让执行器同时认识 HTTP 层的
    错误码，而它是领域层。

    注册表在 on_start 回调里登记——那是 QueryHandle 唯一的来源，且它在语句真正下发
    **之前**触发（P2b 的协议明写「这是取消能力的唯一入口」）。所以从语句下发的那一刻起
    这条查询就是可取消的，没有窗口。
    """
    current = asyncio.current_task()

    def on_start(handle: QueryHandle) -> None:
        """在**驱动的线程里**被调用。

        registry 是一个普通 dict，CPython 下单个赋值是原子的，且这里只写一个键——
        不需要锁。若将来注册表变复杂（比如要维护计数），这一条就要重新想。
        """
        registry.register(run_id, handle=handle, task=current, info=info, driver=driver)

    try:
        return await asyncio.to_thread(
            driver.execute,
            info,
            effective_sql,
            timeout_seconds=timeout_seconds,
            max_rows=max_rows,
            on_start=on_start,
        )
    finally:
        # **必须在 finally**（设计 §1.4）：正常结束、失败、被取消都要清。留下陈旧的
        # handle 会让后续的 cancel 掐掉别人的查询（backend pid 会被复用）。
        # 对未登记的 run 也安全——ConnectionFailed 会在 on_start 之前就抛。
        registry.unregister(run_id)
