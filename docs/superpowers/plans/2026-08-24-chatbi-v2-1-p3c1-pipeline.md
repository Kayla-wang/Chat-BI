# Chat-BI V2-1 · P3c1 问答管线（领域层）Implementation Plan

> **⚠ 这份计划还没写完（2026-08-24 暂停）。** 已完成：Global Constraints · 本机环境 · File Structure · **Task 1（基座：migration 0006 + 三个错误码 + 七个配置项）**。待写：Task 2–8 与末尾三节，位置由 HTML 注释锚点标出（`<!--TASK2-->` … `<!--SELFCHECK-->`，其中 Task 2 只写了 Files/Interfaces 头，`<!--TASK2A-->` / `<!--TASK2B-->` 是它的正文占位）。**Task 1 已经可以照着实施**，其余任务的清单见下面的 File Structure 表。续写时照 Task 1 的粒度（每步一个动作 + 真代码 + 反向验证）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把一句中文问题变成一份带注释的 SQL 草稿，全程只调一次 LLM，且不碰 HTTP。

**Architecture:** 三层。`llm/` 是 async 的提供方协议（ollama + fake），取消靠「生成器被取消 → 关连接」而不是注册表。`semantics/` 把 `schema_cache` 的快照与人工注释装配成 prompt 上下文，带 token 预算与「有 N 张表未进上下文」的显式警告。`pipeline/` 编排：确定性 chips 匹配（无 LLM）→ 上下文装配 → 一次 LLM 流式生成 → 剥壳/解析/格式化/注释挂载。做完这一份，后端**一行 HTTP 问答代码都没有**——管线只能在测试里调，这是有意的（验证上游 spec §1.3 的边界规则）。

**Tech Stack:** Python 3.12 · httpx（已在依赖里，P2c 的 TestClient 用它）· sqlglot 30.17.0 · pydantic-settings · pytest + pytest-asyncio · Alembic

## Global Constraints

**不新增依赖。** `httpx` 已在（`fastapi.testclient` 依赖它），`sqlglot` 已在（P3a）。**不要装 jieba 或任何分词器**——chips 用双向子串匹配，理由见设计 §4.2。

**`pipeline/` 与 `semantics/` 与 `llm/` 都不 import fastapi。** 管线要能脱离 HTTP 测（与 p3b1 的 `execution/` 同一条约定）。`errors.py` 例外：它自身 import fastapi，但那是错误契约不是框架依赖（P2a 起就接受了这一点），本份只有 Task 1 会碰它。

**`llm` 与 `semantics` 不知道彼此**（上游 spec §1.3 规则 3）。pipeline 负责装配。谁要是在 `llm/` 里 import `semantics/`，V2-2 换语义层时就要动 LLM 层。

**只调一次 LLM。** 全流程唯一一次调用在 Task 8 的 `run_ask`。有一条测试断言 `FakeLLMProvider.calls == 1`——它防的是将来有人「顺手把 understand 也交给 LLM」而没人发现总时长翻倍（本机 4.1 tok/s，一次调用 20 秒）。

**时间与随机都要显式传参。** `today: date` 是参数不是 `date.today()`。理由与 P2b 驱动的 `timeout_seconds`、P3a guard 的 `max_rows` 一致：语义相关的纯函数不要隐式依赖全局状态，否则跨年边界测不了。

**每个任务的反向验证都要写明「哪几条转红、哪几条必须保持绿」**，两者都要核对。**「反向验证全绿」也是一个结论**（说明那条路径没有守卫），如实记进偏差，不要改测试去凑——p3a1/p3a2/p3b1/p3b2 各因此补了一条真正有用的测试。

**`ruff check` 与 `ruff format --check` 都必须干净。** 新代码写完先跑一次 `ruff format`，别攒到提交前（p3a1、p3a2、p3b1 各踩过一次）。

**自动化测试一律用 `FakeLLMProvider`**（上游 spec §5.1）。本份**不跑真 Ollama**——那是 p3c2 的退出标准。`ollama.py` 自己的测试用 `httpx.MockTransport`，不连真服务。

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
| `apps/api/src/chatbi/semantics/__init__.py` | 空 | 5 |
| `apps/api/src/chatbi/semantics/base.py` | `ContextProvider` 协议 + `SchemaContext` | 5 |
| `apps/api/src/chatbi/semantics/budget.py` | token 估算 + 选表（纯函数） | 5 |
| `apps/api/src/chatbi/semantics/schema_context.py` | `SchemaContextProvider`：装配 + 白名单断言 | 5 |
| `apps/api/src/chatbi/pipeline/prompt.py` | prompt 模板装配（纯函数） | 6 |
| `apps/api/src/chatbi/pipeline/draft.py` | 剥壳 + 解析 + 格式化 + 注释挂载 | 7 |
| `apps/api/src/chatbi/pipeline/ask.py` | `run_ask` 编排 + 阶段值对象 | 8 |
| `apps/api/tests/test_llm_fake_and_registry.py` | 假实现的五种行为 + provider 选择 | 2 |
| `apps/api/tests/test_llm_ollama.py` | 请求体、流式解析、两个超时（`MockTransport`） | 3 |
| `apps/api/tests/test_pipeline_chips.py` | 匹配规则 + 时间词边界（无夹具） | 4 |
| `apps/api/tests/test_semantics_budget.py` | 估算与选表（无夹具） | 5 |
| `apps/api/tests/test_semantics_context.py` | 装配形状 + 白名单断言 + 警告（无夹具） | 5 |
| `apps/api/tests/test_pipeline_prompt.py` | 模板六件事 + 注入不进标识符位（无夹具） | 6 |
| `apps/api/tests/test_pipeline_draft.py` | 四种脏输出 + 注释挂载三条限制（无夹具） | 7 |
| `apps/api/tests/test_pipeline_ask.py` | 阶段顺序 + 只调一次 LLM + 三条失败路径 | 8 |

### 本份修改的文件

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/db/models.py` | `RUN_STATUSES` 加 `generating` | 1 |
| `apps/api/tests/test_run_models.py` | 那条一致性测试的 `== 6` 改 `== 7` | 1 |
| `apps/api/src/chatbi/errors.py` | 加 `LLM_TIMEOUT` / `LLM_UNAVAILABLE` / `SCHEMA_UNAVAILABLE` | 1 |
| `apps/api/src/chatbi/config.py` | 加七个 LLM 配置项 | 1 |

### 本份不碰的东西

`api/` 下任何文件 · `ALL_ROUTERS` · `execution/` · `guard/` · `runs/` · `datasources/`（只**读** `metadata.known_identifiers` 与 `schema_view` 的类型）—— **`POST /api/ask` 与它的鉴权、事件序列、四个提交点全部在 p3c2。**

### 边界说明

**为什么 `semantics/` 消费 `SchemaSnapshot` + notes 映射，而不是 P2c 的 `SchemaResponse`**：后者是 Pydantic HTTP 响应模型，让 `semantics/` 认识它等于让领域层依赖 HTTP 契约。`merge_schema()`（`schema_view.py`）产出的正是那个 HTTP 模型，所以本份**不复用它**，直接吃 `SchemaSnapshot` 与 `Mapping[tuple[str,str,str], str]`——与 `merge_schema` 自己吃的东西一样。

**`known_identifiers()` 在本份第一次有生产调用方**（P2c 的文件头写了「消费方是 P3 的 prompt 构建」）。它是一个仓储函数（要 session），所以调用发生在 p3c2 的流里，把 `frozenset[str]` 作为参数传进 `SchemaContextProvider.build()`。**本份只负责「收到白名单就断言」这一半**，Task 5 有一条测试喂一个不在白名单里的表并断言抛异常——没有那条测试，这个断言就是恒真的装饰。

**`pipeline/ask.py` 产出「阶段值对象」而不是 SSE 字节**：`Understood` / `Delta` / `Finished` / `NeedsClarification` 四个 frozen dataclass。p3c2 的 `ask_stream` 消费它们、写库、翻成 SSE。这条边界让「管线对不对」与「SSE 编排对不对」能分开测——p3b 那次 `execution/` 与 `api/run_stream.py` 的分工是同一个形状。

**失败一律抛异常，不返回错误码**：`LLMTimeout` / `LLMUnavailable` / `SchemaUnavailable` 往上抛，由 p3c2 映射成错误码。领域层不认识 HTTP 词汇（与 p3b1 的执行器同一条约定，那份的文件头写了理由）。

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

<!--TASK2A-->

<!--TASK2B-->

---

<!--TASK3-->

---

<!--TASK4-->

---

<!--TASK5-->

---

<!--TASK6-->

---

<!--TASK7-->

---

<!--TASK8-->

---

<!--DEVIATIONS-->

---

<!--HANDOFF-->

---

<!--SELFCHECK-->
