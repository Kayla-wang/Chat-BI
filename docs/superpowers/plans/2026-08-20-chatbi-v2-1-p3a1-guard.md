# Chat-BI V2-1 · P3a1 guard（闸 2 与闸 3）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「哪些 SQL 允许执行」这条红线做成一个能穷举边界、可单独验收的纯逻辑模块。

**Architecture:** 两个任务，都在 `guard/` 包里。Task 1 是闸 2（三道 AST 检查：根节点白名单、整树扫描写节点、`into` arg 检查）。Task 2 是闸 3（LIMIT 注入，`limit` arg 的三种节点形态）。全是纯函数——不 import fastapi、不 import sqlalchemy，所以能把边界穷举完，这是上游 spec §5.1 对 guard 的硬要求。

**Tech Stack:** Python 3.12 · sqlglot · pytest · ruff

**设计依据：** `docs/superpowers/specs/2026-08-20-chatbi-v2-1-p3a-guard-design.md`（commit `40aff5e`）的 §1、§2、§3、§6。行文以「设计 §N」引用。上游 spec 是 `2026-08-11-chatbi-v2-1-design.md`。

**P3a 按体量拆成两份**（单份超 ~2000 行就该拆文件）。任务编号连续，跨文件说「Task N」不歧义：

| 份 | 任务 | 交付 |
|---|---|---|
| **本份** `p3a1` | Task 1–2 | 闸 2 三道 AST 检查 · 闸 3 LIMIT 注入 · `Policy` 注入点 |
| `...-p3a2-tables-and-endpoint.md` | Task 3–4 | 四张表 + migration 0005 · `run_events` append-only 仓储 · `POST /{id}/sql/validate` |

做完本份**后端没有任何新端点** —— guard 是一个纯函数库，它的 HTTP 入口在 p3a2 Task 4。这是有意的：安全红线代码先把边界穷举完，再接线。

**P3a 本身是 P3 四段里的第一段**（划分见设计 §0）。P3a 全部做完后仍然**没有执行器、没有 SSE、没有 LLM** —— 那是 P3b/P3c/P3d。

## Global Constraints

**唯一的新依赖是 `sqlglot`**（实测 30.17.0）。纯 Python、无编译依赖。别顺手装别的。

**`guard/` 是安全红线，不 import fastapi、不 import sqlalchemy。** 它的输入是「一条 SQL + 方言名 + 行数上限 + 策略」，输出是一个 frozen dataclass。允许 import `errors.ApiError`（错误契约不是框架依赖，与 `repository.py` 文件头写明的同一条约定）。`guard/validator.py` 保持 **≤200 行**（上游 spec §1.4 点名）。

**白名单是严格白名单。** sqlglot 对不认识的语句**兜底成 `exp.Command` 而不抛 ParseError**（实测：`vacuum` / `call proc()` / `explain select 1` 都是 `Command`）。`Command` 里可以是任何东西，包括厂商特有的写语句——**放行它等于放行一切未知语法**。往白名单加节点类型前，先问「这个类型的内容是否封闭可知」。

**写操作永久禁用，不做任何放行开关**（上游 spec §4.3）。不加 `allow_write` 参数、不加环境变量、不加「管理员可以」的分支。一个能被打开的闸不是闸。

**闸的实现只有一份。** P3b 的执行器调同一个 `validate_sql()`。任何「执行流里再检查一遍」或「这里简单判断一下」都会变成第二个真相源，而两个真相源里总有一个是旧的。

**每个任务的反向验证都要写明「哪几条转红、哪几条必须保持绿」**，两者都要核对。guard 尤其重要：三道检查各守一个缺口，反向验证要能证明它们**互不兜底**——只跑「删掉某道 → 有测试红了」不够，还要证明其余测试**没红**，否则无法区分「这道检查有专属守卫」与「随便删点什么都会红」。

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
- **起点基线：`226 passed` / `28 skipped`**（commit `0563c43`，P2c 结束时）。开工前先跑一次确认。



## File Structure

### 本份创建的文件

| 文件 | 职责 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/guard/__init__.py` | 空 | 1 |
| `apps/api/src/chatbi/guard/policy.py` | `Policy` · `PolicyResolver` 协议 · `EmptyPolicyResolver` | 1 |
| `apps/api/src/chatbi/guard/schemas.py` | `GuardVerdict`（frozen dataclass，不是 Pydantic） | 1 |
| `apps/api/src/chatbi/guard/validator.py` | 闸 2 三道检查（Task 1）+ 闸 3 LIMIT 注入（Task 2）。**≤200 行** | 1、2 |
| `apps/api/tests/test_guard_gate2.py` | 闸 2 的拒绝/放行清单，参数化 | 1 |
| `apps/api/tests/test_guard_gate3.py` | 闸 3 的七种形态 × 三方言 | 2 |
| `apps/api/tests/test_guard_policy.py` | `Policy` 非空即 `NotImplementedError` | 1 |

### 本份修改的文件

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/pyproject.toml` | 加 `sqlglot>=30`（本份唯一的新依赖） | 1 |
| `apps/api/src/chatbi/errors.py` | 加 `WRITE_BLOCKED` / `SQL_PARSE_ERROR` / `MULTIPLE_STATEMENTS` | 1 |

### 本份不碰的东西

四张表与 migration 0005 · `runs/` 包 · `guard/deps.py` · `api/sql_router.py` · `datasources/schemas.py` 的两个 Pydantic 模型 · `api/routers.py` 的接缝——**全部在 p3a2**。

**为什么 `guard/deps.py`（FastAPI 依赖）也在 p3a2**：本份的 `guard/` 一个 fastapi 都不 import，这条约束在文件层面可见比写在注释里可靠。依赖是 HTTP 接线的一部分，跟端点一起做。

### 边界说明

**`guard/` 是独立顶层包，不塞进 `datasources/`**：它不认识数据源模型、不认识仓储、不发任何查询。放进 `datasources/` 会让人以为它需要数据源对象，从而在将来给它传 ORM 对象——那会让它不可脱离库测试，而它是安全红线，必须能穷举边界。

**`GuardVerdict` 是 frozen dataclass 而不是 Pydantic 模型**：guard 是领域层，它的输出要能脱离 HTTP 用（P3b 的执行器直接消费它）。HTTP 响应模型在 p3a2 的 `datasources/schemas.py` 里单独声明，两者刻意分开——执行器不该 import Pydantic 响应模型。

**`validator.py` 的 200 行上限是硬的**（上游 spec §1.4 点名）。Task 2 加完 LIMIT 注入后若超了，正确的拆法是把 LIMIT 处理搬到 `guard/limits.py`，**不是删注释**：那些注释记的是实测结论，删掉之后下一个人会把 `into` 检查和 `_row_cap` 里读两个 arg 的写法当成多余的。



### Task 1: 闸 2 —— 三道 AST 检查

上游 spec §4.3 说「只放行 `SELECT` 与 `WITH`」。照字面实现会留**两个能真正写库的缺口**，所以是三道检查（设计 §1）。本任务结束时 `validate_sql()` 已经能用，只是还不注入 LIMIT（Task 2 加）。

**Files:**
- Create: `apps/api/src/chatbi/guard/__init__.py`（空）· `guard/policy.py` · `guard/schemas.py` · `guard/validator.py`
- Modify: `apps/api/pyproject.toml`（加 `sqlglot>=30`）· `apps/api/src/chatbi/errors.py`
- Test: `apps/api/tests/test_guard_gate2.py` · `apps/api/tests/test_guard_policy.py`

**Interfaces:**
- Consumes: `errors` 里的三个码元组（只取 `code` 与 `message` 两个字段填进 verdict）。**guard 不抛 `ApiError`** ——它靠返回 `GuardVerdict(ok=False, ...)` 表达拒绝，因为「这条 SQL 不合格」不是一个 HTTP 异常，而是一次成功校验的结果。把它翻成 HTTP 是 p3a2 端点的事，而 P3b 的执行器会把它翻成 SSE 的 `validate` 事件——同一个 verdict 两种呈现，抛异常就做不到。
- Produces:
  ```python
  guard.policy.Policy(row_filters: tuple[str, ...], denied_columns: frozenset[str])
  guard.policy.PolicyResolver   # Protocol，resolve(*, user_id, datasource_id) -> Policy
  guard.policy.EmptyPolicyResolver
  guard.schemas.GuardVerdict(ok, effective_sql, code, reason, limit_applied, warnings)
  guard.validator.validate_sql(sql, *, dialect, max_rows, policy) -> GuardVerdict
  errors.WRITE_BLOCKED / SQL_PARSE_ERROR / MULTIPLE_STATEMENTS
  ```
  Task 2 往 `validate_sql` 里加 LIMIT 注入；**p3a2 的 Task 4** 在端点里调它。

- [ ] **Step 1: 装 `sqlglot` 并加三个错误码**

```bash
cd apps/api
uv add sqlglot
uv run python -c "import sqlglot; print(sqlglot.__version__)"   # 记下这个版本号
```

**把实测版本号记进本份的「实施期的偏差」一节**：AST 节点类名（`exp.Insert`）与 arg 名（`args["into"]`、`args["limit"]`）是 sqlglot 的内部结构，跨大版本可能变，而三道检查全靠这些名字。写计划时实测的是 30.17.0。

`apps/api/src/chatbi/errors.py`，在 `COLUMN_ID_AMBIGUOUS` 之后追加：

```python
# 闸 2（上游 spec §4.3、§2.6）。三个都是 400 而不是 403：被拒的原因是「这条语句
# 不允许执行」，不是「你没权限」——403 会让前端渲染成权限问题，而用户改一下 SQL
# 就能过。PERMISSION_DENIED(403) 留给真正的授权失败，那在 require_datasource 里。
#
# reason 里可以带用户自己写的 SQL 的信息（哪一类写操作、解析失败的行列号），那不是
# 结构泄露；但**不带表名与列名**——那部分可能来自被污染的 LLM 输出或库结构。
WRITE_BLOCKED = ("WRITE_BLOCKED", "该语句不允许执行", 400)
SQL_PARSE_ERROR = ("SQL_PARSE_ERROR", "SQL 无法解析", 400)
# 从 WRITE_BLOCKED 里分出来（上游 §2.6 把两者归在一起）：用户动作不同，一个要改掉
# 写操作，一个要删掉分号后面的部分。合成一个码前端只能给一句笼统的话。
MULTIPLE_STATEMENTS = ("MULTIPLE_STATEMENTS", "一次只能执行一条语句", 400)
```

- [ ] **Step 2: 写 `guard/policy.py` 与 `guard/schemas.py`**

`apps/api/src/chatbi/guard/__init__.py`：空文件。

`apps/api/src/chatbi/guard/policy.py`：

```python
"""行列级策略的注入点（上游 spec §4.2、§6）。

V2-1 只有 EmptyPolicyResolver。V2-2 落地行列级权限时**只改这个文件与语义层新表**，
执行器与 guard 的调用方不动——这是 spec §4.2 的承诺，而它成立的前提是
validate_sql() 的签名现在就有 policy 参数。
"""

import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Policy:
    """V2-1 恒为空。"""

    row_filters: tuple[str, ...] = ()
    """要 AND 进 WHERE 的条件表达式。"""

    denied_columns: frozenset[str] = field(default_factory=frozenset)
    """禁止出现在结果里的列名。"""

    @property
    def is_empty(self) -> bool:
        return not self.row_filters and not self.denied_columns


class PolicyResolver(Protocol):
    def resolve(self, *, user_id: uuid.UUID, datasource_id: uuid.UUID) -> Policy: ...


class EmptyPolicyResolver:
    """V2-1 唯一实现：恒返回空策略（上游 spec §4.2）。"""

    def resolve(self, *, user_id: uuid.UUID, datasource_id: uuid.UUID) -> Policy:
        return Policy()
```

`apps/api/src/chatbi/guard/schemas.py`：

```python
"""guard 的输出。

frozen dataclass 而不是 Pydantic 模型：guard 是领域层，它的输出要能脱离 HTTP 用
（P3b 的执行器直接消费它）。HTTP 响应模型在 datasources/schemas.py 里单独声明。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GuardVerdict:
    ok: bool
    effective_sql: str | None
    """实际会下发的语句。ok=False 时为 None——被拒的语句没有「实际会跑的版本」。"""

    code: str | None
    reason: str | None
    limit_applied: bool
    """注入或收紧了行数上限。**前端不要靠比较字符串判断这件事**——sqlglot 会重写
    整条语句（大小写、引号、空白全变），字符串比较必然误报。"""

    warnings: tuple[str, ...] = ()
    """不阻止执行，但用户该知道。"""
```

- [ ] **Step 3: 写失败的测试（闸 2 清单）**

新建 `apps/api/tests/test_guard_gate2.py`。**清单里每一条 SQL 都是写计划时对 sqlglot 30.17.0 实测过的**，判定不是推演：

```python
"""闸 2（AST 校验）—— 上游 spec §4.3 的第二道闸。

三道检查各守一个缺口，测试按检查分组。用参数化而不是一堆独立函数：清单会长，
而每条的断言完全相同，写成独立函数只会让人不敢往里加新样本（spec §5.1 要求
guard 穷举边界）。
"""

import pytest

from chatbi.guard.policy import Policy
from chatbi.guard.validator import validate_sql


def _verdict(sql: str, dialect: str = "postgres"):
    return validate_sql(sql, dialect=dialect, max_rows=1000, policy=Policy())


# ---- 第一道：根节点白名单 + 单语句 ----

WRITE_STATEMENTS = [
    "insert into t values (1)",
    "update t set a = 1",
    "delete from t",
    "drop table t",
    "create table t (a int)",
    "alter table t add column b int",
    "truncate table t",
    "grant select on t to u",
    "copy t from '/tmp/x.csv'",
    "merge into t using s on t.id = s.id when matched then update set a = 1",
]


@pytest.mark.parametrize("sql", WRITE_STATEMENTS)
def test_write_statements_are_blocked(sql: str) -> None:
    verdict = _verdict(sql)

    assert verdict.ok is False
    assert verdict.code == "WRITE_BLOCKED"
    assert verdict.effective_sql is None  # 被拒的语句没有「实际会跑的版本」


UNKNOWN_SYNTAX = ["vacuum", "call proc()", "explain select 1"]


@pytest.mark.parametrize("sql", UNKNOWN_SYNTAX)
def test_syntax_sqlglot_does_not_understand_is_blocked(sql: str) -> None:
    """sqlglot 把不认识的语句兜底成 exp.Command 而**不抛 ParseError**（实测：
    vacuum / call proc() / explain select 1 都是 Command）。Command 里可以是任何
    东西，包括厂商特有的写语句——所以白名单必须是严格白名单。

    副作用：explain select 1 也被拒。这是有意的取舍——放行 Command 换来的
    「支持 EXPLAIN」远不值得打开这个洞。要支持 EXPLAIN 就单独识别它，别放行 Command。
    """
    assert _verdict(sql).ok is False


def test_a_session_setting_is_blocked() -> None:
    """set statement_timeout = 1 的根是 exp.Set（不是 Command）。它不在白名单里，
    所以自动被拒——但要有测试，否则将来有人往白名单加节点时不会想到这条。
    """
    assert _verdict("set statement_timeout = 1").ok is False


def test_multiple_statements_are_rejected() -> None:
    verdict = _verdict("select 1; select 2")

    assert verdict.ok is False
    assert verdict.code == "MULTIPLE_STATEMENTS"


def test_a_trailing_semicolon_is_still_one_statement() -> None:
    """最容易漏的一条：`select 1;` 在 parse() 下是 **1** 条语句。把它判成多语句
    会让大量正常输入被拒——用户习惯性在末尾加分号。
    """
    assert _verdict("select 1;").ok is True


# ---- 第二道：整树扫描写节点 ----


def test_a_data_modifying_cte_is_blocked() -> None:
    """它的根节点是 Select，与正常 CTE **完全相同**（实测），只有整树扫描能区分。

    只判根节点的实现会放行一条真正在写库的语句。
    """
    verdict = _verdict("with x as (insert into t values (1) returning *) select * from x")

    assert verdict.ok is False
    assert verdict.code == "WRITE_BLOCKED"


def test_a_normal_cte_is_allowed() -> None:
    """与上一条互为对照。两者根节点相同，所以一个「见到 WITH 就拒绝」的实现会让
    上一条变绿而这一条变红——两条都要有，才能钉住「按树内容判断」而不是「按语法
    形状判断」。
    """
    assert _verdict("with x as (select 1 a) select * from x").ok is True


# ---- 第三道：into arg 检查 ----


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "clickhouse"])
def test_select_into_is_blocked(dialect: str) -> None:
    """SELECT INTO 会建一张新表，但它的根是 Select、树内写节点**为空**——前两道
    检查全部放行它。三个方言下都是这个形状（实测）。

    这是本份最容易被「优化」掉的一道检查：读代码的人会觉得「都扫过整树了还检查
    into 干什么」。答案是整树里没有任何写节点类可扫。
    """
    verdict = _verdict("select * into new_t from t", dialect=dialect)

    assert verdict.ok is False
    assert verdict.code == "WRITE_BLOCKED"


# ---- 绕过尝试：注释夹带、大小写、空白 ----

BYPASS_ATTEMPTS = [
    "select 1 /* c */; drop table t",
    "select 1 -- c\n; drop table t",
    "InSeRt InTo t VaLuEs (1)",
    "\n\n   insert into t values (1)   \n",
]


@pytest.mark.parametrize("sql", BYPASS_ATTEMPTS)
def test_comment_and_case_variants_do_not_bypass(sql: str) -> None:
    """注释夹带、大小写变形、空白变形全部由 AST 天然处理——**这就是上游 spec §4.3
    写「用 AST 而不是正则」的理由**。不需要任何额外代码，但需要测试证明它成立。

    只断言 ok is False 不断言 code：前两条是多语句（MULTIPLE_STATEMENTS），
    后两条是写操作（WRITE_BLOCKED），这里要说的是「都进不来」。
    """
    assert _verdict(sql).ok is False


# ---- 解析失败 ----

PARSE_FAILURES = ["select from where", "select * from", "select * from t where", "(((("]


@pytest.mark.parametrize("sql", PARSE_FAILURES)
def test_unparseable_sql_is_rejected(sql: str) -> None:
    """上游 spec §4.3：「解析失败即拒绝，不做『看起来像 SELECT 就放过』的兜底」。"""
    verdict = _verdict(sql)

    assert verdict.ok is False
    assert verdict.code == "SQL_PARSE_ERROR"


# ---- 放行清单 ----

ALLOWED = [
    "select 1",
    "select * from t",
    "with x as (select 1 a) select * from x",
    "select a from t union select b from u",
    "select a from t union all select b from u",
    "select * from (select 1 a) s",
    "select t.a from t join u on t.id = u.id",
    "select a, row_number() over (order by b) from t",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_read_only_queries_are_allowed(sql: str) -> None:
    verdict = _verdict(sql)

    assert verdict.ok is True
    assert verdict.code is None
    assert verdict.effective_sql  # 非空


def test_a_string_literal_that_looks_like_a_write_is_allowed() -> None:
    """字面量不是节点，所以 AST 天然不会误判——而**任何正则实现都会在这条上误报**。

    这条是「用 AST 而不是正则」这个决定的直接收益，单独一个测试而不是塞进
    ALLOWED 列表，因为它证明的东西不同。
    """
    assert _verdict("select 'insert into t' as x").ok is True


def test_union_is_allowed_even_though_its_root_is_not_select() -> None:
    """union 的根节点是 exp.Union 而不是 exp.Select。白名单漏了它会把一条合法查询
    判成写操作——而 ALLOWED 列表里那两条 union 用例已经覆盖，这里单独再说一次是为了
    让「白名单有三个类型」这件事在测试名里可见。
    """
    assert _verdict("select a from t union select b from u").ok is True
```

新建 `apps/api/tests/test_guard_policy.py`：

```python
"""Policy 注入点（上游 spec §4.2、§6；设计 §6.1）。"""

import pytest

from chatbi.guard.policy import EmptyPolicyResolver, Policy
from chatbi.guard.validator import validate_sql


def test_the_v2_1_resolver_always_returns_an_empty_policy() -> None:
    import uuid

    policy = EmptyPolicyResolver().resolve(user_id=uuid.uuid4(), datasource_id=uuid.uuid4())

    assert policy.is_empty is True


def test_a_non_empty_policy_is_not_silently_ignored() -> None:
    """V2-1 不可能触发这条（只有 EmptyPolicyResolver），它是 **V2-2 的护栏**：

    一个非空 policy 被无声丢掉，等于行列级权限「看起来生效了实际没有」——那是
    最坏的一类安全失败，因为没有任何症状。宁可让 V2-2 的实施者撞上一个
    NotImplementedError。
    """
    with pytest.raises(NotImplementedError):
        validate_sql(
            "select 1",
            dialect="postgres",
            max_rows=1000,
            policy=Policy(row_filters=("tenant_id = 1",)),
        )


def test_a_policy_with_only_denied_columns_also_raises() -> None:
    """两个字段各自都要能触发。只检查 row_filters 的实现会静默忽略列级策略。"""
    with pytest.raises(NotImplementedError):
        validate_sql(
            "select 1",
            dialect="postgres",
            max_rows=1000,
            policy=Policy(denied_columns=frozenset({"salary"})),
        )
```

- [ ] **Step 4: 跑测试确认失败**

```bash
uv run pytest tests/test_guard_gate2.py tests/test_guard_policy.py -q
```

预期：**全部 ERROR**，`ModuleNotFoundError: No module named 'chatbi.guard.validator'`。

若报 `No module named 'sqlglot'`，说明 Step 1 的 `uv add` 没跑成。

- [ ] **Step 5: 写 `guard/validator.py` 的闸 2 部分**

```python
"""闸 2（AST 校验）与闸 3（LIMIT 注入）——上游 spec §4.3 的第二、三道闸。

**这是安全红线代码**，保持在 200 行以内、只做这一件事（spec §1.4）。不 import
fastapi、不 import sqlalchemy：输入是「一条 SQL + 方言名 + 行数上限 + 策略」，
输出是一个 frozen dataclass。

三道检查为什么分开写，见各自的注释。合成一个函数会让「哪一道漏了」无法定位，
更要紧的是它们各自的反向验证做不出来。
"""

import sqlglot
from sqlglot import exp

from chatbi.errors import MULTIPLE_STATEMENTS, SQL_PARSE_ERROR, WRITE_BLOCKED
from chatbi.guard.policy import Policy
from chatbi.guard.schemas import GuardVerdict

# 严格白名单。sqlglot 把不认识的语句兜底成 exp.Command 而**不抛 ParseError**
# （实测：vacuum / call proc() / explain select 1 都是 Command），而 Command 里
# 可以是任何东西，包括厂商特有的写语句。往这里加类型前先问「这个类型的内容是否
# 封闭可知」——Command 的答案是「不是」。
#
# exp.Union 必须在：`select a from t union select b from u` 的根是 Union 而不是
# Select，漏了它会把一条合法查询判成写操作。
_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.With)

# 整树扫描用。exp.Copy 与 exp.Grant 是 spec §4.3 点名要禁的；exp.Merge 是写。
_WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Merge,
    exp.Copy,
)


def validate_sql(sql: str, *, dialect: str, max_rows: int, policy: Policy) -> GuardVerdict:
    """闸 2 + 闸 3。放行时 effective_sql 是实际会下发的语句。

    max_rows 与 policy 都是显式参数，**不自己读 get_settings()**——与 P2b 驱动的
    execute() 同一条约定：安全红线代码不要隐式全局依赖，否则测试要靠改环境变量
    才能测边界值。
    """
    if not policy.is_empty:
        # V2-1 不可能走到这里（只有 EmptyPolicyResolver）。这是 V2-2 的护栏：
        # 一个非空 policy 被无声丢掉，等于行列级权限「看起来生效了实际没有」。
        raise NotImplementedError("行列级策略在 V2-2 实现（上游 spec §4.2）")

    try:
        statements = sqlglot.parse(sql, dialect=dialect)
    except sqlglot.errors.ParseError as exc:
        # reason 带 sqlglot 的位置信息：那是用户自己刚写的 SQL，不是库结构
        # （上游 §2.6 的前端表现也明写「内联说明 + 报错位置」）
        return _rejected(SQL_PARSE_ERROR, str(exc).splitlines()[0])

    # parse() 而不是 parse_one()：多语句必须**能被看见然后拒绝**，而 parse_one()
    # 在多语句上只给第一条，等于静默丢掉后面那条 drop table。
    if len(statements) != 1:
        return _rejected(MULTIPLE_STATEMENTS, f"收到 {len(statements)} 条语句")

    root = statements[0]
    if root is None:  # parse("") 会给 [None]
        return _rejected(SQL_PARSE_ERROR, "语句为空")

    blocked = _write_reason(root)
    if blocked is not None:
        return _rejected(WRITE_BLOCKED, blocked)

    # 闸 3 在 Task 2 接上。本任务先原样输出，limit_applied 恒 False。
    return GuardVerdict(
        ok=True,
        effective_sql=root.sql(dialect=dialect),
        code=None,
        reason=None,
        limit_applied=False,
    )


def _write_reason(root: exp.Expression) -> str | None:
    """三道检查。返回拒绝理由，或 None 表示放行。

    理由里说清是哪一类写操作（用户自己写的东西，告诉他比让他猜好），但
    **不含表名与列名**——那部分可能来自被污染的 LLM 输出或库结构（spec §4.4）。
    """
    # 第一道：根节点白名单
    if not isinstance(root, _ALLOWED_ROOTS):
        return f"语句类型 {type(root).__name__} 不是查询"

    # 第二道：整树扫描。Postgres 的 data-modifying CTE
    # （with x as (insert ... returning *) select * from x）的根**就是** Select，
    # 与正常 CTE 无法从根节点区分——只有走遍整棵树才能看见那个 Insert。
    for node in root.walk():
        if isinstance(node, _WRITE_NODES):
            return f"语句内含 {type(node).__name__} 操作"

    # 第三道：into arg。`select * into new_t from t` 会建一张新表，但它的根是
    # Select、树内写节点**为空**——前两道全部放行它。三个方言下都是这个形状。
    # 删掉这三行等于给闸 2 开一个能真正写库的缺口。
    if root.args.get("into") is not None:
        return "SELECT INTO 会创建表"

    return None


def _rejected(code_tuple: tuple[str, str, int], reason: str) -> GuardVerdict:
    code, message, _status = code_tuple
    return GuardVerdict(
        ok=False,
        effective_sql=None,
        code=code,
        reason=f"{message}：{reason}",
        limit_applied=False,
    )
```

- [ ] **Step 6: 跑测试确认通过**

```bash
uv run pytest tests/test_guard_gate2.py tests/test_guard_policy.py -q
uv run pytest -q
```

预期：两个文件 **37 passed**（10 写操作 + 3 未知语法 + 1 session setting + 2 多语句 + 2 CTE + 3 方言 × SELECT INTO + 4 绕过 + 4 解析失败 + 8 放行 + 2 单独放行 + 3 policy = 37），全量 **263 passed / 28 skipped**。

**实测条数与这里不符就停下数一遍**，别改断言凑数。参数化用例的条数 = 列表长度，数错了说明清单被改过。

- [ ] **Step 7: 反向验证六条（每条都要看「哪些红、哪些必须绿」）**

1. **删掉第二道（整树扫描的 for 循环）** → `test_a_data_modifying_cte_is_blocked` FAIL，而 `test_a_normal_cte_is_allowed`、`test_select_into_is_blocked`、以及 10 条写操作**全部保持绿**。后半条是重点：它证明整树扫描有专属守卫，而不是「随便删点什么都会红」。
2. **删掉第三道（`into` 检查那三行）** → `test_select_into_is_blocked` 三条 FAIL，而 data-modifying CTE 那条**保持绿**。与第 1 条互为对照：两道检查各守一个缺口，谁都兜不住谁。
3. **`_ALLOWED_ROOTS` 加进 `exp.Command`** → `test_syntax_sqlglot_does_not_understand_is_blocked` 三条 FAIL。这条守的是「白名单必须严格」。
4. **`_ALLOWED_ROOTS` 去掉 `exp.Union`** → 两条 union 放行用例 + `test_union_is_allowed_even_though_its_root_is_not_select` FAIL，其余放行用例保持绿。
5. **`parse()` 换成 `parse_one()`**（并把 `len(statements)` 那段删掉）→ `test_multiple_statements_are_rejected` FAIL，`test_a_trailing_semicolon_is_still_one_statement` **保持绿**。
6. **`policy.is_empty` 那条 `raise` 换成 `pass`** → `test_guard_policy.py` 的两条 FAIL，闸 2 的全部用例保持绿。

- [ ] **Step 8: ruff + 提交**

```bash
uv run ruff check . && uv run ruff format --check .
wc -l src/chatbi/guard/validator.py     # 记下行数，上限 200
git add pyproject.toml uv.lock src/chatbi/errors.py src/chatbi/guard/ \
        tests/test_guard_gate2.py tests/test_guard_policy.py
git commit -m "feat(guard): 闸 2 —— 三道 AST 检查

上游 spec §4.3 说「只放行 SELECT 与 WITH」，照字面实现会留两个能真正写库的
缺口，实测确认（sqlglot 30.17.0）：

1. data-modifying CTE：with x as (insert into t ... returning *) select * from x
   的根节点**就是** Select，与正常 CTE 无法从根区分。要走遍整棵树。
2. SELECT INTO：select * into new_t from t 会建表，但根是 Select 且树内写节点
   为空，前两道检查全部放行。三个方言下都是这个形状。

白名单是严格白名单：sqlglot 把不认识的语句兜底成 exp.Command 而不抛
ParseError（vacuum / call proc() / explain 都是 Command），放行它等于放行
一切未知语法。代价是 EXPLAIN 也被拒，这是有意的取舍。

多语句从 WRITE_BLOCKED 分出 MULTIPLE_STATEMENTS（用户动作不同）。

validate_sql 现在就接收 policy 参数，非空即 NotImplementedError——V2-1 不可能
触发，它是 V2-2 的护栏：无声丢掉一个非空策略等于行列级权限看起来生效了实际
没有。也让 spec §4.2「V2-2 只改 PolicyResolver 与语义层新表」那句承诺成立。

闸 3（LIMIT 注入）在下一个任务接上，本段 limit_applied 恒 False。"
```





---

### Task 2: 闸 3 —— LIMIT 注入

上游 spec §4.3：「强制注入 LIMIT（默认 1000，可配）。已有 LIMIT 且更小则保留原值。」

**实测发现的坑**：`tree.args["limit"]` 装三种节点——`exp.Limit`（`LIMIT 5`）、`exp.Fetch`（`FETCH FIRST 5 ROWS ONLY`）、带 `BY` 的变体（`LIMIT 3 BY x`）。只认第一种，后两种会因为「读不出数值」被当成**没有 LIMIT**，然后 `tree.limit(max)` 把它们整个替换掉：

```
输入  select * from t fetch first 5 rows only
输出  SELECT * FROM t LIMIT 1000        ← FETCH FIRST 5 被静默抹掉
```

不是安全问题（1000 仍是上限），但用户写的「只要 5 行」被无声改成 1000 行，而 `effective_sql` 会回显这个结果——用户只会以为后端算错了。

**Files:**
- Modify: `apps/api/src/chatbi/guard/validator.py`（加 LIMIT 处理，替换 Task 1 里那个 `limit_applied=False` 的占位返回）
- Test: `apps/api/tests/test_guard_gate3.py`

**Interfaces:**
- Consumes: Task 1 的 `validate_sql()` / `GuardVerdict`
- Produces: 签名不变。放行时 `effective_sql` 是注入/收紧后的语句，`limit_applied` 反映是否动过，`warnings` 可能非空（`LIMIT BY`）。Task 4 的端点与 P3b 的执行器都消费这三个字段。

- [ ] **Step 1: 写失败的测试**

新建 `apps/api/tests/test_guard_gate3.py`。**每条的预期输出都是写计划时实测过的**：

```python
"""闸 3（LIMIT 注入）—— 上游 spec §4.3 的第三道闸。

断言 effective_sql 的**内容特征**（含不含某个片段、LIMIT 值是多少）而不是整条
字符串相等：sqlglot 会规范化大小写、引号、空白，写死整条会让这些测试在升级
sqlglot 时集体变红，而那时红的原因与闸 3 的正确性无关。
"""

import pytest

from chatbi.guard.policy import Policy
from chatbi.guard.validator import validate_sql

MAX = 1000


def _verdict(sql: str, dialect: str = "postgres", max_rows: int = MAX):
    return validate_sql(sql, dialect=dialect, max_rows=max_rows, policy=Policy())


def test_a_query_without_a_limit_gets_one() -> None:
    verdict = _verdict("select * from t")

    assert verdict.ok is True
    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is True


def test_a_smaller_limit_is_kept() -> None:
    """spec §4.3「已有 LIMIT 且更小则保留原值」。"""
    verdict = _verdict("select * from t limit 10")

    assert "LIMIT 10" in verdict.effective_sql
    assert "1000" not in verdict.effective_sql
    assert verdict.limit_applied is False


def test_a_larger_limit_is_tightened() -> None:
    verdict = _verdict("select * from t limit 5000")

    assert "LIMIT 1000" in verdict.effective_sql
    assert "5000" not in verdict.effective_sql
    assert verdict.limit_applied is True


def test_a_limit_exactly_at_the_cap_is_kept() -> None:
    """边界值。`<` 与 `<=` 写错只有这一条能看出来——而写错的方向是「把正好合规的
    语句也改写一遍」，effective_sql 看起来没问题，limit_applied 却是 True。
    """
    verdict = _verdict("select * from t limit 1000")

    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is False


def test_fetch_first_within_the_cap_is_left_alone() -> None:
    """FETCH FIRST 也存在 args["limit"] 里，但节点类型是 exp.Fetch。只认 exp.Limit
    的实现会把它当成「没有 LIMIT」并覆盖掉——用户写的「只要 5 行」变成 1000 行。

    这里断言 FETCH 片段仍在：不改写成 LIMIT，因为它已经是一个不超上限的行数限制，
    改写只会让 effective_sql 与用户写的对不上。
    """
    verdict = _verdict("select * from t fetch first 5 rows only")

    assert "FETCH" in verdict.effective_sql.upper()
    assert "1000" not in verdict.effective_sql
    assert verdict.limit_applied is False


def test_fetch_first_over_the_cap_is_tightened() -> None:
    verdict = _verdict("select * from t fetch first 5000 rows only")

    assert "LIMIT 1000" in verdict.effective_sql
    assert "5000" not in verdict.effective_sql
    assert verdict.limit_applied is True


def test_clickhouse_limit_by_is_left_alone_with_a_warning() -> None:
    """LIMIT n BY x 的语义是「每个 x 取 n 行」，总行数无上界。理想做法是再加一个
    总 LIMIT，但 sqlglot 对同一条语句上两个 LIMIT 直接 ParseError（实测），所以没有
    「不改语义又能加总上限」的写法。

    **这不留缺口**：P2b 的驱动层取 max_rows + 1 行后 truncate()，返回行数在那一层
    是硬保证的。闸 3 注入 LIMIT 的额外价值是减少库侧扫描量，对这个边缘语法放弃该
    优化、换取不篡改用户语义，是设计 §2.2 定的取舍。

    warning 让它可见，而不是悄悄放过。
    """
    verdict = _verdict("select * from t limit 3 by x", dialect="clickhouse")

    assert verdict.ok is True
    assert "BY" in verdict.effective_sql.upper()
    assert verdict.limit_applied is False
    assert verdict.warnings  # 非空


def test_a_limit_in_a_subquery_is_not_touched() -> None:
    """子查询里的 LIMIT 5 保留，外层照样注入。走错了会把内层的 5 当成外层的上限，
    于是「外层没有 LIMIT」这个事实被漏掉。
    """
    verdict = _verdict("select * from (select * from t limit 5) s")

    assert "LIMIT 5" in verdict.effective_sql
    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is True


def test_a_non_literal_limit_is_tightened() -> None:
    """LIMIT 的值不是字面量时无法静态判断它是否 ≤ max，收紧是安全的方向。"""
    verdict = _verdict("select * from t limit (select 5)")

    assert verdict.ok is True
    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is True


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "clickhouse"])
def test_the_cap_applies_in_every_dialect(dialect: str) -> None:
    verdict = _verdict("select * from t limit 5000", dialect=dialect)

    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is True


def test_the_cap_comes_from_the_argument_not_from_settings() -> None:
    """max_rows 是显式参数（与 P2b 驱动的 execute() 同一条约定）。若实现改成读
    get_settings()，这条会红——而那种实现让测试必须改环境变量才能测边界值。
    """
    verdict = _verdict("select * from t", max_rows=7)

    assert "LIMIT 7" in verdict.effective_sql


def test_union_gets_the_limit_at_the_outermost_level() -> None:
    """union 的根是 exp.Union，注入要作用于整个 union 而不是最后一个 select。"""
    verdict = _verdict("select a from t union select b from u")

    assert verdict.effective_sql.rstrip().upper().endswith("LIMIT 1000")


def test_a_rejected_statement_has_no_effective_sql() -> None:
    """闸 2 拒绝时不该走到闸 3。被拒的语句没有「实际会跑的版本」。"""
    verdict = _verdict("insert into t values (1)")

    assert verdict.ok is False
    assert verdict.effective_sql is None
    assert verdict.limit_applied is False
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_guard_gate3.py -q
```

预期：**多数 FAIL**。`test_a_smaller_limit_is_kept` 与 `test_a_rejected_statement_has_no_effective_sql` 两条**会假性通过**——Task 1 的实现原样输出语句、`limit_applied` 恒 `False`，正好满足它们。这是预期的，不代表闸 3 已实现；核对 FAIL 的那几条确实是「缺 LIMIT 注入」而不是别的原因。

- [ ] **Step 3: 写闸 3**

`guard/validator.py`：把 Task 1 里那个占位返回替换掉，并加两个辅助函数。

**下面每个 arg 名都是实测过的**（sqlglot 30.17.0）：

| 节点 | 数值在哪 | 备注 |
|---|---|---|
| `exp.Limit`（`LIMIT 5`） | `args["expression"]` → `Literal` | |
| `exp.Fetch`（`FETCH FIRST 5 ROWS ONLY`） | `args["count"]` → `Literal` | 另有 `direction` / `limit_options` |
| `LIMIT 3 BY x` | `args["expression"]` → `Literal`，**外加** `args["expressions"]` → list | 类型仍是 `exp.Limit`，靠 `expressions` 非空区分 |
| `LIMIT (select 5)` | `args["expression"]` → `Subquery` | 不是 Literal → 收紧 |

替换 `validate_sql()` 结尾那段：

```python
    effective_sql, limit_applied, warnings = _apply_limit(
        root, dialect=dialect, max_rows=max_rows
    )
    return GuardVerdict(
        ok=True,
        effective_sql=effective_sql,
        code=None,
        reason=None,
        limit_applied=limit_applied,
        warnings=warnings,
    )
```

加两个辅助函数：

```python
def _apply_limit(
    root: exp.Expression, *, dialect: str, max_rows: int
) -> tuple[str, bool, tuple[str, ...]]:
    """闸 3。返回 (effective_sql, limit_applied, warnings)。

    exp.Union 也有 .limit()，注入会落在最外层（实测），所以这里不需要按根类型分支。
    """
    limit_node = root.args.get("limit")

    # ClickHouse 的 `LIMIT n BY x`：类型仍是 exp.Limit，但多一个 expressions（BY 的
    # 那些列）。它的语义是「每个 x 取 n 行」，总行数无上界；而 sqlglot 对同一条语句上
    # 两个 LIMIT 直接 ParseError，所以没有「保留 BY 又加总上限」的写法。
    #
    # 原样保留 + warning（设计 §2.2）。**这不留缺口**：驱动层取 max_rows + 1 行后
    # truncate()，返回行数在那一层是硬保证的。闸 3 的额外价值是减少库侧扫描量。
    if limit_node is not None and limit_node.args.get("expressions"):
        warning = f"该语句的库侧行数未受限，返回结果仍会被截断到 {max_rows} 行"
        return root.sql(dialect=dialect), False, (warning,)

    current = _row_cap(limit_node)
    if current is not None and current <= max_rows:
        # spec §4.3「已有 LIMIT 且更小则保留原值」。`<=` 而不是 `<`：正好等于上限的
        # 语句已经合规，重写它只会让 effective_sql 与用户写的无谓地不同。
        return root.sql(dialect=dialect), False, ()

    return root.limit(max_rows).sql(dialect=dialect), True, ()


def _row_cap(node: exp.Expression | None) -> int | None:
    """读出语句现有的行数上限。读不出来就返回 None（调用方据此收紧）。

    node 可能是 exp.Limit（数值在 args["expression"]）或 exp.Fetch（数值在
    args["count"]）——**两者都放在 args["limit"] 里**。只认 exp.Limit 会让
    `FETCH FIRST 5 ROWS ONLY` 被当成「没有上限」并覆盖掉，用户的「只要 5 行」
    变成 max_rows 行。

    值不是整数字面量（例如 `LIMIT (select 5)`）时返回 None：无法静态判断它是否
    ≤ max_rows，收紧是安全的方向。
    """
    if node is None:
        return None
    value = node.args.get("expression") or node.args.get("count")
    if isinstance(value, exp.Literal) and value.is_int:
        return int(value.this)
    return None
```

- [ ] **Step 4: 跑测试确认通过**

```bash
uv run pytest tests/test_guard_gate3.py -q && uv run pytest -q
wc -l src/chatbi/guard/validator.py     # 上限 200
```

预期：该文件 **15 passed**（11 条独立 + 3 条方言参数化 + 1）、全量 **278 passed / 28 skipped**。`validator.py` 应在 170–195 行之间。

**若 `validator.py` 超了 200 行**：把 `_apply_limit` 与 `_row_cap` 搬到 `guard/limits.py`，`validator.py` import 它们。**不要删注释**——那些注释记的是实测结论，删掉之后下一个人会把 `into` 检查和 `_row_cap` 里读两个 arg 的写法当成多余的。

- [ ] **Step 5: 反向验证五条**

1. **`_row_cap` 只读 `args["expression"]`（去掉 `or node.args.get("count")`）** → `test_fetch_first_within_the_cap_is_left_alone` FAIL，而 `test_a_smaller_limit_is_kept` **保持绿**。后半条是重点：普通 `LIMIT` 上两种实现表现相同，只有 FETCH 那条能分辨。
2. **删掉 `LIMIT BY` 那个分支** → `test_clickhouse_limit_by_is_left_alone_with_a_warning` FAIL（`effective_sql` 里 BY 消失、`warnings` 为空），其余全绿。
3. **`<=` 改成 `<`** → `test_a_limit_exactly_at_the_cap_is_kept` FAIL（`limit_applied` 变 True），其余全绿。这条是唯一守边界的。
4. **`_row_cap` 去掉 `value.is_int` 判断**（只判 `isinstance(value, exp.Literal)`）→ `test_a_non_literal_limit_is_tightened` **仍然绿**（Subquery 本来就不是 Literal），但要跑一遍确认——它说明那条测试守的是「非字面量」而不是「非整数」，两者要分清。若想守「非整数字面量」得另加一条 `LIMIT '5'` 的用例。
5. **把 `max_rows` 换成 `get_settings().max_result_rows`** → `test_the_cap_comes_from_the_argument_not_from_settings` FAIL。

第 4 条的结论要如实记进「实施期的偏差」：它是一条**没有守卫的路径**，而不是一个 bug。

- [ ] **Step 6: ruff + 提交**

```bash
uv run ruff check . && uv run ruff format --check .
git add src/chatbi/guard/validator.py tests/test_guard_gate3.py
git commit -m "feat(guard): 闸 3 —— LIMIT 注入

args[\"limit\"] 装三种节点（实测 sqlglot 30.17.0）：exp.Limit 的数值在
args[\"expression\"]、exp.Fetch 在 args[\"count\"]、LIMIT n BY x 是 exp.Limit
但额外带 expressions。只认第一种会把 FETCH FIRST 5 与 LIMIT 3 BY x 当成
「没有 LIMIT」并整个覆盖掉——用户写的「只要 5 行」被静默改成 1000 行，而
effective_sql 会回显这个结果。

LIMIT n BY x 原样保留 + warning：它的语义是「每个 x 取 n 行」总行数无上界，
而 sqlglot 对一条语句上两个 LIMIT 直接 ParseError，没有「保留 BY 又加总上限」
的写法。不留缺口——驱动层取 max_rows+1 行后 truncate()，返回行数在那一层是
硬保证的。

边界用 <=：正好等于上限的语句已合规，重写它只让 effective_sql 无谓地不同。

278 passed / 28 skipped。"
```







## 实施期的偏差（执行中回填）

（开工前为空。每个任务做完就记：实测计数与预期不符的地方、对计划的偏离及理由、反向验证里出现的意外结果。**`sqlglot` 的实测版本号必须记在这里**——三道检查全靠它的节点类名与 arg 名。P1/P2 四次的经验是攒着必漏，发现即回填。）

---

## 交接清单（p3a2 与 P3b 要消费的签名）

```python
# chatbi.guard.validator
validate_sql(sql: str, *, dialect: str, max_rows: int, policy: Policy) -> GuardVerdict
#   纯函数。dialect 是 **sqlglot 的方言名**，调用方负责从 datasource.kind 映射过来
#   （三者现在同名，但别假设永远相同——p3a2 的 sql_router 里有一张显式映射表）

# chatbi.guard.schemas
GuardVerdict(ok, effective_sql, code, reason, limit_applied, warnings)
#   ok=False 时 effective_sql 恒为 None
#   limit_applied 是独立布尔字段——**别靠比较字符串判断 LIMIT 有没有被改**，
#   sqlglot 会重写整条语句（大小写、引号、空白全变），字符串比较必然误报

# chatbi.guard.policy
Policy(row_filters: tuple[str, ...], denied_columns: frozenset[str])   # V2-1 恒为空
Policy.is_empty -> bool
PolicyResolver           # Protocol：resolve(*, user_id, datasource_id) -> Policy
EmptyPolicyResolver      # V2-1 唯一实现

# chatbi.errors
WRITE_BLOCKED(400) / SQL_PARSE_ERROR(400) / MULTIPLE_STATEMENTS(400)
```

**p3a2 Task 4 起手要注意的三件事**

1. `guard/deps.py` 还不存在——本份刻意不建它（`guard/` 一个 fastapi 都不 import，这条约束在文件层面可见比写注释可靠）。p3a2 建。
2. **端点必须把 `datasource.kind` 显式映射成 sqlglot 方言名**，不要直接把 `kind` 传进 `validate_sql`。
3. `max_rows` 从 `Settings.max_result_rows` 取并作为参数传入。`validate_sql` **不会**自己读 settings，这是有意的（否则测试要靠改环境变量才能测边界值），本份有一条测试钉住它。

**P3b 执行器**
- 执行前调同一个 `validate_sql()`，把 `verdict.effective_sql` 交给驱动。**不要再写一条校验路径**——闸 2、闸 3 只有这一个实现，两个真相源里总有一个是旧的。
- `verdict.ok is False` 时 run 置 `blocked`（上游 §2.3），流即结束；`code`/`reason` 进 `validate` SSE 事件。
- `run.effective_sql` 存 `verdict.effective_sql`、`run.final_sql` 存用户提交的原文。**两者不同是正常的**，即使一个字都没改（sqlglot 规范化）。
- 要验证「非空 policy 会抛」这条路径，用 `dependency_overrides` 换掉 `policy_resolver_for`（p3a2 建的那个依赖）。

---

## 自查记录

**设计 spec 覆盖核对（本份负责的部分）**

| 设计条目 | 落在哪 |
|---|---|
| §1.1 第一道：根节点白名单 + 单语句 | Task 1 Step 5 的 `_ALLOWED_ROOTS` + `len(statements)` |
| §1.2 第二道：整树扫描写节点 | Task 1 Step 5 的 `for node in root.walk()` |
| §1.3 第三道：`into` arg 检查 | Task 1 Step 5 末 |
| §1.4 三道分开写的理由 | Task 1 Step 7 的反向验证 1、2 互为对照 |
| §1.5 解析失败即拒绝、注释/大小写变形由 AST 处理 | Task 1 Step 3 的 `PARSE_FAILURES` 与 `BYPASS_ATTEMPTS` |
| §2 `limit` arg 的三种形态 | Task 2 Step 3 的对照表 + `_row_cap` |
| §2.1 七种处理规则 | Task 2 Step 1 的用例逐条对应 |
| §2.2 `LIMIT n BY x` 保留原样 + warning | Task 2 Step 3 的 `_apply_limit` 首个分支 |
| §2.3 `effective_sql` 与 `limit_applied` | `GuardVerdict` 两个字段 + Task 2 那条边界用例 |
| §2.4 `max_rows` 显式传入 | Task 2 Step 1 的 `test_the_cap_comes_from_the_argument_not_from_settings` |
| §3 `GuardVerdict` 与三个错误码 | Task 1 Step 1、Step 2 |
| §6 `PolicyResolver` 注入点与 `NotImplementedError` 护栏 | Task 1 Step 2 + `tests/test_guard_policy.py` |
| §8.1–8.3 三份清单 | Task 1 Step 3、Task 2 Step 1 |
| §8.4 反向验证六条 | 分散进两个任务，共 11 条 |

**不在本份的设计小节**：§4（`/sql/validate` 端点）· §5（四张表与 append-only）· §6.2（`PolicyResolver` 做成 FastAPI 依赖）· §7.1 的 `guard/deps.py` 与 `api/sql_router.py`——全部在 p3a2。§0.2 记的 LLM 超时决定在 P3c。

**占位符扫描**：无 TBD / TODO / 「类似 Task N」/ 无代码的「写测试」步骤。每个 Step 要么给出完整代码块，要么给出可直接跑的命令 + 预期输出。

**类型一致性核对**

`GuardVerdict` 的六个字段在 `_rejected()` 与两处 `return GuardVerdict(...)` 共三处构造，字段名一致；`warnings` 有默认值 `()`，所以 `_rejected()` 不传它。`validate_sql` 的签名（`sql` 位置参数 + 三个关键字参数）在两份测试的 `_verdict()` 辅助函数与 p3a2 的端点里一致。`Policy` 的两个字段名（`row_filters` / `denied_columns`）在 `is_empty`、`test_guard_policy.py` 的两条用例、以及 `validate_sql` 的护栏分支里一致。

**每个 `exp.*` 节点名与 arg 名都实测过**（sqlglot 30.17.0）：`Insert`/`Update`/`Delete`/`Drop`/`Create`/`Alter`/`TruncateTable`/`Grant`/`Merge`/`Copy`/`Select`/`Union`/`With`/`Limit`/`Fetch`/`Literal`/`Command`/`Set` 全部存在；`exp.Limit` 的数值在 `args["expression"]`、`exp.Fetch` 在 `args["count"]`、`LIMIT n BY x` 是 `exp.Limit` 且额外带 `args["expressions"]`。**这些名字是 sqlglot 的内部结构**，升级大版本后要重跑本份的测试。

**写作过程中的回改两处**

1. **闸 2 从一道变三道**，两个缺口都是实测出来的（不是从文档推的）。写测试清单时先想到 data-modifying CTE，验证后顺手试了 `SELECT INTO`，发现它连整树扫描都躲得过。
2. **`FETCH FIRST` 的判断修正过一次**。第一次实测的读取代码把 `args["limit"]` 的非 `exp.Limit` 值 `repr()` 成字符串 `'None'`，于是我一度以为 `FETCH FIRST` 不在 `limit` arg 里。补验 arg 键才发现它**在**，只是节点类型不同。教训：**用 `repr()` 兜住未知类型会把「类型不对」伪装成「值为 None」。**
