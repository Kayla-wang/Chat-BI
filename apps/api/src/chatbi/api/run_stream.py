"""执行流的事件序列（上游 spec §2.3 的八个事件）。

**这里是唯一同时认识 guard、执行器、注册表、与 run 仓储的地方。** 它做三件事：编排事件
序列、**在四个点显式提交**、把驱动异常映射成错误码。不做任何 SQL 判断（那在 guard）、
不做取消动作（那在 registry.cancel_run）、不做鉴权（那在 runs.deps.require_run）。

**四个提交点必须显式 commit**（P3b 设计 §2）：客户端断开时本生成器会被取消，那个异常
会让 get_db 回滚整个请求的事务——依赖它自动提交会让**成功的执行有审计、被取消的执行
没有审计**，而 F-304 要审计的恰恰是后者。实测过：断开真跑里那条 run 的
`[(1, validate, ok), (2, execute, cancelled)]` 两条事件，全靠显式 commit 才活下来。

**为什么在 api/ 而不是 execution/**（计划原写 `execution/stream.py`）：本模块认识
`errors.py` 的错误码元组（里面带 HTTP 状态码）与 SSE 载荷的字段名，那些都是 HTTP 层的
词汇。p3b1 的 executor 明确拒绝认识错误码（「在这里翻译会让执行器同时认识 HTTP 层的
错误码，而它是领域层」），把这一层塞进 execution/ 会推翻那个决定。
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from chatbi.config import get_settings
from chatbi.datasources.connection import connection_info
from chatbi.datasources.drivers.base import (
    ConnectionFailed,
    Driver,
    QueryCancelled,
    QueryFailed,
    QueryResult,
    QueryTimeout,
)
from chatbi.datasources.registry import get_driver
from chatbi.db.models import Datasource, Run
from chatbi.errors import (
    CONNECTION_ERROR,
    QUERY_CANCELLED,
    QUERY_FAILED,
    QUERY_TIMEOUT,
    RUN_NOT_EXECUTABLE,
    ApiError,
)
from chatbi.execution.charts import infer_chart_spec
from chatbi.execution.executor import execute_approved
from chatbi.execution.preview import to_preview
from chatbi.execution.registry import cancel_run
from chatbi.execution.sse import sse
from chatbi.guard.policy import PolicyResolver
from chatbi.guard.validator import validate_sql
from chatbi.runs.repository import (
    append_event,
    mark_finished,
    mark_running,
    next_seq,
    save_preview,
)

logger = logging.getLogger(__name__)

# kind -> sqlglot 方言名。与 api/sql_router.py 里那张表**必须一致**——两处都显式写而
# 不是共用一个常量，是因为它们的变更理由不同（这里跟着执行流走，那里跟着编辑器校验
# 走）。若将来加了第四个 kind，两处都要改，而漏一处的表现是「校验能过但执行 500」。
_DIALECTS = {"postgres": "postgres", "mysql": "mysql", "clickhouse": "clickhouse"}

_PING_INTERVAL_SECONDS = 15


def _datasource_of(db: Session, run: Run) -> Datasource:
    """显式取数据源。

    `Run` **没有** relationship（`db` 是叶子模块，spec §1.3 规则 4），也不该有——那会让
    ORM 在属性访问时偷偷发查询。所以这里显式 get，而不是写 `run.datasource.kind`。
    """
    datasource = db.get(Datasource, run.datasource_id)
    if datasource is None:  # 外键是 RESTRICT，理论上不可能
        raise ApiError(*CONNECTION_ERROR)
    return datasource


def _emit(
    db: Session,
    run_id: uuid.UUID,
    *,
    step: str,
    status: str,
    duration_ms: int | None = None,
    detail: dict | None = None,
) -> bytes:
    """写一条 run_event 并返回它的 log 事件（上游 spec §2.3 的 log 载荷与 run_events
    的列完全一致——它们是同一份数据的两面，设计 §7.5）。

    **一个写入点、一个格式。** 分开写会让「日志 Tab 看到的」与「回放看到的」有可能不
    一致，而 spec §3.5 说日志 Tab 就是渲染 run_events。

    seq 用 next_seq() 而不是自己数：问答流（P3c）会先写 understand / generate 两条，
    执行流必须接在后面（p3b1 的交接清单第 3 条）。

    detail **不放结果行内容**（spec §4.6），只放 row_count 之类的标量。
    """
    append_event(
        db,
        run_id=run_id,
        seq=next_seq(db, run_id),
        step=step,
        status=status,
        duration_ms=duration_ms,
        detail=detail,
    )
    payload: dict = {"step": step, "status": status}
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if detail is not None:
        payload["detail"] = detail
    return sse("log", payload)


def _finish_with_error(db: Session, run_id: uuid.UUID, code_tuple, duration_ms: int) -> bytes:
    """失败路径的收尾：写事件 + 终态 + **显式 commit**（提交点 4）。

    返回那条 log 事件的字节，调用方 yield 它。**这个 commit 是本模块最重要的一行**：
    客户端在看到 error 事件后立刻断开时，没提交的这一段会被 get_db 回滚——而 F-304 要
    审计的正是失败与被取消的执行（设计 §2.2）。
    """
    log = _emit(db, run_id, step="execute", status="failed", duration_ms=duration_ms)
    mark_finished(db, run_id, status="failed", error_code=code_tuple[0], duration_ms=duration_ms)
    db.commit()  # ← 提交点 4
    return log


async def stream(
    *, run: Run, db: Session, resolver: PolicyResolver, sql: str
) -> AsyncIterator[bytes]:
    """跑完一条 run 并把八个事件吐出去。**每条流都以 done 结尾**，包括失败与被拒。

    四个提交点都标了序号。少任何一个，那一段的审计会在客户端断开时被 get_db 回滚掉。
    """
    settings = get_settings()
    datasource = _datasource_of(db, run)
    started = time.monotonic()

    # ---- 闸 2 + 闸 3 ----
    verdict = validate_sql(
        sql,
        dialect=_DIALECTS[datasource.kind],
        max_rows=settings.max_result_rows,
        policy=resolver.resolve(user_id=run.user_id, datasource_id=run.datasource_id),
    )
    elapsed = int((time.monotonic() - started) * 1000)

    if not verdict.ok:
        # spec §2.3：「ok=false 时流即结束，run 置 blocked」。**不发 error 事件**——
        # 判定失败是这条流的正常出口，不是异常（与 P3a 的 /sql/validate 返回 200 同理）
        yield sse("validate", {"ok": False, "code": verdict.code, "reason": verdict.reason})
        log = _emit(db, run.id, step="validate", status="blocked", duration_ms=elapsed)
        mark_finished(db, run.id, status="blocked", error_code=verdict.code)
        db.commit()  # ← 提交点 1（被拒路径）
        yield log
        yield sse("done", {"status": "blocked", "duration_ms": elapsed, "row_count": None})
        return

    yield sse("validate", {"ok": True})
    log = _emit(db, run.id, step="validate", status="ok", duration_ms=elapsed)
    db.commit()  # ← 提交点 1
    yield log

    # ---- drafted -> running ----
    if not mark_running(db, run.id, final_sql=sql, effective_sql=verdict.effective_sql or sql):
        # 并发竞态：两个请求同时通过了端点里的状态检查，只有一个拿到那次条件 UPDATE。
        # 流已经开了，所以这里只能发 error（端点层的 409 走不到了）
        db.commit()
        yield sse("error", {"code": RUN_NOT_EXECUTABLE[0], "message": RUN_NOT_EXECUTABLE[1]})
        yield sse("done", {"status": run.status, "duration_ms": elapsed, "row_count": None})
        return
    db.commit()  # ← 提交点 2
    yield sse(
        "execute.started",
        {"dialect": datasource.kind, "effective_sql": verdict.effective_sql},
    )

    # ---- 执行 + 心跳 + 断开检测 ----
    driver: Driver = get_driver(datasource.kind)
    info = connection_info(datasource)
    task = asyncio.create_task(
        execute_approved(
            driver,
            info,
            run_id=run.id,
            effective_sql=verdict.effective_sql or sql,
            timeout_seconds=settings.query_timeout_seconds,
            max_rows=settings.max_result_rows,
        )
    )

    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=_PING_INTERVAL_SECONDS)
            if task in done:
                break
            # 载荷是空的：驱动不提供进度，**不假装有进度条**（spec §2.3）
            yield sse("ping", {})
    except (asyncio.CancelledError, GeneratorExit):
        # **客户端断开的触发点就在这里**（实施期实测，见 p3b2 偏差 Task 5）。
        #
        # Starlette 的 StreamingResponse 把 body 迭代器与 listen_for_disconnect 放在一个
        # task group 里赛跑，`http.disconnect` 一到就**取消迭代器**——所以本生成器是在
        # 上面那个 await 处收到 CancelledError 的，`request.is_disconnected()` 那种轮询
        # **永远不会被执行到**（真 uvicorn 上装探针实测：只记到 wait:enter 与
        # raised:CancelledError，轮询那一行一次都没跑）。之前「TestClient 下
        # is_disconnected 恒 False」被当成 TestClient 的局限，其实那个检查在哪都不触发。
        #
        # **cancel_run 必须同步调，不能 to_thread**：我们正处在一个已被取消的 anyio
        # cancel scope 里，任何 await 会立刻再抛 CancelledError（GeneratorExit 下 await
        # 更是非法的）。代价是阻塞事件循环几毫秒（driver.cancel 要另开一条连接），
        # 换来的是查询不会继续跑在用户的生产库上——闸 4 的全部意义就在这里。
        #
        # 不吞异常：处理完原样重抛，Starlette 与 asyncio 的语义要保持。
        logger.info("客户端断开，取消 run %s", run.id)
        cancel_run(db, run.id)  # 内部自己 commit
        raise

    # ---- 结果或异常 ----
    total_ms = int((time.monotonic() - started) * 1000)
    try:
        result: QueryResult = task.result()
    except (asyncio.CancelledError, QueryCancelled):
        # cancel_run 已经写过状态与事件并 commit 过了（它是取消的唯一入口）。
        #
        # **两个异常都要兜，而正常路径抛的是 CancelledError**（p3b1 实施期实测）：
        # cancel_run 的第 2 步 task.cancel() 与第 1 步之间没有 await，所以上面那个 task
        # 必然以 CancelledError 结束，驱动线程稍后抛的 QueryCancelled 到不了这里。
        # QueryCancelled 留给「查询被别人在库上掐了」那条路（pg_cancel_backend 等），
        # 那时没人 cancel 这个 task。**注意 CancelledError 是 BaseException**，
        # `except Exception` 兜不住它——漏了它的表现是流中途死掉、连 done 都发不出去
        # （实测：响应体整条变空）。
        #
        # 这里 catch 它是安全的：本生成器自己被取消时，异常会在上面的 asyncio.wait 处
        # 抛出而不是这一行。
        yield sse("error", {"code": QUERY_CANCELLED[0], "message": QUERY_CANCELLED[1]})
        yield sse("done", {"status": "cancelled", "duration_ms": total_ms, "row_count": None})
        return
    except QueryTimeout:
        yield _finish_with_error(db, run.id, QUERY_TIMEOUT, total_ms)
        yield sse("error", {"code": QUERY_TIMEOUT[0], "message": QUERY_TIMEOUT[1]})
        yield sse("done", {"status": "failed", "duration_ms": total_ms, "row_count": None})
        return
    except QueryFailed as exc:
        # **message 带库的原始报错**——分析师要靠它改 SQL（P2b 的 QueryFailed 刻意保留
        # 了原文）。这与 spec §4.4 不冲突：那条针对连接类错误（可能含地址端口）
        yield _finish_with_error(db, run.id, QUERY_FAILED, total_ms)
        yield sse("error", {"code": QUERY_FAILED[0], "message": f"{QUERY_FAILED[1]}：{exc}"})
        yield sse("done", {"status": "failed", "duration_ms": total_ms, "row_count": None})
        return
    except ConnectionFailed:
        # 地址端口进**服务端日志**，不进响应（spec §4.4）
        logger.warning(
            "run %s 连接失败：%s:%s/%s",
            run.id,
            datasource.host,
            datasource.port,
            datasource.database,
        )
        yield _finish_with_error(db, run.id, CONNECTION_ERROR, total_ms)
        yield sse("error", {"code": CONNECTION_ERROR[0], "message": CONNECTION_ERROR[1]})
        yield sse("done", {"status": "failed", "duration_ms": total_ms, "row_count": None})
        return

    # ---- 结果、图表、收尾 ----
    columns, rows, truncated = to_preview(result, limit=settings.preview_rows)
    save_preview(db, run.id, columns=columns, rows=rows, truncated=truncated)
    yield sse(
        "result",
        {
            "columns": columns,
            "rows": rows,
            "row_count": result.row_count,
            "truncated": truncated,
        },
    )

    spec = infer_chart_spec(result.columns, result.row_count)
    yield sse(
        "chart_spec",
        {"type": spec.type, "x": spec.x, "y": list(spec.y), "reason": spec.reason},
    )

    log_execute = _emit(
        db,
        run.id,
        step="execute",
        status="ok",
        duration_ms=total_ms,
        detail={"row_count": result.row_count},  # 只记行数，不记结果行（§4.6）
    )
    log_render = _emit(db, run.id, step="render", status="ok")
    mark_finished(db, run.id, status="succeeded", row_count=result.row_count, duration_ms=total_ms)
    db.commit()  # ← 提交点 3
    yield log_execute
    yield log_render
    yield sse(
        "done",
        {"status": "succeeded", "duration_ms": total_ms, "row_count": result.row_count},
    )
