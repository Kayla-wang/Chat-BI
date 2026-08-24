# Chat-BI V2-1 · P3c1 基座、LLM 层与 chips Implementation Plan

> **P3c 按体量拆成三份**（超 2000 行就该拆文件）。任务编号连续，跨文件说「Task N」不歧义：
> - **本份 p3c1（Task 1–4）**：`generating` 状态与配置基座 · `llm/`（协议 + fake + ollama）· `pipeline/chips.py`。做完这一份，**问答的「理解」那一半已经能穷举测，而一个 token 都还没生成过**。
> - **p3c2（Task 5–8）**：`semantics/`（选表 + token 预算 + 装配）· `pipeline/prompt.py` · `pipeline/draft.py` · `pipeline/ask.py` 编排。做完后端**一行 HTTP 问答代码都没有**，管线只能在测试里调（这是有意的，验证上游 spec §1.3 的边界规则）。
> - **p3c3（Task 9–11）**：`POST /api/ask` 的端点与事件序列 · 四个提交点 · 断开收尾 · **真 Ollama 端到端**（P3c 的退出标准）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把一句中文问题变成一份带注释的 SQL 草稿，全程只调一次 LLM，且不碰 HTTP。

**Architecture:** 两块加一个基座。`llm/` 是 async 的提供方协议（ollama + fake），取消靠「生成器被取消 → 关连接」而不是注册表——这是它与 P2b 同步驱动的有意差异。`pipeline/chips.py` 是确定性的意图匹配（**不调 LLM**），毫秒级返回，它是「一次 LLM 调用」那个决定的落地。基座是 `generating` 状态、三个错误码与七个 LLM 配置项。

**Tech Stack:** Python 3.12 · httpx（已在依赖里，P2c 的 TestClient 用它）· sqlglot 30.17.0 · pydantic-settings · pytest + pytest-asyncio · Alembic

## Global Constraints

**不新增依赖。** `httpx` 已在（`fastapi.testclient` 依赖它），`sqlglot` 已在（P3a）。**不要装 jieba 或任何分词器**——chips 用双向子串匹配，理由见设计 §4.2。

**`pipeline/` 与 `semantics/` 与 `llm/` 都不 import fastapi。** 管线要能脱离 HTTP 测（与 p3b1 的 `execution/` 同一条约定）。`errors.py` 例外：它自身 import fastapi，但那是错误契约不是框架依赖（P2a 起就接受了这一点），本份只有 Task 1 会碰它。

**`llm` 与 `semantics` 不知道彼此**（上游 spec §1.3 规则 3）。pipeline 负责装配。谁要是在 `llm/` 里 import `semantics/`，V2-2 换语义层时就要动 LLM 层。

**只调一次 LLM。** 全流程唯一一次调用在 p3c2 的 `run_ask`（Task 8）。本份的责任是给它备好守卫：`FakeLLMProvider.calls` 这个计数器（Task 2）就是那条约束的唯一凭据，它防的是将来有人「顺手把 understand 也交给 LLM」而没人发现总时长翻倍（本机 4.1 tok/s，一次调用 20 秒）。**本份的 chips 匹配一次 LLM 都不调**，这是同一条约束的另一半。

**时间与随机都要显式传参。** `today: date` 是参数不是 `date.today()`。理由与 P2b 驱动的 `timeout_seconds`、P3a guard 的 `max_rows` 一致：语义相关的纯函数不要隐式依赖全局状态，否则跨年边界测不了。

**每个任务的反向验证都要写明「哪几条转红、哪几条必须保持绿」**，两者都要核对。**「反向验证全绿」也是一个结论**（说明那条路径没有守卫），如实记进偏差，不要改测试去凑——p3a1/p3a2/p3b1/p3b2 各因此补了一条真正有用的测试。

**`ruff check` 与 `ruff format --check` 都必须干净。** 新代码写完先跑一次 `ruff format`，别攒到提交前（p3a1、p3a2、p3b1 各踩过一次）。

**自动化测试一律用 `FakeLLMProvider`**（上游 spec §5.1）。本份**不跑真 Ollama**——那是 p3c3 的退出标准。`ollama.py` 自己的测试用 `httpx.MockTransport`，不连真服务。

## 本机环境

```bash
# apps/api 下，每个任务开工前 export 这三个
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
```

- 原生 PostgreSQL 16。**本份不需要 Docker、不需要 Ollama。**
- 跑测试用 `.venv/Scripts/python.exe -m pytest`（`uv run` 也行）。**注意 pytest 会 `alembic downgrade base` 清空 `chatbi_test`**。
- 起点：**405 passed / 28 skipped**（P3b 完成时的读数，commit `cc9f47c`）。

## File Structure

### 本份创建的文件

| 文件 | 职责 | 任务 |
|---|---|---|
| `migrations/versions/0006_run_generating.py` | `ck_runs_status` 加第七个值 `generating` | 1 |
| `apps/api/src/chatbi/llm/__init__.py` | 空 | 2 |
| `apps/api/src/chatbi/llm/base.py` | `LLMProvider` 协议 + `LLMTimeout` / `LLMUnavailable` | 2 |
| `apps/api/src/chatbi/llm/fake.py` | `FakeLLMProvider`，五种可配置行为 | 2 |
| `apps/api/src/chatbi/llm/registry.py` | `name → provider`，读 `Settings` | 2 |
| `apps/api/src/chatbi/llm/ollama.py` | httpx 流式 + 两个超时 | 3 |
| `apps/api/src/chatbi/pipeline/__init__.py` | 空 | 4 |
| `apps/api/src/chatbi/pipeline/chips.py` | `match_chips` + 中文时间词表（纯函数） | 4 |
| `apps/api/tests/test_llm_fake_and_registry.py` | 假实现的五种行为 + provider 选择 | 2 |
| `apps/api/tests/test_llm_ollama.py` | 请求体、流式解析、两个超时（`MockTransport`） | 3 |
| `apps/api/tests/test_pipeline_chips.py` | 匹配规则 + 时间词边界（无夹具） | 4 |

### 本份修改的文件

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/db/models.py` | `RUN_STATUSES` 加 `generating` | 1 |
| `apps/api/tests/test_run_models.py` | 那条一致性测试的 `== 6` 改 `== 7` | 1 |
| `apps/api/src/chatbi/errors.py` | 加 `LLM_TIMEOUT` / `LLM_UNAVAILABLE` / `SCHEMA_UNAVAILABLE` | 1 |
| `apps/api/src/chatbi/config.py` | 加七个 LLM 配置项 | 1 |

### 本份不碰的东西

`api/` 下任何文件 · `ALL_ROUTERS` · `execution/` · `guard/` · `runs/` · `datasources/` · `semantics/` · `pipeline/` 下除 `chips.py` 以外的文件 —— **上下文装配与 prompt 在 p3c2，`POST /api/ask` 与它的鉴权、事件序列、四个提交点在 p3c3。**

**尤其别在本份提前写 `semantics/`**：Task 4 的 `resolved_tables` 是它的输入，而那个契约要等 chips 的测试全绿才算定下来。提前写会让两边的假设互相迁就。

### 边界说明

**`chips.py` 吃 `SchemaSnapshot` + notes 映射，不吃 P2c 的 `SchemaResponse`**：后者是 Pydantic HTTP 响应模型，让领域层认识它等于让它依赖 HTTP 契约。`merge_schema()`（`schema_view.py`）产出的正是那个 HTTP 模型，所以本份**不复用它**，直接吃 `SchemaSnapshot` 与 `Mapping[tuple[str,str,str], str]`——与 `merge_schema` 自己吃的东西一样。p3c2 的 `semantics/` 同理。

**`resolved_tables` 是本份对 p3c2 的唯一契约**：`"schema.table"` 形式，与 `metadata.known_identifiers()` 的第三种形式一致（p3c2 要拿它去断言白名单）。**空元组是一个有意义的信号**（「一张都没命中」），p3c2 的兜底策略依赖它——所以 Task 4 不许在没命中时返回全部表，那会让下游分不清「命中了全部」与「什么都没命中」。

**失败一律抛异常，不返回错误码**：`LLMTimeout` / `LLMUnavailable` 往上抛，由 p3c3 映射成错误码。领域层不认识 HTTP 词汇（与 p3b1 的执行器同一条约定，那份的文件头写了理由）。

---

### Task 1: 基座 —— `generating` 状态、三个错误码、七个配置项

**Files:**
- Create: `apps/api/migrations/versions/0006_run_generating.py`
- Modify: `apps/api/src/chatbi/db/models.py`（`RUN_STATUSES`）· `apps/api/src/chatbi/errors.py` · `apps/api/src/chatbi/config.py`
- Test: `apps/api/tests/test_run_models.py`（改一条）· `apps/api/tests/test_config.py`（加一条）

**Interfaces:**
- Produces:
  ```python
  RUN_STATUSES  # 七个值，含 "generating"
  errors.LLM_TIMEOUT / LLM_UNAVAILABLE / SCHEMA_UNAVAILABLE   # (code, message, status) 三元组
  Settings.llm_provider / llm_model / llm_base_url / llm_first_token_timeout
         / llm_total_timeout / llm_keep_alive / llm_prompt_token_budget
  ```

- [ ] **Step 1: 改那条一致性测试，让它先红**

`tests/test_run_models.py` 里 `test_the_status_constant_matches_the_check_constraint` 的最后一行：

```python
    assert len(RUN_STATUSES) == 7
```

同时在 `RUN_STATUSES` 里加 `"generating"`（`src/chatbi/db/models.py`）：

```python
RUN_STATUSES: tuple[str, ...] = (
    "generating",  # 草稿正在生成（P3c）。放第一个：它是 run 的起点状态
    "drafted",
    "blocked",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)
```

**先改常量再改 migration 是有意的顺序**：这样那条一致性测试会以「DB 拒绝了 `generating`」的形式失败，而那正是它存在的理由（常量加了新状态但 CHECK 没改，错误会出现在别处）。

- [ ] **Step 2: 跑测试确认它红**

```bash
.venv/Scripts/python.exe -m pytest tests/test_run_models.py -q
```

预期：`test_the_status_constant_matches_the_check_constraint` FAIL，报 `IntegrityError` 提到 `ck_runs_status`。**不是 AssertionError**——如果是 AssertionError（`== 7` 没过），说明常量没改成功。

- [ ] **Step 3: 写 migration 0006**

`apps/api/migrations/versions/0006_run_generating.py`：

```python
"""run 的 generating 状态

Revision ID: 0006
Revises: 0005

草稿生成期间的状态（P3c 设计 §7）。加它而不是复用现有状态的三条理由：
状态机诚实（被断开的问答流能记成 generating -> cancelled）· 免费收紧执行入口
（P3b 的「非 drafted 一律 409」自动拦住「草稿还在流就点运行」）· P3d 的历史列表
需要它才能正确渲染。

CHECK 用字面量而不是引用 db.models.RUN_STATUSES —— migration 是历史快照，不该在
将来因为那个常量被改而改变含义（与 0005 同一条约定）。两者一致由
tests/test_run_models.py 钉住。
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_OLD = "status in ('drafted','blocked','running','succeeded','failed','cancelled')"
_NEW = (
    "status in ('generating','drafted','blocked','running','succeeded','failed','cancelled')"
)


def upgrade() -> None:
    op.drop_constraint("ck_runs_status", "runs", type_="check")
    op.create_check_constraint("ck_runs_status", "runs", _NEW)


def downgrade() -> None:
    # 先把 generating 的行清成 failed，否则旧 CHECK 建不上去。
    # 语义是对的：一条停在 generating 的 run 没有草稿，回退后它确实是失败的。
    op.execute(sa.text("update runs set status = 'failed' where status = 'generating'"))
    op.drop_constraint("ck_runs_status", "runs", type_="check")
    op.create_check_constraint("ck_runs_status", "runs", _OLD)
```

`downgrade` 里那条 `update` 不是可选的：**`downgrade base` 是测试夹具每次都跑的路径**，留着 `generating` 的行会让下一次 `pytest` 在建约束时炸掉，而报错出现在夹具里、看起来与本次改动无关（p2c1 踩过同形的坑：改 `upgrade`/`downgrade` 不对称会把测试库弄坏）。

- [ ] **Step 4: 跑测试确认转绿**

```bash
.venv/Scripts/python.exe -m pytest tests/test_run_models.py -q
```

预期：全绿。夹具会先 `downgrade base` 再 `upgrade head`，所以 0006 会被真的跑一遍。

- [ ] **Step 5: 加三个错误码**

`src/chatbi/errors.py` 末尾（`RUN_NOT_FOUND` 之后）：

```python
# 问答流（上游 spec §2.6 列了前两个，第三个是 P3c 新增）。三个都**只出现在 SSE 的
# error 事件载荷里**，不作为 HTTP 状态返回——流已经是 200 了。状态码那一位只用于让
# ApiError 元组形状一致（与闸 4 那批同一条约定，见上）。
LLM_TIMEOUT = ("LLM_TIMEOUT", "模型响应超时，请重试", 504)
LLM_UNAVAILABLE = ("LLM_UNAVAILABLE", "模型服务不可用，请检查推理服务是否已启动", 503)
# **不要挪用 LLM_UNAVAILABLE 表示这件事**（P3c 设计 §9.2）：「数据源还没拉过表结构」
# 与模型无关，用 LLM 的码会让用户去查 Ollama 而问题在数据源页。文案要能指路。
SCHEMA_UNAVAILABLE = ("SCHEMA_UNAVAILABLE", "该数据源尚未拉取表结构，请先在数据源页刷新", 409)
```

`LLM_TIMEOUT` 的 `message` 由调用方拼得更具体（「模型未在 60 秒内响应」vs「生成超过 180 秒已中止」，见 Task 3）——运维要靠那句话判断是服务没起来还是模型跑飞了。

- [ ] **Step 6: 加七个配置项**

`src/chatbi/config.py` 的 `Settings` 里，`preview_rows` 之后：

```python
    # ---- LLM（P3c 设计 §3.5、§5.2）----
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:8b"
    llm_base_url: str = "http://127.0.0.1:11434"
    # **两个超时不是一个**（设计 §3.2）：上游 spec §4.5 的单一 30s 已被实测推翻。
    #   首 token 迟迟不来 = 模型在加载或服务不可达。本机冷启动含模型加载实测 36s，
    #     而模型被换出内存后还会再发生，所以给 60s。
    #   首 token 来了之后 = 模型在正常吐字只是慢（实测 4.1 tok/s），这时要管的是
    #     「别无限吐下去」（进入重复循环时会一直生成），180s 约容得下 700 token。
    # 单一超时无论取什么值都同时对这两件事说话：30s 则冷启动必然误报，180s 则
    # 「服务根本没起来」也要等 3 分钟才告诉用户。
    llm_first_token_timeout: float = 60.0
    llm_total_timeout: float = 180.0
    # 让模型常驻内存，避免 36s 冷启动反复落在用户头上。内存紧张的部署要能调小，
    # 所以它是配置而不是硬编码。
    llm_keep_alive: str = "30m"
    # prompt 的 token 预算（设计 §5.2）。超了就砍表，**并在 warnings 里写明砍了几张**
    # ——静默截断的表现是「SQL 是垃圾但没人知道为什么」。
    llm_prompt_token_budget: int = 6000
```

- [ ] **Step 7: 加一条配置测试**

`tests/test_config.py` 加：

```python
def test_the_llm_timeouts_are_two_separate_knobs(monkeypatch) -> None:
    """**两个超时必须能分别配**（P3c 设计 §3.2）。

    合成一个值的实现在这条测试上会红。它守的不是「有没有默认值」，而是「首 token 与
    总时长是两件不同的事」这个判断——上游 spec §4.5 的单一 30s 已被实测推翻（本机
    冷启动 36s，单一 30s 会让冷启动必然误报超时）。
    """
    monkeypatch.setenv("CHATBI_SECRET_KEY", "s3cret")
    monkeypatch.setenv("CHATBI_LLM_FIRST_TOKEN_TIMEOUT", "5")
    monkeypatch.setenv("CHATBI_LLM_TOTAL_TIMEOUT", "7")

    settings = Settings()

    assert settings.llm_first_token_timeout == 5.0
    assert settings.llm_total_timeout == 7.0


def test_the_llm_defaults_match_the_measured_numbers() -> None:
    """默认值就是设计 §0.1 那组实测数字推出来的，改它们要先重测。"""
    settings = Settings(secret_key="s3cret")

    assert settings.llm_first_token_timeout == 60.0  # 覆盖 36s 冷启动
    assert settings.llm_total_timeout == 180.0  # 4.1 tok/s 下约 700 token
    assert settings.llm_provider == "ollama"
```

**用 `Settings()` 直接构造，不要用 `get_settings()`**：后者是 `lru_cache`，在测试里读它要清两次缓存（前面不清读不到 monkeypatch 的值，后面不清会把值泄给同进程后面的测试）。`tests/test_config.py` 里现有的五条测试全部直接构造 `Settings()`，跟着它们走。

`CHATBI_SECRET_KEY` 必须设（或作为构造参数传）：`Settings` 有个 `model_validator` 在缺主密钥时抛 `ValueError`，不设它这条测试会以一个跟 LLM 无关的错误失败。

- [ ] **Step 8: 跑测试 + ruff + 提交**

```bash
.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_run_models.py -q
.venv/Scripts/python.exe -m ruff format src/chatbi/ tests/ && .venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pytest -q
```

预期全量 **407 passed / 28 skipped**（405 + 两条新配置测试；`== 7` 那条是改的不是加的）。实际数记进偏差。

```bash
git add apps/api/migrations/versions/0006_run_generating.py apps/api/src/chatbi/db/models.py \
        apps/api/src/chatbi/errors.py apps/api/src/chatbi/config.py \
        apps/api/tests/test_run_models.py apps/api/tests/test_config.py
git commit -m "feat(runs): generating 状态、LLM 错误码与配置

runs.status 加第七个值 generating（migration 0006）。它让状态机诚实（被断开的
问答流记成 generating -> cancelled），且免费收紧了执行入口——P3b 的「非 drafted
一律 409」自动拦住「草稿还在流就点运行」，执行端点一行不用改。

downgrade 里先把 generating 的行清成 failed：downgrade base 是测试夹具每次都跑的
路径，留着那些行会让下一次 pytest 在建旧约束时炸掉，而报错出现在夹具里。

两个 LLM 超时而不是一个（上游 spec §4.5 的单一 30s 已被实测推翻）：首 token 60s
覆盖 36s 冷启动，总时长 180s 兜住模型跑飞。两种失败的含义不同，单一值无论取多少
都同时对两件事说话。

SCHEMA_UNAVAILABLE 是新码：数据源没拉过表结构与模型无关，挪用 LLM_UNAVAILABLE
会让用户去查 Ollama 而问题在数据源页。"
```

---

### Task 2: `llm/` 的协议、假实现与注册表

**Files:**
- Create: `src/chatbi/llm/__init__.py`（空）· `src/chatbi/llm/base.py` · `src/chatbi/llm/fake.py` · `src/chatbi/llm/registry.py`
- Test: `tests/test_llm_fake_and_registry.py`

**Interfaces:**
- Consumes: Task 1 的 `Settings.llm_*`
- Produces:
  ```python
  llm.base.LLMProvider          # Protocol: name, model, stream(prompt, *, first_token_timeout, total_timeout)
  llm.base.LLMTimeout(kind)     # kind ∈ {"first_token", "total"}
  llm.base.LLMUnavailable
  llm.fake.FakeLLMProvider(*, chunks=(), stall=False, endless=False, raises=None, chunk_delay=0.0)
  llm.fake.FakeLLMProvider.calls: int
  llm.registry.get_provider(settings) -> LLMProvider
  ```

- [ ] **Step 1: 写 `llm/base.py`**

```python
"""LLMProvider 协议与它的三个失败。

**这一层是 async 的，与 P2b 的数据库驱动有意不同型**（P3c 设计 §3.1）。驱动是同步的、
由执行器包 to_thread，因为 psycopg / pymysql / clickhouse-connect 没有可用的 async
实现；而 LLM 就是一个 HTTP 接口，httpx 原生支持 async 流式读。这个差异买到两件事：

1. **省掉线程与事件循环之间的胶水。** 同步实现要把 token 从线程送回事件循环，得自己
   接一个 queue + 哨兵值，而那层胶水在取消时有真实的坑——p3b1 实测过「to_thread 的
   task 被 cancel 后线程会继续跑到底」。
2. **取消是免费的。** 生成器被取消 → httpx 关连接 → Ollama 自己停止生成。**不需要
   注册表、不需要另开一条连接发取消**——对比 execution/registry.py，那整个模块都是
   为了「掐掉库侧查询」而存在的。

**别把这一层「顺手统一成同步」**：那会把上面第 2 条免费的取消变成一个要重新造注册表
的问题。

只 import 标准库——与 drivers/base.py 同一条约定：协议层在没装 httpx 的环境里也能
import 成功，registry 的惰性加载依赖这一点。
"""

from collections.abc import AsyncIterator
from typing import Protocol


class LLMError(Exception):
    """LLM 层全部失败的共同基类。调用方用一个 except 兜住它。"""


class LLMTimeout(LLMError):
    """两个超时之一（设计 §3.2）。

    kind 区分它们，因为**两种失败的运维含义完全不同**：`first_token` 说明模型在加载
    或服务不可达（本机冷启动含模型加载实测 36s），`total` 说明模型在正常吐字但跑飞了
    （进入重复循环时会一直生成）。message 要能让人一眼分辨——出问题时运维手上往往
    只有这一句话。
    """

    def __init__(self, kind: str, seconds: float) -> None:
        if kind not in ("first_token", "total"):
            raise ValueError(f"kind 只能是 first_token 或 total，收到 {kind!r}")
        self.kind = kind
        self.seconds = seconds
        message = (
            f"模型未在 {seconds:g} 秒内响应"
            if kind == "first_token"
            else f"生成超过 {seconds:g} 秒已中止"
        )
        super().__init__(message)


class LLMUnavailable(LLMError):
    """连不上推理服务，或它返回了错误状态。

    **消息不带 base_url**：与 P2b 的 ConnectionFailed 同一条（spec §4.4，地址端口进
    服务端日志、不进响应）。它连一个能塞地址的入口都不给，这样「顺手把 url 拼进
    消息里」这件事做不到。
    """

    def __init__(self) -> None:
        super().__init__("模型服务不可用")


class LLMProvider(Protocol):
    """一次性的文本生成。**只有一个方法**——本段不需要对话历史、不需要函数调用。

    name / model 落进 runs.llm_provider 与 runs.llm_model（spec §4.6 要求每次 run 记下
    用了哪个模型，否则「同一个问题上周还能出对 SQL」这类问题无法排查）。
    """

    name: str
    model: str

    def stream(
        self, prompt: str, *, first_token_timeout: float, total_timeout: float
    ) -> AsyncIterator[str]:
        """流式吐出文本片段。**片段不保证是完整 token 或完整行**，调用方自己拼。

        两个超时都是**必传关键字参数**，不给默认值：与 P2b 驱动的 timeout_seconds 同
        一条约定——安全或体验相关的参数不要让调用方「忘了传就用一个隐含的默认」。

        抛 LLMTimeout（两种 kind）或 LLMUnavailable，不抛别的。
        """
        ...
```

- [ ] **Step 2: 写 `llm/fake.py`**

```python
"""确定性的假 provider。**自动化测试一律用它**（上游 spec §5.1）。

三个旋钮覆盖五种要测的行为——旋钮比行为少是有意的，每个旋钮都对应一件真实会发生的事：

| 要测的路径 | 怎么配 |
|---|---|
| 正常出草稿 | `chunks=("select 1",)` |
| 首 token 超时 | `raises=LLMTimeout("first_token", 60)` |
| 吐了一半才超时 | `chunks=(...), raises_after=LLMTimeout("total", 180)` |
| 模型跑偏出垃圾 | `chunks=("这是一段说明文字，不是 SQL",)` |
| 服务不可用 | `raises=LLMUnavailable()` |

**缺 embed / chat 之类方法是故意的**（与 P2b、p3b1 的假驱动同形）：管线若调了协议之外
的方法，会以 AttributeError 暴露而不是静默走一条没设计过的路。

**不睡真实的时间**：超时行为用「直接抛 LLMTimeout」模拟。真的 await 一个 60 秒的 sleep
会让测试跑 60 秒，而超时**机制**本身该由 ollama.py 自己的测试守（Task 3 用
httpx.MockTransport）。这里要测的是「管线拿到 LLMTimeout 之后怎么办」。
"""

from collections.abc import AsyncIterator, Iterable

from chatbi.llm.base import LLMError


class FakeLLMProvider:
    name = "fake"

    def __init__(
        self,
        *,
        chunks: Iterable[str] = ("select 1",),
        model: str = "fake-model",
        raises: LLMError | None = None,
        raises_after: LLMError | None = None,
    ) -> None:
        self.model = model
        self._chunks = tuple(chunks)
        self._raises = raises
        self._raises_after = raises_after
        self.calls = 0
        self.prompts: list[str] = []
        """每次调用的 prompt 原文。测试靠它断言 prompt 里有什么、没有什么。"""

    async def stream(
        self, prompt: str, *, first_token_timeout: float, total_timeout: float
    ) -> AsyncIterator[str]:
        self.calls += 1
        self.prompts.append(prompt)
        if self._raises is not None:
            raise self._raises
        for chunk in self._chunks:
            yield chunk
        if self._raises_after is not None:
            raise self._raises_after
```

**`calls` 这个计数器是本份一条约束的守卫**：全流程只调一次 LLM（见 Global Constraints）。Task 8 有一条测试断言 `== 1`。

- [ ] **Step 3: 写 `llm/registry.py`**

```python
"""name → provider。与 datasources/registry.py 同形（惰性 import）。

**「可插拔」的证据是这个文件加一条测试**（设计 §1.2、§3.5）。上游 spec §1.2 还列了
openai_compatible.py，本份**不做**：本机没有 OpenAI 兼容端点可验，而一份跑不过的
provider 比没有更糟——它会让「可插拔」看起来已经被证明。要接云端 LLM 时再加，那时有
端点可验。这一处偏离记在 P3c 设计 §12。
"""

from chatbi.config import Settings
from chatbi.llm.base import LLMProvider


def get_provider(settings: Settings) -> LLMProvider:
    """按配置造一个 provider。

    **settings 是显式参数不是 get_settings()**：测试要能喂不同配置而不动环境变量，
    与 P2b 驱动的 timeout_seconds、P3a guard 的 max_rows 同一条约定。

    惰性 import：`llm/base.py` 只 import 标准库，所以在没装 httpx 的环境里 import 本
    模块也不会炸——只有真的要 ollama 时才会碰 httpx。
    """
    if settings.llm_provider == "fake":
        from chatbi.llm.fake import FakeLLMProvider

        return FakeLLMProvider(model=settings.llm_model)
    # Task 3 在这里加 ollama 分支。**在那之前默认配置会走到下面那行 ValueError**，
    # 这是有意的：本份分任务提交，一个只认识 fake 的注册表比一个 import 不存在模块的
    # 注册表更容易定位问题。
    raise ValueError(f"未知的 LLM provider：{settings.llm_provider}")
```

- [ ] **Step 4: 写测试**

`tests/test_llm_fake_and_registry.py`：

```python
"""假 provider 的五种行为 + provider 选择（P3c 设计 §3.4、§3.5）。

无夹具：这一层不碰库、不碰 HTTP。
"""

import pytest

from chatbi.config import Settings
from chatbi.llm.base import LLMTimeout, LLMUnavailable
from chatbi.llm.fake import FakeLLMProvider
from chatbi.llm.registry import get_provider

_TIMEOUTS = {"first_token_timeout": 1.0, "total_timeout": 2.0}


async def _collect(provider: FakeLLMProvider) -> str:
    return "".join([chunk async for chunk in provider.stream("p", **_TIMEOUTS)])


@pytest.mark.asyncio
async def test_the_fake_yields_its_chunks_in_order() -> None:
    provider = FakeLLMProvider(chunks=("select ", "city ", "from t"))

    assert await _collect(provider) == "select city from t"
    assert provider.calls == 1
    assert provider.prompts == ["p"]


@pytest.mark.asyncio
async def test_the_fake_can_fail_before_the_first_chunk() -> None:
    """首 token 超时：一个 token 都没吐出来。管线在这条路径上不该产出任何草稿。"""
    provider = FakeLLMProvider(raises=LLMTimeout("first_token", 60))

    with pytest.raises(LLMTimeout) as excinfo:
        await _collect(provider)

    assert excinfo.value.kind == "first_token"
    assert "60" in str(excinfo.value)


@pytest.mark.asyncio
async def test_the_fake_can_fail_after_some_chunks() -> None:
    """**吐了一半才超时**——这是最难处理的一条路径（设计 §9.3：半截稿不落库但前端
    不清空）。收到的片段必须能被调用方看见，异常也必须真的抛出来。
    """
    provider = FakeLLMProvider(
        chunks=("select ", "pg_sleep("), raises_after=LLMTimeout("total", 180)
    )
    seen: list[str] = []

    with pytest.raises(LLMTimeout) as excinfo:
        async for chunk in provider.stream("p", **_TIMEOUTS):
            seen.append(chunk)

    assert seen == ["select ", "pg_sleep("], "超时前吐出的片段丢了——半截稿就无从谈起"
    assert excinfo.value.kind == "total"


@pytest.mark.asyncio
async def test_the_fake_can_be_unavailable() -> None:
    provider = FakeLLMProvider(raises=LLMUnavailable())

    with pytest.raises(LLMUnavailable):
        await _collect(provider)


def test_the_timeout_kind_is_validated() -> None:
    """kind 打错字时立刻炸，而不是产出一句意义不明的 message。"""
    with pytest.raises(ValueError):
        LLMTimeout("firsttoken", 60)


def test_the_unavailable_message_does_not_leak_the_address() -> None:
    """spec §4.4：地址端口进服务端日志、不进响应。**LLMUnavailable 连参数都不收**，
    所以「顺手把 url 拼进消息」这件事做不到。
    """
    assert "http" not in str(LLMUnavailable())


def test_the_provider_is_chosen_by_configuration() -> None:
    """**这条就是「可插拔」的证据**（设计 §3.5）：换一个配置值就换一个实现，不需要
    改任何调用方。
    """
    settings = Settings(secret_key="s", llm_provider="fake", llm_model="m")

    provider = get_provider(settings)

    assert provider.name == "fake"
    assert provider.model == "m"


def test_an_unknown_provider_is_a_clear_error() -> None:
    """错字要指向配置，而不是在第一次调用时以 AttributeError 出现在管线里。"""
    settings = Settings(secret_key="s", llm_provider="ollam")

    with pytest.raises(ValueError, match="ollam"):
        get_provider(settings)
```

**给四条 async 测试各加 `@pytest.mark.asyncio`，不要用模块级 `pytestmark`**：这个文件里有四条同步测试，模块级标记会把它们也标成 async，而 pytest-asyncio 对同步函数带 asyncio 标记会警告或报错（取决于 `asyncio_mode`）。`tests/test_executor.py`（p3b1）就是逐条加装饰器的，跟着它走。

- [ ] **Step 5: 跑测试**

```bash
.venv/Scripts/python.exe -m pytest tests/test_llm_fake_and_registry.py -q
```

预期 **8 passed**。

- [ ] **Step 6: 反向验证两条（每次只改一处，跑完立刻恢复）**

**先 `cp` 备份要改的文件** —— 改未提交的新文件时 `git checkout` 救不了（它会把文件删掉）。

1. **`FakeLLMProvider.stream` 里的 `self.calls += 1` 删掉** → `test_the_fake_yields_its_chunks_in_order` FAIL。这条确认那个计数器**真的在数**：它是 Task 8「只调一次 LLM」那条约束的唯一守卫，如果它自己不准，那条约束就没有守卫。
2. **`raises_after` 改成在 `for` 循环之前抛** → `test_the_fake_can_fail_after_some_chunks` FAIL 在 `seen == [...]` 那句，而 `test_the_fake_can_fail_before_the_first_chunk` **保持绿**。这一对区分了两种超时路径——它们在设计 §9.3 里的处理方式不同（一个有半截稿要留在编辑器里，一个什么都没有）。

- [ ] **Step 7: ruff + 提交**

```bash
.venv/Scripts/python.exe -m ruff format src/chatbi/ tests/ && .venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pytest -q
git add apps/api/src/chatbi/llm/ apps/api/tests/test_llm_fake_and_registry.py
git commit -m "feat(llm): LLMProvider 协议、假实现与注册表

协议是 async 的，与 P2b 的数据库驱动有意不同型：驱动同步是因为 psycopg/pymysql/
clickhouse-connect 没有 async 实现，而 LLM 就是个 HTTP 接口。这个差异买到两件事——
省掉线程与事件循环之间那层 queue 胶水（p3b1 实测过 to_thread 的 task 被 cancel 后
线程会继续跑到底），以及取消变成免费的（关连接即停，不需要 execution/registry.py
那种注册表）。文件头写明了这条，别顺手统一成同步。

LLMTimeout 带 kind 区分首 token 与总时长：两种失败的运维含义不同（前者是模型在加载
或服务不可达，后者是模型跑飞），而出问题时运维手上往往只有那句 message。
LLMUnavailable 不收参数，所以「把 base_url 拼进消息」做不到（spec §4.4）。

假 provider 三个旋钮覆盖五种路径，**不睡真实时间**——超时机制由 ollama.py 自己的
测试守（httpx.MockTransport），这里测的是「拿到 LLMTimeout 之后怎么办」。

注册表本次只认识 fake，ollama 分支在下一个任务加：一个只认识 fake 的注册表比一个
import 不存在模块的注册表更容易定位问题。openai_compatible.py 不做（设计 §1.2）。"
```

---

### Task 3: `llm/ollama.py` —— 流式与两个超时

**Files:**
- Create: `src/chatbi/llm/ollama.py`
- Modify: `src/chatbi/llm/registry.py`（加 ollama 分支）
- Test: `tests/test_llm_ollama.py`

**Interfaces:**
- Consumes: Task 2 的 `LLMProvider` / `LLMTimeout` / `LLMUnavailable`
- Produces:
  ```python
  llm.ollama.OllamaProvider(*, base_url, model, keep_alive="30m", temperature=0.0, client=None)
  # client 是可注入的 httpx.AsyncClient —— 测试用 MockTransport 造一个塞进来
  ```

**本任务不连真 Ollama。** 用 `httpx.MockTransport` 造响应：那是唯一能确定性地测「首 token 迟到」与「吐到一半超时」的办法。真跑是 p3c3 的退出标准。

- [ ] **Step 1: 写 `llm/ollama.py`**

```python
"""Ollama 的 /api/generate 流式调用（P3c 设计 §3.3）。

两个超时的实现方式不同，这是本文件的核心：
  first_token —— 用 asyncio.timeout 包住「拿到第一个片段」这段等待。
  total       —— 用一个 deadline 在每次拿到片段后检查，超了就 break 并抛。
**不要用一个 asyncio.timeout 包住整个循环**：那样两种失败会抛出同一个异常，而它们的
运维含义完全不同（设计 §3.2），运维手上只有那句 message。

取消是免费的：调用方取消这个生成器 → async with client.stream 退出 → 连接关闭 →
Ollama 侧停止生成。**这里不需要任何显式的取消动作**，与 execution/registry.py 那种
「另开一条连接发 pg_cancel_backend」是两个世界（P3c 设计 §3.1）。
"""

import json
from collections.abc import AsyncIterator

import httpx

from chatbi.llm.base import LLMTimeout, LLMUnavailable

_TIMEOUT_FLOOR = 0.001


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        keep_alive: str = "30m",
        temperature: float = 0.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._keep_alive = keep_alive
        self._temperature = temperature
        self._client = client
        """可注入 —— 测试塞一个 MockTransport 的 client 进来。None 时每次调用自己建
        一个（单机部署下一次问答一条连接，不值得维护一个长命 client）。"""

    async def stream(
        self, prompt: str, *, first_token_timeout: float, total_timeout: float
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": self._keep_alive,
            # temperature 默认 0：出 SQL 不需要创造力，而确定性让「同一个问题两次给
            # 不同 SQL」这种最难排查的现象消失（设计 §3.3）
            "options": {"temperature": self._temperature},
        }
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            async for chunk in self._stream_with(
                client, payload, first_token_timeout, total_timeout
            ):
                yield chunk
        finally:
            if owns_client:
                await client.aclose()

    async def _stream_with(
        self,
        client: httpx.AsyncClient,
        payload: dict,
        first_token_timeout: float,
        total_timeout: float,
    ) -> AsyncIterator[str]:
        import asyncio

        loop = asyncio.get_running_loop()
        deadline = loop.time() + total_timeout
        first = True
        try:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=httpx.Timeout(None, connect=first_token_timeout),
            ) as response:
                if response.status_code >= 400:
                    # **不读响应体也不进消息**：Ollama 的错误体可能带模型路径
                    raise LLMUnavailable()
                lines = response.aiter_lines()
                while True:
                    budget = (
                        first_token_timeout
                        if first
                        else max(deadline - loop.time(), _TIMEOUT_FLOOR)
                    )
                    try:
                        async with asyncio.timeout(budget):
                            line = await anext(lines)
                    except StopAsyncIteration:
                        return
                    except TimeoutError:
                        raise LLMTimeout(
                            "first_token" if first else "total",
                            first_token_timeout if first else total_timeout,
                        ) from None
                    first = False
                    piece, done = _parse_line(line)
                    if piece:
                        yield piece
                    if done:
                        return
                    if loop.time() >= deadline:
                        raise LLMTimeout("total", total_timeout)
        except httpx.HTTPError as exc:
            # 连不上、DNS 失败、读超时。**原始异常不往上带**（它的 str 里有 url）
            raise LLMUnavailable() from exc


def _parse_line(line: str) -> tuple[str, bool]:
    """一行 NDJSON → (文本片段, 是否结束)。

    **解析不了的行静默跳过**：Ollama 在流里偶尔插入空行，而为了一个空行让整次生成失败
    是不成比例的。真正的失败由状态码与超时兜住。
    """
    line = line.strip()
    if not line:
        return "", False
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return "", False
    return str(data.get("response") or ""), bool(data.get("done"))
```

`import asyncio` 放在函数里是为了让文件头那句「只 import 标准库与 httpx」成立时也不显得突兀——**实际上应该提到模块顶部**，实施时按 ruff 的意见办（`PLC0415` 若启用会要求提上去）。**先写在顶部**，这条注释只是解释为什么你会在别处看到函数内 import。

- [ ] **Step 2: 把 ollama 加进注册表**

`src/chatbi/llm/registry.py` 里，`fake` 分支之后、`raise ValueError` 之前：

```python
    if settings.llm_provider == "ollama":
        from chatbi.llm.ollama import OllamaProvider

        return OllamaProvider(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            keep_alive=settings.llm_keep_alive,
        )
```

同时把 Task 2 留在那里的「Task 3 在这里加 ollama 分支」那条注释删掉。

- [ ] **Step 3: 写测试**

`tests/test_llm_ollama.py`：

```python
"""Ollama provider：请求体、流式解析、两个超时（P3c 设计 §3.2、§3.3）。

**不连真 Ollama**。用 httpx.MockTransport 造响应——那是唯一能确定性地测「首 token
迟到」与「吐到一半超时」的办法（真服务上这两件事都不可复现）。真跑是 p3c3 的退出标准。
"""

import asyncio
import json

import httpx
import pytest

from chatbi.llm.base import LLMTimeout, LLMUnavailable
from chatbi.llm.ollama import OllamaProvider

_FAST = {"first_token_timeout": 5.0, "total_timeout": 5.0}


def _ndjson(*pieces: str, done: bool = True) -> bytes:
    lines = [json.dumps({"response": p, "done": False}) for p in pieces]
    if done:
        lines.append(json.dumps({"response": "", "done": True}))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _provider(handler, **kwargs) -> OllamaProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaProvider(base_url="http://x:11434", model="m", client=client, **kwargs)


@pytest.mark.asyncio
async def test_the_pieces_are_yielded_as_they_arrive() -> None:
    provider = _provider(lambda request: httpx.Response(200, content=_ndjson("select ", "1")))

    pieces = [p async for p in provider.stream("q", **_FAST)]

    assert pieces == ["select ", "1"], "空的 done 行不该产出一个空片段"


@pytest.mark.asyncio
async def test_the_request_carries_stream_keep_alive_and_zero_temperature() -> None:
    """三个字段各有理由（设计 §3.3）：stream 决定能不能边生成边显示；keep_alive 让模型
    常驻、避免 36s 冷启动反复落在用户头上；temperature=0 让同一个问题两次给同一条 SQL。
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=_ndjson("select 1"))

    provider = _provider(handler, keep_alive="1h")
    [p async for p in provider.stream("q", **_FAST)]

    assert seen["stream"] is True
    assert seen["keep_alive"] == "1h"
    assert seen["options"]["temperature"] == 0.0
    assert seen["prompt"] == "q"


@pytest.mark.asyncio
async def test_a_malformed_line_is_skipped_not_fatal() -> None:
    """Ollama 偶尔在流里插入空行或非 JSON。**为一行垃圾让整次生成失败是不成比例的**
    ——真正的失败由状态码与超时兜住。
    """
    body = b'{"response":"a","done":false}\n\n not json \n{"response":"b","done":true}\n'
    provider = _provider(lambda request: httpx.Response(200, content=body))

    assert [p async for p in provider.stream("q", **_FAST)] == ["a", "b"]


@pytest.mark.asyncio
async def test_a_slow_first_token_raises_the_first_token_kind() -> None:
    """**首 token 超时**。kind 必须是 first_token——它告诉运维「模型在加载或服务不可
    达」，而那与「模型跑飞了」要采取的行动完全不同。
    """

    async def slow_body():
        await asyncio.sleep(1.0)
        yield _ndjson("late")

    provider = _provider(lambda request: httpx.Response(200, content=slow_body()))

    with pytest.raises(LLMTimeout) as excinfo:
        [p async for p in provider.stream("q", first_token_timeout=0.05, total_timeout=5.0)]

    assert excinfo.value.kind == "first_token"


@pytest.mark.asyncio
async def test_a_runaway_generation_raises_the_total_kind() -> None:
    """**总时长超时**：首 token 很快，但之后一直吐。这是模型进入重复循环的形态。

    断言 kind == "total" 而不只是「抛了 LLMTimeout」：**一个把两种超时合成一个异常的
    实现也能让「抛了」通过**，而那正是设计 §3.2 要防的事。
    """

    async def endless():
        yield _ndjson("a", done=False)
        while True:
            await asyncio.sleep(0.02)
            yield _ndjson("a", done=False)

    provider = _provider(lambda request: httpx.Response(200, content=endless()))
    seen: list[str] = []

    with pytest.raises(LLMTimeout) as excinfo:
        async for piece in provider.stream("q", first_token_timeout=5.0, total_timeout=0.2):
            seen.append(piece)

    assert excinfo.value.kind == "total"
    assert seen, "超时前吐出的片段丢了——半截稿就无从谈起（设计 §9.3）"


@pytest.mark.asyncio
async def test_an_error_status_is_unavailable_without_the_address() -> None:
    provider = _provider(lambda request: httpx.Response(500, text="model not found: /root/.ollama"))

    with pytest.raises(LLMUnavailable) as excinfo:
        [p async for p in provider.stream("q", **_FAST)]

    assert "ollama" not in str(excinfo.value).lower(), "响应体进了消息——它可能带模型路径"
    assert "http" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_connection_failure_is_unavailable_without_the_address() -> None:
    """spec §4.4：地址端口进服务端日志、不进响应。httpx 的原始异常 str 里**有 url**，
    所以必须换成 LLMUnavailable 而不是直接往上抛。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("failed to connect", request=request)

    provider = _provider(handler)

    with pytest.raises(LLMUnavailable) as excinfo:
        [p async for p in provider.stream("q", **_FAST)]

    assert "x:11434" not in str(excinfo.value)


def test_ollama_is_the_default_provider() -> None:
    """默认配置要能造出 ollama（Task 2 的注册表只认识 fake，本任务补上）。"""
    from chatbi.config import Settings
    from chatbi.llm.registry import get_provider

    provider = get_provider(Settings(secret_key="s"))

    assert provider.name == "ollama"
    assert provider.model == "qwen3:8b"
```

**`httpx.Response(200, content=<async generator>)` 是 MockTransport 里造流式响应的办法**：httpx 接受异步可迭代对象作为 content。若这个版本的 httpx 不接受（实测一下），退路是 `httpx.Response(200, stream=httpx.AsyncByteStream(...))` 的自定义子类——**先按上面写，跑不通再换，并把实际用法记进偏差**。

- [ ] **Step 4: 跑测试**

```bash
.venv/Scripts/python.exe -m pytest tests/test_llm_ollama.py -q
```

预期 **9 passed**，总耗时几百毫秒（两条超时测试各用 0.05–0.2 秒的超时值，**不要用真实的 60/180**）。

- [ ] **Step 5: 反向验证三条（每次只改一处，跑完立刻恢复）**

1. **把两个超时合成一个**（`asyncio.timeout(total_timeout)` 包住整个 while 循环，抛 `LLMTimeout("total", ...)`） → `test_a_slow_first_token_raises_the_first_token_kind` FAIL（kind 是 total），而 `test_a_runaway_generation_raises_the_total_kind` **保持绿**。**这一对就是设计 §3.2 的实证**：合成之后「服务没起来」与「模型跑飞」变得无法区分，而合成的实现在一半测试上仍然是绿的。
2. **`except httpx.HTTPError` 那段改成 `raise`（直接把原始异常往上抛）** → 两条 `does_not_leak_the_address` 里的连接那条 FAIL。这条钉住 spec §4.4——httpx 的异常 str 里带 url。
3. **`_parse_line` 的 `except json.JSONDecodeError` 删掉** → `test_a_malformed_line_is_skipped_not_fatal` FAIL，其余全绿。确认那条容错真的在起作用而不是碰巧。

- [ ] **Step 6: ruff + 提交**

```bash
.venv/Scripts/python.exe -m ruff format src/chatbi/ tests/ && .venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pytest -q
git add apps/api/src/chatbi/llm/ollama.py apps/api/src/chatbi/llm/registry.py apps/api/tests/test_llm_ollama.py
git commit -m "feat(llm): Ollama provider，两个超时分别实现

首 token 用 asyncio.timeout 包住「等第一个片段」，总时长用 deadline 在每次拿到片段后
检查。**不用一个 timeout 包住整个循环**：那样两种失败抛同一个异常，而它们的运维含义
完全不同（前者是模型在加载或服务不可达，后者是模型跑飞），出问题时运维手上只有那句
message。反向验证 1 实证了这一点——合成之后仍有一半测试是绿的。

keep_alive 让模型常驻（避免 36s 冷启动反复落在用户头上），temperature=0 让同一个问题
两次给同一条 SQL。

httpx 的异常与错误响应体都不往上带：前者的 str 里有 url，后者可能带模型路径
（spec §4.4）。NDJSON 里解析不了的行静默跳过——为一行垃圾让整次生成失败不成比例。

测试用 httpx.MockTransport 而不是真 Ollama：那是唯一能确定性地测「首 token 迟到」与
「吐到一半超时」的办法，且全部测试跑在毫秒级。真跑是 p3c3 的退出标准。"
```

---

### Task 4: `pipeline/chips.py` —— 确定性匹配与时间词

**Files:**
- Create: `src/chatbi/pipeline/__init__.py`（空）· `src/chatbi/pipeline/chips.py`
- Test: `tests/test_pipeline_chips.py`

**Interfaces:**
- Consumes: `chatbi.datasources.drivers.base.SchemaSnapshot` / `TableSchema` / `ColumnSchema`（P2b 已有的 frozen dataclass）
- Produces:
  ```python
  pipeline.chips.Chip(kind: str, label: str, value: str, hit: bool)      # frozen
  pipeline.chips.ChipMatch(chips: tuple[Chip, ...], resolved_tables: tuple[str, ...],
                           time_range: tuple[date, date] | None)          # frozen
  pipeline.chips.match_chips(question, snapshot, *, today, notes=None) -> ChipMatch
  pipeline.chips.resolve_time_phrase(question, *, today) -> tuple[str, date, date] | None
  # resolved_tables 里是 "schema.table" 形式（与 known_identifiers 的第三种形式一致）
  ```

**这个任务是「一次 LLM 调用」那个决定的落地**（设计 §2.1）。它必须毫秒级返回——`understand` 事件要在用户按下回车后立刻发出去，那 20 秒的空白正是它要填的。

- [ ] **Step 1: 写时间词的失败测试**

`tests/test_pipeline_chips.py`（先只写时间那部分）：

```python
"""chips 匹配与中文时间词（P3c 设计 §4）。无夹具——纯函数。

**today 是显式参数**，所以跨年、跨月、闰年边界都能穷举。读系统时钟的实现测不了这些。
"""

from datetime import date

import pytest

from chatbi.datasources.drivers.base import ColumnSchema, SchemaSnapshot, TableSchema
from chatbi.pipeline.chips import match_chips, resolve_time_phrase

_TODAY = date(2026, 8, 24)  # 周一


@pytest.mark.parametrize(
    ("question", "start", "end"),
    [
        ("今天卖了多少", date(2026, 8, 24), date(2026, 8, 24)),
        ("昨天卖了多少", date(2026, 8, 23), date(2026, 8, 23)),
        ("本周的订单", date(2026, 8, 24), date(2026, 8, 30)),
        ("上周的订单", date(2026, 8, 17), date(2026, 8, 23)),
        ("本月营收", date(2026, 8, 1), date(2026, 8, 31)),
        ("上个月营收", date(2026, 7, 1), date(2026, 7, 31)),
        ("上月营收", date(2026, 7, 1), date(2026, 7, 31)),
        ("本季度营收", date(2026, 7, 1), date(2026, 9, 30)),
        ("上季度营收", date(2026, 4, 1), date(2026, 6, 30)),
        ("今年营收", date(2026, 1, 1), date(2026, 12, 31)),
        ("去年营收", date(2025, 1, 1), date(2025, 12, 31)),
        ("最近 7 天的订单", date(2026, 8, 18), date(2026, 8, 24)),
        ("最近7天的订单", date(2026, 8, 18), date(2026, 8, 24)),
        ("近 30 天的订单", date(2026, 7, 26), date(2026, 8, 24)),
        ("最近 3 个月", date(2026, 6, 1), date(2026, 8, 31)),
    ],
)
def test_the_time_phrases_resolve_to_absolute_ranges(question, start, end) -> None:
    """**「最近 7 天」含今天**（设计 §4.4）：用户说「最近 7 天」时期望里有今天，
    否则他会问「过去一周」。这类差一天的问题在数字对不上时极难排查，所以钉死。
    """
    resolved = resolve_time_phrase(question, today=_TODAY)

    assert resolved is not None, f"{question!r} 没识别出时间词"
    _label, actual_start, actual_end = resolved
    assert (actual_start, actual_end) == (start, end)


def test_the_label_keeps_the_original_words() -> None:
    """label 存原词、value 存绝对区间（设计 §4.4）。**回放要用 value**——一个月后
    「上个月」的含义已经变了。
    """
    label, start, end = resolve_time_phrase("上个月各城市营收", today=_TODAY)

    assert label == "上个月"
    assert (start, end) == (date(2026, 7, 1), date(2026, 7, 31))


def test_a_question_without_a_time_phrase_resolves_to_none() -> None:
    assert resolve_time_phrase("各城市营收", today=_TODAY) is None


@pytest.mark.parametrize(
    ("today", "start", "end"),
    [
        (date(2026, 1, 15), date(2025, 12, 1), date(2025, 12, 31)),  # 跨年
        (date(2026, 3, 5), date(2026, 2, 1), date(2026, 2, 28)),  # 平年 2 月
        (date(2024, 3, 5), date(2024, 2, 1), date(2024, 2, 29)),  # 闰年 2 月
    ],
)
def test_last_month_handles_year_and_leap_boundaries(today, start, end) -> None:
    """**这三条是 today 必须是参数的理由**：读系统时钟的实现只能在一年里的某几天
    验到跨年，而那时问题已经在生产上了。
    """
    _label, actual_start, actual_end = resolve_time_phrase("上个月", today=today)

    assert (actual_start, actual_end) == (start, end)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/Scripts/python.exe -m pytest tests/test_pipeline_chips.py -q
```

预期：全部 ERROR（`ModuleNotFoundError: chatbi.pipeline.chips`）。

- [ ] **Step 3: 写时间词解析**

`src/chatbi/pipeline/chips.py`（先写时间那半）：

```python
"""问题 → 意图 chips（P3c 设计 §4）。**纯函数，毫秒级，不调 LLM。**

为什么不调 LLM 抽实体（上游 spec §2.2 原本那么写）：本机一次 LLM 调用 20 秒（4.1
tok/s），而 chips 不影响 SQL 产出——它是给用户看的意图反馈，价值恰恰在于「在等草稿的
那 20 秒里先给点反馈」。LLM 版要等 15 秒才出来，那时用户已经在怀疑是不是挂了。
详见设计 §2.1，那里还记了第三条理由（确定性匹配能穷举测，LLM 抽实体不能）。

**不引分词器**（jieba 之类）：要装依赖，且对「订单金额」这种复合词的切法不稳定。改用
双向子串包含 + 下划线拆词，代价是同义词会漏（问「营收」而列叫 amount、注释写「金额」
时匹配不到）。这与上游 spec §0 已声明的降级一致（V2-1 的术语理解只靠 schema 注释，
同义词表在 V2-2），而漏的后果被「一张表都没命中时给全部表完整列」兜住（Task 5）。
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta

from chatbi.datasources.drivers.base import SchemaSnapshot

_RECENT_DAYS = re.compile(r"(?:最近|近|过去)\s*(\d+)\s*天")
_RECENT_MONTHS = re.compile(r"(?:最近|近|过去)\s*(\d+)\s*个?月")


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _month_end(day: date) -> date:
    return _next_month(_month_start(day)) - timedelta(days=1)


def _next_month(first: date) -> date:
    return first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1)


def _months_back(first: date, months: int) -> date:
    total = first.year * 12 + (first.month - 1) - months
    return date(total // 12, total % 12 + 1, 1)


def resolve_time_phrase(question: str, *, today: date) -> tuple[str, date, date] | None:
    """识别一个中文时间词，返回 (原词, 起, 止)，都是**含端点**的日期。

    只认第一个匹配到的词。一句话里出现两个时间词（「上个月和今年」）时取靠前的那个——
    正确处理它需要真正的语义理解，而 V2-1 声明了那在 V2-2。**这个限制要在 chip 的
    label 上体现**（用户看到「上个月」就知道机器按哪个算的）。
    """
    if match := _RECENT_DAYS.search(question):
        days = int(match.group(1))
        return match.group(0), today - timedelta(days=days - 1), today
    if match := _RECENT_MONTHS.search(question):
        months = int(match.group(1))
        start = _months_back(_month_start(today), months - 1)
        return match.group(0), start, _month_end(today)
    quarter_start = _month_start(today).replace(month=(today.month - 1) // 3 * 3 + 1)
    table: tuple[tuple[str, date, date], ...] = (
        ("今天", today, today),
        ("昨天", today - timedelta(days=1), today - timedelta(days=1)),
        ("本周", today - timedelta(days=today.weekday()), today - timedelta(days=today.weekday()) + timedelta(days=6)),
        ("上周", today - timedelta(days=today.weekday() + 7), today - timedelta(days=today.weekday() + 1)),
        ("本月", _month_start(today), _month_end(today)),
        ("上个月", _month_start(_months_back(_month_start(today), 1)), _month_start(today) - timedelta(days=1)),
        ("上月", _month_start(_months_back(_month_start(today), 1)), _month_start(today) - timedelta(days=1)),
        ("本季度", quarter_start, _month_end(_months_back(quarter_start, -2))),
        ("上季度", _months_back(quarter_start, 3), quarter_start - timedelta(days=1)),
        ("今年", date(today.year, 1, 1), date(today.year, 12, 31)),
        ("去年", date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)),
    )
    # **顺序敏感**：「上个月」必须排在「上月」前面，否则「上个月」会被「上月」的子串
    # 匹配切成错的 label（区间恰好相同所以测不出来，但 label 会显示成「上月」）。
    # 同理「本周」在「本月」前面无所谓，它们不互为子串。
    for label, start, end in table:
        if label in question:
            return label, start, end
    return None
```

`_months_back(quarter_start, -2)` 是「往后两个月」，用来取季度末——**负数参数是有意的**，`_months_back` 的实现天然支持它（整数月运算）。若觉得难读，实施时可以加一个 `_months_forward`，但**不要改成 `+timedelta(days=90)`**：那在跨月长度不同时会错。

- [ ] **Step 4: 跑测试确认时间那部分转绿**

```bash
.venv/Scripts/python.exe -m pytest tests/test_pipeline_chips.py -q
```

预期 **19 passed**（15 条参数化 + label + None + 3 条边界）。**若「本季度」那条红**，先核对 `_month_end(_months_back(quarter_start, -2))` 的语义再改测试——2026-08-24 在 Q3（7–9 月），所以是 7/1–9/30。

- [ ] **Step 5: 写表列匹配的失败测试**

同一个测试文件追加：

```python
def _snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        tables=(
            TableSchema(
                schema_name="demo_sales",
                name="orders",
                comment="订单",
                columns=(
                    ColumnSchema(name="id", data_type="uuid"),
                    ColumnSchema(name="city", data_type="text", comment="城市"),
                    ColumnSchema(
                        name="order_amount", data_type="numeric", is_numeric=True, comment="金额"
                    ),
                ),
            ),
            TableSchema(
                schema_name="demo_sales",
                name="customers",
                comment="客户",
                columns=(ColumnSchema(name="name", data_type="text", comment="姓名"),),
            ),
        )
    )


def test_a_table_comment_in_the_question_resolves_that_table() -> None:
    """中文注释是 V2-1 术语理解的**唯一**来源（spec §0：同义词表在 V2-2）。
    问「订单」要能命中注释为「订单」的表。
    """
    result = match_chips("上个月的订单", _snapshot(), today=_TODAY)

    assert result.resolved_tables == ("demo_sales.orders",)
    assert any(c.kind == "table" and c.label == "订单" and c.hit for c in result.chips)


def test_an_english_identifier_matches_after_underscore_splitting() -> None:
    """问题里不会带下划线，所以 order_amount 要能被「amount」命中。"""
    result = match_chips("show me the amount", _snapshot(), today=_TODAY)

    assert any(c.kind == "column" and "amount" in c.value for c in result.chips)


def test_short_identifiers_do_not_match() -> None:
    """`id` 会命中大量问题而说明不了任何事（设计 §4.2）。长度 ≤2 的纯英文标识符
    不参与匹配——**否则每个 chip 列表里都有一个没用的 id**。
    """
    result = match_chips("what did we do", _snapshot(), today=_TODAY)

    assert not [c for c in result.chips if c.value.endswith(".id")]


def test_a_time_chip_is_included_and_carries_the_absolute_range() -> None:
    result = match_chips("上个月的订单", _snapshot(), today=_TODAY)

    time_chips = [c for c in result.chips if c.kind == "time"]
    assert len(time_chips) == 1
    assert time_chips[0].label == "上个月"
    assert time_chips[0].value == "2026-07-01/2026-07-31"
    assert result.time_range == (date(2026, 7, 1), date(2026, 7, 31))


def test_nothing_matched_gives_no_resolved_tables() -> None:
    """**空的 resolved_tables 不是错误**：Task 5 的兜底（给全部表完整列）依赖这个信号。
    这里不能返回「全部表」——那会让 Task 5 分不清「命中了全部」与「一张都没命中」。
    """
    result = match_chips("讲个笑话", _snapshot(), today=_TODAY)

    assert result.resolved_tables == ()
    assert result.chips == ()


def test_a_column_note_participates_in_matching() -> None:
    """人工备注（column_notes，P2c）也是匹配来源，且优先于库注释——管理员是对着这个
    业务写的（设计 §8.3 的同一条理由）。
    """
    notes = {("demo_sales", "orders", "order_amount"): "营收"}

    result = match_chips("上个月营收", _snapshot(), today=_TODAY, notes=notes)

    assert any(c.kind == "column" and c.label == "营收" for c in result.chips)
    assert result.resolved_tables == ("demo_sales.orders",)


def test_at_most_eight_chips_but_all_tables_stay_resolved() -> None:
    """chips 上限 8 个（界面那条横排放不下更多），**但 resolved_tables 不受限**——
    上下文选表用后者，砍掉它会让模型看不见本该看见的表（设计 §4.3）。
    """
    tables = tuple(
        TableSchema(
            schema_name="s",
            name=f"table_{i}",
            comment=f"表{i}",
            columns=(ColumnSchema(name=f"col_{i}", data_type="text", comment=f"列{i}"),),
        )
        for i in range(10)
    )
    question = " ".join(f"表{i} 列{i}" for i in range(10))

    result = match_chips(question, SchemaSnapshot(tables=tables), today=_TODAY)

    assert len(result.chips) == 8
    assert len(result.resolved_tables) == 10
```

- [ ] **Step 6: 写表列匹配**

`chips.py` 追加：

```python
@dataclass(frozen=True)
class Chip:
    kind: str
    """table | column | time"""
    label: str
    """给用户看的词（命中的注释原文，或时间词原文）。"""
    value: str
    """机器用的值：table → "schema.table"；column → "schema.table.column"；
    time → "YYYY-MM-DD/YYYY-MM-DD"。**回放用 value 而不是 label**（设计 §4.4）。"""
    hit: bool
    """是否落到了真实的 schema 对象（时间则是识别成功）。前端用 ok 色（Figma §4.3）。
    V2-1 里它恒为 True——没命中的东西根本不会成为 chip。**保留这个字段**是因为 V2-2
    的语义层会产出「你说的这个词我不认识」的 chip，那时它才有 False。"""


@dataclass(frozen=True)
class ChipMatch:
    chips: tuple[Chip, ...] = ()
    resolved_tables: tuple[str, ...] = ()
    """"schema.table" 形式，与 known_identifiers 的第三种形式一致（Task 5 要拿它去
    断言白名单）。**不受 chips 上限影响**。"""
    time_range: tuple[date, date] | None = None


_MAX_CHIPS = 8
_MIN_ASCII_LEN = 3
"""长度 ≤2 的纯英文标识符（id / no / dt）不参与匹配：命中率高但信息量为零。"""


def _candidates(word: str) -> tuple[str, ...]:
    """一个标识符的可匹配形式：原词 + 下划线拆出的段（问题里不会带下划线）。"""
    parts = [word, *word.split("_")] if "_" in word else [word]
    return tuple(p for p in parts if not p.isascii() or len(p) >= _MIN_ASCII_LEN)


def _matches(word: str, question: str) -> bool:
    lowered = question.lower()
    return any(c.lower() in lowered for c in _candidates(word))


def match_chips(
    question: str,
    snapshot: SchemaSnapshot,
    *,
    today: date,
    notes: dict[tuple[str, str, str], str] | None = None,
) -> ChipMatch:
    """双向子串匹配（设计 §4.2）。**表 chip 优先、然后列、最后时间**（§4.3 的上限
    按这个顺序砍）。
    """
    notes = notes or {}
    table_chips: list[Chip] = []
    column_chips: list[Chip] = []
    resolved: list[str] = []

    for table in snapshot.tables:
        qualified = f"{table.schema_name}.{table.name}"
        table_hit = _matches(table.name, question) or bool(
            table.comment and table.comment in question
        )
        hit_columns: list[Chip] = []
        for column in table.columns:
            note = notes.get((table.schema_name, table.name, column.name))
            # 人工备注优先于库注释（设计 §8.3）：管理员是对着这个业务写的
            label_source = note or column.comment or column.name
            if _matches(column.name, question) or (
                label_source != column.name and label_source in question
            ):
                hit_columns.append(
                    Chip(
                        kind="column",
                        label=label_source,
                        value=f"{qualified}.{column.name}",
                        hit=True,
                    )
                )
        if table_hit or hit_columns:
            resolved.append(qualified)
            if table_hit:
                table_chips.append(
                    Chip(kind="table", label=table.comment or table.name, value=qualified, hit=True)
                )
            column_chips.extend(hit_columns)

    time_chips: list[Chip] = []
    time_range: tuple[date, date] | None = None
    if resolved_time := resolve_time_phrase(question, today=today):
        label, start, end = resolved_time
        time_range = (start, end)
        time_chips.append(
            Chip(kind="time", label=label, value=f"{start.isoformat()}/{end.isoformat()}", hit=True)
        )

    chips = (*table_chips, *column_chips, *time_chips)[:_MAX_CHIPS]
    return ChipMatch(chips=chips, resolved_tables=tuple(resolved), time_range=time_range)
```

**`resolved_tables` 在 `chips` 被截断后仍然完整**——这一条有专门的测试（Step 5 最后一条）。它防的是「界面放不下」这个显示问题去污染「模型能看见什么」这个语义问题。

- [ ] **Step 7: 跑测试**

```bash
.venv/Scripts/python.exe -m pytest tests/test_pipeline_chips.py -q
```

预期 **26 passed**（19 + 7）。

- [ ] **Step 8: 反向验证三条（每次只改一处，跑完立刻恢复）**

1. **`_MIN_ASCII_LEN` 改成 1** → `test_short_identifiers_do_not_match` FAIL，其余全绿。确认那条限制真的在起作用。
2. **`chips = (...)[:_MAX_CHIPS]` 那行改成同时截断 `resolved`（`tuple(resolved)[:_MAX_CHIPS]`）** → `test_at_most_eight_chips_but_all_tables_stay_resolved` FAIL 在 `len(...) == 10`。**这一条是本任务最重要的反向验证**：它钉住「显示上限不许影响模型能看见什么」，而这个错误在小库上永远不会暴露（10 张表以下两者相同）。
3. **时间词表里「上个月」与「上月」调换顺序** → **预期全绿**（两者区间相同，只有 label 不同，而参数化测试没有断言 label）。**这是一个结论**：说明「顺序敏感」那条注释目前没有守卫。如实记进偏差，并补一条断言 `resolve_time_phrase("上个月", ...)` 的 label 是「上个月」的测试——`test_the_label_keeps_the_original_words` 已经覆盖了这一点，所以**先跑一次确认它是否真的转红**，若真红则第 3 条不是全绿，把实际结果记下来。

- [ ] **Step 9: ruff + 提交**

```bash
.venv/Scripts/python.exe -m ruff format src/chatbi/ tests/ && .venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pytest -q
git add apps/api/src/chatbi/pipeline/ apps/api/tests/test_pipeline_chips.py
git commit -m "feat(pipeline): 确定性 chips 匹配与中文时间词

understand 那一步不调 LLM（改了上游 spec §2.2 的管线顺序）：本机一次 LLM 调用 20 秒，
而 chips 不影响 SQL 产出——它的价值恰恰在于「在等草稿的那 20 秒里先给点反馈」，LLM 版
要等 15 秒才出来，那时用户已经在怀疑是不是挂了。第三条理由是确定性匹配能穷举测。

不引分词器：双向子串包含 + 下划线拆词。代价是同义词会漏（问「营收」而列叫 amount），
与 spec §0 声明的降级一致，且被 Task 5 的「一张表都没命中就给全部表完整列」兜住。

时间词解析出的绝对区间会进 prompt（本地模型不知道今天几号），label 存原词、value 存
区间——回放必须用 value，一个月后「上个月」的含义已经变了。today 是显式参数，所以
跨年与闰年边界能穷举测。

resolved_tables 不受 chips 显示上限影响：截断它会让模型看不见本该看见的表，而这个
错误在 10 张表以下的库上永远不会暴露。有一条测试专门钉它。"
```

---

## 实施期的偏差（执行中回填）

（开工前为空。每个任务做完就记：实测计数与预期不符的地方、对计划的偏离及理由、反向验证里的意外结果。**本份特别要记的四处**：Task 1 全量的实际数 · Task 3 Step 3 那个 `httpx.Response(content=<async generator>)` 在本机 httpx 版本上到底能不能用（跑不通时换了什么写法）· Task 3 反向验证 1「两个超时合成一个」的实际红绿分布 · Task 4 反向验证 3「时间词表调换顺序」到底是全绿还是红了一条。**「反向验证全绿」是结论不是噪声**，p3a1/p3a2/p3b1/p3b2 各因此补了一条真正有用的测试。）

---

## 交接清单（p3c2 要消费的签名）

```python
# LLM 层（chatbi.llm）
class LLMProvider(Protocol):
    name: str
    model: str
    def stream(self, prompt: str, *, first_token_timeout: float,
               total_timeout: float) -> AsyncIterator[str]: ...
#   两个超时都是必传关键字参数（没有默认值，别让调用方忘了传）
#   **只抛 LLMTimeout / LLMUnavailable**，都是 LLMError 的子类
#   LLMTimeout.kind ∈ {"first_token", "total"} —— p3c3 映射错误码时两者都是
#   LLM_TIMEOUT，但 message 已经写好了区分（运维靠它判断是服务没起来还是模型跑飞）

get_provider(settings: Settings) -> LLMProvider     # chatbi.llm.registry
FakeLLMProvider(*, chunks=(), model="fake-model", raises=None, raises_after=None)
#   .calls 与 .prompts —— p3c2 的「只调一次 LLM」与「prompt 里有什么」都断言它们

# 意图匹配（chatbi.pipeline.chips）
match_chips(question, snapshot, *, today: date, notes=None) -> ChipMatch
#   ChipMatch.chips: tuple[Chip, ...]            最多 8 个，表 > 列 > 时间
#   ChipMatch.resolved_tables: tuple[str, ...]   "schema.table"，**不受 chips 上限影响**
#   ChipMatch.time_range: tuple[date, date] | None
#   Chip(kind, label, value, hit) —— 直接 dataclasses.asdict 就能进 runs.chips 与 SSE
#   **空的 resolved_tables 表示「一张都没命中」**，p3c2 的兜底（给全部表完整列）靠它

resolve_time_phrase(question, *, today) -> tuple[str, date, date] | None
#   (原词, 起, 止)，都含端点。p3c2 把区间拼进 prompt（本地模型不知道今天几号）

# 配置（chatbi.config.Settings）
llm_provider / llm_model / llm_base_url / llm_keep_alive
llm_first_token_timeout=60.0 / llm_total_timeout=180.0 / llm_prompt_token_budget=6000

# 错误码（chatbi.errors）—— p3c3 用，p3c2 不用
LLM_TIMEOUT(504) / LLM_UNAVAILABLE(503) / SCHEMA_UNAVAILABLE(409)
#   三个都**只进 SSE 的 error 载荷**，不作为 HTTP 状态返回（流已经是 200）

# 状态（chatbi.db.models.RUN_STATUSES）
("generating", "drafted", "blocked", "running", "succeeded", "failed", "cancelled")
#   run 的起点是 generating。P3b 的「非 drafted 一律 409」因此自动拦住
#   「草稿还在流就点运行」——执行端点一行不用改
```

**p3c2 开工前要知道的两条**：

1. **`notes` 的键是 `(schema, table, column)` 三元组**，与 `schema_view.merge_schema()` 收的映射同形。p3c2 从 `metadata.list_notes()` 的 ORM 对象一行推导式构造它（`{(n.schema_name, n.table_name, n.column_name): n.note for n in ...}`——实际字段名以 `db/models.py` 的 `ColumnNote` 为准，实施时核对）。
2. **`chips.py` 已经做了「人工备注优先于库注释」这个决定**（Task 4 Step 6）。p3c2 的注释挂载（Task 7）要用**同一个优先级**，否则 chip 上显示「营收」而 SQL 行尾注释显示「金额」，用户会以为是两个东西。

---

## 自查记录

**设计 spec 覆盖核对（本份负责的部分）**

| 设计条目 | 落在哪 |
|---|---|
| §3.1 async 协议、与驱动有意不同型 | Task 2 Step 1 的文件头 |
| §3.2 两个超时、两种失败含义不同 | Task 2 的 `LLMTimeout(kind)` + Task 3 Step 1 的两套实现 + Task 3 反向验证 1 |
| §3.3 `keep_alive` / `temperature=0` / 不回显地址 | Task 3 Step 1 + Step 3 的三条测试 |
| §3.4 假 provider 五种行为 | Task 2 Step 2（三个旋钮覆盖五种） |
| §3.5 provider 走配置、`openai_compatible` 推后 | Task 2 Step 3 + `test_the_provider_is_chosen_by_configuration` |
| §2.1 understand 不调 LLM 的三条理由 | Task 4 Step 3 的文件头 |
| §4.1 签名与 `today` 显式传参 | Task 4 Step 1 的三条边界测试 |
| §4.2 双向子串、短标识符不参与 | Task 4 Step 6 + 反向验证 1 |
| §4.3 chips 上限 8 但 `resolved_tables` 不受限 | Task 4 Step 5 最后一条 + 反向验证 2 |
| §4.4 时间词表 + 「最近 7 天」含今天 + `value` 存绝对区间 | Task 4 Step 1 的 15 条参数化 |
| §7 `generating` 状态 + migration | Task 1 Step 1–4 |
| §9.2 三个错误码（含新增的 `SCHEMA_UNAVAILABLE`） | Task 1 Step 5 |
| §0.1 的实测数字进配置默认值 | Task 1 Step 6 + `test_the_llm_defaults_match_the_measured_numbers` |

**不在本份的设计小节**：§5（上下文装配与 prompt 红线）· §6（SSE 与四个提交点）· §8（剥壳与注释挂载）· §9.1、§9.3（澄清出口与半截稿）· §10.3（真 Ollama 退出标准）—— 前两组在 p3c2，后两组在 p3c3。

**计数链**：405（起点）→ Task 1 后 **407**（+2 配置测试）→ Task 2 后 **415**（+8）→ Task 3 后 **424**（+9）→ Task 4 后 **450**（+26）。skip 恒 28。**这些是估算**，实测与它不符时记进偏差而不是改测试去凑——p3a1 那次把测试条数手算错了一处（估 37 实为 42），连带后面两段的基线都要顺移。

**占位符扫描**：无 TBD / TODO / 「类似 Task N」/ 无代码的「写测试」步骤。Task 3 Step 3 末尾那句「若这个版本的 httpx 不接受，退路是…」与 Task 4 反向验证 3 的「先跑一次确认它是否真的转红」写的是**观察方式与应对**，不是「遇到问题再说」。

**类型一致性核对**

`LLMTimeout(kind, seconds)` 的两个位置参数在 Task 2（定义）、Task 2 测试、Task 3（`ollama.py` 抛出）、Task 3 测试四处一致。`FakeLLMProvider` 的关键字参数只有 `chunks` / `model` / `raises` / `raises_after` 四个，Task 2 的测试与交接清单一致——**没有 `stall` / `endless`**（早期考虑过，改成「直接抛」了，因为睡 60 秒的测试不可接受）。`OllamaProvider` 的 `client` 参数在 Task 3 的实现与测试里都是 `httpx.AsyncClient | None`。`match_chips` 的 `notes` 是 `dict[tuple[str,str,str], str] | None`，与 `schema_view.merge_schema()` 收的映射同形（那边是 `Mapping`，本份用 `dict` 因为要 `.get()`——**若实施时改成 `Mapping` 也对**，交接清单里写的是三元组键这个本质）。

`get_provider(settings)` 收 `Settings` 而不是无参：Task 2 与 Task 3 的测试都靠这一点喂不同配置而不动环境变量。**这与 `get_settings()` 那个 `lru_cache` 是两件事**，别在实施时「顺手」让它自己去读全局配置。
