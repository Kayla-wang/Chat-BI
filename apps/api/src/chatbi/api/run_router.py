"""/api/runs/{run_id}/execute 的两个端点（上游 spec §2.3）。

**这个文件只做鉴权、状态检查、与响应包装**。事件序列的编排在 api/run_stream.py——它长
到需要单独一个文件（计划的规模自查预告了这一点），而两者的关注点确实不同：这里是
HTTP 语义（409 该在流之前、DELETE 恒 204），那里是流的内容与四个提交点。

**取消动作一律经 registry.cancel_run**，本文件不自己 cancel 任何东西：那样 cancel_run
本身能被单独测，而那是必需的——另一个触发器（客户端断开）在 run_stream 里，走的是同
一个函数。
"""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from chatbi.api.run_stream import stream
from chatbi.auth.schemas import ErrorResponse
from chatbi.db.base import get_db
from chatbi.db.models import Run
from chatbi.errors import RUN_NOT_EXECUTABLE, ApiError
from chatbi.execution.registry import cancel_run
from chatbi.guard.deps import policy_resolver_for
from chatbi.guard.policy import PolicyResolver
from chatbi.runs.deps import require_run
from chatbi.runs.schemas import ExecuteRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])

_Db = Annotated[Session, Depends(get_db)]
_Target = Annotated[Run, Depends(require_run)]
_Resolver = Annotated[PolicyResolver, Depends(policy_resolver_for)]

_TARGET = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}
_CONFLICT = {409: {"model": ErrorResponse}}


@router.post(
    "/{run_id}/execute",
    responses=_TARGET | _CONFLICT,
    response_class=StreamingResponse,
)
def execute(
    payload: ExecuteRequest,
    run: _Target,
    db: _Db,
    resolver: _Resolver,
) -> StreamingResponse:
    """执行流（上游 spec §2.3）。

    **状态检查在流开始之前**：一个 run 恰好执行一次（设计 §5），而 409 是 HTTP 层的
    答案——一旦开了 SSE 流就只能在流里发 error，那对「你点重复了」这种情况是很差的
    体验（前端要解析流才知道请求没被接受）。

    流里还会再判一次（mark_running 的条件 UPDATE），那是**并发竞态**的兜底：两个请求
    同时通过这里的检查时，只有一个能拿到那次 UPDATE。

    **端点是 `def` 而不是 `async def`**：它自己不 await 任何东西，只构造
    StreamingResponse。生成器仍然在事件循环上跑，所以设计 §4 的并发边界不变。

    `X-Accel-Buffering: no` 与 `Cache-Control: no-cache` 是 SSE 的实践必需：前者让 nginx
    不缓冲这条流（缓冲会让事件攒够一批才吐给浏览器，心跳就失去意义），后者防中间层缓存。
    """
    if run.status != "drafted":
        raise ApiError(*RUN_NOT_EXECUTABLE)

    return StreamingResponse(
        stream(run=run, db=db, resolver=resolver, sql=payload.sql),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/{run_id}/execute", status_code=204, responses=_TARGET)
async def cancel(run: _Target, db: _Db) -> Response:
    """取消一条正在跑的查询（上游 spec §2.3）。

    `to_thread` 是必需的（设计 §4）：cancel_run 内部的 driver.cancel() 要另开一条连接，
    同步调用会卡住事件循环。（run_stream 里那个断开触发点是同步调的，因为它处在一个
    已被取消的 cancel scope 里、不能再 await——见那边的注释。）

    **恒 204，不管有没有真的取消到东西。** 取消一个已经结束的查询是幂等的正常情况
    （用户点得晚了一点），不是错误。cancel_run 的返回值只进日志。
    """
    cancelled = await asyncio.to_thread(cancel_run, db, run.id)
    logger.info("取消 run %s：%s", run.id, "已取消" if cancelled else "查询已结束或未开始")
    return Response(status_code=204)
