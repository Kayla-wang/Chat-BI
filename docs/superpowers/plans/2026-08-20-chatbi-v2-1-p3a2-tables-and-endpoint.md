# Chat-BI V2-1 · P3a2 四张表与 `/sql/validate` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P3 后续三段要用的四张表建好（含 `run_events` 的 append-only 仓储），并把 p3a1 的 guard 接成一个 HTTP 端点。

**Architecture:** 两个任务，互不依赖。Task 3 是 migration 0005 的四张表 + 四个模型 + `runs/repository.py`（**只有** `append_event` 与 `list_events`，append-only 是 F-304 的核心）。Task 4 把 p3a1 的 `validate_sql()` 接成 `POST /api/datasources/{id}/sql/validate` —— 这是本段唯一同时认识 `Datasource` 与 guard 的地方。

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.x ORM · Alembic · Pydantic v2 · pytest · ruff

**设计依据：** `docs/superpowers/specs/2026-08-20-chatbi-v2-1-p3a-guard-design.md`（commit `40aff5e`）的 §4、§5、§6.2、§7。行文以「设计 §N」引用。上游 spec 是 `2026-08-11-chatbi-v2-1-design.md`。

**P3a 按体量拆成两份**（单份超 ~2000 行就该拆文件）。任务编号连续：

| 份 | 任务 | 交付 |
|---|---|---|
| `...-p3a1-guard.md` | Task 1–2 | 闸 2 三道 AST 检查 · 闸 3 LIMIT 注入 · `Policy` 注入点 |
| **本份** `p3a2` | Task 3–4 | 四张表 + migration 0005 · `run_events` append-only 仓储 · `POST /{id}/sql/validate` |

**开工前必须先读 p3a1 的「交接清单」一节**，Task 4 直接消费那里的三个签名（`validate_sql` / `GuardVerdict` / `Policy`），其中两条最容易踩：`dialect` 参数要的是 **sqlglot 的方言名**（由本份显式映射，不要直接传 `kind`），`max_rows` 要从 `Settings` 取并作为参数传入（`validate_sql` 不自己读 settings）。

**起点是 p3a1 结束时的状态：`285 passed` / `28 skipped`**（实测值，commit `a7d1550`）。计划初稿写的 278 是算错的测试条数 + 少算了 p3a1 实施期多加的一条测试，见 p3a1 的偏差 1 与偏差 3。实测不是 285 就先回 p3a1 核对。

**Task 3 不依赖 p3a1**（表与 guard 无关），所以两个任务的顺序可以换；但 Task 4 必须在 p3a1 之后。

## Global Constraints

**不新增依赖。** `sqlglot` 在 p3a1 已装。本份只用已有的 FastAPI / SQLAlchemy / Alembic / Pydantic。

**不改 `guard/` 的任何文件。** 本份**消费** p3a1 的 `validate_sql()`，不修改它。如果实施中觉得需要改 guard，那说明 p3a1 漏了东西——回去补 p3a1 并补一条 guard 层的测试，而不是在端点里绕过去。

**闸的实现只有一份。** P3b 的执行器也调同一个 `validate_sql()`。任何「端点里再检查一遍」或「这里简单判断一下」都会变成第二个真相源，而两个真相源里总有一个是旧的。

**`run_events` 是 append-only**（上游 spec §2.5、§4.6，F-304）。`runs/repository.py` 里**只有** `append_event()` 与 `list_events()`——没有 update、没有 delete。有一条测试扫模块的导出名来守这件事。

**`/sql/validate` 不写库、不建 run、不记事件**（设计 §4.3）。它每 300ms 就可能被调一次，为每次按键建审计记录会把 `run_events` 变成击键日志，而 F-304 要审计的是**执行**，不是编辑过程。

**每个任务的反向验证都要写明「哪几条转红、哪几条必须保持绿」**，两者都要核对。只跑「改了某处 → 有测试红了」不够，还要确认其余测试**没红**——否则无法区分「这处有专属守卫」与「随便动点什么都会红」。**反向验证全绿也是一个结论**（说明那条路径没有守卫），要如实记进偏差，不要改测试去凑。

**`ruff check` 与 `ruff format --check` 都必须干净**（`35e66c1` 已把全仓格式化过，这条现在真的成立）。每个任务提交前跑。

## 本机环境

```bash
# apps/api 下，每个任务开工前 export 这四个
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
export CHATBI_TEST_PG_DSN=postgresql://chatbi:chatbi@localhost:5432/chatbi_test
```

- 原生 PostgreSQL 16（`localhost:5432`，`chatbi`/`chatbi`）。**本份不需要 Docker、不需要 Ollama、不需要 `CREATEROLE`。**
- `CHATBI_TEST_MYSQL_DSN` / `CHATBI_TEST_CLICKHOUSE_DSN` 不设，那两个 kind 的契约测继续 skip 并计数（预期状态）。
- **起点基线：`285 passed` / `28 skipped`**（p3a1 结束时实测）。开工前先跑一次确认，不符就先回 p3a1 核对。



## File Structure

### 本份创建的文件

| 文件 | 职责 | 任务 |
|---|---|---|
| `apps/api/migrations/versions/0005_runs.py` | 四张表 | 3 |
| `apps/api/src/chatbi/runs/__init__.py` | 空 | 3 |
| `apps/api/src/chatbi/runs/repository.py` | **只有** `append_event()` / `list_events()` | 3 |
| `apps/api/tests/test_run_models.py` | 四张表的外键行为、status CHECK、`unique (run_id, seq)` | 3 |
| `apps/api/tests/test_run_events.py` | append-only：仓储形状 + seq 唯一 | 3 |
| `apps/api/src/chatbi/guard/deps.py` | `policy_resolver_for`（FastAPI 依赖） | 4 |
| `apps/api/src/chatbi/api/sql_router.py` | `POST /{id}/sql/validate` | 4 |
| `apps/api/tests/test_sql_router.py` | 端点编排（鉴权、200+ok=false、字段完整） | 4 |

### 本份修改的文件

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/db/models.py` | 加 `RUN_STATUSES` 常量 + `Conversation` / `Run` / `RunEvent` / `RunResultPreview` | 3 |
| `apps/api/tests/test_migrations.py` | `TABLES` 加四张 | 3 |
| `apps/api/src/chatbi/datasources/schemas.py` | 加 `SqlValidateRequest` / `SqlValidateResponse` | 4 |
| `apps/api/src/chatbi/api/routers.py` | `ALL_ROUTERS` 加 `sql_router` | 4 |

### 边界说明

**`runs/` 是独立顶层包**，与 `datasources/` 平级。本份只有 `repository.py`，P3b/P3c/P3d 往里加。不放进 `db/`：`db` 是叶子模块（上游 spec §1.3 规则 4），只有模型与会话，不含业务查询。

**`api/sql_router.py` 是唯一同时认识 `Datasource` 与 guard 的地方**：从 `datasource.kind` 取方言、从 `Settings` 取上限、从依赖取 policy，然后调纯函数。

**`SqlValidateRequest` / `SqlValidateResponse` 放 `datasources/schemas.py` 而不是 `guard/schemas.py`**：后者是领域层的 frozen dataclass，前者是 Pydantic HTTP 模型。两者刻意分开——`GuardVerdict` 要能被 P3b 的执行器直接消费，而执行器不该 import Pydantic 响应模型。



### Task 3: 四张表（migration 0005）与 `run_events` 的 append-only 仓储

照上游 spec §2.5 建表。本任务**只做 `run_events` 的仓储**，其余三张表只有表和模型——与 P2c1「表先建、仓储跟着消费方」同一个安排（设计 §5.3）。例外是 `run_events`：append-only 是 F-304 的核心且**与消费方无关**，在这里定下比等 P3b 再补可靠。

**Files:**
- Create: `apps/api/migrations/versions/0005_runs.py` · `apps/api/src/chatbi/runs/__init__.py`（空）· `apps/api/src/chatbi/runs/repository.py`
- Modify: `apps/api/src/chatbi/db/models.py` · `apps/api/tests/test_migrations.py`
- Test: `apps/api/tests/test_run_models.py` · `apps/api/tests/test_run_events.py`

**Interfaces:**
- Consumes: `users.id` / `datasources.id`（P1、P2a 已有）
- Produces:
  ```python
  db.models.Conversation / Run / RunEvent / RunResultPreview
  runs.repository.append_event(session, *, run_id, seq, step, status,
                               duration_ms, detail) -> RunEvent
  runs.repository.list_events(session, run_id) -> list[RunEvent]
  ```
  P3b 写 run 与事件、P3c 写 conversation 与 run、P3d 读回放。

- [ ] **Step 1: 写失败的测试（建模层）**

新建 `apps/api/tests/test_run_models.py`：

```python
"""四张表的约束与外键行为（上游 spec §2.5）。

用 count 而不是 session.get() 验删除行为：四个模型都**没有定义 relationship**
（db 是叶子模块），所以 SQLAlchemy 不知道 DB 级的 ON DELETE CASCADE——identity map
里的旧对象会被直接返回，断言永远看不到 CASCADE 生效。这个坑 P2c1 踩过一次。
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from chatbi.db.models import Conversation, Run, RunEvent, RunResultPreview


def _count(session, model) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(model))


@pytest.fixture
def make_conversation(db_session, make_user, make_datasource):
    def _make(**kwargs):
        conversation = Conversation(
            id=uuid.uuid4(),
            user_id=kwargs.get("user_id") or make_user().id,
            datasource_id=kwargs.get("datasource_id") or make_datasource().id,
            title=kwargs.get("title", "月度营收"),
        )
        db_session.add(conversation)
        db_session.flush()
        return conversation

    return _make


@pytest.fixture
def make_run(db_session, make_conversation):
    def _make(**kwargs):
        conversation = kwargs.get("conversation") or make_conversation()
        run = Run(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=conversation.user_id,
            datasource_id=conversation.datasource_id,
            question=kwargs.get("question", "上个月营收多少"),
            status=kwargs.get("status", "drafted"),
            parent_run_id=kwargs.get("parent_run_id"),
        )
        db_session.add(run)
        db_session.flush()
        return run

    return _make


def test_deleting_a_conversation_takes_its_runs(db_session, make_run) -> None:
    """runs.conversation_id 是 CASCADE：run 脱离会话没有意义。"""
    run = make_run()
    conversation = db_session.get(Conversation, run.conversation_id)
    assert _count(db_session, Run) == 1

    db_session.delete(conversation)
    db_session.flush()

    assert _count(db_session, Run) == 0


def test_deleting_a_run_takes_its_events_and_preview(db_session, make_run) -> None:
    """两张从表都是 CASCADE。"""
    run = make_run()
    db_session.add(
        RunEvent(run_id=run.id, seq=1, step="validate", status="ok", detail={})
    )
    db_session.add(
        RunResultPreview(run_id=run.id, columns=[], rows=[], truncated=False)
    )
    db_session.flush()

    db_session.delete(run)
    db_session.flush()

    assert _count(db_session, RunEvent) == 0
    assert _count(db_session, RunResultPreview) == 0


def test_a_datasource_with_history_cannot_be_deleted(db_session, make_run) -> None:
    """runs.datasource_id 与 conversations.datasource_id 都是 RESTRICT：删数据源不该
    静默销毁历史问答记录。要删得先处理历史——这是**有意的摩擦**（设计 §5.1）。

    与 P2c 的 schema_cache / column_notes 用 CASCADE 是有意的不同：缓存与注释是可
    重建的派生数据，run 是不可重建的审计记录。
    """
    from chatbi.db.models import Datasource

    run = make_run()
    datasource = db_session.get(Datasource, run.datasource_id)

    db_session.delete(datasource)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_a_parent_run_only_breaks_the_link(db_session, make_run) -> None:
    """runs.parent_run_id 是 SET NULL（F-401 下钻链路）：删掉父 run 不该连带删掉
    下钻出来的子 run，断链就够。所以这一列可空。
    """
    parent = make_run()
    child = make_run(conversation=db_session.get(Conversation, parent.conversation_id),
                     parent_run_id=parent.id)

    db_session.delete(parent)
    db_session.flush()
    db_session.expire_all()

    assert _count(db_session, Run) == 1
    assert db_session.get(Run, child.id).parent_run_id is None


def test_an_unknown_run_status_is_rejected(db_session, make_run) -> None:
    """status 的 CHECK 在 migration 里（与 users.role / datasources.kind 一致）。"""
    run = make_run()
    run.status = "definitely-not-a-status"

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_same_seq_cannot_be_used_twice_for_one_run(db_session, make_run) -> None:
    """unique (run_id, seq) 是 append-only 的**真正守卫**：即使有人绕过仓储直接写，
    重放一个已用过的 seq 也会被 DB 拒绝（设计 §5.2）。
    """
    run = make_run()
    db_session.add(RunEvent(run_id=run.id, seq=1, step="validate", status="ok"))
    db_session.flush()

    db_session.add(RunEvent(run_id=run.id, seq=1, step="execute", status="ok"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_two_runs_can_both_use_seq_one(db_session, make_run) -> None:
    """唯一键是 (run_id, seq) 复合的。写成只对 seq 唯一会让第二个 run 无法记事件——
    而那个失败要到 P3b 才会出现，报错也不指向这里。
    """
    first, second = make_run(), make_run()
    db_session.add(RunEvent(run_id=first.id, seq=1, step="validate", status="ok"))
    db_session.add(RunEvent(run_id=second.id, seq=1, step="validate", status="ok"))
    db_session.flush()

    assert _count(db_session, RunEvent) == 2
```

- [ ] **Step 2: 写失败的测试（append-only 仓储）**

新建 `apps/api/tests/test_run_events.py`：

```python
"""run_events 的 append-only（上游 spec §2.5、§4.6，F-304）。"""

import uuid

import pytest
import sqlalchemy as sa

from chatbi.db.models import Conversation, Run, RunEvent
from chatbi.runs import repository
from chatbi.runs.repository import append_event, list_events


@pytest.fixture
def run(db_session, make_user, make_datasource):
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
        status="drafted",
    )
    db_session.add(record)
    db_session.flush()
    return record


def test_appending_events_keeps_them_in_seq_order(db_session, run) -> None:
    """回放按 seq 排序，**不按 at**：同毫秒内的事件顺序不确定（设计 §10）。

    故意乱序 append，验证 list_events 仍按 seq 给出。
    """
    for seq, step in ((3, "execute"), (1, "validate"), (2, "render")):
        append_event(
            db_session, run_id=run.id, seq=seq, step=step, status="ok",
            duration_ms=seq * 10, detail=None,
        )

    events = list_events(db_session, run.id)

    assert [event.seq for event in events] == [1, 2, 3]
    assert [event.step for event in events] == ["validate", "render", "execute"]


def test_the_repository_has_no_update_or_delete_path(db_session, run) -> None:
    """append-only 的落实方式是**仓储的形状**（设计 §5.2）：模块里不存在
    update/delete 函数。这条测试防的是「有人为了修一个 bug 顺手加一个
    update_event」——那会让 F-304 的承诺失效，而没有任何测试会因此变红。

    不加数据库层的触发器：应用账号必须能 INSERT，用触发器禁 UPDATE 会让 migration
    的 downgrade 变复杂，而收益只是防住故意绕过仓储的人——那种人也能改触发器。
    """
    exported = [name for name in dir(repository) if not name.startswith("_")]

    assert "append_event" in exported
    assert "list_events" in exported
    forbidden = [name for name in exported if "update" in name or "delete" in name]
    assert forbidden == []


def test_list_events_does_not_leak_another_runs_events(db_session, run, make_user,
                                                        make_datasource) -> None:
    other_conversation = Conversation(
        id=uuid.uuid4(), user_id=make_user().id, datasource_id=make_datasource().id, title="o"
    )
    db_session.add(other_conversation)
    db_session.flush()
    other = Run(
        id=uuid.uuid4(),
        conversation_id=other_conversation.id,
        user_id=other_conversation.user_id,
        datasource_id=other_conversation.datasource_id,
        question="q",
        status="drafted",
    )
    db_session.add(other)
    db_session.flush()

    append_event(db_session, run_id=run.id, seq=1, step="validate", status="ok",
                 duration_ms=None, detail=None)
    append_event(db_session, run_id=other.id, seq=1, step="execute", status="ok",
                 duration_ms=None, detail=None)

    assert [event.step for event in list_events(db_session, run.id)] == ["validate"]


def test_detail_accepts_none_and_a_dict(db_session, run) -> None:
    """detail 可空。**不放结果行内容**（上游 §4.6：只记行数）——那条约束的执行在
    P3b 写事件的地方，这里只钉住这一列能存 None 与普通 dict。
    """
    append_event(db_session, run_id=run.id, seq=1, step="validate", status="ok",
                 duration_ms=None, detail=None)
    append_event(db_session, run_id=run.id, seq=2, step="execute", status="ok",
                 duration_ms=42, detail={"row_count": 100})

    events = list_events(db_session, run.id)

    assert events[0].detail is None
    assert events[1].detail == {"row_count": 100}
    assert events[1].duration_ms == 42


def test_events_survive_in_insertion_order_within_the_same_seq_gap(db_session, run) -> None:
    """id 是 bigserial，但排序依据是 seq 而不是 id——这条钉住「别偷懒按 id 排」。

    seq 故意留空档（1, 5, 10）：按 id 排和按 seq 排在这个用例下结果相同，所以
    还要配合上面那条乱序用例才能真正证明是按 seq。两条一起才有意义。
    """
    for seq in (1, 5, 10):
        append_event(db_session, run_id=run.id, seq=seq, step="s", status="ok",
                     duration_ms=None, detail=None)

    assert [event.seq for event in list_events(db_session, run.id)] == [1, 5, 10]
    assert db_session.scalar(sa.select(sa.func.count()).select_from(RunEvent)) == 3
```

- [ ] **Step 3: 跑测试确认失败**

```bash
uv run pytest tests/test_run_models.py tests/test_run_events.py -q
```

预期：**全部 ERROR**，`ImportError: cannot import name 'Conversation' from 'chatbi.db.models'`。

- [ ] **Step 4: 写 migration 0005**

新建 `apps/api/migrations/versions/0005_runs.py`：

```python
"""conversations, runs, run_events, run_result_previews

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

RUN_STATUSES = ("drafted", "blocked", "running", "succeeded", "failed", "cancelled")


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # RESTRICT 而不是 CASCADE：会话是审计对象，删用户/数据源不该静默销毁历史
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("datasource_id", sa.Uuid(),
                  sa.ForeignKey("datasources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # run 脱离会话没有意义 -> CASCADE
        sa.Column("conversation_id", sa.Uuid(),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("datasource_id", sa.Uuid(),
                  sa.ForeignKey("datasources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("chips", postgresql.JSONB(), nullable=True),
        # 三个 SQL 列都可空：drafted 时只有 generated_sql，blocked 时可能只有 final_sql
        sa.Column("generated_sql", sa.Text(), nullable=True),  # F-302 AC2 左侧
        sa.Column("final_sql", sa.Text(), nullable=True),      # 右侧
        sa.Column("effective_sql", sa.Text(), nullable=True),  # 注入 LIMIT 后实际下发
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("llm_provider", sa.String(50), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        # SET NULL（F-401 下钻）：删父 run 只断链，不连带删子 run。所以可空
        sa.Column("parent_run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        # CHECK 只写在 migration 里，与 users.role / datasources.kind 一致：建表永远走
        # Alembic，模型的 __table_args__ 根本不会被执行，写两份只会得到两份不同步的约束
        sa.CheckConstraint(
            "status in ('drafted','blocked','running','succeeded','failed','cancelled')",
            name="ck_runs_status",
        ),
    )
    op.create_index("ix_runs_conversation_id", "runs", ["conversation_id"])
    op.create_index("ix_runs_user_id", "runs", ["user_id"])
    # P3d 的历史列表按数据源 + 状态过滤（上游 §2.4）
    op.create_index("ix_runs_datasource_id", "runs", ["datasource_id"])

    op.create_table(
        "run_events",
        # bigserial：事件量远大于其他表，且没有对外暴露 id 的需求
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    # append-only 的**真正守卫**：即使有人绕过仓储直接写，重放一个已用过的 seq
    # 也会被 DB 拒绝。复合唯一而不是只对 seq 唯一——否则第二个 run 记不了事件
    op.create_index("uq_run_events_seq", "run_events", ["run_id", "seq"], unique=True)

    op.create_table(
        "run_result_previews",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("rows", postgresql.JSONB(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_table("run_result_previews")
    op.drop_index("uq_run_events_seq", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("ix_runs_datasource_id", table_name="runs")
    op.drop_index("ix_runs_user_id", table_name="runs")
    op.drop_index("ix_runs_conversation_id", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
```

`RUN_STATUSES` 那个常量在 migration 里定义了但 CHECK 用的是字面量 SQL——**这是有意的**：migration 是历史快照，不该在将来因为常量被改而改变含义。模型那边的 `RUN_STATUSES` 由测试钉住与这里一致。

**`downgrade()` 的顺序**：先删有外键指向别人的表。`runs.parent_run_id` 是自引用，`drop_table("runs")` 会连带删掉它，不需要单独处理。

- [ ] **Step 5: 加四个模型**

`apps/api/src/chatbi/db/models.py` 末尾追加。顶部的 `RUN_STATUSES` 常量与 `ROLES` / `DATASOURCE_KINDS` 放在一起：

```python
RUN_STATUSES: tuple[str, ...] = (
    "drafted",
    "blocked",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)
```

```python
class Conversation(Base):
    """一次多轮问答的容器（上游 spec §2.2：省略 conversation_id 时新建）。

    title 可空：P3c 决定它怎么来（截取问题或让 LLM 起名），本段不做。
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("datasources.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class Run(Base):
    """一次问答 + 执行的完整记录。审计的主体（上游 spec §4.6）。

    三个 SQL 列的分工是 F-302 AC2 的 diff 两侧 + 实际下发：
      generated_sql  LLM 原始生成版（左侧）
      final_sql      用户批准的版本（右侧）
      effective_sql  guard 注入 LIMIT/策略后真正下发的语句
    三者都可空：drafted 时只有 generated_sql，blocked 时可能只有 final_sql。

    status 的 CHECK 只在 migration 里，与 Datasource.kind 一致。
    """

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("datasources.id", ondelete="RESTRICT"), nullable=False
    )
    question: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    chips: Mapped[list[Any] | None] = mapped_column(JSONB(), nullable=True)
    generated_sql: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    final_sql: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    effective_sql: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    row_count: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class RunEvent(Base):
    """append-only 的事件流（上游 spec §2.5、§4.6，F-304）。

    **仓储层只暴露 append 与 list，没有 UPDATE/DELETE 路径。** 别在这里加
    relationship，也别给它写 update 方法——F-304 的可审计承诺全靠这一点。

    回放按 seq 排序，**不按 at**：同毫秒内的事件顺序不确定。
    """

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    step: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)
    at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class RunResultPreview(Base):
    """结果摘要，只存前 100 行（上游 spec §2.5）。回放时重跑取全量。"""

    __tablename__ = "run_result_previews"

    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    columns: Mapped[list[Any]] = mapped_column(JSONB(), nullable=False)
    rows: Mapped[list[Any]] = mapped_column(JSONB(), nullable=False)
    truncated: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.text("false")
    )
```

- [ ] **Step 6: 写 `runs/repository.py`**

`apps/api/src/chatbi/runs/__init__.py`：空文件。

`apps/api/src/chatbi/runs/repository.py`：

```python
"""run 事件流的持久化。

**这个模块只有 append 与 list，没有 update、没有 delete。** 上游 spec §2.5 与 §4.6
都要求 run_events 是 append-only（F-304 全链路可审计），落实方式就是仓储的形状——
往这里加一个 update_event 会让那个承诺失效，而不会有任何测试因此变红，所以
tests/test_run_events.py 里有一条测试专门扫本模块的导出名。

不 import fastapi：持久化是领域逻辑（spec §1.3 规则 2）。
"""

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from chatbi.db.models import RunEvent


def append_event(
    session: Session,
    *,
    run_id: uuid.UUID,
    seq: int,
    step: str,
    status: str,
    duration_ms: int | None = None,
    detail: dict[str, Any] | None = None,
) -> RunEvent:
    """追加一条事件。

    seq 由调用方给（执行流按事件顺序从 1 递增）。`unique (run_id, seq)` 会在重放一个
    已用过的 seq 时抛 IntegrityError——**那说明调用方的序号管理有 bug，不要 catch 掉
    它来「修复」**。

    detail 里**不放结果行内容**（上游 §4.6：不记录结果行内容到日志，只记行数）。
    结果摘要存 run_result_previews，受同样的权限控制；事件流是运维视角的，不该成为
    数据外泄的旁路。
    """
    event = RunEvent(
        run_id=run_id,
        seq=seq,
        step=step,
        status=status,
        duration_ms=duration_ms,
        detail=detail,
    )
    session.add(event)
    session.flush()
    return event


def list_events(session: Session, run_id: uuid.UUID) -> list[RunEvent]:
    """按 seq 升序。**不按 at 排序**——同毫秒内的事件顺序不确定，而回放要的是
    确定的顺序。也不按 id 排：id 是插入顺序，而 seq 是逻辑顺序，两者在乱序 append
    时会不一致。
    """
    statement = (
        sa.select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
    )
    return list(session.scalars(statement))
```

- [ ] **Step 7: 迁移双向断言加四张表**

`apps/api/tests/test_migrations.py`：

```python
TABLES = {
    "users",
    "sessions",
    "datasources",
    "datasource_grants",
    "schema_cache",
    "column_notes",
    "conversations",
    "runs",
    "run_events",
    "run_result_previews",
}
```

- [ ] **Step 8: 跑测试确认通过**

```bash
uv run pytest tests/test_run_models.py tests/test_run_events.py -q && uv run pytest -q
```

预期：两个文件 **12 passed**（7 建模 + 5 仓储），全量 **297 passed / 28 skipped**。

`test_migrations_roundtrip` 会真的 `downgrade base` 再 `upgrade head`，所以 0005 的 `downgrade()` 写错会在这里暴露，不需要单独测。

- [ ] **Step 9: 反向验证五条**

1. **`runs.conversation_id` 改成 `RESTRICT`** → `test_deleting_a_conversation_takes_its_runs` FAIL，其余全绿。
2. **`runs.datasource_id` 改成 `CASCADE`** → `test_a_datasource_with_history_cannot_be_deleted` FAIL（不抛 IntegrityError），其余全绿。这条守的是「审计记录不被静默销毁」。
3. **`parent_run_id` 改成 `CASCADE`** → `test_deleting_a_parent_run_only_breaks_the_link` FAIL（子 run 被连带删了，count 是 0 而不是 1）。
4. **`uq_run_events_seq` 去掉 `run_id`（只对 seq 唯一）** → `test_two_runs_can_both_use_seq_one` FAIL，而 `test_the_same_seq_cannot_be_used_twice_for_one_run` **保持绿**。两条互为对照。
5. **`list_events` 的 `order_by(RunEvent.seq)` 改成 `order_by(RunEvent.id)`** → `test_appending_events_keeps_them_in_seq_order` FAIL（乱序 append 那条），而 `test_events_survive_in_insertion_order_within_the_same_seq_gap` **保持绿**（那条的 seq 与 id 顺序一致）。这实证了后者单独存在时守不住排序——**两条必须都有**。

**反向验证 1–4 要改 migration，做完记得核对测试库的迁移状态**：p2c1 踩过一次，改 `upgrade()`/`downgrade()` 不对称时恢复代码不等于恢复库。这里四条都只改约束不改表结构，`downgrade` 仍能跑通，但跑完还是要 `uv run pytest tests/test_migrations.py -q` 确认一次。

- [ ] **Step 10: ruff + 提交**

```bash
uv run ruff check . && uv run ruff format --check .
git add migrations/versions/0005_runs.py src/chatbi/db/models.py src/chatbi/runs/ \
        tests/test_migrations.py tests/test_run_models.py tests/test_run_events.py
git commit -m "feat(db): conversations / runs / run_events / run_result_previews

照上游 spec §2.5 建四张表。外键的删除行为按「可重建的派生数据 vs 不可重建的
审计记录」分：runs.conversation_id 与两张从表 CASCADE，user_id 与
datasource_id 用 RESTRICT（删数据源不该静默销毁历史问答，要删得先处理历史
——有意的摩擦），parent_run_id 用 SET NULL（删父 run 只断 F-401 的下钻链）。

这与 P2c 的 schema_cache / column_notes 用 CASCADE 是有意的不同。

run_events 的 append-only（F-304）靠两件事落实：仓储只有 append_event 与
list_events 两个函数（有一条测试扫模块导出名，防住「顺手加个 update」），
以及 unique (run_id, seq) —— 后者是真正的守卫，绕过仓储直接写也会被 DB 拒。

list_events 按 seq 排序而不是 at 或 id：同毫秒内的 at 顺序不确定，而 id 是
插入顺序、seq 是逻辑顺序，乱序 append 时两者不一致。

其余三张表本段只有表与模型，仓储跟着各自的消费方（P3b/P3c/P3d）走。

297 passed / 28 skipped。"
```






---

### Task 4: `POST /api/datasources/{id}/sql/validate`

上游 spec §2.4 写的是 `POST /api/sql/validate`。**改挂到数据源下**：dialect 由 `datasource.kind` 决定，不带数据源就只能猜方言——而同一条 SQL 在不同方言下判定不同（`LIMIT 3 BY x` 在 postgres 下是 `ParseError`，在 clickhouse 下合法）。顺带让权限与 `/test`、`/schema`、`/grants` 自动一致（设计 §4）。

**Files:**
- Create: `apps/api/src/chatbi/guard/deps.py` · `apps/api/src/chatbi/api/sql_router.py`
- Modify: `apps/api/src/chatbi/datasources/schemas.py` · `apps/api/src/chatbi/api/routers.py`
- Test: `apps/api/tests/test_sql_router.py`

**Interfaces:**
- Consumes: Task 1–2 的 `validate_sql()` / `GuardVerdict` / `EmptyPolicyResolver` · P2b 的 `require_datasource` · `Settings.max_result_rows`
- Produces:
  ```python
  guard.deps.policy_resolver_for() -> PolicyResolver     # FastAPI 依赖，可 override
  datasources.schemas.SqlValidateRequest / SqlValidateResponse
  POST /api/datasources/{id}/sql/validate -> 200（ok 在体内）| 401 | 403 | 404
  ```

- [ ] **Step 1: 依赖、Pydantic 模型、方言映射**

`apps/api/src/chatbi/guard/deps.py`：

```python
"""guard 的 FastAPI 依赖。

policy_resolver_for 做成依赖**只为可测**：P3b 的执行器测试要能塞一个返回非空策略的
假 resolver，验证 validate_sql 真的会抛 NotImplementedError。P1 遗留 2 是反例
（get_identity_provider 当初不是依赖，测试里换不掉，拖到 P2a Task 1 才补）。
"""

from chatbi.guard.policy import EmptyPolicyResolver, PolicyResolver


def policy_resolver_for() -> PolicyResolver:
    """V2-1 恒返回 EmptyPolicyResolver（上游 spec §4.2）。"""
    return EmptyPolicyResolver()
```

`apps/api/src/chatbi/datasources/schemas.py` 末尾追加：

```python
class SqlValidateRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)
    """上限 100k 字符：一条人写或 LLM 生成的分析 SQL 远不到这个量级，而没有上限
    意味着每次按键都可能让服务端解析一个几十 MB 的字符串。"""


class SqlValidateResponse(BaseModel):
    """guard 判定的 HTTP 形态。

    **判定失败也返回 200**，ok=false 在体内——编辑器停止输入 300ms 就调一次
    （spec §2.4），用 4xx 表达「你这条 SQL 有写操作」会让前端把正常的输入过程当成
    错误流：用户打字打到一半必然产生大量语法不完整的中间态。401/403/404 仍然是真的
    HTTP 错误。
    """

    ok: bool
    code: str | None
    reason: str | None
    effective_sql: str | None
    limit_applied: bool
    """**前端不要靠比较字符串判断 LIMIT 有没有被改**——sqlglot 会重写整条语句
    （大小写、引号、空白全变），字符串比较必然误报。"""

    warnings: list[str]
```

- [ ] **Step 2: 写失败的测试**

新建 `apps/api/tests/test_sql_router.py`：

```python
"""POST /api/datasources/{id}/sql/validate。

只测**编排**：鉴权、判定失败仍 200、响应字段完整、方言按 kind 选。闸 2/闸 3 的
清单在 tests/test_guard_gate2.py 与 test_guard_gate3.py 已经测过，在 HTTP 层再跑
一遍只是让同一件事慢十倍（设计 §8.5）。
"""

import uuid

from fastapi.testclient import TestClient


def _post(client: TestClient, datasource_id, sql: str):
    return client.post(f"/api/datasources/{datasource_id}/sql/validate", json={"sql": sql})


def test_a_valid_query_comes_back_ok_with_the_effective_sql(
    admin_client, make_datasource
) -> None:
    datasource = make_datasource()

    response = _post(admin_client, datasource.id, "select * from demo_sales.orders")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["code"] is None
    assert "LIMIT 1000" in body["effective_sql"]
    assert body["limit_applied"] is True
    assert body["warnings"] == []


def test_a_write_statement_is_rejected_with_200(admin_client, make_datasource) -> None:
    """**判定失败也是 200**，ok=false 在体内（设计 §4.1）。编辑器每 300ms 调一次，
    用 4xx 会让前端把正常输入过程当成错误流。
    """
    datasource = make_datasource()

    response = _post(admin_client, datasource.id, "insert into t values (1)")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "WRITE_BLOCKED"
    assert body["reason"]  # 非空——用户要知道为什么
    assert body["effective_sql"] is None


def test_the_dialect_follows_the_datasource_kind(admin_client, make_datasource) -> None:
    """同一条 SQL 在两个 kind 下判定不同：`limit 3 by x` 在 clickhouse 下合法、在
    postgres 下是 ParseError。这条钉住「方言不是猜的」——也正是这个端点必须挂在
    数据源下的理由（设计 §4）。
    """
    ch = make_datasource(kind="clickhouse", port=8123)
    pg = make_datasource(kind="postgres")

    assert _post(admin_client, ch.id, "select * from t limit 3 by x").json()["ok"] is True
    pg_body = _post(admin_client, pg.id, "select * from t limit 3 by x").json()
    assert pg_body["ok"] is False
    assert pg_body["code"] == "SQL_PARSE_ERROR"


def test_a_limit_by_query_carries_a_warning(admin_client, make_datasource) -> None:
    ch = make_datasource(kind="clickhouse", port=8123)

    body = _post(admin_client, ch.id, "select * from t limit 3 by x").json()

    assert body["ok"] is True
    assert body["limit_applied"] is False
    assert body["warnings"]  # 非空


def test_an_anonymous_request_is_rejected(client: TestClient, make_datasource) -> None:
    """401 是真的 HTTP 错误，与「判定失败」不同。"""
    assert _post(client, make_datasource().id, "select 1").status_code == 401


def test_a_missing_datasource_is_404(admin_client) -> None:
    response = _post(admin_client, uuid.uuid4(), "select 1")

    assert response.status_code == 404
    assert response.json()["code"] == "DATASOURCE_NOT_FOUND"


def test_an_analyst_without_a_grant_is_403(client: TestClient, make_datasource,
                                           make_user, login_as) -> None:
    datasource = make_datasource()
    login_as(make_user(role="analyst"))

    response = _post(client, datasource.id, "select 1")

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_an_analyst_with_a_grant_can_validate(client: TestClient, db_session,
                                              make_datasource, make_user, login_as) -> None:
    """analyst 是这个端点的主要用户——他在编辑器里改 SQL（F-302）。"""
    from chatbi.datasources.repository import set_grant

    datasource = make_datasource()
    analyst = make_user(role="analyst")
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)
    login_as(analyst)

    assert _post(client, datasource.id, "select 1").json()["ok"] is True


def test_an_empty_sql_is_a_422(admin_client, make_datasource) -> None:
    """Pydantic 的 min_length=1 挡在 guard 之前。422 而不是 200+ok=false：空请求体
    是**协议错误**，不是一次得出「不通过」的校验。
    """
    response = admin_client.post(
        f"/api/datasources/{make_datasource().id}/sql/validate", json={"sql": ""}
    )

    assert response.status_code == 422


def test_the_response_carries_no_credentials(admin_client, make_datasource) -> None:
    datasource = make_datasource(password="ds-pw-123456")

    body = _post(admin_client, datasource.id, "select 1").text

    for leaked in ("ds-pw-123456", "secret_ciphertext", "secret_nonce"):
        assert leaked not in body
```

- [ ] **Step 3: 跑测试确认失败**

```bash
uv run pytest tests/test_sql_router.py -q
```

预期：**10 条全部 FAIL/ERROR**。`test_a_missing_datasource_is_404` 与 `test_an_anonymous_request_is_rejected` 两条**会因为路由不存在而拿到 404**，前者断言了 `code == "DATASOURCE_NOT_FOUND"`（路由不存在时响应体是 `{"detail": "Not Found"}` → 红）、后者断言 401（拿到 404 → 红），所以两条仍然会红。**核对失败原因确实是这两个，不是别的。**

- [ ] **Step 4: 写 `api/sql_router.py`**

```python
"""/api/datasources/{id}/sql/validate 的 HTTP 编排。

**本文件是唯一同时认识 Datasource 与 guard 的地方**：从 datasource.kind 取方言、
从 Settings 取行数上限、从依赖取 policy，然后调纯函数。guard 自己不认识数据源模型
（它是安全红线，必须能脱离库穷举边界）。

不写 db.commit()：这个端点不写库（设计 §4.3——它每 300ms 就可能被调一次，为每次
按键建审计记录会把 run_events 变成击键日志，而 F-304 要审计的是执行，不是编辑过程）。
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from chatbi.auth.deps import current_user
from chatbi.auth.schemas import ErrorResponse
from chatbi.config import get_settings
from chatbi.datasources.deps import require_datasource
from chatbi.datasources.schemas import SqlValidateRequest, SqlValidateResponse
from chatbi.db.models import Datasource, User
from chatbi.guard.deps import policy_resolver_for
from chatbi.guard.policy import PolicyResolver
from chatbi.guard.validator import validate_sql

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/datasources", tags=["sql"])

_CurrentUser = Annotated[User, Depends(current_user)]
_Target = Annotated[Datasource, Depends(require_datasource)]
_Resolver = Annotated[PolicyResolver, Depends(policy_resolver_for)]

_TARGET = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}

# kind -> sqlglot 方言名。三者现在同名，但**显式写出来**而不是直接传 kind：
# 两套命名空间的巧合不是契约，将来加一个 kind（比如 "trino"）时映射可能不同。
_DIALECTS = {"postgres": "postgres", "mysql": "mysql", "clickhouse": "clickhouse"}


@router.post(
    "/{datasource_id}/sql/validate",
    response_model=SqlValidateResponse,
    responses=_TARGET,
)
def validate(
    payload: SqlValidateRequest,
    datasource: _Target,
    resolver: _Resolver,
    user: _CurrentUser,
) -> SqlValidateResponse:
    """闸 2 + 闸 3 的判定（上游 spec §2.4）。

    **判定失败返回 200 + ok=false**，不是 4xx——见 SqlValidateResponse 的文档字符串。
    """
    verdict = validate_sql(
        payload.sql,
        dialect=_DIALECTS[datasource.kind],
        max_rows=get_settings().max_result_rows,
        policy=resolver.resolve(user_id=user.id, datasource_id=datasource.id),
    )
    return SqlValidateResponse(
        ok=verdict.ok,
        code=verdict.code,
        reason=verdict.reason,
        effective_sql=verdict.effective_sql,
        limit_applied=verdict.limit_applied,
        warnings=list(verdict.warnings),
    )
```

- [ ] **Step 5: 接进 `ALL_ROUTERS`**

`apps/api/src/chatbi/api/routers.py`：

```python
from chatbi.api.sql_router import router as sql_router

ALL_ROUTERS: tuple[APIRouter, ...] = (
    auth_router,
    datasource_router,
    schema_router,
    sql_router,
    user_router,
)
```

`sql_router` 与前两个同 prefix，但路径多两段（`/{id}/sql/validate`），不会与 `/{datasource_id}` 抢匹配——与 grants、schema 同一个情形，声明顺序无所谓。

- [ ] **Step 6: 跑测试确认通过**

```bash
uv run pytest tests/test_sql_router.py -q && uv run pytest -q
```

预期：该文件 **10 passed**，全量 **307 passed / 28 skipped**。

`test_app_assembly.py::test_all_routers_are_mounted_on_the_real_app` **不需要改**（它遍历 `ALL_ROUTERS` 并对 OpenAPI paths 断言，自适应）。但注意它守不住「漏了 Step 5」——router 不在 `ALL_ROUTERS` 里就不会被遍历到；那种情况下红的是本文件的 10 条。两者各守一半。

- [ ] **Step 7: 反向验证四条**

1. **`_DIALECTS[datasource.kind]` 换成硬编码 `"postgres"`** → `test_the_dialect_follows_the_datasource_kind` 与 `test_a_limit_by_query_carries_a_warning` FAIL，其余全绿。这条守的是「方言不是猜的」，也是这个端点挂在数据源下的全部理由。
2. **判定失败改成抛 `ApiError(*WRITE_BLOCKED)`（即返回 400）** → `test_a_write_statement_is_rejected_with_200` FAIL，而 401/403/404 三条**保持绿**。后半条重要：它证明「真 HTTP 错误」与「判定失败」两条路径是分开的，改一条不影响另一条。
3. **`max_rows` 换成写死的 `1000`** → 全部保持绿（`Settings.max_result_rows` 默认就是 1000）。**这是一条没有守卫的路径**，如实记进「实施期的偏差」——要守它得加一条改 `CHATBI_MAX_RESULT_ROWS` 环境变量的测试，而 `get_settings()` 有 `lru_cache`，那需要清缓存，成本高于收益。guard 层的 `test_the_cap_comes_from_the_argument_not_from_settings` 已经守住了「guard 不自己读 settings」这一半。
4. **`resolver.resolve(...)` 换成 `Policy()`** → 全部保持绿（V2-1 的 resolver 恒返回空策略，两者等价）。同样是**没有守卫的路径**，要记。它的真正守卫在 P3b：那里会用 `dependency_overrides` 塞一个返回非空策略的假 resolver。

第 3、4 条的结论要如实写进偏差记录：**它们是已知的无守卫路径，不是 bug**。发现「反向验证全绿」时不要改测试去凑，要么承认它没被守住并写明，要么加一条真能守住的测试。

- [ ] **Step 8: ruff + 全量 + 提交**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -q      # 307 passed / 28 skipped
git add src/chatbi/guard/deps.py src/chatbi/api/sql_router.py src/chatbi/api/routers.py \
        src/chatbi/datasources/schemas.py tests/test_sql_router.py
git commit -m "feat(api): POST /api/datasources/{id}/sql/validate

上游 spec §2.4 写的是 /api/sql/validate，改挂到数据源下：dialect 由 kind 决定，
不带数据源只能猜方言——而 limit 3 by x 在 clickhouse 下合法、在 postgres 下是
ParseError，同一条 SQL 两种判定。顺带让权限与 /test、/schema 自动一致。

判定失败返回 200 + ok=false，不是 4xx：编辑器停止输入 300ms 就调一次，用 4xx
会让前端把正常输入过程当成错误流（打字到一半必然产生语法不完整的中间态）。
401/403/404 仍然是真的 HTTP 错误，两条路径分开。

kind -> sqlglot 方言名显式映射而不是直接传 kind：三者现在同名，但两套命名空间
的巧合不是契约。

307 passed / 28 skipped。"
```





## 收尾：要回填进上游 spec 的三处（做完 Task 4 后一次做掉）

这三处都是 P3a 对上游 spec 的**有意偏离**（设计 §9.1）。不回填的后果具体：下一个读 spec 的人会以为实现写错了，或者照 spec 重写一遍已经被证伪的做法。

- [x] **回填 1：§2.4 的端点路径** —— 已做（`2026-08-11` spec 第 165 行 + §3.5 那处对旧路径的引用也一起改了）

`docs/superpowers/specs/2026-08-11-chatbi-v2-1-design.md` 的 REST 端点表里，`POST /api/sql/validate` 改成 `POST /api/datasources/{id}/sql/validate`，并加一句理由：dialect 由 `kind` 决定，不带数据源只能猜方言（`limit 3 by x` 在 clickhouse 下合法、在 postgres 下是 `ParseError`）。

- [x] **回填 2：§2.6 的错误码表加 `MULTIPLE_STATEMENTS`** —— 已做

原表把多语句归在 `WRITE_BLOCKED`（「AST 命中写操作/DDL/多语句」）。拆开并写明理由：用户动作不同，一个要改掉写操作，一个要删掉分号后面的部分。

- [x] **回填 3：§4.3 闸 2 那段加一句「只看根节点不够」** —— 已做，加了一张三道检查的表 + `exp.Command` 兜底。**顺带发现 spec 内部本来就不一致**：§5.1 早就点名要测「CTE 里藏 DML、`SELECT ... INTO`」，是 §4.3 的实现描述漏了那一层，两节现在对齐了

原文是「sqlglot 解析后只放行 `SELECT` 与 `WITH`」。加一句：**照字面实现会留两个能真正写库的缺口**——data-modifying CTE 的根节点就是 `Select`，`SELECT INTO` 连整树扫描都躲得过（树内写节点为空，靠 `into` arg 识别）。两者都是实测确认的，详见 P3a 设计 §1.2、§1.3。

顺带加一句 `exp.Command` 的兜底行为：sqlglot 对不认识的语句不抛 `ParseError` 而是给一个 `Command` 节点，所以白名单必须是严格白名单。

- [x] **回填 4：把本份与 p3a1 的实施结果写进各自的「实施期的偏差」，然后提交** —— 已做

```bash
git add docs/superpowers/specs/2026-08-11-chatbi-v2-1-design.md \
        docs/superpowers/plans/2026-08-20-chatbi-v2-1-p3a1-guard.md \
        docs/superpowers/plans/2026-08-20-chatbi-v2-1-p3a2-tables-and-endpoint.md
git commit -m "docs: 回填 P3a 的实施期偏差，并把三处有意偏离同步进上游 spec"
```

---

## 实施期的偏差（执行中回填）

### 两个任务都已完成（2026-08-20/21）

| 任务 | commit | 实测 | 计划预期 |
|---|---|---|---|
| Task 3 四张表 + append-only 仓储 | `9999141` | **299 passed** / 28 skipped | 297（多了 2 条测试，见偏差 1、2） |
| Task 4 `/sql/validate` | `0e6cc47` | **310 passed** / 28 skipped | 307（同上，多 1 条） |

migration 0005 的 up/down 双向由 `test_migrations_roundtrip` 自动覆盖，一次通过。

### 偏差 1：一条测试原本守的是列宽而不是 CHECK

计划里 `test_an_unknown_run_status_is_rejected` 用 `"definitely-not-a-status"`（**23 字符**）当非法状态值。`status` 是 `String(20)`，所以它先撞列长度限制抛 `DataError`，**在 CHECK 约束之前就炸了**——那条测试守的是列宽，不是 `ck_runs_status`。

改成 `"nope"`（4 字符）后才真正触发 CHECK。顺带加了 `test_the_status_constant_matches_the_check_constraint`：遍历 `RUN_STATUSES` 把每个值都 flush 一遍。理由是那个常量与 migration 的 CHECK 是**两份字面量**（migration 是历史快照，不引用常量），常量加了新状态而 CHECK 没改的话，那个状态会在 P3b 的执行流里被 DB 拒绝，报错完全不指向这里。

**这个形状值得记**：用超长值测 CHECK 约束会得到一条看起来绿、实际守错东西的测试。

### 偏差 2：`runs.datasource_id` 的 RESTRICT 本来没有守卫

Task 3 Step 9 的反向验证第 2 条（`runs.datasource_id` 改成 `CASCADE`）**按计划该红，实测全绿**。

原因：`make_run` 让 run 与 conversation 用同一个数据源，而 `conversations.datasource_id` **也是** RESTRICT——删数据源时那条外键先拦住了。所以 `test_a_datasource_with_history_cannot_be_deleted` 守的是 conversations 那一列，`runs` 这一列的 RESTRICT 谁都没守。

加了 `test_a_run_pins_its_own_datasource_even_when_the_conversation_points_elsewhere`：让 run 指向另一个数据源，删它时只有 runs 这条外键能拦。加完重跑那条反向验证，从全绿变成红 1 条。

### 偏差 3：计划里一处对 sqlglot 的假设是错的（从实测结论错误推广来的）

计划的 `test_the_dialect_follows_the_datasource_kind` 断言 `limit 3 by x` 在 clickhouse 下合法、**在 postgres 下是 `SQL_PARSE_ERROR`**。实测**这是错的**——三个方言下 sqlglot 都能解析它，都产生带 `expressions` 的 `exp.Limit`：

```
postgres    根=Select  limit=Limit  expressions=True  ->  SELECT * FROM t LIMIT 3 BY x
mysql       根=Select  limit=Limit  expressions=True  ->  SELECT * FROM t LIMIT 3 BY x
clickhouse  根=Select  limit=Limit  expressions=True  ->  SELECT * FROM t LIMIT 3 BY x
```

这个假设的来源是**把一个实测结论错误地推广了**：写 P3a 设计时实测过 `limit 3 by x limit 5000`（两个 LIMIT）会 `ParseError`，我据此以为 `LIMIT BY` 本身是 ClickHouse 独占语法。**两件事无关。**

两个后果，都已处理：

1. **那条测试改用 ClickHouse 的 `SETTINGS` 子句**。实测 `select * from t settings max_threads = 1` 只有 clickhouse 方言接受，postgres 与 mysql 都是 `ParseError`——这才是真正的方言差异。
2. **闸 3 的 `LIMIT BY` 分支不是 ClickHouse 独占的**。一条 `limit 3 by x` 发到 Postgres 数据源会被 guard 放过（原样保留 + warning），然后由**库侧**报语法错。这是可接受的反馈路径：P3b 会返回 `QUERY_FAILED` 并带库的原文，用户据此改 SQL——guard 不做语法教师。已写进 `test_a_limit_by_query_carries_a_warning` 的注释。**设计 §2.2 把它称作「ClickHouse 的 `LIMIT n BY x`」，措辞偏窄**，行为上对三个方言一视同仁。

### 偏差 4：一条测试在实现前就是绿的（空洞通过）

`test_the_response_carries_no_credentials` 只做否定断言（「响应里没有密码」）。路由还不存在时 FastAPI 返回 `{"detail": "Not Found"}`，里面当然也没有凭据——**所以它在 Step 3「确认失败」那一步是绿的**，11 条里只有它通过。

补上 `assert response.status_code == 200` 的下限后，11 条全红。

**P2c 的自查记录里记过完全同一个坑**（那次是「两条只做否定断言的测试补了状态码下限」），这次写计划时还是漏了。所以这条留在了测试的文档字符串里，而不只是记在偏差里。

### 反向验证的结果

Task 3 五条、Task 4 四条，全部与计划一致（含偏差 2 那条修正后的）。两处值得记：

- **Task 3 反向 4**（唯一索引去掉 `run_id`）红 2 条而非 1 条：`test_list_events_does_not_leak_another_runs_events` 也建两个 run 各用 `seq=1`，所以它也被破掉。而 `test_the_same_seq_cannot_be_used_twice_for_one_run` **保持绿**——互为对照成立。
- **Task 4 反向 3、4 如预期全绿**（`max_rows` 写死、`resolver.resolve` 换成 `Policy()`）。这是计划已经写明的两条**无守卫路径**，不是 bug：前者的另一半由 guard 层的 `test_the_cap_comes_from_the_argument_not_from_settings` 守，后者的真正守卫在 P3b（用 `dependency_overrides` 塞返回非空策略的假 resolver）。**没有改测试去凑。**

### 一处操作层面的记录

Task 4 的四条反向验证串在一个 bash 命令里跑，**超过了 8 分钟的命令超时**（每次改完都要跑一次 11 条端点测试，而端点测试要建库夹具）。中断时文件停在反向 3 的修改状态，靠 `/tmp` 里的备份恢复。

**下次把反向验证拆成每次 1–2 条跑**，别串四条。顺带确认了一件事：改的是未提交的新文件时 `git checkout` 救不了（会直接删掉它），所以那个 `cp $R /tmp/xx.bak` 的习惯不能省。

---

## 交接清单（P3b / P3c / P3d 要消费的签名）

```python
# 模型（chatbi.db.models）
Conversation / Run / RunEvent / RunResultPreview
RUN_STATUSES = ("drafted","blocked","running","succeeded","failed","cancelled")
#   status 的 CHECK 在 migration 0005 里，模型侧只有常量；两者一致由测试钉住

# 审计（chatbi.runs.repository）
append_event(session, *, run_id, seq: int, step: str, status: str,
             duration_ms: int | None = None, detail: dict | None = None) -> RunEvent
list_events(session, run_id) -> list[RunEvent]
#   **没有 update / delete**（F-304）。detail 里不放结果行内容（上游 §4.6：只记行数）
#   seq 由调用方给，从 1 递增。unique (run_id, seq) 会在重放已用过的 seq 时抛
#   IntegrityError —— 那说明调用方的序号管理有 bug，**不要 catch 掉它来「修复」**

# guard 的 FastAPI 依赖（chatbi.guard.deps）
policy_resolver_for() -> PolicyResolver
#   可被 dependency_overrides 替换。P3b 要验「非空 policy 会抛 NotImplementedError」
#   就靠它塞一个假 resolver

# 端点
POST /api/datasources/{id}/sql/validate -> 200（ok 在体内）| 401 | 403 | 404
#   响应体 SqlValidateResponse：ok / code / reason / effective_sql /
#   limit_applied / warnings
```

**P3b 执行器**
- run 的三个 SQL 列分工：`generated_sql`（LLM 原始版，F-302 AC2 左侧）· `final_sql`（用户批准的原文，右侧）· `effective_sql`（guard 注入后实际下发）。**三者都可空**，因为 drafted 时只有第一个、blocked 时可能只有第二个。
- `verdict.ok is False` → run 置 `blocked`，流即结束（上游 §2.3）。
- 事件 `seq` 从 1 递增。回放**按 seq 排序，不按 at 也不按 id**：同毫秒内的 `at` 顺序不确定，而 `id` 是插入顺序、`seq` 是逻辑顺序，乱序 append 时两者不一致。
- `QUERY_TIMEOUT` / `QUERY_CANCELLED` 两个错误码由 P3b 新增。
- `run_result_previews` 只存前 100 行（上游 §2.5），全量导出在 P3d 重跑 SQL。

**P3c 问答流**
- `conversations.title` 可空，怎么来由 P3c 定（截取问题或让 LLM 起名）。
- `run.generated_sql` **不经过 guard**——它可能是废的，那正是 `blocked` 状态要表达的。guard 只在执行流上跑。
- `conversations` 与 `runs` 的仓储本份没做（只有表和模型），跟着 P3c 的写路径一起加。

**P3d 回放**
- `list_events()` 已就位。`runs` 的三个索引（`conversation_id` / `user_id` / `datasource_id`）是为历史列表的过滤准备的（上游 §2.4：按数据源/状态过滤）。

---

## 自查记录

**设计 spec 覆盖核对（本份负责的部分）**

| 设计条目 | 落在哪 |
|---|---|
| §4 `/sql/validate` 挂到数据源下、契约 | Task 4 Step 1、Step 4 |
| §4.1 判定失败也返回 200 | Task 4 Step 2 的 `test_a_write_statement_is_rejected_with_200` |
| §4.2 `limit_applied` 独立字段 | `SqlValidateResponse` 的字段与文档字符串 |
| §4.3 端点无状态、不建 run | `sql_router.py` 的文件头 + 不写 `db.commit()` |
| §5 四张表的建表 SQL | Task 3 Step 4 |
| §5.1 七个外键的删除行为 | Task 3 Step 4 + Step 1 的四条删除行为用例 |
| §5.2 append-only 的落实方式 | Task 3 Step 6 的仓储 + Step 2 的导出名扫描用例 + `unique (run_id, seq)` |
| §5.3 只做 `run_events` 的仓储 | Task 3（其余三张表只有表与模型） |
| §6.2 `PolicyResolver` 做成 FastAPI 依赖 | Task 4 Step 1 的 `guard/deps.py` |
| §7.4 `runs/` 是独立顶层包 | File Structure 的边界说明 |
| §8.5 端点测试不重复 guard 的清单 | Task 4 Step 2 的文件头 |
| §9.1 三处有意偏离要回填 | 「收尾」一节 |

**不在本份的设计小节**：§1（闸 2）· §2（闸 3）· §3（`GuardVerdict` 与错误码）· §6.1（`Policy` 参数与护栏）——全部在 p3a1。

**计数链核对**：285（p3a1 结束，实测）→ 297（Task 3 +12）→ **307（Task 4 +10）**。skip 全程恒 28。（初稿写的 278/290/300 基于 p3a1 那个算错的条数，已按实测顺移。）实测与本表不符就停下核对，别改断言凑数。

**占位符扫描**：无 TBD / TODO / 「类似 Task N」/ 无代码的「写测试」步骤。Task 4 Step 7 的第 3、4 条明确写了「预期全绿」以及为什么那不是 bug——那不是占位符，是一条如实记录的结论。

**类型一致性核对**

四个模型的字段名与 migration 0005 的列名逐一对应（`Run` 十七列、`RunEvent` 八列、`Conversation` 五列、`RunResultPreview` 四列）。`append_event()` 的六个关键字参数与 `RunEvent` 的可写列一致（不含 `id` 与 `at`，两者由 DB 给）。`SqlValidateResponse` 的六个字段与 `GuardVerdict` 的六个字段一一对应，只有 `warnings` 做了 `tuple -> list` 转换（Pydantic 序列化需要）。

`_DIALECTS` 的键必须与 `db.models.DATASOURCE_KINDS` 完全一致——**漏一个 kind 会让那种数据源的 `/sql/validate` 抛 `KeyError` 500**。这条没有专属测试（`make_datasource` 默认建 postgres），Task 4 Step 2 的 `test_the_dialect_follows_the_datasource_kind` 只覆盖了 postgres 与 clickhouse 两个。**mysql 那个键没有测试覆盖**，如实记在这里；要补就往那条用例加一个 mysql 分支。

**写作过程中的回改一处**

**`run_events.id` 用 `BigInteger` + `autoincrement=True` 而不是 `sa.BigInteger` 的默认**。上游 spec §2.5 写的是 `bigserial`，SQLAlchemy 里主键 `BigInteger` 默认就会生成 `BIGSERIAL`，但显式写 `autoincrement=True` 是为了让「这一列不由应用给值」在模型上可见——`append_event()` 不传 `id`，读代码的人不该需要去查 SQLAlchemy 的默认行为才能确认这一点。
