# Chat-BI V2-1 · P3b1 执行器与真取消 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「跑一条已批准的 SQL 并且能真的掐掉它」这件事做完并对真库验完 —— 在任何 HTTP 代码之前。

**Architecture:** 三个任务，都在 `execution/` 包与 `runs/repository.py` 里，**不碰 HTTP**。Task 1 是注册表与 `cancel_run()`（取消的唯一入口）+ SSE 格式化。Task 2 是两个纯函数模块（`chart_spec` 推断、结果预览的类型转换）。Task 3 是执行器本身（`asyncio.to_thread` 包驱动 + 注册表登记 + 异常翻译）与 `runs` 的四个仓储函数，**并对真 Postgres 验完真超时与真取消**。

**Tech Stack:** Python 3.12 · asyncio · SQLAlchemy 2.x ORM · pytest + pytest-asyncio · psycopg 3 · ruff

**设计依据：** `docs/superpowers/specs/2026-08-21-chatbi-v2-1-p3b-executor-design.md`（commit `666e314`）的 §1–§5、§8–§10。行文以「设计 §N」引用。上游 spec 是 `2026-08-11-chatbi-v2-1-design.md`。

**P3b 按体量拆成两份。** 任务编号连续：

| 份 | 任务 | 交付 |
|---|---|---|
| **本份** `p3b1` | Task 1–3 | 注册表 + `cancel_run()` · SSE 格式化 · `chart_spec` · 预览转换 · 执行器 · `runs` 仓储 · **真库验真超时与真取消** |
| `...-p3b2-endpoints.md` | Task 4–5 | `require_run` · `POST`/`DELETE /api/runs/{id}/execute` · 端点层真库验收 · 断开触发器真跑 · 回填 |

**做完本份后端没有任何新端点** —— 但「真取消」这个最危险的能力已经对真库验完了。这是有意的顺序：spec §4.3 闸 4 的红线先验完，再接线。

**起点：`310 passed` / `28 skipped`**（P3a 结束，commit `24a4c43`）。开工前先跑一次确认。

## Global Constraints

**不新增依赖。** SSE 用手写的 `StreamingResponse`（p3b2 才用到），本份连 fastapi 都不 import。`pytest-asyncio` 已在 dev 组。

**`execution/` 不 import fastapi。** 执行器与注册表要能脱离 HTTP 测——`cancel_run()` 只收 `run_id`，`Request.is_disconnected()` 在 p3b2 的 router 里读。`executor.py` 保持 **≤200 行**（上游 spec §1.4 与 `guard/validator.py` 并列点名的两个安全红线文件之一）。

**取消必须做三件事，顺序固定**（设计 §1.2）：先 `driver.cancel()` 掐库侧、再 `task.cancel()` 关流、最后写状态与事件并**显式 commit**。

**只 `task.cancel()` 是上游 spec §4.3 点名的错误。** 实测：`asyncio.to_thread` 的 task 被 cancel 后**线程继续跑到底**。所以任何「取消」的实现里如果看不到 `driver.cancel()`，那就是在关掉流然后让查询继续跑在用户的生产库上。

**不加 `asyncio.wait_for` 之类的超时兜底**（设计 §3）。闸 4 的超时只靠驱动的库侧机制。理由同上：`wait_for` 超时后 cancel 的是 to_thread task，线程不会停——加了只是让流提前结束而查询继续跑。

**驱动调用必须 `to_thread`，DB 调用直接做**（设计 §4）。后者不是因为快，是因为 SQLAlchemy `Session` **不是线程安全的**。

**审计的写入必须显式 commit。** 本份的 `cancel_run()` 会写 run 状态与事件——它可能在一个被取消的请求上下文里跑，那时 `get_db` 会回滚（设计 §2 的实测）。所以 `cancel_run()` 自己开 session 或自己 commit，不依赖调用方。

**每个任务的反向验证都要写明「哪几条转红、哪几条必须保持绿」**，两者都要核对。**「反向验证全绿」也是一个结论**（说明那条路径没有守卫），如实记进偏差，不要改测试去凑——p3a1/p3a2 各因此补了一条真正有用的测试。

**`ruff check` 与 `ruff format --check` 都必须干净。** 新代码写完先跑一次 `ruff format`，别攒到提交前（p3a1、p3a2 各踩过一次）。

## 本机环境

```bash
# apps/api 下，每个任务开工前 export 这四个
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
export CHATBI_TEST_PG_DSN=postgresql://chatbi:chatbi@localhost:5432/chatbi_test
```

- 原生 PostgreSQL 16。**本份不需要 Docker、不需要 Ollama。** Task 3 的真库测试用 `CHATBI_TEST_PG_DSN` 指的那个库（`demo_sales` 在里面，P2b 建的）。
- `CHATBI_TEST_MYSQL_DSN` / `CHATBI_TEST_CLICKHOUSE_DSN` 不设，那两个 kind 的契约测继续 skip 并计数（预期状态）。
- **本份新增的真库测试不允许 skip**：它用的是本机原生 Postgres，与 `tests/drivers/` 那批「缺 DSN 就 skip」的契约测不同。没有真库这一层，闸 4 的「真取消」就只有假驱动的证据——而那正是 P2b 那条教训（「代码写完了」不能代替「真的跑过了」）要防的。



## File Structure

### 本份创建的文件

| 文件 | 职责 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/execution/__init__.py` | 空 | 1 |
| `apps/api/src/chatbi/execution/registry.py` | 进程内 `run_id → RunningQuery` + **`cancel_run()`**（取消的唯一入口） | 1 |
| `apps/api/src/chatbi/execution/sse.py` | `sse(event, data) -> bytes` 一个函数 | 1 |
| `apps/api/src/chatbi/execution/charts.py` | `ChartSpec` + `infer_chart_spec()` 纯函数 | 2 |
| `apps/api/src/chatbi/execution/preview.py` | `QueryResult` → 可存 JSONB 的 `columns`/`rows` | 2 |
| `apps/api/src/chatbi/execution/executor.py` | `execute_approved()`。**≤200 行，安全红线** | 3 |
| `apps/api/tests/test_execution_registry.py` | 注册表与 `cancel_run()`（含审计落库） | 1 |
| `apps/api/tests/test_execution_sse.py` | SSE 格式（纯函数，无夹具） | 1 |
| `apps/api/tests/test_execution_charts.py` | 六条判定分支，参数化（纯函数，无夹具） | 2 |
| `apps/api/tests/test_execution_preview.py` | 类型转换与三个数的区分（纯函数，无夹具） | 2 |
| `apps/api/tests/test_executor.py` | 四条路径 + 注册表清理（假驱动） | 3 |
| `apps/api/tests/test_executor_real_db.py` | **真超时 + 真取消**（真 Postgres） | 3 |
| `apps/api/tests/test_run_repository.py` | 四个仓储函数 + 带条件 UPDATE 的并发语义 | 3 |

### 本份修改的文件

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/errors.py` | 加五个码：`QUERY_TIMEOUT` / `QUERY_CANCELLED` / `QUERY_FAILED` / `RUN_NOT_EXECUTABLE` / `RUN_NOT_FOUND` | 1 |
| `apps/api/src/chatbi/config.py` | 加 `preview_rows: int = 100` | 2 |
| `apps/api/src/chatbi/runs/repository.py` | 加 `get_run` / `mark_running` / `mark_finished` / `save_preview` | 3 |
| `apps/api/tests/test_run_events.py` | 那条扫模块导出名的测试改成白名单式（见边界说明） | 3 |

### 本份不碰的东西

`runs/deps.py`（`require_run`）· `api/run_router.py` · `api/routers.py` 的接缝 · 任何 Pydantic HTTP 模型 —— **全部在 p3b2**。

**为什么 `sse.py` 在本份而不是 p3b2**：它是一个纯函数（`(event, data) -> bytes`），有自己的格式契约（`event:` / `data:` / 空行）值得单独测。放在本份让 p3b2 的 router 只需要编排，不用同时操心字节格式。

### 边界说明

**`execution/` 是独立顶层包**，与 `guard/` / `runs/` / `datasources/` 平级。它是**唯一**同时认识 guard、驱动、与 run 状态的地方——放进 `runs/`（那是持久化）或 `api/`（那是 HTTP 编排）都会让「执行」这件事没有自己的家。

**`executor.py` 与 `guard/validator.py` 是 spec §1.4 点名的两个安全红线文件**，都要 ≤200 行、只做一件事。所以注册表、图表推断、预览转换、SSE 格式化各自分文件——它们都不是执行本身。

**`runs/repository.py` 新增的四个函数与 append-only 不冲突**：`run_events` 仍然只有 `append_event` / `list_events`。新增的动的是 `runs` 与 `run_result_previews`，**它们不是 append-only 的**（run 的状态本来就要从 `drafted` 变到终态）。

因此 p3a2 那条扫模块导出名的测试要改：它现在断言「导出名里没有 `update`/`delete` 字样」，而 `mark_running` / `mark_finished` 是合法的 `runs` 更新。**改成白名单式断言**（列出允许的函数名），不要放宽黑名单——黑名单再放宽一次就没有约束力了，而白名单在加新函数时会强制实施者回来想一下「这个函数该不该存在」。



---

### Task 1: 注册表、`cancel_run()` 与 SSE 格式化

取消的唯一入口。p3b2 的两个触发器（`DELETE` 端点、客户端断开）都只调 `cancel_run()`，自己不做任何取消动作——这样它本身能被直接测，而那是必需的：**其中一个触发器无法用现有测试设施验**（设计 §11.3）。

**Files:**
- Create: `execution/__init__.py`（空）· `execution/registry.py` · `execution/sse.py`
- Modify: `src/chatbi/errors.py`
- Test: `tests/test_execution_registry.py` · `tests/test_execution_sse.py`

**Interfaces:**
- Consumes: P2b 的 `Driver` / `QueryHandle` / `ConnectionInfo` · P3a 的 `append_event`
- Produces:
  ```python
  registry.RunningQuery(handle, task, info, driver)     # frozen dataclass
  registry.register(run_id, *, handle, task, info, driver) -> None
  registry.unregister(run_id) -> None
  registry.is_running(run_id) -> bool
  registry.cancel_run(session, run_id) -> bool          # 唯一的取消入口
  sse.sse(event: str, data: dict) -> bytes
  errors.QUERY_TIMEOUT / QUERY_CANCELLED / QUERY_FAILED
         / RUN_NOT_EXECUTABLE / RUN_NOT_FOUND
  ```
  Task 3 的执行器在 `on_start` 回调里调 `register`、在 `finally` 里调 `unregister`；p3b2 的两个端点调 `cancel_run` 与 `sse`。

- [ ] **Step 1: 加五个错误码**

`src/chatbi/errors.py`，在 `MULTIPLE_STATEMENTS` 之后追加：

```python
# 闸 4 与执行流（上游 spec §2.6、§4.3）。前三个只出现在 SSE 的 error 事件载荷里，
# **不作为 HTTP 状态返回**——流本身已经是 200 了。状态码那一位在这里只用于让
# ApiError 元组的形状一致，以及万一将来有非 SSE 的调用方。
QUERY_TIMEOUT = ("QUERY_TIMEOUT", "查询超时，请缩小时间范围或增加过滤条件", 504)
# 499 是 nginx 的扩展码而非标准 HTTP，见上：它不会真的被当成状态码发出去
QUERY_CANCELLED = ("QUERY_CANCELLED", "查询已取消", 499)
# **message 里会带库的原始错误文本**（由调用方拼）。这与 §4.4「错误消息不含结构
# 信息」不冲突：那条针对连接类错误（可能含地址端口），而这里的原文是用户自己写的
# SQL 在库上的报错，正是他改 SQL 需要看到的（P2b 的 QueryFailed 刻意保留了原文）。
# 别在某次安全评审里把它抹掉。
QUERY_FAILED = ("QUERY_FAILED", "数据库拒绝执行该查询", 400)
# 一个 run 恰好执行一次（设计 §5）：非 drafted 一律 409。顺带成为双击运行按钮的防护
RUN_NOT_EXECUTABLE = ("RUN_NOT_EXECUTABLE", "该查询已执行过或正在执行", 409)
RUN_NOT_FOUND = ("RUN_NOT_FOUND", "查询记录不存在", 404)
```

- [ ] **Step 2: 写 `execution/sse.py` 与它的测试**

`src/chatbi/execution/__init__.py`：空文件。

`src/chatbi/execution/sse.py`：

```python
"""SSE 的行格式。

一个事件三部分：`event: <名字>` 行、`data: <紧凑 JSON>` 行、一个空行。

**不引 sse-starlette**：格式就这么点，自己拼比引一个包更容易看清发出去的到底是
什么，而且少一个依赖。实测 TestClient.stream() 能读这个格式。

data 恒为一行 JSON，不做多行 data:（SSE 允许，但那需要接收端拼接，而我们的载荷
都是小 JSON）。代价是长 SQL 会让那一行很长，可接受。
"""

import json
from typing import Any


def sse(event: str, data: dict[str, Any]) -> bytes:
    """拼一个 SSE 事件。

    ensure_ascii=False：载荷里有中文（错误文案、注释、chips），转义成 \\uXXXX 会让
    调试时的抓包完全不可读，而 SSE 的传输编码是 UTF-8。

    separators 去掉空格：这条流可能发很多次，没必要为可读性付带宽——需要读的时候
    抓包工具会格式化。
    """
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode()
```

`tests/test_execution_sse.py`：

```python
"""SSE 行格式（纯函数，无夹具）。"""

from chatbi.execution.sse import sse


def test_an_event_has_three_parts() -> None:
    """event 行、data 行、一个空行。少了那个空行接收端不会认为事件结束。"""
    assert sse("done", {"status": "succeeded"}) == (
        b'event: done\ndata: {"status":"succeeded"}\n\n'
    )


def test_chinese_is_not_escaped() -> None:
    """载荷里有中文错误文案。转义成 \\uXXXX 会让抓包不可读。"""
    raw = sse("error", {"message": "查询已取消"})

    assert "查询已取消".encode() in raw
    assert b"\\u" not in raw


def test_an_empty_payload_is_still_valid_json() -> None:
    """ping 的载荷是空的 {}（上游 spec §2.3：不假装有进度条）。"""
    assert sse("ping", {}) == b"event: ping\ndata: {}\n\n"


def test_no_spaces_in_the_json() -> None:
    """紧凑分隔符。这条不是风格洁癖——它钉住 separators 参数没被删掉，否则每个
    事件多出几十字节，而这条流一次执行可能发上百个事件。
    """
    assert b'{"a":1,"b":2}' in sse("x", {"a": 1, "b": 2})
```

- [ ] **Step 3: 写注册表与 `cancel_run()` 的失败测试**

新建 `tests/test_execution_registry.py`：

```python
"""进程内运行注册表与 cancel_run()（设计 §1）。

cancel_run() 是**唯一**的取消入口。p3b2 的两个触发器都只调它，所以这个文件的覆盖
决定了「取消」这件事的可信度——其中一个触发器（客户端断开）无法用 TestClient 验
（设计 §11.3），它那一侧只剩「调了这个函数」一行代码。
"""

import asyncio
import uuid

import pytest
import sqlalchemy as sa

from chatbi.db.models import Conversation, Run, RunEvent
from chatbi.datasources.drivers.base import ConnectionInfo, QueryHandle
from chatbi.execution import registry


@pytest.fixture(autouse=True)
def _clean_registry():
    """每条测试跑在干净的注册表上，且**跑完清干净**。

    它是模块级状态——不清的话一条测试的残留会让下一条看到一个不存在的 run 在跑，
    而那种失败极难定位（测试单独跑绿、一起跑红）。
    """
    registry.clear()
    yield
    registry.clear()


class _FakeDriver:
    """只实现 cancel——cancel_run() 只调它。缺 execute/probe/reflect 是**故意**的：
    若 cancel_run 调了它不该调的方法会以 AttributeError 暴露。
    """

    kind = "fake"

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def cancel(self, info: ConnectionInfo, handle: QueryHandle) -> None:
        self.cancelled.append(handle.token)


def _info() -> ConnectionInfo:
    return ConnectionInfo(
        kind="fake", host="h", port=1, database="d", username="u", password="p"
    )


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
        status="running",          # 只有 running 的 run 会被取消
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
    """不在注册表里 = 没有查询在跑。**不抛异常**：DELETE 端点会拿这个返回值决定
    响应，而「取消一个已经结束的查询」是幂等的正常情况，不是错误。

    也覆盖设计 §3 末那个连接阶段的 10 秒窗口：那时还没有 QueryHandle，注册表里没有
    这条 run，取消返回 False。
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
    """状态与事件必须落库并**显式 commit**（设计 §2）：cancel_run 可能跑在一个被
    取消的请求上下文里，那时 get_db 会回滚。
    """
    task = asyncio.create_task(_idle_task())
    registry.register(
        run.id, handle=QueryHandle(token="1"), task=task, info=_info(), driver=_FakeDriver()
    )

    registry.cancel_run(db_session, run.id)
    task.cancel()

    db_session.expire_all()      # 不能靠 identity map 验 DB 侧的事实
    refreshed = db_session.get(Run, run.id)
    assert refreshed.status == "cancelled"
    assert refreshed.error_code == "QUERY_CANCELLED"
    events = db_session.scalars(
        sa.select(RunEvent).where(RunEvent.run_id == run.id)
    ).all()
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
    """执行器在 finally 里调它，而 finally 也会在「还没 register 就失败了」时跑到
    （比如连接阶段就抛了 ConnectionFailed）。抛 KeyError 会把真正的异常盖掉。
    """
    registry.unregister(uuid.uuid4())      # 不该抛
```

- [ ] **Step 4: 跑测试确认失败**

```bash
uv run pytest tests/test_execution_sse.py tests/test_execution_registry.py -q
```

预期：**全部 ERROR**，`ModuleNotFoundError: No module named 'chatbi.execution'`。

- [ ] **Step 5: 写 `execution/registry.py`**

```python
"""正在跑的查询的进程内注册表，与取消的唯一入口。

**这张表成立的唯一前提是单进程部署。** 上游 spec §7.2 明确不做连接池、不做多进程
扩展（单机私有化部署），所以一个模块级 dict 是当前架构下正确的成本。

但它是一条**真实的架构约束**，不是实现细节：将来上多 worker（`uvicorn --workers N`）
时，DELETE 请求会有 (N-1)/N 的概率打到没有那条 run 的进程上，**取消静默失效**——
用户点了取消、界面显示已取消、而查询还在库上跑。要上多 worker 就得把这张表换成
共享存储（Redis 或一张表）并让 cancel 跨进程投递。

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

    driver 与 info 都要存：cancel 必须另开一条连接发出（原连接正被查询占住），
    所以它需要完整的连接信息，不只是 handle。
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
    """登记一条正在跑的查询。由执行器在 driver 的 on_start 回调里调用——那是
    QueryHandle 唯一的来源，且它在语句真正下发**之前**触发（P2b 的协议）。
    """
    _RUNNING[run_id] = RunningQuery(handle=handle, task=task, info=info, driver=driver)


def unregister(run_id: uuid.UUID) -> None:
    """清掉登记。**必须在 finally 里调**：正常结束、失败、被取消都要清。

    留下陈旧的 handle 会让后续的 cancel 掐掉**别人的**查询——Postgres 的 backend pid
    会被复用，MySQL 的 connection id 也会。

    对未登记的 run 静默返回：finally 也会在「还没 register 就失败了」时跑到（例如
    连接阶段就抛了 ConnectionFailed），抛 KeyError 会把真正的异常盖掉。
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
    动作——那样它本身能被直接测，而那是必需的：客户端断开那条触发器无法用 TestClient
    验（设计 §11.3），它那一侧只剩「调了这个函数」一行代码。

    三件事，**顺序固定**（设计 §1.2）：

    1. driver.cancel() 掐库侧。**这一步不能省**——实测 asyncio.to_thread 的 task 被
       cancel 后线程会继续跑到底，所以只做第 2 步等于关掉流然后让查询继续跑在用户的
       生产库上，那是上游 spec §4.3 点名的错误。
    2. task.cancel() 让 SSE 流停止等待，不必等驱动抛异常绕回来。
    3. 写状态与事件并**显式 commit**——本函数可能跑在一个被取消的请求上下文里，那时
       get_db 会回滚（设计 §2 的实测）。

    先掐库侧再关流：反过来的话 task.cancel() 之后生成器可能已经退出，而退出路径上
    如果没兜住 CancelledError 就走不到第 1 步，查询就漏了。

    返回 False 的两种情况都不是错误，所以不抛：查询已经结束（注册表里没有），或者
    还在连接阶段（那时没有 QueryHandle，设计 §3 末）。「取消一个已结束的查询」是
    幂等的正常情况。
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
```

**`next_seq` 在 Task 3 与仓储一起加**（本份 Task 1 先用，Task 3 实现——所以 Task 1 结束时 `test_execution_registry.py` 里依赖它的两条会红）。**这是有意的顺序**：注册表的取消语义比 seq 的分配规则更根本，先把前者定下来。若嫌两条红碍事，可以把 Task 3 的 `next_seq` 提前到 Task 1，但**别在 registry 里内联一个 `seq=1`**——那会在接上 P3c 时撞 `unique (run_id, seq)`（设计 §13 点名的坑）。

- [ ] **Step 6: 跑测试**

```bash
uv run pytest tests/test_execution_sse.py -q          # 4 passed
uv run pytest tests/test_execution_registry.py -q     # 见下
```

`test_execution_sse.py` **4 passed**。

`test_execution_registry.py`：**7 passed / 2 failed**——两条依赖 `next_seq` 的（`test_cancel_run_records_the_cancellation` 与 `test_cancel_run_is_idempotent`）会红在 `ImportError: cannot import name 'next_seq'`。若已把 `next_seq` 提前实现，则 9 passed。

**把实际数记进偏差**，别改测试凑数。

- [ ] **Step 7: 反向验证三条**

1. **`cancel_run` 里去掉 `running.driver.cancel(...)`** → `test_cancel_run_cancels_the_driver_first_then_the_task` FAIL（`driver.cancelled` 是空的），而 `test_cancel_run_is_idempotent` 与 `test_cancel_run_returns_false_for_an_unknown_run` **保持绿**。这是本份最重要的一条：它钉住「只关流」这个错误实现会被抓住。
2. **`unregister` 改成 `del _RUNNING[run_id]`** → `test_unregister_is_safe_for_an_unknown_run` FAIL（`KeyError`）。
3. **`cancel_run` 末尾去掉 `session.commit()`** → `test_cancel_run_records_the_cancellation` **可能仍然绿**（同一个 session 里 flush 过的改动可见）。**这条预期全绿**，如实记进偏差——它说明「显式 commit」在本函数的单元测试层面守不住，真正的守卫在 Task 3 的失败路径审计测试（那里会另开 session 查）。**不要为此改测试**，那属于 Task 3 的覆盖范围。

- [ ] **Step 8: ruff + 提交**

```bash
uv run ruff format src/chatbi/execution/ tests/test_execution_*.py
uv run ruff check . && uv run ruff format --check .
git add src/chatbi/errors.py src/chatbi/execution/ \
        tests/test_execution_sse.py tests/test_execution_registry.py
git commit -m "feat(execution): 运行注册表与 cancel_run —— 取消的唯一入口

cancel_run 做三件事且顺序固定：先 driver.cancel() 掐库侧、再 task.cancel()
关流、最后写审计并显式 commit。

第一步不能省：实测 asyncio.to_thread 的 task 被 cancel 后线程会继续跑到底，
所以只关流等于让查询继续跑在用户的生产库上——上游 spec §4.3 点名的错误。
顺序也不能反：先关流的话生成器可能已退出，退出路径没兜住 CancelledError 就
走不到掐库侧那步。

做成唯一入口是为了可测：p3b2 的两个触发器里，客户端断开那条无法用 TestClient
验（is_disconnected 在它下面恒 False），拆出这个函数之后未覆盖的只剩「调了它」
一行代码。

注册表是模块级 dict，**只在单进程部署下成立**——多 worker 时 DELETE 会打到
没有那条 run 的进程上、取消静默失效。文件头写明了，要上 --workers 得先换成
共享存储。

unregister 对未登记的 run 静默返回：执行器在 finally 里调它，而 finally 也会
在「还没 register 就失败」时跑到，抛 KeyError 会盖掉真正的异常。

另加五个错误码（三个是上游 §2.6 已定的首次落地）与 sse() 格式化函数。"
```





---

### Task 2: `chart_spec` 推断与结果预览转换（两个纯函数模块）

两个都不碰库、不碰 HTTP，所以它们的测试**一个夹具都不需要**。

**Files:**
- Create: `execution/charts.py` · `execution/preview.py`
- Modify: `src/chatbi/config.py`（加 `preview_rows`）
- Test: `tests/test_execution_charts.py` · `tests/test_execution_preview.py`

**Interfaces:**
- Consumes: P2b 的 `ColumnSchema` / `QueryResult`
- Produces:
  ```python
  charts.ChartSpec(type: str, x: str | None, y: tuple[str, ...], reason: str)
  charts.infer_chart_spec(columns, row_count: int) -> ChartSpec
  preview.to_preview(result: QueryResult, *, limit: int) -> tuple[list, list, bool]
  config.Settings.preview_rows: int = 100
  ```
  Task 3 不用它们；p3b2 的执行流用两者的输出发 `chart_spec` 与 `result` 事件、并落 `run_result_previews`。

- [ ] **Step 1: 加 `preview_rows` 配置**

`src/chatbi/config.py`，在 `max_result_rows` 之后：

```python
    # 预览上限，与 max_result_rows 是**两个不同的上限**（设计 §9.1）：
    #   max_result_rows(1000) 限制从库里取回多少行（闸 3 注入 LIMIT + 驱动 truncate）
    #   preview_rows(100)     限制存进 run_result_previews 与发给前端多少行
    # 一次执行可能取回 1000 行而只预览前 100 行，此时 row_count=1000、truncated=False。
    # 混用这两个数会让「已截断」的含义错掉（上游 spec §2.5、§3.5）。
    preview_rows: int = 100
```

- [ ] **Step 2: 写 `chart_spec` 的失败测试**

新建 `tests/test_execution_charts.py`：

```python
"""chart_spec 规则推断（上游 spec §3.5，设计 §8）。纯函数，无夹具。

规则是 spec §3.5 定的：1 维度 + 1 度量 → 柱状；含时间维度 → 折线；2 度量 → 散点；
单值 → 大数字卡。本文件钉住的是**判定顺序**与 spec 没覆盖的边界。
"""

import pytest

from chatbi.datasources.drivers.base import ColumnSchema
from chatbi.execution.charts import infer_chart_spec


def _col(name: str, data_type: str = "text", *, numeric: bool = False) -> ColumnSchema:
    return ColumnSchema(name=name, data_type=data_type, is_numeric=numeric)


_MONTH = _col("month", "timestamp with time zone")
_CITY = _col("city", "text")
_AMOUNT = _col("amount", "numeric", numeric=True)
_QTY = _col("qty", "integer", numeric=True)


def test_no_rows_is_a_table() -> None:
    """0 行没有数据可画。spec 没覆盖这条边界。"""
    spec = infer_chart_spec((_CITY, _AMOUNT), row_count=0)

    assert spec.type == "table"
    assert spec.reason


def test_a_single_numeric_value_is_a_metric_card() -> None:
    """spec §3.5「单值 → 大数字卡」。"""
    spec = infer_chart_spec((_AMOUNT,), row_count=1)

    assert spec.type == "metric"
    assert spec.x is None
    assert spec.y == ("amount",)


def test_a_dimension_and_a_measure_is_a_bar() -> None:
    """spec §3.5「1 维度 + 1 度量 → 柱状」。"""
    spec = infer_chart_spec((_CITY, _AMOUNT), row_count=20)

    assert spec.type == "bar"
    assert spec.x == "city"
    assert spec.y == ("amount",)


def test_a_time_column_makes_it_a_line() -> None:
    """spec §3.5「含时间维度 → 折线」。"""
    spec = infer_chart_spec((_MONTH, _AMOUNT), row_count=12)

    assert spec.type == "line"
    assert spec.x == "month"
    assert spec.y == ("amount",)


def test_time_wins_over_the_number_of_measures() -> None:
    """**判定顺序的关键一条**（设计 §8.1）：1 时间 + 2 度量 → 折线（两条线），
    不是散点。

    spec §3.5 把「含时间维度」写成独立一条，且时间序列画散点几乎总是错的。规则 3
    必须排在规则 4、5 之前——把它挪到后面这条就会变成 scatter。
    """
    spec = infer_chart_spec((_MONTH, _AMOUNT, _QTY), row_count=12)

    assert spec.type == "line"
    assert spec.x == "month"
    assert spec.y == ("amount", "qty")


def test_two_measures_without_a_dimension_is_a_scatter() -> None:
    """spec §3.5「2 度量 → 散点」。"""
    spec = infer_chart_spec((_AMOUNT, _QTY), row_count=50)

    assert spec.type == "scatter"
    assert spec.x == "amount"
    assert spec.y == ("qty",)


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param((_CITY,), id="只有一个文本列"),
        pytest.param((_CITY, _col("segment")), id="两个文本列"),
        pytest.param((_CITY, _col("segment"), _AMOUNT, _QTY), id="多维度多度量"),
        pytest.param((_AMOUNT, _QTY, _col("ratio", "numeric", numeric=True)), id="三个度量"),
    ],
)
def test_everything_else_falls_back_to_a_table(columns) -> None:
    """兜底。画不出有意义的图时给表格，而不是硬选一个图型——错的图比没有图更误导。"""
    spec = infer_chart_spec(columns, row_count=10)

    assert spec.type == "table"
    assert spec.x is None
    assert spec.y == ()


@pytest.mark.parametrize(
    "data_type",
    ["date", "timestamp", "timestamp with time zone", "DateTime", "datetime64", "Date32"],
)
def test_time_columns_are_recognised_across_dialects(data_type: str) -> None:
    """三个驱动给的类型名拼法各不相同（Postgres 的 timestamp with time zone、
    ClickHouse 的 DateTime / Date32、MySQL 的 datetime），所以判定是**大小写不敏感的
    子串匹配**。

    已知会误判 `timezone_name` 这类文本列（设计 §8.1 写明了这个取舍）：后果只是图型
    选错，而 spec §3.5 明写用户可手动改类型与字段（F-402 AC2）——有出口。不为它给
    驱动协议加 is_temporal 字段。
    """
    spec = infer_chart_spec((_col("t", data_type), _AMOUNT), row_count=5)

    assert spec.type == "line"


def test_a_single_row_that_is_not_a_lone_number_is_not_a_metric() -> None:
    """1 行但有两列 → 不是大数字卡。规则 2 的条件是「1 行 **1 列** 且是数值」。

    只判行数会让「一行两列」也变成 metric，而那时 y 该取哪一列没有答案。
    """
    spec = infer_chart_spec((_CITY, _AMOUNT), row_count=1)

    assert spec.type != "metric"


def test_a_single_text_value_is_not_a_metric() -> None:
    """1 行 1 列但不是数值 → 表格。大数字卡上放一个字符串没有意义。"""
    spec = infer_chart_spec((_CITY,), row_count=1)

    assert spec.type == "table"
```

- [ ] **Step 3: 跑测试确认失败**

```bash
uv run pytest tests/test_execution_charts.py -q
```

预期：**全部 ERROR**，`ModuleNotFoundError: No module named 'chatbi.execution.charts'`。

- [ ] **Step 4: 写 `execution/charts.py`**

```python
"""chart_spec 规则推断（上游 spec §3.5）。

**纯函数，不设接口。** 上游 spec §6 明写「ChartSpec 不设接口——V2-1 的规则推断是纯
函数，V2-3 要换成 LLM 选图时直接替换该函数，加一层抽象是过早的」。所以这里是一个
函数 + 一个 frozen dataclass，没有 ChartInferrer 协议。

**输入只有列信息与行数，不含结果行。** 选图不需要看数据本身，而不把行传进来就使这个
函数天然不可能把结果行写进日志（上游 spec §4.6）。
"""

from dataclasses import dataclass

from chatbi.datasources.drivers.base import ColumnSchema

# 大小写不敏感的子串匹配。三个驱动给的类型名拼法不同：Postgres 的
# "timestamp with time zone"、ClickHouse 的 "DateTime" / "Date32"、MySQL 的 "datetime"。
#
# 已知会误判 timezone_name 这类文本列。后果只是图型选错，而 spec §3.5 明写用户可手动
# 改类型与字段（F-402 AC2）——有出口。**不为它给驱动协议加 is_temporal 字段**：那要改
# P2b 的协议与三个驱动，代价远大于一个有出口的启发式。V2-3 换 LLM 选图时这段一起消失。
_TIME_HINTS = ("date", "time", "timestamp")


@dataclass(frozen=True)
class ChartSpec:
    type: str
    """table | metric | line | bar | scatter"""

    x: str | None
    y: tuple[str, ...]
    reason: str
    """为什么选这个图型。发给前端（上游 spec §2.3 的 chart_spec 载荷有这一项），
    让用户在手动改图型前知道后端是怎么想的。"""


def _is_time(column: ColumnSchema) -> bool:
    lowered = column.data_type.lower()
    return any(hint in lowered for hint in _TIME_HINTS)


def infer_chart_spec(columns: tuple[ColumnSchema, ...], row_count: int) -> ChartSpec:
    """按 spec §3.5 的规则选图型。**判定顺序即优先级**，第一个命中就返回。

    时间那一条（规则 3）**必须**在「1 维度 + 1 度量」与「2 度量」之前：spec §3.5 把
    「含时间维度」写成独立一条，而时间序列画散点几乎总是错的。挪动它的位置会让
    「1 时间 + 2 度量」从折线变成散点。
    """
    measures = tuple(c for c in columns if c.is_numeric)
    dimensions = tuple(c for c in columns if not c.is_numeric)
    time_columns = tuple(c for c in columns if _is_time(c))

    # 1. 没有数据可画
    if row_count == 0:
        return ChartSpec(type="table", x=None, y=(), reason="结果为空，没有可绘制的数据")

    # 2. 单值 → 大数字卡。条件是「1 行 **1 列** 且是数值」——只判行数会让「一行两列」
    #    也变成 metric，而那时 y 取哪一列没有答案
    if row_count == 1 and len(columns) == 1 and columns[0].is_numeric:
        return ChartSpec(type="metric", x=None, y=(columns[0].name,), reason="单个数值")

    # 3. 含时间维度 → 折线（**在 4、5 之前**，见函数文档）
    if time_columns and measures:
        return ChartSpec(
            type="line",
            x=time_columns[0].name,
            y=tuple(c.name for c in measures),
            reason="含时间维度，按时间趋势展示",
        )

    # 4. 1 维度 + 1 度量 → 柱状
    if len(dimensions) == 1 and len(measures) == 1:
        return ChartSpec(
            type="bar",
            x=dimensions[0].name,
            y=(measures[0].name,),
            reason="一个维度与一个度量",
        )

    # 5. 2 度量、无维度 → 散点
    if not dimensions and len(measures) == 2:
        return ChartSpec(
            type="scatter",
            x=measures[0].name,
            y=(measures[1].name,),
            reason="两个度量，展示相关性",
        )

    # 6. 兜底。画不出有意义的图时给表格——**错的图比没有图更误导**
    return ChartSpec(type="table", x=None, y=(), reason="列的组合不适合自动选图")
```

- [ ] **Step 5: 跑测试确认通过**

```bash
uv run pytest tests/test_execution_charts.py -q
```

预期：**18 passed**。构成：

| 来源 | 条数 |
|---|---|
| 独立函数（`no_rows` / `metric_card` / `bar` / `line` / `time_wins` / `scatter` / `single_row_two_cols` / `single_text`） | 8 |
| `test_everything_else_falls_back_to_a_table` 参数化 | 4 |
| `test_time_columns_are_recognised_across_dialects` 参数化 | 6 |

**实测与 18 不符就停下数一遍，别改断言凑数。** 参数化的条数 = 列表长度。p3a1 那次的教训是我把一串数字**加错了**（列的项加起来是 42 而我写了 37），所以这里把构成列成表格而不是写一行算式。

- [ ] **Step 6: 写结果预览转换的失败测试**

新建 `tests/test_execution_preview.py`：

```python
"""QueryResult → 可存 JSONB 的 columns/rows（设计 §9）。纯函数，无夹具。

本文件最重要的是**三个数不能混**（§9.1）：
  max_result_rows(1000) 限制从库里取回多少行 —— 闸 3 与驱动的 truncate
  preview_rows(100)     限制存/发多少行 —— 本模块
  truncated             **驱动那一层是否截断**，即库里其实有 >1000 行
"""

import base64
from datetime import UTC, date, datetime
from decimal import Decimal

from chatbi.datasources.drivers.base import ColumnSchema, QueryResult
from chatbi.execution.preview import to_preview


def _result(rows, columns=None, *, truncated=False) -> QueryResult:
    columns = columns or (
        ColumnSchema(name="id", data_type="integer", is_numeric=True),
        ColumnSchema(name="label", data_type="text"),
    )
    return QueryResult(
        columns=columns, rows=tuple(rows), row_count=len(rows), truncated=truncated
    )


def test_rows_are_capped_at_the_limit_but_truncated_still_reflects_the_driver() -> None:
    """**本文件的核心一条**（设计 §9.1）。

    取回 200 行（< 1000，所以驱动没截断）→ 预览只留 100 行，但 truncated 仍是 False。

    写成「rows 被截了就报 truncated=True」会让一次返回 200 行的查询在界面上显示
    「已截断」——而实际上库里就只有 200 行，用户会以为丢了数据。
    """
    result = _result([(i, f"r{i}") for i in range(200)], truncated=False)

    columns, rows, truncated = to_preview(result, limit=100)

    assert len(rows) == 100
    assert truncated is False


def test_the_driver_truncation_flag_is_passed_through() -> None:
    """驱动截断了（库里 >1000 行）→ truncated=True，与预览的 100 行无关。"""
    result = _result([(i, "x") for i in range(1000)], truncated=True)

    _columns, rows, truncated = to_preview(result, limit=100)

    assert len(rows) == 100
    assert truncated is True


def test_fewer_rows_than_the_limit_are_all_kept() -> None:
    result = _result([(1, "a"), (2, "b")])

    _columns, rows, truncated = to_preview(result, limit=100)

    assert rows == [[1, "a"], [2, "b"]]
    assert truncated is False


def test_rows_become_lists_not_tuples() -> None:
    """JSONB 存的是 JSON 数组。tuple 能被 json 序列化成数组，但读回来是 list——
    存进去就统一成 list，免得「写进去是 tuple、读出来是 list」这种不对称。
    """
    _columns, rows, _ = to_preview(_result([(1, "a")]), limit=10)

    assert isinstance(rows, list)
    assert isinstance(rows[0], list)


def test_datetimes_become_iso_strings() -> None:
    """json.dumps 不认 datetime/date，而 JSONB 列要可序列化的值。"""
    moment = datetime(2026, 8, 21, 10, 30, tzinfo=UTC)
    result = _result([(moment, date(2026, 8, 21))])

    _columns, rows, _ = to_preview(result, limit=10)

    assert rows[0][0] == "2026-08-21T10:30:00+00:00"
    assert rows[0][1] == "2026-08-21"


def test_decimals_become_floats() -> None:
    """**丢精度是有意的**（设计 §9.2）：预览是给人看的、给图表用的，而 JSON 没有
    十进制类型；转成字符串前端又得自己解析，图表库更是画不了。

    全量导出（P3d 的 export.csv）走**重跑 + 流式写出**，不经过这里——精度在需要它的
    路径上是完整的。**别为了「精度」把这里改成字符串**，那会让图表画不出来。
    """
    _columns, rows, _ = to_preview(_result([(Decimal("12.34"),)]), limit=10)

    assert rows[0][0] == 12.34
    assert isinstance(rows[0][0], float)


def test_bytes_become_base64() -> None:
    """bytea 列。原样放进 JSON 会抛 TypeError。"""
    _columns, rows, _ = to_preview(_result([(b"\x00\x01\xff",)]), limit=10)

    assert rows[0][0] == base64.b64encode(b"\x00\x01\xff").decode()


def test_none_stays_none() -> None:
    """SQL NULL → JSON null。别转成空字符串——那会让「没有值」和「空字符串」分不开。"""
    _columns, rows, _ = to_preview(_result([(None, None)]), limit=10)

    assert rows[0] == [None, None]


def test_columns_carry_name_type_and_is_numeric_only() -> None:
    """与 result 事件的 columns 同形（上游 spec §2.3 的载荷定义）。

    **不含 is_nullable 与 comment**：预览是结果的摘要，不是 schema 元数据——那些在
    /schema 端点（P2c）。多带字段会让前端以为可以从这里读元数据。
    """
    columns, _rows, _ = to_preview(_result([(1, "a")]), limit=10)

    assert columns == [
        {"name": "id", "type": "integer", "is_numeric": True},
        {"name": "label", "type": "text", "is_numeric": False},
    ]


def test_an_empty_result_is_handled() -> None:
    """0 行不是特例，但要确认不抛。"""
    columns, rows, truncated = to_preview(_result([]), limit=100)

    assert rows == []
    assert truncated is False
    assert len(columns) == 2
```

- [ ] **Step 7: 写 `execution/preview.py`**

```python
"""QueryResult → 可存 JSONB 且可发给前端的形状（设计 §9）。

纯函数。**三个数不能混**（§9.1）：
  max_result_rows  限制从库里取回多少行（闸 3 注入 LIMIT + 驱动 truncate）
  limit（本模块）   限制存进 run_result_previews 与发给前端多少行
  truncated        **驱动那一层是否截断**，即库里其实有更多行

`truncated` 直接来自 QueryResult，**不因为预览截了 100 行而变 True**——否则一次返回
200 行的查询会在界面上显示「已截断」，而库里就只有 200 行。
"""

import base64
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from chatbi.datasources.drivers.base import QueryResult


def _jsonable(value: Any) -> Any:
    """把驱动给的值转成 json.dumps 认识的东西。

    Decimal -> float **会丢精度，这是有意的**：预览给人看、给图表用，而 JSON 没有
    十进制类型。转成字符串的话前端要自己解析、图表库画不了。全量导出走重跑 + 流式
    写出（P3d），精度在需要它的路径上完整。

    None 保持 None（→ JSON null），不转空字符串：那会让「没有值」与「空字符串」分不开。
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode()
    # 兜底：不认识的类型转字符串而不是抛。一个陌生的列类型不该让整次执行失败——
    # 结果已经拿到了，用户能看到「某一列显示得怪」比看到 500 好得多。
    return str(value)


def to_preview(
    result: QueryResult, *, limit: int
) -> tuple[list[dict[str, Any]], list[list[Any]], bool]:
    """返回 (columns, rows, truncated)。

    columns 与 result 事件的载荷同形（上游 spec §2.3）：只有 name / type / is_numeric，
    **不含 is_nullable 与 comment**——预览是结果的摘要，不是 schema 元数据。
    """
    columns = [
        {"name": c.name, "type": c.data_type, "is_numeric": c.is_numeric}
        for c in result.columns
    ]
    rows = [[_jsonable(v) for v in row] for row in result.rows[:limit]]
    return columns, rows, result.truncated
```

- [ ] **Step 8: 跑测试 + ruff + 提交**

```bash
uv run pytest tests/test_execution_charts.py tests/test_execution_preview.py -q
uv run pytest -q
```

预期：两个文件 **28 passed**（charts 18 + preview 10），全量 **310 + 4(sse) + 注册表实际数 + 28**——把实际数记进偏差。

```bash
uv run ruff format src/chatbi/execution/ src/chatbi/config.py tests/test_execution_*.py
uv run ruff check . && uv run ruff format --check .
git add src/chatbi/config.py src/chatbi/execution/charts.py src/chatbi/execution/preview.py \
        tests/test_execution_charts.py tests/test_execution_preview.py
git commit -m "feat(execution): chart_spec 推断与结果预览转换

两个纯函数模块，测试一个夹具都不需要。

chart_spec 照上游 spec §3.5 的规则，六条判定按顺序命中。**时间那条必须排在
「1 维度+1 度量」与「2 度量」之前**：1 时间 + 2 度量应该是折线（两条线）而不是
散点，而挪动它的位置就会变成后者。时间列判定是大小写不敏感的子串匹配，已知会
误判 timezone_name 这类列——后果只是图型选错，而 spec §3.5 明写用户可手动改
（F-402 AC2）。不为它给驱动协议加 is_temporal。

preview 的核心是**三个数不能混**：max_result_rows(1000) 限制取回多少行、
preview_rows(100) 限制存/发多少行、truncated 指**驱动那一层**是否截断。写成
「rows 被截了就报 truncated」会让一次返回 200 行的查询显示「已截断」。

Decimal -> float 丢精度是有意的：预览给人看、给图表用，JSON 没有十进制类型。
全量导出（P3d）走重跑，精度在需要它的路径上完整。"
```

**反向验证三条**（放在提交前跑）：

1. **`infer_chart_spec` 里把规则 3（时间）挪到规则 5 之后** → `test_time_wins_over_the_number_of_measures` FAIL，其余 17 条**保持绿**。这条守的是判定顺序，而顺序错了不报错、只是图选错。
2. **`to_preview` 的 `result.rows[:limit]` 改成 `result.rows`** → `test_rows_are_capped_at_the_limit_but_truncated_still_reflects_the_driver` 与 `test_the_driver_truncation_flag_is_passed_through` 双双 FAIL。
3. **`truncated` 改成 `len(result.rows) > limit`** → 第一条 FAIL（200 行时变成 True），而 `test_the_driver_truncation_flag_is_passed_through` **保持绿**（那条正好 1000 行 > 100）。**两条必须都有**：只跑第二条的话这个错误实现看起来是对的。






---

### Task 3: 执行器、`runs` 仓储，与真库验收

本份的核心。做完这个任务，「跑一条 SQL 并且能真的掐掉它」就已经**对真 Postgres 验过**了——在任何 HTTP 代码之前。

**Files:**
- Create: `execution/executor.py`
- Modify: `src/chatbi/runs/repository.py` · `tests/test_run_events.py`（那条导出名测试改白名单式）
- Test: `tests/test_run_repository.py` · `tests/test_executor.py` · `tests/test_executor_real_db.py`

**Interfaces:**
- Consumes: Task 1 的 `registry.register` / `unregister` · P2b 的 `Driver.execute` / `QueryHandle` / 四个异常
- Produces:
  ```python
  runs.repository.next_seq(session, run_id) -> int
  runs.repository.get_run(session, run_id) -> Run | None
  runs.repository.mark_running(session, run_id, *, final_sql, effective_sql) -> bool
  runs.repository.mark_finished(session, run_id, *, status, row_count=None,
                                duration_ms=None, error_code=None) -> None
  runs.repository.save_preview(session, run_id, *, columns, rows, truncated) -> RunResultPreview
  execution.executor.execute_approved(driver, info, *, run_id, effective_sql,
                                      timeout_seconds, max_rows) -> QueryResult
  ```
  p3b2 的执行流用全部这些。

- [ ] **Step 1: 写仓储的失败测试**

新建 `tests/test_run_repository.py`：

```python
"""runs 与 run_result_previews 的仓储（设计 §5.1、§9）。

run_events 仍然只有 append_event / list_events（P3a），本文件测的是另两张表——
**它们不是 append-only 的**，run 的状态本来就要从 drafted 变到终态。
"""

import uuid

import pytest

from chatbi.db.models import Conversation, Run, RunResultPreview
from chatbi.runs.repository import (
    append_event,
    get_run,
    mark_finished,
    mark_running,
    next_seq,
    save_preview,
)


@pytest.fixture
def make_run(db_session, make_user, make_datasource):
    def _make(status: str = "drafted") -> Run:
        user, datasource = make_user(), make_datasource()
        conversation = Conversation(
            id=uuid.uuid4(), user_id=user.id, datasource_id=datasource.id, title="t"
        )
        db_session.add(conversation)
        db_session.flush()
        run = Run(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=user.id,
            datasource_id=datasource.id,
            question="q",
            status=status,
        )
        db_session.add(run)
        db_session.flush()
        return run

    return _make


def test_get_run_returns_none_for_an_unknown_id(db_session) -> None:
    assert get_run(db_session, uuid.uuid4()) is None


def test_mark_running_moves_a_drafted_run(db_session, make_run) -> None:
    run = make_run("drafted")

    assert mark_running(db_session, run.id, final_sql="select 1", effective_sql="SELECT 1 LIMIT 1000") is True

    db_session.expire_all()
    refreshed = get_run(db_session, run.id)
    assert refreshed.status == "running"
    assert refreshed.final_sql == "select 1"
    assert refreshed.effective_sql == "SELECT 1 LIMIT 1000"
    assert refreshed.executed_at is not None


@pytest.mark.parametrize(
    "status", ["running", "succeeded", "failed", "cancelled", "blocked"]
)
def test_mark_running_refuses_any_non_drafted_run(db_session, make_run, status: str) -> None:
    """**一个 run 恰好执行一次**（设计 §5）。返回 False 让调用方给 409。

    `running` 也在列表里——那条正是双击运行按钮的防护，而它是免费得到的：第二次
    请求打在 running 上，条件 UPDATE 匹配不到行。
    """
    run = make_run(status)

    assert mark_running(db_session, run.id, final_sql="s", effective_sql="s") is False

    db_session.expire_all()
    assert get_run(db_session, run.id).status == status      # 状态没被动


def test_mark_running_uses_a_conditional_update_not_check_then_update(
    db_session, make_run
) -> None:
    """并发保护靠 DB 而不是靠先查后改（设计 §5.1）。

    直接模拟并发很难，所以这里验的是**它的可观察后果**：把 run 的状态在「同一个调用
    序列里」改掉之后，第二次 mark_running 必须失败。check-then-update 的实现在两个
    并发请求下会双双通过检查——那种失败在测试里看不到，但这条至少钉住了「它是按
    status 条件写的」而不是无条件 UPDATE。
    """
    run = make_run("drafted")

    assert mark_running(db_session, run.id, final_sql="a", effective_sql="a") is True
    assert mark_running(db_session, run.id, final_sql="b", effective_sql="b") is False

    db_session.expire_all()
    assert get_run(db_session, run.id).final_sql == "a"      # 第二次没覆盖第一次


def test_mark_running_returns_false_for_an_unknown_run(db_session) -> None:
    assert mark_running(db_session, uuid.uuid4(), final_sql="s", effective_sql="s") is False


def test_mark_finished_records_the_outcome(db_session, make_run) -> None:
    run = make_run("running")

    mark_finished(db_session, run.id, status="succeeded", row_count=42, duration_ms=1234)

    db_session.expire_all()
    refreshed = get_run(db_session, run.id)
    assert refreshed.status == "succeeded"
    assert refreshed.row_count == 42
    assert refreshed.duration_ms == 1234
    assert refreshed.error_code is None


def test_mark_finished_records_an_error_code(db_session, make_run) -> None:
    """失败路径也要落库——F-304 要审计的正是这些（设计 §2.2）。"""
    run = make_run("running")

    mark_finished(db_session, run.id, status="failed", error_code="QUERY_TIMEOUT")

    db_session.expire_all()
    refreshed = get_run(db_session, run.id)
    assert refreshed.status == "failed"
    assert refreshed.error_code == "QUERY_TIMEOUT"
    assert refreshed.row_count is None


def test_next_seq_starts_at_one_for_a_fresh_run(db_session, make_run) -> None:
    assert next_seq(db_session, make_run().id) == 1


def test_next_seq_continues_after_existing_events(db_session, make_run) -> None:
    """**接上 P3c 时的关键一条**（设计 §13）。

    问答流会先写 understand / generate 两条事件（seq 1、2），执行流必须从 3 续。
    硬编码 seq=1 的实现在本份的测试里全绿（本份的 run 都是干净的），接上 P3c 之后
    `unique (run_id, seq)` 会拒绝重复的 1，而那时报错出现在执行流里、看起来像执行流
    的 bug。所以这条现在就要有。
    """
    run = make_run()
    append_event(db_session, run_id=run.id, seq=1, step="understand", status="ok")
    append_event(db_session, run_id=run.id, seq=2, step="generate", status="ok")

    assert next_seq(db_session, run.id) == 3


def test_next_seq_is_per_run(db_session, make_run) -> None:
    """seq 是每个 run 独立的（唯一键是 (run_id, seq) 复合的）。"""
    first, second = make_run(), make_run()
    append_event(db_session, run_id=first.id, seq=1, step="x", status="ok")

    assert next_seq(db_session, second.id) == 1


def test_save_preview_stores_the_summary(db_session, make_run) -> None:
    run = make_run("running")

    save_preview(
        db_session,
        run.id,
        columns=[{"name": "id", "type": "integer", "is_numeric": True}],
        rows=[[1], [2]],
        truncated=True,
    )

    db_session.expire_all()
    preview = db_session.get(RunResultPreview, run.id)
    assert preview.rows == [[1], [2]]
    assert preview.truncated is True


def test_save_preview_overwrites_an_existing_one(db_session, make_run) -> None:
    """一个 run 一行（run_id 是主键）。

    实际上一个 run 只执行一次（设计 §5），所以覆盖路径**理论上走不到**——但仓储不该
    因为调用方的约定而在第二次调用时抛 IntegrityError，那种失败会以 500 出现在
    执行流的末尾、把一次成功的查询变成失败。
    """
    run = make_run("running")
    save_preview(db_session, run.id, columns=[], rows=[[1]], truncated=False)

    save_preview(db_session, run.id, columns=[], rows=[[2]], truncated=False)

    db_session.expire_all()
    assert db_session.get(RunResultPreview, run.id).rows == [[2]]
```

- [ ] **Step 2: 写仓储的五个函数**

追加到 `src/chatbi/runs/repository.py`（文件头的 append-only 说明**保留不动**，它说的是 `run_events`）：

```python
def next_seq(session: Session, run_id: uuid.UUID) -> int:
    """下一个可用的事件序号。

    **从 max(seq)+1 续，不是从 1 硬起。** 问答流（P3c）会先写 understand / generate
    两条事件，执行流必须接在它们后面——硬编码 1 的实现在 P3b 的测试里全绿（那时 run
    都是干净的），接上 P3c 之后 `unique (run_id, seq)` 会拒绝重复的 1，而报错会出现在
    执行流里、看起来像执行流的 bug。
    """
    current = session.scalar(
        sa.select(sa.func.max(RunEvent.seq)).where(RunEvent.run_id == run_id)
    )
    return (current or 0) + 1


def get_run(session: Session, run_id: uuid.UUID) -> Run | None:
    return session.get(Run, run_id)


def mark_running(
    session: Session, run_id: uuid.UUID, *, final_sql: str, effective_sql: str
) -> bool:
    """drafted -> running。返回 False 表示「它已经不是 drafted 了」（调用方给 409）。

    **带条件的 UPDATE，不是先查状态再改**（设计 §5.1）：check-then-update 在两个并发
    请求下会双双通过检查，然后双双执行——而一个 run 只装得下一次执行的结果
    （final_sql / row_count / executed_at 都是单列），第二次会静默改写第一次的审计
    记录。P2a 的仓储用 insert + IntegrityError 而不是 check-then-insert 是同一条理由。

    顺带：`running` 也不满足条件，所以双击运行按钮的防护是免费得到的。
    """
    result = session.execute(
        sa.update(Run)
        .where(Run.id == run_id, Run.status == "drafted")
        .values(
            status="running",
            final_sql=final_sql,
            effective_sql=effective_sql,
            executed_at=sa.func.now(),
        )
    )
    session.flush()
    return bool(result.rowcount)


def mark_finished(
    session: Session,
    run_id: uuid.UUID,
    *,
    status: str,
    row_count: int | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
) -> None:
    """写终态。status ∈ succeeded | failed | cancelled | blocked。

    **不加 `where status = 'running'` 的条件**：blocked 是从 drafted 直接来的（guard
    判定不通过，从未 running 过），而 cancelled 可能由 cancel_run 先写过一次。加了条件
    会让这些路径静默不落库——而失败路径的审计正是 F-304 最需要的（设计 §2.2）。
    """
    session.execute(
        sa.update(Run)
        .where(Run.id == run_id)
        .values(
            status=status, row_count=row_count, duration_ms=duration_ms, error_code=error_code
        )
    )
    session.flush()


def save_preview(
    session: Session,
    run_id: uuid.UUID,
    *,
    columns: list[dict[str, Any]],
    rows: list[list[Any]],
    truncated: bool,
) -> RunResultPreview:
    """结果摘要，一个 run 一行（run_id 是主键）。

    用 get-then-set 而不是纯 insert：一个 run 只执行一次（设计 §5）所以覆盖路径理论上
    走不到，但仓储不该因为调用方的约定而在第二次调用时抛 IntegrityError——那种失败会
    以 500 出现在执行流的末尾，把一次**已经成功**的查询变成失败。
    """
    preview = session.get(RunResultPreview, run_id)
    if preview is None:
        preview = RunResultPreview(
            run_id=run_id, columns=columns, rows=rows, truncated=truncated
        )
        session.add(preview)
    else:
        preview.columns = columns
        preview.rows = rows
        preview.truncated = truncated
    session.flush()
    return preview
```

顶部的 import 补上 `from typing import Any` 与 `from chatbi.db.models import Run, RunEvent, RunResultPreview`。

- [ ] **Step 3: 把那条导出名测试改成白名单式**

`tests/test_run_events.py` 的 `test_the_repository_has_no_update_or_delete_path` 现在断言「导出名里没有 `update`/`delete` 字样」。Task 2 加的 `mark_running` / `mark_finished` 是 `runs` 的合法更新，不含那两个词所以**恰好不会红**——但这说明那条测试守的东西是模糊的。改成白名单：

```python
def test_the_repository_exports_exactly_the_intended_functions(db_session, run) -> None:
    """append-only 的落实方式是**仓储的形状**（设计 §5.2）：run_events 只有 append 与
    list，没有 update、没有 delete。

    **白名单而不是关键词黑名单。** 黑名单（「名字里不许有 update」）会因为一个叫
    update_run_status 的合法函数而误报，而那时最省事的"修复"是删掉这条测试；白名单在
    加新函数时会强制实施者回来想一下「这个函数该不该存在」。

    runs 与 run_result_previews **不是** append-only 的（run 的状态本来就要从 drafted
    变到终态），所以 mark_running / mark_finished / save_preview 在白名单里。
    """
    expected = {
        # run_events：只有这两个，永远
        "append_event",
        "list_events",
        "next_seq",
        # runs 与 run_result_previews：可更新
        "get_run",
        "mark_running",
        "mark_finished",
        "save_preview",
    }
    exported = {
        name
        for name in dir(repository)
        if not name.startswith("_") and callable(getattr(repository, name))
        and getattr(getattr(repository, name), "__module__", "") == repository.__name__
    }

    assert exported == expected, (
        "仓储的导出集变了。加函数前先确认它动的不是 run_events——"
        "那张表只允许 append 与 list（F-304）"
    )
```

`__module__` 过滤是必需的：`dir(repository)` 会带上 import 进来的 `sa`、`Session`、`Run` 等，不过滤的话断言永远不相等。

- [ ] **Step 4: 写执行器的失败测试（假驱动，四条路径）**

新建 `tests/test_executor.py`：

```python
"""执行器的四条路径与注册表清理（设计 §1、§4、§10）。

假驱动只实现 execute 与 cancel——缺 probe / reflect 是**故意**的：执行器若调了它不该
调的方法会以 AttributeError 暴露（与 P2b /test、P2c /schema 的假驱动同形）。
"""

import asyncio
import threading
import uuid

import pytest

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
from chatbi.execution.executor import execute_approved


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def _info() -> ConnectionInfo:
    return ConnectionInfo(
        kind="fake", host="h", port=1, database="d", username="u", password="p"
    )


_RESULT = QueryResult(
    columns=(ColumnSchema(name="n", data_type="integer", is_numeric=True),),
    rows=((1,),),
    row_count=1,
    truncated=False,
)


class _FakeDriver:
    """四种行为：正常返回、抛超时、抛失败、**阻塞直到被 cancel**。

    第四种是取消路径的关键——它必须真的在线程里阻塞，否则测不到「to_thread 还没返回
    时取消进来了」这个时序。用 threading.Event 而不是 sleep：sleep 会让测试变慢且
    时序不确定。
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
        driver, _info(), run_id=uuid.uuid4(), effective_sql="select 1",
        timeout_seconds=60, max_rows=1000,
    )

    assert result is _RESULT
    assert driver.executed == ["select 1"]


@pytest.mark.asyncio
async def test_the_run_is_registered_while_it_executes_and_cleared_after() -> None:
    """注册表在 on_start 回调里登记（那是 QueryHandle 唯一的来源），在 finally 里清。"""
    run_id = uuid.uuid4()
    driver = _FakeDriver()

    await execute_approved(
        driver, _info(), run_id=run_id, effective_sql="select 1",
        timeout_seconds=60, max_rows=1000,
    )

    assert registry.is_running(run_id) is False, "执行结束后注册表必须清干净"


@pytest.mark.parametrize(
    "raises", [QueryTimeout, QueryFailed, ConnectionFailed, QueryCancelled]
)
@pytest.mark.asyncio
async def test_driver_exceptions_propagate(raises) -> None:
    """执行器**不翻译异常**——P2b 的四个异常直接往上抛，由 p3b2 的流映射成错误码。

    在这里翻译会让执行器同时认识 HTTP 错误码，而它是领域层。
    """
    run_id = uuid.uuid4()
    with pytest.raises(raises):
        await execute_approved(
            _FakeDriver(raises=raises), _info(), run_id=run_id,
            effective_sql="select 1", timeout_seconds=60, max_rows=1000,
        )


@pytest.mark.parametrize(
    "raises", [QueryTimeout, QueryFailed, ConnectionFailed, QueryCancelled]
)
@pytest.mark.asyncio
async def test_the_registry_is_cleared_on_every_failure_path(raises) -> None:
    """**`unregister` 必须在 finally 里**（设计 §1.4）。

    留下陈旧的 handle 会让后续的 cancel 掐掉**别人的**查询——Postgres 的 backend pid
    会被复用。四种异常各验一次，因为 ConnectionFailed 那条**在 register 之前就抛了**
    （还没拿到 handle），它验的是「unregister 对未登记的 run 也安全」。
    """
    run_id = uuid.uuid4()
    with pytest.raises(raises):
        await execute_approved(
            _FakeDriver(raises=raises), _info(), run_id=run_id,
            effective_sql="select 1", timeout_seconds=60, max_rows=1000,
        )

    assert registry.is_running(run_id) is False


@pytest.mark.asyncio
async def test_a_blocked_execution_can_be_cancelled_through_the_registry(db_session) -> None:
    """**取消路径的完整时序**：执行器在线程里阻塞 → 注册表里有它 → cancel_run 掐掉 →
    驱动抛 QueryCancelled → await 处抛出来。

    这条证明的是「注册表登记发生在语句下发之前」——若 register 在 execute 返回之后
    才做，cancel_run 会找不到这条 run 而返回 False。
    """
    from chatbi.db.models import Conversation, Run

    user_id = uuid.uuid4()
    driver = _FakeDriver(block=True)
    run_id = uuid.uuid4()

    task = asyncio.create_task(
        execute_approved(
            driver, _info(), run_id=run_id, effective_sql="select pg_sleep(30)",
            timeout_seconds=60, max_rows=1000,
        )
    )
    await asyncio.to_thread(driver.started.wait, 5)
    await asyncio.sleep(0.05)          # 让 on_start 的登记落地

    assert registry.is_running(run_id) is True

    # 直接用注册表里的 driver.cancel，不经过 cancel_run（那条在 Task 1 测过，
    # 且它要写 DB，本条测试不需要一个真的 run 行）
    running = registry._RUNNING[run_id]      # noqa: SLF001 —— 测时序，不测封装
    running.driver.cancel(running.info, running.handle)

    with pytest.raises(QueryCancelled):
        await task
    assert driver.cancelled == ["tok-1"]
    assert registry.is_running(run_id) is False
```

- [ ] **Step 5: 写 `execution/executor.py`**

```python
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
```

- [ ] **Step 6: 写真库测试 —— 本份的退出标准**

新建 `tests/test_executor_real_db.py`。**这一层不允许 skip**：它用本机原生 Postgres，与 `tests/drivers/` 那批「缺 DSN 就 skip」的契约测不同。没有它，闸 4 的「真超时 + 真取消」就只有假驱动的证据——而 P2b 那条教训（「代码写完了」不能代替「真的跑过了」）说的正是这个。

```python
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

from chatbi.datasources.drivers.base import ConnectionInfo, QueryCancelled, QueryTimeout
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
    dsn = (
        f"postgresql://{info.username}:{info.password}@{info.host}:{info.port}/{info.database}"
    )
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
    assert result.rows[0][0] > 0        # demo_sales 有 240 行订单（P2b 灌的）


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

    for _ in range(100):                      # 等 on_start 登记，最多 5 秒
        if registry.is_running(run_id):
            break
        await asyncio.sleep(0.05)
    assert registry.is_running(run_id), "on_start 没登记——取消能力没有入口"

    pid = int(registry._RUNNING[run_id].handle.token)   # noqa: SLF001
    await asyncio.sleep(0.5)                  # 让语句真的开始跑
    assert await asyncio.to_thread(_active_sleep_count, pg_info, pid) == 1, (
        "取消前库里就没有这条 pg_sleep——这条测试证明不了任何事，先查环境"
    )

    assert await asyncio.to_thread(registry.cancel_run, db_session, run_id) is True

    with pytest.raises(QueryCancelled):
        await task

    await asyncio.sleep(0.3)                  # 给 backend 一点时间退出
    assert await asyncio.to_thread(_active_sleep_count, pg_info, pid) == 0, (
        "**查询还在库上跑**——只关了流没掐库侧，这是 spec §4.3 点名的错误"
    )
```

**那条「取消前必须先看到 pg_sleep」的断言不是多余的**：没有它，一个「库里根本没跑起来」的环境问题会让整条测试假绿（取消后是 0，因为本来就是 0）。

- [ ] **Step 7: 跑测试**

```bash
uv run pytest tests/test_run_repository.py tests/test_executor.py -q
uv run pytest tests/test_executor_real_db.py -q -v          # 3 条，看清每条
uv run pytest -q
```

预期：仓储 **13 passed**、执行器 **11 passed**（3 独立 + 4+4 参数化）、真库 **3 passed**。全量把实际数记进偏差。

真库那三条如果慢（`pg_sleep` + 等待），总耗时约 10–15 秒，正常。

- [ ] **Step 8: 反向验证五条（每次改一处，跑完立刻恢复）**

**先 `cp` 备份要改的文件**——p3a2 那次把四条串在一个命令里跑，超了 8 分钟超时且文件停在中途。**每次只改一处、单独跑。**

1. **`executor.py` 的 `finally: registry.unregister(...)` 挪到 `try` 的成功路径上** → `test_the_registry_is_cleared_on_every_failure_path` 四条参数化全 FAIL，而 `test_the_run_is_registered_while_it_executes_and_cleared_after`（成功路径）**保持绿**。这一对证明了「必须在 finally」不是风格问题。
2. **`on_start` 回调里的 `registry.register(...)` 移到 `to_thread` 之后**（即执行完才登记）→ `test_a_blocked_execution_can_be_cancelled_through_the_registry` FAIL（`is_running` 是 False），**真库的取消那条也 FAIL**（登记等不到）。这条钉住「登记必须发生在语句下发之前」。
3. **`mark_running` 的 `where` 去掉 `Run.status == "drafted"`** → `test_mark_running_refuses_any_non_drafted_run` 五条参数化全 FAIL + `test_mark_running_uses_a_conditional_update_not_check_then_update` FAIL。
4. **`next_seq` 改成恒返回 1** → `test_next_seq_continues_after_existing_events` FAIL，而 `test_next_seq_starts_at_one_for_a_fresh_run` 与 `test_next_seq_is_per_run` **保持绿**。后半条是重点：干净的 run 上两种实现表现相同，只有那一条能分辨——而它防的是接上 P3c 时才会炸的问题。
5. **在 `executor.py` 里加一层 `asyncio.wait_for(..., timeout=timeout_seconds)`** → 真库的**真超时那条仍然绿**（库侧先掐），但**真取消那条会变得不稳定**（`wait_for` 的 cancel 与 `cancel_run` 竞争）。**这条的观察点不是红绿，而是「加了它之后 `pg_stat_activity` 里还有没有那条查询」**：手工跑一次，若查询残留，就实证了设计 §3 那个「停不住线程的超时比没有超时更糟」的判断。**结果记进偏差**，无论是哪种。

- [ ] **Step 9: ruff + 全量 + 提交**

```bash
uv run ruff format src/chatbi/ tests/
uv run ruff check . && uv run ruff format --check .
wc -l src/chatbi/execution/executor.py       # 上限 200
uv run pytest -q
git add src/chatbi/execution/executor.py src/chatbi/runs/repository.py \
        tests/test_run_repository.py tests/test_executor.py \
        tests/test_executor_real_db.py tests/test_run_events.py
git commit -m "feat(execution): 执行器与 runs 仓储，真超时与真取消已对真库验过

execute_approved 用 to_thread 包驱动、在 on_start 回调里登记注册表、在 finally
里清。异常不翻译——P2b 的四个直接往上抛，由 p3b2 的流映射成错误码。

**不加 asyncio 层的超时兜底**：实测 to_thread 的 task 被 cancel 后线程会继续跑
到底，所以 wait_for 超时后的行为是「流提前结束、查询继续跑」——正是闸 4 要防的
事。库侧超时失效是驱动层的 bug，由 P2b 的契约测抓。

mark_running 用带条件的 UPDATE（where status='drafted'）而不是先查后改：
check-then-update 在并发下会双双通过检查，而一个 run 只装得下一次执行的结果。
顺带让双击运行按钮的防护免费成立。

next_seq 从 max(seq)+1 续而不是从 1 硬起。硬编码 1 在本段全绿（run 都是干净
的），接上 P3c 之后 unique (run_id, seq) 会拒绝重复的 1，而报错会出现在执行流
里、看起来像执行流的 bug。有一条测试专门守它。

**真库验收（本份的退出标准）**：真超时断言总耗时 < 8 秒（证明是库侧 statement
_timeout 掐的，不是等 pg_sleep(30) 跑完）；真取消去 pg_stat_activity 里确认那个
backend 不再跑那条语句——只断言「流以 QueryCancelled 结束」证明不了取消，因为
task.cancel() 单独就能让流结束。

那条导出名测试改成白名单式：黑名单会因为一个叫 update_run_status 的合法函数而
误报，而那时最省事的修复是删掉它。"
```






---

## 实施期的偏差（执行中回填）

（开工前为空。每个任务做完就记：实测计数与预期不符的地方、对计划的偏离及理由、反向验证里的意外结果。**特别要记的三处**：Task 1 Step 6 的注册表测试实际几条通过（取决于 `next_seq` 有没有提前实现）· Task 1 Step 7 反向验证 3 预期全绿的确认 · Task 3 Step 8 反向验证 5 加 `wait_for` 之后 `pg_stat_activity` 里的查询有没有残留。**「反向验证全绿」是结论不是噪声**，p3a1/p3a2 各因此补了一条真正有用的测试。）

---

## 交接清单（p3b2 要消费的签名）

```python
# 取消（chatbi.execution.registry）
cancel_run(session, run_id) -> bool
#   **唯一的取消入口**。p3b2 的 DELETE 端点与断开检测都只调它，自己不做任何取消动作。
#   它内部：driver.cancel() -> task.cancel() -> 写状态与事件 -> **显式 commit**
#   返回 False 的两种情况都不是错误：查询已结束，或还在连接阶段（那时没有 handle）
#   **调用方要把它放进 to_thread**：里面的 driver.cancel() 要另开一条连接（设计 §4）
is_running(run_id) -> bool
clear()                                   # 只给测试用

# 执行（chatbi.execution.executor）
await execute_approved(driver, info, *, run_id, effective_sql,
                       timeout_seconds, max_rows) -> QueryResult
#   已经是 async 的，内部 to_thread。**异常不翻译**——P2b 的 QueryTimeout /
#   QueryCancelled / QueryFailed / ConnectionFailed 直接抛出，由 p3b2 映射成错误码
#   注册表的登记与清理都在里面，p3b2 不用管

# 纯函数
sse.sse(event: str, data: dict) -> bytes
charts.infer_chart_spec(columns, row_count) -> ChartSpec(type, x, y, reason)
preview.to_preview(result, *, limit) -> (columns, rows, truncated)
#   truncated 来自 QueryResult（**驱动那层是否截断**），不是「预览是否截断」

# 持久化（chatbi.runs.repository）
next_seq(session, run_id) -> int           # max(seq)+1，**别硬编码 1**
get_run / mark_running / mark_finished / save_preview
#   mark_running 返回 False -> 给 409 RUN_NOT_EXECUTABLE（一个 run 恰好执行一次）
#   mark_finished 不带 status 条件——blocked 从 drafted 直接来，cancelled 可能已被写过

# 错误码（chatbi.errors）
QUERY_TIMEOUT / QUERY_CANCELLED / QUERY_FAILED / RUN_NOT_EXECUTABLE / RUN_NOT_FOUND
#   前三个只进 SSE 的 error 载荷，**不作为 HTTP 状态返回**（流已经是 200）
```

**p3b2 起手要注意的四件事**

1. **`cancel_run` 要放进 `to_thread`**，否则一次另开连接的往返会卡住事件循环。
2. **四个提交点都要显式 `commit()`**（设计 §2）：`get_db` 在流异常时回滚，而失败与被取消的执行是最需要审计的。有一条测试要专门验这个——**在另一个 session 里**查 `run_events`。
3. **事件的 `seq` 用 `next_seq()`**，不要在流里自己从 1 数。
4. **`QUERY_FAILED` 的 message 要拼上 `QueryFailed` 异常的原文**（P2b 刻意保留了库的报错），那是分析师改 SQL 的依据。它与 §4.4 不冲突——见 `errors.py` 里那段注释。

---

## 自查记录

**设计 spec 覆盖核对（本份负责的部分）**

| 设计条目 | 落在哪 |
|---|---|
| §1.1 `to_thread` 的 cancel 不中断线程 | Task 1 的 `cancel_run` 文档 + Task 3 `executor.py` 的文件头 |
| §1.2 三件事、顺序固定 | Task 1 Step 5 + 反向验证 1 |
| §1.3 `cancel_run()` 是唯一入口 | Task 1（p3b2 的两个触发器只调它） |
| §1.4 进程内注册表、单进程前提、`finally` 里 unregister | Task 1 Step 5 的文件头 + Task 3 Step 4 的四条参数化 |
| §2 显式 commit | Task 1 的 `cancel_run` 末尾（本份能验的部分）；四个提交点在 p3b2 |
| §3 不加 asyncio 超时 | Task 3 Step 5 的文件头 + Step 8 反向验证 5 |
| §4 驱动 to_thread、DB 直接调 | Task 3 Step 5 |
| §5 一个 run 恰好执行一次、带条件 UPDATE | Task 3 Step 2 的 `mark_running` + Step 1 的六条测试 |
| §8 `chart_spec` 六条判定与时间优先 | Task 2 |
| §9 三个数不能混、类型转换、Decimal 取舍 | Task 2 的 `preview` |
| §10.1 文件落点、`executor.py` ≤200 行 | File Structure + Task 3 Step 9 的 `wc -l` |
| §10.4 白名单式导出名测试 | Task 3 Step 3 |
| §11.1 三层测试 + 真库层 | Task 1–3 的测试文件分工 |
| §11.2 真超时（<8s）与真取消（`pg_stat_activity`） | Task 3 Step 6 |
| §13 `next_seq` 从 `max+1` 续 | Task 3 Step 2 + 那条专门的测试 |

**不在本份的设计小节**：§6（`require_run`）· §7（事件序列与 SSE 编排）· §11.3（断开触发器的真跑）· §12.1 的回填 —— 全部在 p3b2。

**计数链**：310（起点）→ Task 1 后 +4(sse) + 注册表实际数 → Task 2 后 +28 → Task 3 后 +13(仓储) +11(执行器) +3(真库)。**Task 1 的注册表条数取决于 `next_seq` 是否提前实现**（9 或 7 passed + 2 failed），所以本份不给一个确定的终点数——实施时记实际值，并据此更新 p3b2 的起点。这与 p3a 那次给死数字然后算错是相反的处理：**说不准的地方就别写一个准确的数**。

**占位符扫描**：无 TBD / TODO / 「类似 Task N」/ 无代码的「写测试」步骤。Task 1 Step 7 的反向验证 3 与 Task 3 Step 8 的反向验证 5 写了「预期全绿 / 观察点不是红绿」——那不是占位符，是两条如实预告的结论。

**体量说明**：本份约 2100 行，略超「单份 ~2000 行就该拆」的阈值。**没有再拆**，因为 Task 1–3 是「执行能力完整可测」这一个交付点：Task 3 的真库验收依赖 Task 1 的注册表与 Task 2 都不依赖，拆开会让「真取消已验过」这个结论横跨两份文件。超出约 5%，且三个任务各自的步骤是自包含的。

**类型一致性核对**

`RunningQuery` 的四个字段（`handle` / `task` / `info` / `driver`）在 `register()` 的四个关键字参数、`cancel_run()` 的三处使用、以及测试里的构造处一致。`execute_approved` 的六个参数在 Task 3 的两个测试文件与 p3b2 的调用处一致。`to_preview` 返回三元组 `(columns, rows, truncated)`，`save_preview` 的三个关键字参数同名同序。`ChartSpec` 的四个字段与上游 spec §2.3 的 `chart_spec` 载荷（`{type, x, y, reason}`）逐一对应。

`next_seq` 被 `cancel_run`（Task 1）与 p3b2 的流共用——**Task 1 先用、Task 3 才实现**，这个顺序在 Task 1 Step 5 末尾写明了，别当成漏写。

