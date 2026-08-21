# Chat-BI V2-1 · P3b2 执行流 SSE 与取消端点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 p3b1 的执行能力接成两个端点，并把「客户端断开也会掐掉库侧查询」这条真的跑一次。

**Architecture:** 两个任务。Task 4 是 `require_run` 依赖与 `POST`/`DELETE /api/runs/{run_id}/execute`——SSE 生成器负责事件序列、四个显式提交点、异常映射、心跳与断开检测。Task 5 是端点层的真库验收（`DELETE` 触发真取消，去 `pg_stat_activity` 里确认）、**断开触发器的一次真跑**，以及三处回填。

**Tech Stack:** Python 3.12 · FastAPI（`StreamingResponse`）· asyncio · SQLAlchemy 2.x · pytest + pytest-asyncio · psycopg 3 · ruff

**设计依据：** `docs/superpowers/specs/2026-08-21-chatbi-v2-1-p3b-executor-design.md`（commit `666e314`）的 §2、§6、§7、§11.3、§12。行文以「设计 §N」引用。

**P3b 的第二份。** 任务编号接 p3b1：

| 份 | 任务 | 交付 |
|---|---|---|
| `...-p3b1-executor.md` | Task 1–3 | 注册表 + `cancel_run()` · SSE 格式化 · `chart_spec` · 预览转换 · 执行器 · `runs` 仓储 · 真库验真超时与真取消 |
| **本份** `p3b2` | Task 4–5 | `require_run` · 两个端点 · 端点层真库验收 · 断开触发器真跑 · 回填 |

**开工前必须先读 p3b1 的「交接清单」一节**，尤其那四条注意事项：`cancel_run` 要放进 `to_thread`、四个提交点都要显式 `commit()`、`seq` 用 `next_seq()`、`QUERY_FAILED` 要拼上库的原文。

**起点是 p3b1 结束时的实测值**（那份计划刻意没给死数字，因为 Task 1 的条数取决于 `next_seq` 有没有提前实现）。开工前跑一次记下来，本份的每个预期数都从它往上加。

## Global Constraints

**不新增依赖。** SSE 用手写的 `StreamingResponse` + `media_type="text/event-stream"`，p3b1 的 `sse()` 负责字节格式。**实测确认不需要 `sse-starlette`**：`TestClient.stream()` 能读到事件行。

**不改 `execution/` 与 `guard/` 的任何文件。** 本份**消费** p3b1 与 P3a 的成果。如果实施中觉得需要改它们，那说明上一份漏了东西——回去补那一份并补一条那一层的测试，而不是在 router 里绕过去。

**四个提交点都要显式 `commit()`**（设计 §2）。**这是本份最容易踩且最隐蔽的一条**：`get_db` 在流中途异常时会 `ROLLBACK`（实测），所以依赖它自动提交会让**成功的执行有审计、失败与被取消的执行没有审计**——而 F-304 要审计的恰恰是后者。开发时测成功路径一切正常，只有失败路径的审计是空的。

**验证审计落库必须在另一个 session 里查**（或先 `expire_all()`）。同一个 session 会命中 identity map 而假绿——P2c1 与 p3a2 各踩过一次同形的坑。

**`cancel_run()` 要放进 `to_thread`**（设计 §4）：它内部的 `driver.cancel()` 要另开一条连接，同步调用会卡住事件循环，而那会让取消功能在最需要它的时候不可用。

**`sql` 是编辑器当前内容，不是草稿**（上游 spec §2.3）。它被记为 `run.final_sql`，与 `run.generated_sql`（LLM 原始版，P3c 写）是 F-302 AC2 diff 的两侧。

**每条流都以 `done` 结尾**，包括失败与被拒。前端只需要一个终止信号。

**反向验证要写明「哪几条转红、哪几条必须保持绿」**，「全绿」也是结论。p3a1/p3a2/p3b1 三次各因为认真对待「全绿」而补了一条真有用的测试。

**`ruff check` 与 `ruff format --check` 都必须干净。** 新代码写完先跑一次 `ruff format`。

## 本机环境

```bash
# apps/api 下，每个任务开工前 export 这四个
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
export CHATBI_TEST_PG_DSN=postgresql://chatbi:chatbi@localhost:5432/chatbi_test
```

- 原生 PostgreSQL 16。**不需要 Docker、不需要 Ollama。**
- Task 5 的「断开真跑」要起一次 `uvicorn`（端口 8123，与之前 P2c 那次真跑同一个端口习惯）。**跑完记得停掉它**——P2c 那次留了一个进程要用 `taskkill //PID` 收。
- Task 5 的真库测试**不允许 skip**，与 p3b1 的 `test_executor_real_db.py` 同一条理由。



## File Structure

### 本份创建的文件

| 文件 | 职责 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/runs/deps.py` | `require_run`（所有者 + `can_query` + 非 viewer） | 4 |
| `apps/api/src/chatbi/api/run_router.py` | `POST` / `DELETE /api/runs/{run_id}/execute` | 4 |
| `apps/api/tests/test_run_router.py` | 事件序列、鉴权、409、失败路径的审计落库 | 4 |
| `apps/api/tests/test_run_router_real_db.py` | **`DELETE` 触发真取消**（`pg_stat_activity` 探测） | 5 |

### 本份修改的文件

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/runs/schemas.py`（新建） | `ExecuteRequest`（只有 `sql` 一个字段） | 4 |
| `apps/api/src/chatbi/api/routers.py` | `ALL_ROUTERS` 加 `run_router` | 4 |
| `docs/superpowers/specs/2026-08-11-chatbi-v2-1-design.md` | 三处回填（见「收尾」一节） | 5 |

### 本份不碰的东西

`execution/` 的五个模块 · `guard/` · `runs/repository.py` · P3a 与 p3b1 的任何测试 —— **全部已完成**。

**为什么 `ExecuteRequest` 放新建的 `runs/schemas.py` 而不是 `datasources/schemas.py`**：它是 run 的请求模型，与数据源无关。`datasources/schemas.py` 已经因为 P2c 与 P3a 塞进了 schema 与 SQL 校验的模型（12 个类），再加会让「这个文件装什么」说不清。P3c/P3d 还要往 `runs/schemas.py` 加（问答流请求、历史响应），现在建正好。

### 边界说明

**`api/run_router.py` 是唯一同时认识 guard、执行器、注册表、与 run 仓储的地方**。它做四件事：鉴权（靠 `require_run`）、编排事件序列、在四个点提交、把驱动异常映射成错误码。**不做**任何 SQL 判断（那在 guard）、不做取消动作（那在 `cancel_run`）。

**`runs/deps.py` 与 `datasources/deps.py` 平级**，形状也一致：「取 + 判定 + 抛 `ApiError`」，不 import crypto、不 import 驱动。

**SSE 生成器可能长到需要拆**（设计 §14 的规模自查预告了这一点）：如果 `run_router.py` 超过 250 行，把「事件序列的编排」抽成 `execution/stream.py`（一个 async 生成器），router 只留鉴权与 `StreamingResponse` 包装。**按不抽来写**，超了再拆——先写出来才知道它实际多长。



---

### Task 4: `require_run` 与两个端点

**Files:**
- Create: `runs/deps.py` · `runs/schemas.py` · `api/run_router.py`
- Modify: `api/routers.py`
- Test: `tests/test_run_router.py`

**Interfaces:**
- Consumes: p3b1 全部（见那份的交接清单）· P3a 的 `validate_sql` / `policy_resolver_for` · P2b 的 `connection_info` / `driver_for`
- Produces:
  ```python
  runs.deps.require_run(run_id, db, user) -> Run
  runs.schemas.ExecuteRequest(sql: str)
  POST   /api/runs/{run_id}/execute  -> 200 SSE | 401 | 403 | 404 | 409
  DELETE /api/runs/{run_id}/execute  -> 204 | 401 | 403 | 404
  ```

- [ ] **Step 1: 写 `runs/deps.py` 与 `runs/schemas.py`**

`src/chatbi/runs/deps.py`：

```python
"""run 的 FastAPI 依赖。

与 datasources/deps.py 同形：只做「取 + 判定 + 抛 ApiError」。不 import 驱动、不 import
crypto——HTTP 层没有任何需要明文密码的理由。
"""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from chatbi.auth.deps import current_user
from chatbi.datasources.repository import get_visible
from chatbi.db.base import get_db
from chatbi.db.models import Run, User
from chatbi.errors import PERMISSION_DENIED, RUN_NOT_FOUND, ApiError
from chatbi.runs.repository import get_run


def require_run(
    run_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> Run:
    """按路径参数取 run，三条不满足任一就抛（设计 §6）。

    参数名必须叫 run_id——FastAPI 按名字从路径 {run_id} 里取。

    **不存在与不属于本人都是 404**，不是 403。理由与 datasources 的做法**有意不同**：
    数据源是**共享资源**，一个 analyst 知道「有这么个数据源但我没被授权」是合理的、
    也是他去找管理员要授权的前提；run 是**私有资源**，没有这个诉求，而用 403 区分
    「不存在」与「存在但不是你的」会确认那个 id 存在。

    另两条是 403（「你不该做这件事」而不是「它不存在」）：
    - 对 run.datasource_id 没有 can_query：授权可能在 run 创建**之后**被撤销，
      不重新检查等于给了一条绕过 datasource_grants 的路。
    - 角色是 viewer：上游 spec §4.2 明写「viewer 只看历史，不能执行」。**这一条不被
      上一条覆盖**——一个 viewer 完全可以有 can_query 授权（grants 表不区分角色），
      漏了它 viewer 就能执行查询。

    **admin 也不例外**（设计 §6.2）：他要停掉一条跑飞的查询，正确的路径是去数据库侧
    kill，而不是在应用里给自己开一个能操作别人 run 的后门。别因为「admin 应该能管
    一切」的直觉把这里改掉。
    """
    run = get_run(db, run_id)
    if run is None or run.user_id != user.id:
        raise ApiError(*RUN_NOT_FOUND)
    if user.role == "viewer":
        raise ApiError(*PERMISSION_DENIED)
    if get_visible(db, user, run.datasource_id) is None:
        raise ApiError(*PERMISSION_DENIED)
    return run
```

`src/chatbi/runs/schemas.py`：

```python
"""run 的请求/响应模型。

P3c 会往这里加问答流的请求、P3d 加历史与回放的响应。放在 runs/ 而不是
datasources/schemas.py：那个文件已经装了数据源、schema 元数据、SQL 校验三类模型
（12 个类），再加会让「这个文件装什么」说不清。
"""

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)
    """**编辑器当前内容，不是草稿**（上游 spec §2.3）。服务端把它记为 run.final_sql，
    与 run.generated_sql（LLM 原始版）构成 F-302 AC2 diff 的两侧。

    上限与 /sql/validate 的 SqlValidateRequest 一致（100k 字符）。
    """
```

- [ ] **Step 2: 写 `api/run_router.py`**

```python
"""/api/runs/{run_id}/execute 的 HTTP 编排（上游 spec §2.3）。

**本文件是唯一同时认识 guard、执行器、注册表、与 run 仓储的地方。** 它做四件事：
鉴权（靠 require_run）、编排事件序列、**在四个点显式提交**、把驱动异常映射成错误码。
不做任何 SQL 判断（那在 guard）、不做取消动作（那在 registry.cancel_run）。

**四个提交点必须显式 commit**（设计 §2）：get_db 在流中途异常时会 ROLLBACK（实测），
依赖它自动提交会让**成功的执行有审计、失败与被取消的执行没有审计**——而 F-304 要审计
的恰恰是后者。这个失败模式只影响失败路径，开发时测成功路径完全正常。
"""

import asyncio
import logging
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from chatbi.auth.schemas import ErrorResponse
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
from chatbi.db.base import get_db
from chatbi.db.models import Run, User
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
from chatbi.guard.deps import policy_resolver_for
from chatbi.guard.policy import PolicyResolver
from chatbi.guard.validator import validate_sql
from chatbi.runs.deps import require_run
from chatbi.runs.repository import (
    append_event,
    mark_finished,
    mark_running,
    next_seq,
    save_preview,
)
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

# kind -> sqlglot 方言名。与 api/sql_router.py 里那张表**必须一致**——两处都显式写而
# 不是共用一个常量，是因为它们的变更理由不同（这里跟着执行流走，那里跟着编辑器校验
# 走）。若将来加了第四个 kind，两处都要改，而漏一处的表现是「校验能过但执行 500」。
_DIALECTS = {"postgres": "postgres", "mysql": "mysql", "clickhouse": "clickhouse"}

_PING_INTERVAL_SECONDS = 15


@router.post(
    "/{run_id}/execute",
    responses=_TARGET | _CONFLICT,
    response_class=StreamingResponse,
)
def execute(
    payload: ExecuteRequest,
    request: Request,
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
    """
    if run.status != "drafted":
        raise ApiError(*RUN_NOT_EXECUTABLE)

    return StreamingResponse(
        _stream(request=request, run=run, db=db, resolver=resolver, sql=payload.sql),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _datasource_of(db: Session, run: Run) -> Datasource:
    """显式取数据源。

    `Run` **没有** relationship（`db` 是叶子模块，spec §1.3 规则 4），也不该有——那会让
    ORM 在属性访问时偷偷发查询。所以这里显式 get，而不是写 `run.datasource.kind`。
    """
    datasource = db.get(Datasource, run.datasource_id)
    if datasource is None:      # 外键是 RESTRICT，理论上不可能
        raise ApiError(*CONNECTION_ERROR)
    return datasource
```

（`Datasource` 加进顶部的 `from chatbi.db.models import ...`。）

`X-Accel-Buffering: no` 与 `Cache-Control: no-cache` 两个头是 SSE 的实践必需：前者让 nginx 不缓冲这条流（缓冲会让事件攒够一批才吐给浏览器，心跳就失去意义），后者防中间层缓存。

**端点是 `def` 而不是 `async def`**：它自己不 await 任何东西，只构造 `StreamingResponse`。FastAPI 会把同步路由放进 threadpool，而**生成器 `_stream` 仍然在事件循环上跑**（它是 async 生成器）——所以设计 §4 的并发边界仍然成立。写成 `async def` 也对，但 `def` 更准确地表达了「这个函数体里没有异步的事」。

- [ ] **Step 3: 写 SSE 生成器**

同一个文件，接在后面。**这是本份的核心**，四个提交点都在这里：

```python
def _emit(db: Session, run_id: uuid.UUID, *, step: str, status: str,
          duration_ms: int | None = None, detail: dict | None = None) -> bytes:
    """写一条 run_event 并返回它的 log 事件（上游 spec §2.3 的 log 载荷与 run_events
    的列完全一致——它们是同一份数据的两面，设计 §7.5）。

    **一个写入点、一个格式。** 分开写会让「日志 Tab 看到的」与「回放看到的」有可能不
    一致，而 spec §3.5 说日志 Tab 就是渲染 run_events。

    seq 用 next_seq() 而不是自己数：问答流（P3c）会先写 understand / generate 两条，
    执行流必须接在后面（p3b1 的交接清单第 3 条）。

    detail **不放结果行内容**（spec §4.6），只放 row_count 之类的标量。
    """
    append_event(
        db, run_id=run_id, seq=next_seq(db, run_id), step=step,
        status=status, duration_ms=duration_ms, detail=detail,
    )
    payload: dict = {"step": step, "status": status}
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if detail is not None:
        payload["detail"] = detail
    return sse("log", payload)


async def _stream(*, request: Request, run: Run, db: Session,
                  resolver: PolicyResolver, sql: str):
    """执行流的事件序列（上游 spec §2.3 的八个事件）。

    **四个显式提交点**（设计 §2），每个都标了序号。少任何一个，那一段的审计会在流异常
    时被 get_db 回滚掉——而失败与被取消的执行是最需要审计的。
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
        db.commit()                                             # ← 提交点 1（被拒路径）
        yield log
        yield sse("done", {"status": "blocked", "duration_ms": elapsed, "row_count": None})
        return

    yield sse("validate", {"ok": True})
    log = _emit(db, run.id, step="validate", status="ok", duration_ms=elapsed)
    db.commit()                                                 # ← 提交点 1
    yield log

    # ---- drafted -> running ----
    if not mark_running(
        db, run.id, final_sql=sql, effective_sql=verdict.effective_sql or sql
    ):
        # 并发竞态：两个请求同时通过了端点里的状态检查，只有一个拿到那次条件 UPDATE。
        # 流已经开了，所以这里只能发 error（端点层的 409 走不到了）
        db.commit()
        yield sse("error", {"code": RUN_NOT_EXECUTABLE[0], "message": RUN_NOT_EXECUTABLE[1]})
        yield sse("done", {"status": run.status, "duration_ms": elapsed, "row_count": None})
        return
    db.commit()                                                 # ← 提交点 2
    yield sse(
        "execute.started",
        {"dialect": datasource.kind, "effective_sql": verdict.effective_sql},
    )

    # ---- 执行 + 心跳 + 断开检测 ----
    driver: Driver = get_driver(datasource.kind)
    info = connection_info(datasource)
    task = asyncio.create_task(
        execute_approved(
            driver, info, run_id=run.id, effective_sql=verdict.effective_sql or sql,
            timeout_seconds=settings.query_timeout_seconds,
            max_rows=settings.max_result_rows,
        )
    )

    while True:
        done, _pending = await asyncio.wait({task}, timeout=_PING_INTERVAL_SECONDS)
        if task in done:
            break
        # 心跳的间隙顺便看客户端还在不在。**这一条无法用 TestClient 验**
        # （is_disconnected 在它下面恒 False，设计 §11.3）——Task 5 用一次真跑验它
        if await request.is_disconnected():
            logger.info("客户端断开，取消 run %s", run.id)
            await asyncio.to_thread(cancel_run, db, run.id)      # 内部自己 commit
            return
        # 载荷是空的：驱动不提供进度，**不假装有进度条**（spec §2.3）
        yield sse("ping", {})

    # ---- 结果或异常 ----
    total_ms = int((time.monotonic() - started) * 1000)
    try:
        result: QueryResult = task.result()
    except QueryCancelled:
        # cancel_run 已经写过状态与事件并 commit 过了（它是取消的唯一入口）
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
            run.id, datasource.host, datasource.port, datasource.database,
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
        {"columns": columns, "rows": rows, "row_count": result.row_count,
         "truncated": truncated},
    )

    spec = infer_chart_spec(result.columns, result.row_count)
    yield sse(
        "chart_spec",
        {"type": spec.type, "x": spec.x, "y": list(spec.y), "reason": spec.reason},
    )

    log_execute = _emit(
        db, run.id, step="execute", status="ok", duration_ms=total_ms,
        detail={"row_count": result.row_count},        # 只记行数，不记结果行（§4.6）
    )
    log_render = _emit(db, run.id, step="render", status="ok")
    mark_finished(
        db, run.id, status="succeeded", row_count=result.row_count, duration_ms=total_ms
    )
    db.commit()                                                 # ← 提交点 3
    yield log_execute
    yield log_render
    yield sse(
        "done",
        {"status": "succeeded", "duration_ms": total_ms, "row_count": result.row_count},
    )


def _finish_with_error(db: Session, run_id: uuid.UUID, code_tuple, duration_ms: int) -> bytes:
    """失败路径的收尾：写事件 + 终态 + **显式 commit**（提交点 4）。

    返回那条 log 事件的字节，调用方 yield 它。**这个 commit 是本份最重要的一行**：
    没有它，失败路径上写的所有东西会在流结束时被 get_db 回滚——而 F-304 要审计的正是
    失败与被取消的执行（设计 §2.2）。
    """
    log = _emit(db, run_id, step="execute", status="failed", duration_ms=duration_ms)
    mark_finished(db, run_id, status="failed", error_code=code_tuple[0], duration_ms=duration_ms)
    db.commit()                                                 # ← 提交点 4
    return log
```

**`yield` 与 `commit` 的顺序**：先写库 + commit，再 yield。反过来的话客户端可能在收到事件后立刻断开，而那时 commit 还没跑——事件发出去了但没落库，回放里就缺一条。

- [ ] **Step 4: `DELETE` 端点与 `ALL_ROUTERS`**

```python
@router.delete("/{run_id}/execute", status_code=204, responses=_TARGET)
async def cancel(run: _Target, db: _Db) -> Response:
    """取消一条正在跑的查询（上游 spec §2.3）。

    **它只调 cancel_run()**，自己不做任何取消动作——那样 cancel_run 本身能被单独测，
    而那是必需的：另一个触发器（客户端断开）无法用 TestClient 验（设计 §11.3）。

    `to_thread` 是必需的（设计 §4）：cancel_run 内部的 driver.cancel() 要另开一条连接，
    同步调用会卡住事件循环。

    **恒 204，不管有没有真的取消到东西。** 取消一个已经结束的查询是幂等的正常情况
    （用户点得晚了一点），不是错误。cancel_run 的返回值只进日志。
    """
    cancelled = await asyncio.to_thread(cancel_run, db, run.id)
    logger.info("取消 run %s：%s", run.id, "已取消" if cancelled else "查询已结束或未开始")
    return Response(status_code=204)
```

`api/routers.py`：

```python
from chatbi.api.run_router import router as run_router

ALL_ROUTERS: tuple[APIRouter, ...] = (
    auth_router,
    datasource_router,
    run_router,
    schema_router,
    sql_router,
    user_router,
)
```

`run_router` 的 prefix 是 `/api/runs`，与其余四个（`/api/datasources`、`/api/auth`、`/api/users`）不重叠，声明顺序无所谓。

- [ ] **Step 5: 写端点测试**

新建 `tests/test_run_router.py`：

```python
"""POST / DELETE /api/runs/{run_id}/execute（上游 spec §2.3）。

用假驱动覆盖 driver_for 的下游——**但注意 run_router 不用那个依赖**，它直接调
registry.get_driver()，因为方言与驱动都要从 run.datasource_id 取。所以这里用
monkeypatch 换掉 get_driver（见 with_driver 夹具的说明）。

**本文件最重要的一条是 test_a_failed_execution_still_records_the_audit_trail**：
它守的是设计 §2 那个只影响失败路径的坑。
"""

import threading
import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from chatbi.datasources.drivers.base import (
    ColumnSchema,
    ConnectionFailed,
    QueryFailed,
    QueryHandle,
    QueryResult,
    QueryTimeout,
)
from chatbi.db.models import Conversation, Run, RunEvent, RunResultPreview

_RESULT = QueryResult(
    columns=(
        ColumnSchema(name="city", data_type="text"),
        ColumnSchema(name="amount", data_type="numeric", is_numeric=True),
    ),
    rows=(("北京", 100), ("上海", 200)),
    row_count=2,
    truncated=False,
)


class _FakeDriver:
    """只实现 execute 与 cancel。缺 probe / reflect 是**故意**的。"""

    kind = "postgres"        # 必须是真 kind——_DIALECTS 与 connection_info 都按它走

    def __init__(self, *, result=_RESULT, raises=None, block=False) -> None:
        self._result, self._raises, self._block = result, raises, block
        self._released = threading.Event()
        self.started = threading.Event()
        self.cancelled: list[str] = []

    def execute(self, info, sql, *, timeout_seconds, max_rows, on_start=None):
        if on_start is not None:
            on_start(QueryHandle(token="4242"))
        self.started.set()
        if self._raises is not None:
            raise self._raises("库侧报错：column x does not exist")
        if self._block:
            self._released.wait(timeout=10)
            from chatbi.datasources.drivers.base import QueryCancelled

            raise QueryCancelled("查询已取消")
        return self._result

    def cancel(self, info, handle) -> None:
        self.cancelled.append(handle.token)
        self._released.set()


@pytest.fixture
def with_driver(monkeypatch):
    """换掉 registry.get_driver。

    **不能用 dependency_overrides**：run_router 不通过 FastAPI 依赖取驱动（方言与驱动都
    要从 run.datasource_id 推，而那要先取到 run）。所以这里 monkeypatch 两个模块里的
    引用——`api.run_router` 里 import 的那个名字，以及 `execution.registry` 用不到它。
    """
    def _install(driver: _FakeDriver) -> _FakeDriver:
        monkeypatch.setattr("chatbi.api.run_router.get_driver", lambda kind: driver)
        return driver

    return _install


@pytest.fixture
def make_run(db_session, make_user, make_datasource, login_as, client: TestClient):
    """建一个 drafted 的 run，并把它的所有者登录进 client。

    所有者必须有 can_query——require_run 会重新检查（授权可能在 run 创建后被撤销）。
    admin 无条件可见所有数据源，所以用 admin 最省事。
    """
    from chatbi.execution import registry

    registry.clear()

    def _make(status: str = "drafted") -> Run:
        owner = make_user(role="admin")
        datasource = make_datasource(kind="postgres")
        conversation = Conversation(
            id=uuid.uuid4(), user_id=owner.id, datasource_id=datasource.id, title="t"
        )
        db_session.add(conversation)
        db_session.flush()
        run = Run(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=owner.id,
            datasource_id=datasource.id,
            question="上个月各城市营收",
            status=status,
        )
        db_session.add(run)
        db_session.flush()
        login_as(owner)
        return run

    yield _make
    registry.clear()


def _events(response) -> list[tuple[str, str]]:
    """把 SSE 流解析成 [(event, data), ...]。"""
    events, current = [], None
    for line in response.iter_lines():
        if line.startswith("event: "):
            current = line.removeprefix("event: ")
        elif line.startswith("data: ") and current is not None:
            events.append((current, line.removeprefix("data: ")))
            current = None
    return events


def _names(events) -> list[str]:
    return [name for name, _ in events]


def test_a_successful_execution_emits_the_full_sequence(
    client: TestClient, make_run, with_driver
) -> None:
    """上游 spec §2.3 的事件序列（设计 §7.2）。"""
    run = make_run()
    with_driver(_FakeDriver())

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select city, amount from t"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response)

    names = _names(events)
    assert names[0] == "validate"
    assert "execute.started" in names
    assert "result" in names
    assert "chart_spec" in names
    assert names[-1] == "done", "**每条流都以 done 结尾**——前端只需要一个终止信号"


def test_the_effective_sql_is_echoed(client: TestClient, make_run, with_driver) -> None:
    """spec §2.3：effective_sql「必须回显（可审计的前提）」。它是注入 LIMIT 后的版本，
    与用户提交的 sql 不同——即使一个字都没改，sqlglot 也会重写整条语句。
    """
    run = make_run()
    with_driver(_FakeDriver())

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select city from t"}
    ) as response:
        events = dict(_events(response))

    assert "LIMIT 1000" in events["execute.started"]


def test_a_blocked_sql_ends_the_stream_without_an_error_event(
    client: TestClient, db_session, make_run, with_driver
) -> None:
    """spec §2.3：「ok=false 时流即结束，run 置 blocked」。

    **不发 error 事件**——判定失败是这条流的正常出口，不是异常（与 P3a 的
    /sql/validate 返回 200 同一个道理）。
    """
    run = make_run()
    with_driver(_FakeDriver())

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "insert into t values (1)"}
    ) as response:
        events = _events(response)

    names = _names(events)
    assert "error" not in names
    assert "execute.started" not in names, "被拒的语句不该下发"
    assert names[-1] == "done"
    assert "WRITE_BLOCKED" in dict(events)["validate"]

    db_session.expire_all()
    assert db_session.get(Run, run.id).status == "blocked"


def test_a_failed_execution_still_records_the_audit_trail(
    client: TestClient, db_session, make_run, with_driver
) -> None:
    """**本文件最重要的一条**（设计 §2）。

    get_db 在流中途异常时会 ROLLBACK（实测）。若执行流依赖它自动提交，则**成功的执行
    有审计、失败的没有**——而 F-304 要审计的恰恰是失败与被取消的执行。这个失败模式只
    影响失败路径，开发时测成功路径完全正常。

    用 expire_all() 之后再查：同一个 session 会命中 identity map 而假绿（P2c1 与 p3a2
    各踩过一次同形的坑）。
    """
    run = make_run()
    with_driver(_FakeDriver(raises=QueryTimeout))

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select 1"}
    ) as response:
        events = dict(_events(response))

    assert "QUERY_TIMEOUT" in events["error"]

    db_session.expire_all()
    refreshed = db_session.get(Run, run.id)
    assert refreshed.status == "failed"
    assert refreshed.error_code == "QUERY_TIMEOUT"
    steps = db_session.scalars(
        sa.select(RunEvent.step).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)
    ).all()
    assert steps == ["validate", "execute"], "失败路径的事件被回滚了——四个提交点漏了"


def test_a_query_failure_carries_the_database_message(
    client: TestClient, make_run, with_driver
) -> None:
    """QUERY_FAILED 的 message **带库的原始报错**——分析师要靠它改 SQL（P2b 的
    QueryFailed 刻意保留了原文）。与 spec §4.4 不冲突：那条针对连接类错误。
    """
    run = make_run()
    with_driver(_FakeDriver(raises=QueryFailed))

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select x from t"}
    ) as response:
        events = dict(_events(response))

    assert "column x does not exist" in events["error"]


def test_a_connection_failure_does_not_leak_the_address(
    client: TestClient, make_run, with_driver, make_datasource
) -> None:
    """spec §4.4：地址端口进服务端日志，不进响应。"""
    run = make_run()
    with_driver(_FakeDriver(raises=ConnectionFailed))

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select 1"}
    ) as response:
        body = "".join(line for line in response.iter_lines())

    assert "CONNECTION_ERROR" in body
    assert "db.internal" not in body        # make_datasource 的默认 host
    assert "5432" not in body


def test_the_result_preview_is_stored(
    client: TestClient, db_session, make_run, with_driver
) -> None:
    run = make_run()
    with_driver(_FakeDriver())

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select city, amount from t"}
    ) as response:
        _events(response)

    db_session.expire_all()
    preview = db_session.get(RunResultPreview, run.id)
    assert preview.rows == [["北京", 100], ["上海", 200]]
    assert preview.truncated is False


def test_the_chart_spec_follows_the_columns(
    client: TestClient, make_run, with_driver
) -> None:
    """1 维度（city）+ 1 度量（amount）→ 柱状（spec §3.5）。"""
    run = make_run()
    with_driver(_FakeDriver())

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select city, amount from t"}
    ) as response:
        events = dict(_events(response))

    assert '"type":"bar"' in events["chart_spec"]
    assert '"x":"city"' in events["chart_spec"]


@pytest.mark.parametrize(
    "status", ["running", "succeeded", "failed", "cancelled", "blocked"]
)
def test_a_run_can_only_be_executed_once(
    client: TestClient, make_run, with_driver, status: str
) -> None:
    """**409 在流开始之前**（设计 §5）：一旦开了 SSE 流就只能在流里发 error，而那对
    「你点重复了」是很差的体验（前端要解析流才知道请求没被接受）。

    `running` 也在列表里——那正是双击运行按钮的防护。
    """
    run = make_run(status)
    with_driver(_FakeDriver())

    response = client.post(f"/api/runs/{run.id}/execute", json={"sql": "select 1"})

    assert response.status_code == 409
    assert response.json()["code"] == "RUN_NOT_EXECUTABLE"


def test_an_anonymous_request_is_rejected(client: TestClient, make_run) -> None:
    run = make_run()
    client.cookies.clear()

    assert client.post(f"/api/runs/{run.id}/execute", json={"sql": "select 1"}).status_code == 401


def test_an_unknown_run_is_404(client: TestClient, make_run) -> None:
    make_run()      # 登录一个用户

    response = client.post(f"/api/runs/{uuid.uuid4()}/execute", json={"sql": "select 1"})

    assert response.status_code == 404
    assert response.json()["code"] == "RUN_NOT_FOUND"


def test_another_users_run_is_404_not_403(
    client: TestClient, db_session, make_run, make_user, login_as
) -> None:
    """**404 而不是 403**（设计 §6.1）：run 是私有资源，用 403 区分「不存在」与
    「存在但不是你的」会确认那个 id 存在。

    这与 require_datasource 的做法**有意不同**——数据源是共享资源，知道「有这么个数据源
    但我没被授权」是合理的，也是去找管理员要授权的前提。
    """
    run = make_run()
    login_as(make_user(role="admin"))       # 换成另一个 admin

    response = client.post(f"/api/runs/{run.id}/execute", json={"sql": "select 1"})

    assert response.status_code == 404
    assert response.json()["code"] == "RUN_NOT_FOUND"


def test_a_viewer_cannot_execute(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    """spec §4.2「viewer 只看历史，不能执行」。

    **这条不被「有没有 can_query」覆盖**——viewer 完全可以有 grant（grants 表不区分
    角色），漏了这条检查 viewer 就能执行查询。
    """
    from chatbi.datasources.repository import set_grant

    viewer = make_user(role="viewer")
    datasource = make_datasource(kind="postgres")
    set_grant(db_session, datasource_id=datasource.id, user_id=viewer.id, can_query=True)
    conversation = Conversation(
        id=uuid.uuid4(), user_id=viewer.id, datasource_id=datasource.id, title="t"
    )
    db_session.add(conversation)
    db_session.flush()
    run = Run(
        id=uuid.uuid4(), conversation_id=conversation.id, user_id=viewer.id,
        datasource_id=datasource.id, question="q", status="drafted",
    )
    db_session.add(run)
    db_session.flush()
    login_as(viewer)

    response = client.post(f"/api/runs/{run.id}/execute", json={"sql": "select 1"})

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_delete_returns_204_even_when_nothing_was_running(
    client: TestClient, make_run
) -> None:
    """**恒 204**：取消一个已经结束的查询是幂等的正常情况（用户点得晚了一点），
    不是错误。
    """
    run = make_run()

    assert client.delete(f"/api/runs/{run.id}/execute").status_code == 204


def test_delete_on_another_users_run_is_404(
    client: TestClient, make_run, make_user, login_as
) -> None:
    """取消别人的查询和执行别人的 run 一样不该允许。**admin 也不例外**（设计 §6.2）。"""
    run = make_run()
    login_as(make_user(role="admin"))

    assert client.delete(f"/api/runs/{run.id}/execute").status_code == 404


def test_an_empty_sql_is_a_422(client: TestClient, make_run) -> None:
    """Pydantic 的 min_length=1 挡在 guard 之前。"""
    run = make_run()

    assert client.post(f"/api/runs/{run.id}/execute", json={"sql": ""}).status_code == 422
```

- [ ] **Step 6: 跑测试**

```bash
uv run pytest tests/test_run_router.py -q
uv run pytest -q
```

预期该文件 **20 passed**：15 条独立 + `test_a_run_can_only_be_executed_once` 的 5 条参数化。

**先跑一次「实现之前」确认它们红**（在 Step 2–4 之前做过的话跳过）。这里要特别核对两条只做否定断言的：`test_a_connection_failure_does_not_leak_the_address` 与 `test_an_anonymous_request_is_rejected`——**前者在路由不存在时会空洞通过**（响应体是 `{"detail":"Not Found"}`，里面确实没有地址）。它已经断言了 `"CONNECTION_ERROR" in body` 作为下限，所以实际会红；**p3a2 那次就是漏了这个下限**，这次写进去了。

- [ ] **Step 7: 反向验证六条（每次只改一处，跑完立刻恢复）**

**先 `cp` 备份**。p3a2 那次把四条串在一个命令里跑，超了 8 分钟超时且文件停在中途。

1. **去掉 `_finish_with_error` 里的 `db.commit()`** → `test_a_failed_execution_still_records_the_audit_trail` FAIL（`steps` 是空的或 run 还停在 `running`），而**所有成功路径的测试保持绿**。**这一对是本份最重要的反向验证**：它实证了设计 §2 那个「只影响失败路径」的判断。
2. **去掉提交点 2（`mark_running` 后的 `commit`）** → 观察哪条红。**如果全绿**，说明 `running` 这个中间状态没有专属守卫——如实记进偏差，并考虑加一条测试（在 `execute.started` 之后、结果之前查 `run.status == "running"`；用假驱动的 `block=True` 可以做到）。
3. **端点里的 `if run.status != "drafted"` 那三行删掉** → `test_a_run_can_only_be_executed_once` 五条参数化**不会全红**：流里的 `mark_running` 会兜住它们，但那时状态码是 200（流已开）而不是 409。所以五条都红在 `assert response.status_code == 409`。这证明了「409 要在流之前判」这个决定有守卫。
4. **`require_run` 里 `run.user_id != user.id` 那半个条件删掉** → `test_another_users_run_is_404_not_403` 与 `test_delete_on_another_users_run_is_404` 双双 FAIL。
5. **`require_run` 里 viewer 那条检查删掉** → `test_a_viewer_cannot_execute` FAIL，其余全绿。这条守的是「viewer 检查不被 can_query 覆盖」。
6. **`_emit` 里的 `next_seq(db, run_id)` 改成写死 `1`** → **预期全绿**（本份的 run 都是干净的，第一条事件的 seq 本来就是 1；但第二条事件会撞 `unique (run_id, seq)`……实际上会红在 `IntegrityError`）。**跑一次看到底是哪种**，结果记进偏差——p3b1 的 `test_next_seq_continues_after_existing_events` 已经在仓储层守了它，这里只是确认端点层用的是那个函数。









---

### Task 5: 真库验收与断开触发器的真跑

**本段的退出标准。** p3b1 已经在执行器层验过真取消，本任务验的是**通过 `DELETE` 端点触发**时同样成立，以及**客户端断开**那条触发器真的会掐掉库侧查询。

**Files:**
- Test: `tests/test_run_router_real_db.py`
- 一次手工真跑（uvicorn + 客户端中断），结果写进偏差

**Interfaces:** 无新签名。

- [ ] **Step 1: 写 `DELETE` 触发真取消的测试**

新建 `tests/test_run_router_real_db.py`。**不允许 skip**，与 p3b1 的 `test_executor_real_db.py` 同一条理由。

```python
"""执行流对真 Postgres 的验收（设计 §11.2）。

p3b1 已经验过「执行器层的 cancel_run 能掐掉库侧查询」。这里验的是**通过 DELETE 端点
触发时同样成立**——那条路径多了 to_thread、多了 require_run、多了一个并发的 HTTP 请求。

只断言「流以 QUERY_CANCELLED 结束」证明不了取消：task.cancel() 单独就能让流结束而查询
继续跑（设计 §1.1 的实测）。所以去 pg_stat_activity 里看。
"""

import os
import threading
import time
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from chatbi.db.models import Conversation, Run
from chatbi.execution import registry


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def _pg_dsn() -> str:
    return os.environ["TEST_DATABASE_URL"].replace("postgresql+psycopg", "postgresql")


def _active_sleep_count(pid: int) -> int:
    """在**另一条连接**上问：那个 backend 还在跑 pg_sleep 吗？

    这是「真取消」唯一的直接证据。必须另开连接——被取消的那条正被查询占住。
    """
    with psycopg.connect(_pg_dsn()) as conn:
        row = conn.execute(
            "select count(*) from pg_stat_activity "
            "where pid = %s and state = 'active' and query like %s",
            (pid, "%pg_sleep%"),
        ).fetchone()
    return row[0]


@pytest.fixture
def real_run(db_session, make_user, login_as, client: TestClient):
    """一个指向**真库**的数据源 + 一条 drafted run，所有者已登录。

    数据源指向 TEST_DATABASE_URL 那个库（demo_sales 在里面）。用 make_datasource 不行
    ——它的默认 host 是 db.internal，连不上。
    """
    from urllib.parse import unquote, urlparse

    from chatbi.datasources.crypto import aad_for_datasource, seal
    from chatbi.db.models import Datasource

    parsed = urlparse(_pg_dsn())
    owner = make_user(role="admin")
    datasource_id = uuid.uuid4()
    sealed = seal(unquote(parsed.password or ""), aad=aad_for_datasource(datasource_id))
    datasource = Datasource(
        id=datasource_id,
        name=f"真库-{datasource_id.hex[:8]}",
        kind="postgres",
        host=parsed.hostname,
        port=parsed.port,
        database=parsed.path.lstrip("/"),
        username=unquote(parsed.username or ""),
        secret_ciphertext=sealed.ciphertext,
        secret_nonce=sealed.nonce,
        created_by=owner.id,
    )
    db_session.add(datasource)
    db_session.flush()
    conversation = Conversation(
        id=uuid.uuid4(), user_id=owner.id, datasource_id=datasource.id, title="t"
    )
    db_session.add(conversation)
    db_session.flush()
    run = Run(
        id=uuid.uuid4(), conversation_id=conversation.id, user_id=owner.id,
        datasource_id=datasource.id, question="q", status="drafted",
    )
    db_session.add(run)
    db_session.flush()
    login_as(owner)
    return run


def test_a_real_query_runs_through_the_endpoint(client: TestClient, real_run) -> None:
    """先证明这条路通，否则下面那条的红分不清「取消生效」与「根本连不上」。"""
    with client.stream(
        "POST",
        f"/api/runs/{real_run.id}/execute",
        json={"sql": "select count(*) as n from demo_sales.orders"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_lines())

    assert '"status":"succeeded"' in body
    assert '"row_count":1' in body


def test_delete_really_kills_the_backend_query(client: TestClient, real_run) -> None:
    """**本份最重要的一条。**

    TestClient 是同步的，所以流的消费与 DELETE 必须在两个线程里：主线程消费流，
    另一个线程等到 execute.started 之后发 DELETE。

    时序：起流 → 等注册表登记（那时语句已下发）→ 确认库里**有**这条 pg_sleep →
    DELETE → 确认库里**没有**了。
    """
    observed: dict = {}

    def canceller() -> None:
        for _ in range(200):                  # 等注册表登记，最多 10 秒
            if registry.is_running(real_run.id):
                break
            time.sleep(0.05)
        else:
            observed["error"] = "on_start 没登记——取消能力没有入口"
            return
        observed["pid"] = int(registry._RUNNING[real_run.id].handle.token)  # noqa: SLF001
        time.sleep(0.5)                        # 让语句真的开始跑
        observed["before"] = _active_sleep_count(observed["pid"])
        observed["delete_status"] = client.delete(
            f"/api/runs/{real_run.id}/execute"
        ).status_code

    worker = threading.Thread(target=canceller, daemon=True)
    worker.start()
    with client.stream(
        "POST", f"/api/runs/{real_run.id}/execute", json={"sql": "select pg_sleep(30)"}
    ) as response:
        body = "".join(response.iter_lines())
    worker.join(timeout=20)

    assert "error" not in observed, observed.get("error")
    assert observed["delete_status"] == 204
    assert observed["before"] == 1, (
        "取消前库里就没有这条 pg_sleep——这条测试证明不了任何事，先查环境"
    )
    assert "QUERY_CANCELLED" in body

    time.sleep(0.3)                            # 给 backend 一点时间退出
    assert _active_sleep_count(observed["pid"]) == 0, (
        "**查询还在库上跑**——只关了流没掐库侧，这是 spec §4.3 点名的错误"
    )
```

**那条「取消前必须先看到 pg_sleep」的断言不是多余的**：没有它，一个「库里根本没跑起来」的环境问题会让整条测试假绿（取消后是 0，因为本来就是 0）。

- [ ] **Step 2: 跑真库测试**

```bash
uv run pytest tests/test_run_router_real_db.py -q -v
```

预期 **2 passed**，耗时约 5–10 秒。

若第二条卡住不返回，最可能是「流的消费与 DELETE 互相等待」——TestClient 的 portal 是单线程的，`client.delete` 在另一个线程里发可能与流的读取竞争。**若真的卡住，改用 `httpx.Client` 直连一个真起的 uvicorn**（那时这条测试就与 Step 3 的真跑合并）。**把实际情况记进偏差**，别把断言删掉了改成「只验流结束」——那样这条测试就失去意义了。

- [ ] **Step 3: 断开触发器的一次真跑（手工，结果进偏差）**

**这条无法自动化**：实测 `TestClient` 下 `Request.is_disconnected()` **恒为 `False`**（客户端只读 3 行就退出，服务端仍跑完 50 次循环）。TestClient 走 ASGI 的内存传输，客户端提前退出不产生 `http.disconnect` 消息。

所以按设计 §11.3 的分工：`cancel_run()` 与 `DELETE` 触发器在回归套件里（Step 1、2 与 p3b1），**断开那条用一次真跑验**，未覆盖的只剩「`is_disconnected()` 变 True 时会调 `cancel_run`」这一行。

**准备**（用 `chatbi_test` 库，不碰开发库；测试的 `_migrated` 夹具下次会把它清干净）：

```bash
cd apps/api
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_SECRET_KEY=dev-only-not-for-production
export CHATBI_COOKIE_SECURE=0

uv run python -m chatbi.cli create-user disc@example.com 断开真跑 --role admin --password pw-12345678
uv run uvicorn chatbi.main:app --port 8123 --log-level info    # 前台跑，看得到日志
```

另一个终端里：

```bash
cd /tmp
# 1. 登录
curl -s -c ck.txt -X POST http://127.0.0.1:8123/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"disc@example.com","password":"pw-12345678"}' -o /dev/null -w '%{http_code}\n'

# 2. 建一个指向应用库自己的数据源（中文名要用文件传，Git Bash 的 -d 会 mangle 编码）
python -c "
import json
open('ds.json','wb').write(json.dumps({'name':'断开真跑库','kind':'postgres','host':'localhost','port':5432,'database':'chatbi_test','username':'chatbi','password':'chatbi'},ensure_ascii=False).encode('utf-8'))
"
DS=$(curl -s -b ck.txt -X POST http://127.0.0.1:8123/api/datasources \
  -H 'Content-Type: application/json' --data-binary @ds.json | python -c "import json,sys;print(json.load(sys.stdin)['id'])")

# 3. 手工造一条 drafted run（问答流是 P3c，这里直接写库）
uv run python - <<PY
import os, uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from chatbi.db.models import Conversation, Run, User, Datasource
import sqlalchemy as sa
e = create_engine(os.environ["CHATBI_DATABASE_URL"])
with Session(e) as s:
    user = s.scalars(sa.select(User).where(User.email == "disc@example.com")).one()
    ds = s.scalars(sa.select(Datasource)).first()
    conv = Conversation(id=uuid.uuid4(), user_id=user.id, datasource_id=ds.id, title="t")
    s.add(conv); s.flush()
    run = Run(id=uuid.uuid4(), conversation_id=conv.id, user_id=user.id,
              datasource_id=ds.id, question="q", status="drafted")
    s.add(run); s.commit()
    print(run.id)
PY
# 把上面打印的 run_id 记下来，设成 RUN=<那个 uuid>

# 4. 起一条 30 秒的查询，**读几行就 Ctrl-C**（模拟客户端断开）
curl -N -b ck.txt -X POST "http://127.0.0.1:8123/api/runs/$RUN/execute" \
  -H 'Content-Type: application/json' -d '{"sql":"select pg_sleep(30)"}'
# 看到 execute.started 之后按 Ctrl-C

# 5. 立刻去库里看那条查询还在不在
uv run python -c "
import psycopg
with psycopg.connect('postgresql://chatbi:chatbi@localhost:5432/chatbi_test') as c:
    n = c.execute(\"select count(*) from pg_stat_activity where state='active' and query like '%pg_sleep%'\").fetchone()[0]
    print('库里还在跑的 pg_sleep 数 =', n, '  <- 必须是 0')
"

# 6. 确认审计落库了（被取消的执行是最需要审计的）
uv run python -c "
import os, sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from chatbi.db.models import Run, RunEvent
e = create_engine(os.environ['CHATBI_DATABASE_URL'])
with Session(e) as s:
    run = s.scalars(sa.select(Run).order_by(Run.created_at.desc())).first()
    print('status =', run.status, '| error_code =', run.error_code)
    print('events =', [(x.seq, x.step, x.status) for x in s.scalars(sa.select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq))])
"
```

**三条都要成立**：uvicorn 日志里有「客户端断开，取消 run …」· 步骤 5 是 `0` · 步骤 6 显示 `status = cancelled` / `error_code = QUERY_CANCELLED` 且事件里有 `validate` 与 `execute`。

**跑完停掉 uvicorn**（P2c 那次留了一个进程，要 `taskkill //PID <pid> //F` 才收掉）。

**把三条的实际输出抄进「实施期的偏差」。** 这是这条触发器唯一的证据——它不在回归套件里，所以那段记录就是它的全部凭据。若第 5 步不是 0，**那是一个真实的缺陷**：说明断开检测那一行没有真的走到 `cancel_run`，回去查 `is_disconnected()` 的调用位置（它在 ping 循环里，只有心跳间隙才检查——如果查询在 15 秒内就返回了，那个分支根本没机会跑；用 `pg_sleep(30)` 就是为了保证它跑到）。

- [ ] **Step 4: ruff + 全量 + 提交**

```bash
uv run ruff format src/chatbi/ tests/
uv run ruff check . && uv run ruff format --check .
wc -l src/chatbi/api/run_router.py      # 超过 250 就按 File Structure 的边界说明拆出 stream.py
uv run pytest -q
git add src/chatbi/runs/deps.py src/chatbi/runs/schemas.py src/chatbi/api/run_router.py \
        src/chatbi/api/routers.py tests/test_run_router.py tests/test_run_router_real_db.py
git commit -m "feat(api): 执行流 SSE 与取消端点

POST /api/runs/{run_id}/execute 走 spec §2.3 的八个事件，DELETE 触发取消。

**四个提交点都显式 commit**：get_db 在流中途异常时会 ROLLBACK（实测），依赖它
自动提交会让成功的执行有审计、失败与被取消的执行没有——而 F-304 要审计的恰恰是
后者。反向验证 1 实证了这一点：去掉失败路径那个 commit 之后，只有审计那条测试
转红，所有成功路径的测试保持绿。

409 在流开始之前判（一个 run 恰好执行一次）：一旦开了 SSE 流就只能在流里发
error，而那对「你点重复了」是很差的体验。流里的 mark_running 条件 UPDATE 是
并发竞态的兜底。

require_run 三条：所有者 + can_query + 非 viewer。第三条不被第二条覆盖（viewer
可以有 grant）。不存在与非本人都是 404 而不是 403——run 是私有资源，与
require_datasource 对共享资源用 403 有意不同。admin 也不例外。

DELETE 恒 204：取消一个已结束的查询是幂等的正常情况。cancel_run 放进 to_thread
（它内部要另开一条连接）。

真库验收：DELETE 触发后去 pg_stat_activity 确认那个 backend 不再跑那条语句，
并且在取消**之前**先断言它在跑——没有前一半，一个「库里根本没跑起来」的环境
问题会让整条测试假绿。"
```





---

## 收尾：三处回填进上游 spec（做完 Task 5 后一次做掉）

设计 §12.1 列的四处偏离里，前三处要回填。不回填的后果具体：下一个读 spec 的人会以为实现写错了，或照 spec 重写一遍已被推翻的做法。

- [ ] **回填 1：§2.6 加两个错误码**

`docs/superpowers/specs/2026-08-11-chatbi-v2-1-design.md` 的错误码表加 `QUERY_FAILED`（库拒绝执行，**message 带库的原文**——与超时/取消/连不上都不同）与 `RUN_NOT_EXECUTABLE`（409，一个 run 恰好执行一次）。

顺带在 `QUERY_TIMEOUT` / `QUERY_CANCELLED` 那两行加一句：**它们只出现在 SSE 的 `error` 事件载荷里，不作为 HTTP 状态返回**（流已经是 200）。

- [ ] **回填 2：§2.3 补 run 的一次性语义与执行授权**

那一节现在只说了请求体与事件表。补两句：

- **一个 run 恰好执行一次**：非 `drafted` 一律 409（`runs` 的结果字段是单列，多次执行会改写审计记录）。「改了 SQL 重跑」= 建新 run。
- **执行授权**：所有者 + `can_query` + 非 viewer；不存在与非本人都是 404（run 是私有资源，与数据源的 403 有意不同）。

- [ ] **回填 3：§2.5 的 `run_result_previews` 注释点明两个上限**

那行注释现在是「只存前 100 行摘要」。补一句：**100（`preview_rows`）与闸 3 的 1000（`max_result_rows`）是两个不同的上限**，而 `truncated` 指的是**驱动那一层是否截断**（库里其实有 >1000 行），不是「预览是否截断」。混用会让一次返回 200 行的查询显示「已截断」。

- [ ] **回填 4：写偏差 + 提交**

```bash
git add docs/superpowers/specs/2026-08-11-chatbi-v2-1-design.md         docs/superpowers/plans/2026-08-21-chatbi-v2-1-p3b1-executor.md         docs/superpowers/plans/2026-08-21-chatbi-v2-1-p3b2-endpoints.md
git commit -m "docs: 回填 P3b 的实施期偏差，并把三处有意偏离同步进上游 spec"
```

---

## 实施期的偏差（执行中回填）

（开工前为空。**本份必须记的五处**：Task 4 Step 6 的实际条数 · Step 7 反向验证 2（去掉提交点 2）到底哪条红，若全绿则说明 `running` 中间态没有守卫 · Step 7 反向验证 6（`next_seq` 写死 1）的实际表现 · Task 5 Step 2 那条真库测试有没有卡住（TestClient 的 portal 是单线程的）· **Task 5 Step 3 断开真跑的三条实际输出**——那是这条触发器唯一的凭据，它不在回归套件里。）

---

## 交接清单（P3c / P3d 要消费的签名）

```python
# 端点
POST   /api/runs/{run_id}/execute  -> 200 SSE | 401 | 403 | 404 | 409 | 422
DELETE /api/runs/{run_id}/execute  -> 204 | 401 | 403 | 404
#   POST 的请求体只有 {sql}，它是**编辑器当前内容**，被记为 run.final_sql

# 依赖（chatbi.runs.deps）
require_run(run_id, db, user) -> Run
#   所有者 + can_query + 非 viewer。不存在与非本人都是 404（run 是私有资源）
#   P3c/P3d 的 run 相关端点复用它。**别为 admin 开后门**（设计 §6.2）

# 请求模型（chatbi.runs.schemas）
ExecuteRequest(sql: str)
#   P3c 往这里加问答流的请求模型、P3d 加历史与回放的响应模型
```

**P3c 问答流**
- 建 run 时 `status='drafted'`，写 `question` / `chips` / `generated_sql` / `llm_provider` / `llm_model`。**`final_sql` 与 `effective_sql` 留空**——那两列由执行流写。
- **事件的 `seq` 用 `next_seq()`**：问答流写 `understand`(1) / `generate`(2)，执行流会从 3 续。硬编码会撞 `unique (run_id, seq)`。
- 「改了 SQL 重跑」= 建**新** run（一个 run 恰好执行一次）。要不要设 `parent_run_id` 由 P3c/P4 定——F-401 的下钻用同一列，混用会让「下钻链」与「重跑链」分不开，**建议重跑不设**。
- 问答流也是 SSE，可以复用 `execution/sse.py` 的 `sse()`。**四个提交点那条教训同样适用**：问答流的事件也会在流异常时被 `get_db` 回滚。

**P3d 回放**
- `run.status` 的六个值都会出现在历史列表里，`blocked` 与 `cancelled` 也要有界面呈现。
- `run_result_previews` 的 `rows` 已经转换过（`Decimal → float` 丢了精度）。回放展示用它；**`export.csv` 重跑取全量**，别从预览里导。
- `list_events()` 按 `seq` 排序（P3a 已实现），别按 `at` 或 `id`。

**运维文档要写的两条**
1. **注册表是进程内的**：多 worker 部署（`uvicorn --workers N`）下 `DELETE` 会有 (N-1)/N 的概率打到没有那条 run 的进程上，**取消静默失效**。要上多 worker 得先把它换成共享存储。
2. **SSE 需要反向代理不缓冲**：router 已发 `X-Accel-Buffering: no`，但若用非 nginx 的代理要单独确认，否则事件会攒批、心跳失去意义。

---

## 自查记录

**设计 spec 覆盖核对（本份负责的部分）**

| 设计条目 | 落在哪 |
|---|---|
| §2.3 四个提交点 | Task 4 Step 3 的四处标号 + Step 7 反向验证 1 |
| §6 `require_run` 三条 + 404/403 的分界 | Task 4 Step 1 + Step 5 的四条鉴权测试 |
| §6.2 admin 也不例外 | `require_run` 的文档 + `test_delete_on_another_users_run_is_404` |
| §7.1 SSE 格式 | 复用 p3b1 的 `sse()` |
| §7.2 成功路径九步 | Task 4 Step 3 + `test_a_successful_execution_emits_the_full_sequence` |
| §7.3 五条失败路径 + 每条以 `done` 结尾 | Task 4 Step 3 的五个 except + 三条失败测试 |
| §7.4 五个错误码（p3b1 已加）的使用 | Task 4 Step 3 |
| §7.5 `log` 事件与 `run_events` 同源 | `_emit()` 一个写入点 |
| §7.6 `ping` 循环用 `asyncio.wait` 的超时 | Task 4 Step 3 的 while 循环 |
| §5 一个 run 恰好执行一次（409 在流之前） | Task 4 Step 2 + 五条参数化 + 反向验证 3 |
| §11.3 断开触发器无法自动化测 | Task 5 Step 3 的手工真跑 |
| §12.1 三处回填 | 「收尾」一节 |

**不在本份的设计小节**：§1（注册表与 `cancel_run`）· §3（不加 asyncio 超时）· §4（并发边界，本份只遵守）· §8（`chart_spec`）· §9（预览转换）—— 全部在 p3b1。

**占位符扫描**：无 TBD / TODO / 「类似 Task N」/ 无代码的「写测试」步骤。Task 4 Step 7 的反向验证 2、6 与 Task 5 Step 2 的「若卡住」写的是**观察方式与应对**，不是「遇到问题再说」。

**类型一致性核对**

`_stream` 的五个关键字参数与 `execute` 里的调用一致。`_emit` 的签名与 `append_event` 的六个参数对齐（少了 `seq`，因为它内部算）。`_finish_with_error` 收的 `code_tuple` 是 `errors.py` 里那种三元组，用 `[0]` 取 code——与 P3a 的 `_rejected` 同形。`ExecuteRequest.sql` 的上限（100k）与 `SqlValidateRequest.sql` 一致。

`_DIALECTS` 在 `api/run_router.py` 与 `api/sql_router.py` **各有一份**，内容必须相同。**这是有意的重复**（两者的变更理由不同），但漏改一处的表现是「校验能过但执行 500」。加第四个 kind 时两处都要改——没有测试能守住这一点，只有这条注释。

**一处对设计的补充**：设计没定端点函数是 `def` 还是 `async def`。本计划用 `def`（函数体里没有异步的事，生成器仍在事件循环上跑），并在 Task 4 Step 2 末尾写明了理由与「写成 async def 也对」。

