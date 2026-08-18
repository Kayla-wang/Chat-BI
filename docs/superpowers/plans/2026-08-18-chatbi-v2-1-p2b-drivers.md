# Chat-BI V2-1 · P2b 驱动协议与三驱动 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 定下 `Driver` 协议并实现 Postgres / MySQL / ClickHouse 三个驱动，全部过同一套契约用例（连通性、schema 反射、类型映射、语句超时、真取消、行截断），并建立「skip 必须计数上报」的测试机制。

**Architecture:** `datasources/drivers/` 一库一文件，共用 `drivers/base.py` 里的协议与值对象；`datasources/registry.py` 做 `kind → 驱动` 映射，是外界唯一的取用入口。驱动**不认识 ORM、不认识 HTTP、不认识 `Datasource` 模型**——它的输入是一个 `ConnectionInfo` 值对象，由调用方从模型 + `read_password` 组装。这样驱动能脱离应用库单测，也不会有人在驱动里顺手写一条 `select(Datasource)`。

**Tech Stack:** Python 3.12 · psycopg 3（已装）· pymysql · clickhouse-connect · pytest

**上游 spec:** [2026-08-11-chatbi-v2-1-design.md](../specs/2026-08-11-chatbi-v2-1-design.md)（§1.2 模块布局、§1.4 单文件规模、§2.3 取消、§4.3 四道闸、§5.1 驱动契约测）
**上游计划:** [P2a HTTP 层](2026-08-13-chatbi-v2-1-p2a-datasource-api.md) 与 [P2a 领域层](2026-08-13-chatbi-v2-1-p2a-datasource-persistence.md)（末尾交接清单 = 本份消费的签名）
**下游计划:**
1. [P2b `/test` 端点与示例库](2026-08-18-chatbi-v2-1-p2b-test-endpoint-and-demo.md)——Task 5–7，消费本份末尾交接清单。
2. P2c F-201 元数据接入（`schema_cache` / `column_notes` / `/schema` / 人工补注释），消费本份的 `reflect()` 输出。
3. P3 执行器——消费本份的 `execute()` 与 `cancel()`，不再改驱动。

**任务编号从 Task 1 重新开始**（P2a 的六个任务已完成）。跨段引用写成「P2a Task 4」，段内写「Task 2」。

## Global Constraints

每个任务的要求都隐含包含本节。P2a 的 Global Constraints 里仍然有效的部分不重复：Python 3.12 + uv、Alembic 不用 `create_all()`、TDD 与**双向**验证、提交信息格式、分支 `feature_v2.0`、不能加 `pytest-xdist`。

**新增依赖**（本段只加这两个）
- `pymysql>=1.1`（MySQL）· `clickhouse-connect>=0.8`（ClickHouse）。Postgres 用已装的 `psycopg[binary]>=3.1`。
- **不引入 SQLAlchemy 的外部库方言**。驱动直连各自的 DBAPI：SQLAlchemy 的抽象在这里是负担——我们要的恰恰是各库不同的取消原语与超时设置方式，抹平它们等于把要用的东西藏起来。
- 不引入 `sqlalchemy-clickhouse`、`mysqlclient`（需要编译工具链）。

**驱动的边界（本段最重要的一条）**
- 驱动**不 import** `chatbi.db.*`、不 import `fastapi`、不 import `chatbi.datasources.repository`。它的输入是 `ConnectionInfo`，输出是值对象。
- 组装 `ConnectionInfo`（含调 `read_password`）是**调用方**的事，在 Task 5 的 `/test` 与 P3 的执行器里。
- 一库一文件，各自 ≤200 行（spec §1.4）。共用逻辑放 `base.py` 的默认实现，不允许出现一个 600 行的 `drivers.py`。

**四道闸里本段承担的两道**（spec §4.3）
- **闸 1 只读探测**：`probe()` 要回答「这个账号能不能写」。探测方式必须是**只读的**——不能真去建表。
- **闸 4 语句超时 + 真取消**：默认超时 60s（可配）。取消必须**真的取消后端查询**（Postgres `pg_cancel_backend`、MySQL `KILL QUERY`、ClickHouse `KILL QUERY WHERE query_id=`），只关连接不算。闸 2（AST 校验）与闸 3（LIMIT 注入）属 `guard`，是 P3 的事——**本段的 `execute()` 不做任何 SQL 检查**，它只负责把已批准的语句跑出去。

**行截断**
- `execute()` 接受 `max_rows`，多取一行来判断是否被截断（取 `max_rows + 1` 行，返回时截到 `max_rows` 并置 `truncated=True`）。不要靠 `row_count == max_rows` 猜——恰好等于上限时那是误报。

**测试与 skip（spec §5.1，本段的红线）**
- 契约测**允许 skip 但必须计数上报**。这与应用库测试的规则相反（那里缺库就是失败），别照抄 `conftest.py` 里 `pytest.fail` 的写法。
- **CI 输出里 skip 数必须显式打印。** v1 就是因为「无本地库 → skip」被当成绿灯，MySQL/PG 驱动到重写前一次真库都没跑过。
- 三个驱动跑**同一套**契约用例（参数化），不各写一份——各写一份必然出现「某个驱动少测了取消」。

**错误码**（spec §2.6）
- 本段在 `errors.py` 新增 `CONNECTION_ERROR`(503) 一个。`QUERY_TIMEOUT` 与 `QUERY_CANCELLED` 由驱动抛**领域异常**，映射成错误码是 P3 执行器的事——本段只定义异常类型。
- 错误消息不回显地址、端口、库名、用户名（spec §4.4）。

## 本机环境（2026-08-18 实测）

- **原生 PostgreSQL 16 可用**：`localhost:5432`，`chatbi`/`chatbi`，`chatbi` 与 `chatbi_test` 两库已建好。Postgres 驱动的契约测**本机就能真跑**，不需要 Docker。
- **Docker 守护进程不可用**：Docker Desktop 已装，但 `wsl -l -v` 显示无任何发行版，`docker version` 连不上 npipe。`docker/compose.test.yml` **尚不存在**（`docker/` 下只有 `compose.yml` 与 `initdb/`）。
- 因此本段的验证策略是：**Postgres 真跑，MySQL / ClickHouse 按契约写完并留 skip**，「三库全绿、skip 数为 0」作为下游那份的收尾门禁任务。这是有意的排期选择，不是放宽 spec §5.1——门禁不过 P2b 就不算完。
- 环境变量（前三个同 P2a，后两个本段新增、缺省即 skip）：

```bash
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
# 契约测的目标库；不设则该驱动的契约测 skip 并计数
export CHATBI_TEST_PG_DSN=postgresql://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_TEST_MYSQL_DSN=mysql://root:chatbi@localhost:3306/chatbi_test
export CHATBI_TEST_CLICKHOUSE_DSN=clickhouse://default:@localhost:8123/default
```

- 所有命令在 `apps/api/` 下跑。**起点基线：`134 passed`**（P2a 结束时的值）。开工前先跑一次确认。

---

## File Structure

### 本份创建的文件

| 文件 | 职责 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/datasources/drivers/__init__.py` | 包标记（空） | 1 |
| `apps/api/src/chatbi/datasources/drivers/base.py` | `Driver` 协议、`ConnectionInfo` / `ProbeResult` / `TableSchema` / `ColumnSchema` / `QueryResult` / `QueryHandle` 值对象、四个领域异常、公用默认实现 | 1 |
| `apps/api/src/chatbi/datasources/registry.py` | `kind → 驱动` 映射；`get_driver(kind)` 是外界唯一入口 | 1 |
| `apps/api/tests/test_driver_base.py` | 值对象语义：`ConnectionInfo.repr()` 脱敏、截断判定、异常层次 | 1 |
| `apps/api/tests/test_registry.py` | 注册表：已知 kind 拿到驱动、未知 kind 报错、三个 kind 都登记了、惰性 import | 1 |
| `apps/api/tests/drivers/__init__.py` | 包标记（空） | 2 |
| `apps/api/tests/drivers/conftest.py` | 契约测夹具：按 DSN 环境变量参数化驱动，缺 DSN 则 skip 并计数 | 2 |
| `apps/api/tests/drivers/test_driver_contract.py` | **三驱动共用**的契约用例，参数化跑。Task 2 建立并对 Postgres 真跑，Task 3/4 只往参数表里加一项 | 2 |
| `apps/api/src/chatbi/datasources/drivers/postgres.py` | Postgres 驱动（`pg_cancel_backend` 取消、`statement_timeout` 超时） | 2 |
| `apps/api/src/chatbi/datasources/drivers/mysql.py` | MySQL 驱动（`KILL QUERY` 取消、`MAX_EXECUTION_TIME` 超时） | 3 |
| `apps/api/src/chatbi/datasources/drivers/clickhouse.py` | ClickHouse 驱动（`KILL QUERY WHERE query_id=` 取消、`max_execution_time` 超时） | 4 |
| `apps/api/tests/test_clickhouse_types.py` | `_unwrap` / `_is_numeric` 的纯字符串单测。**不需要真库**，所以不受 skip 影响 | 4 |

### 本份修改的文件

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/pyproject.toml` | 加 `pymysql>=1.1`（Task 3）、`clickhouse-connect>=0.8`（Task 4） | 3、4 |
| `apps/api/src/chatbi/errors.py` | 加 `CONNECTION_ERROR`(503) | 1 |
| `apps/api/src/chatbi/config.py` | 加 `query_timeout_seconds`（默认 60）、`max_result_rows`（默认 1000） | 1 |
| `apps/api/tests/conftest.py` | 加 `skip 计数上报` 的 `pytest_terminal_summary` 钩子 | 1 |

### 下游那份会创建的文件（列此便于对照，**不在本份实施**）

`docker/compose.test.yml`（三库）· `apps/api/src/chatbi/api/datasource_router.py` 的 `/test` 路由 · `migrations/versions/0003_demo_sales.py` · `seed-demo` CLI 命令。

### 边界说明

`base.py` 只 import 标准库与 `typing`——**它连 psycopg 都不 import**，那是 `postgres.py` 的事。这保证「协议」这一层永远能在没装任何驱动包的环境里 import 成功（`registry.py` 的懒加载依赖这一点，见 Task 1）。

`registry.py` 用**惰性 import**：`get_driver("mysql")` 时才 `import chatbi.datasources.drivers.mysql`。否则没装 `clickhouse-connect` 的环境里连 `import chatbi.main` 都会炸——而 P2c/P3/P4 的开发者不该为了跑前端测试去装三个数据库驱动。

`ConnectionInfo` 里的 `password` 是 `str | None` 明文。它由调用方从 `read_password()` 取得，**在驱动里用完即弃，绝不进日志**。`ConnectionInfo` 的 `repr()` 必须脱敏（Task 1 有测试钉这条）。

---

### Task 1: `Driver` 协议、值对象、注册表、skip 计数机制

本任务**不写任何驱动**，也不连任何外部库。它定的是接下来三个任务共同遵守的形状——协议定错，三个驱动会各自长出变通写法。

**Files:**
- Create: `apps/api/src/chatbi/datasources/drivers/__init__.py`（空）
- Create: `apps/api/src/chatbi/datasources/drivers/base.py`
- Create: `apps/api/src/chatbi/datasources/registry.py`
- Create: `apps/api/tests/test_driver_base.py`
- Create: `apps/api/tests/test_registry.py`
- Modify: `apps/api/src/chatbi/errors.py`（加 `CONNECTION_ERROR`）
- Modify: `apps/api/src/chatbi/config.py`（加两个设置）
- Modify: `apps/api/tests/conftest.py`（加 skip 计数上报钩子）

**Interfaces:**
- Consumes: `chatbi.config.get_settings()`（P1）· `chatbi.db.models.DATASOURCE_KINDS`（P2a Task 3）
- Produces:
```python
# --- 值对象（全部 frozen dataclass）---
chatbi.datasources.drivers.base.ConnectionInfo
#   kind: str · host: str · port: int · database: str · username: str
#   password: str | None · options: dict[str, Any]
#   repr() 恒不含 password
chatbi.datasources.drivers.base.ColumnSchema      # name, data_type, is_nullable, is_numeric, comment
chatbi.datasources.drivers.base.TableSchema       # name, schema_name, columns: tuple[ColumnSchema, ...], comment
chatbi.datasources.drivers.base.SchemaSnapshot    # tables: tuple[TableSchema, ...]
chatbi.datasources.drivers.base.ProbeResult       # reachable: bool, server_version: str, can_write: bool
chatbi.datasources.drivers.base.QueryHandle       # token: str —— 跨连接取消所需的全部信息
chatbi.datasources.drivers.base.QueryResult       # columns: tuple[ColumnSchema, ...], rows: tuple[tuple, ...],
#                                                   row_count: int, truncated: bool

# --- 异常（都继承 DriverError）---
chatbi.datasources.drivers.base.DriverError
chatbi.datasources.drivers.base.ConnectionFailed      # 连不上；消息里不得含地址端口
chatbi.datasources.drivers.base.QueryTimeout          # 超过 statement timeout
chatbi.datasources.drivers.base.QueryCancelled        # 被 cancel() 掐掉
chatbi.datasources.drivers.base.QueryFailed           # 语法错、权限不足等库侧拒绝

# --- 协议 ---
chatbi.datasources.drivers.base.Driver                # Protocol，见 Step 4 的完整签名
chatbi.datasources.drivers.base.truncate(rows, max_rows) -> tuple[tuple[tuple, ...], bool]

# --- 注册表 ---
chatbi.datasources.registry.get_driver(kind: str) -> Driver     # 惰性 import
chatbi.datasources.registry.UnknownDriver                        # ValueError 子类

# --- 配置 ---
chatbi.config.Settings.query_timeout_seconds: int = 60
chatbi.config.Settings.max_result_rows: int = 1000
```

- [ ] **Step 1: 写失败的测试**

新建 `apps/api/tests/test_driver_base.py`——**这个文件不需要数据库也不需要任何驱动包**：

```python
"""值对象与协议的语义测试。不连任何库，不 import 任何驱动实现。"""

import pytest

from chatbi.datasources.drivers.base import (
    ConnectionFailed,
    ConnectionInfo,
    DriverError,
    QueryCancelled,
    QueryFailed,
    QueryTimeout,
    truncate,
)


def _info(**overrides) -> ConnectionInfo:
    base = {
        "kind": "postgres",
        "host": "db.internal",
        "port": 5432,
        "database": "analytics",
        "username": "ro_user",
        "password": "super-secret-pw",
    }
    return ConnectionInfo(**(base | overrides))


def test_connection_info_repr_hides_the_password() -> None:
    """这个对象会进异常回溯的局部变量表，而 pytest --showlocals 会原样打出来。"""
    info = _info()

    assert "super-secret-pw" not in repr(info)
    assert "super-secret-pw" not in str(info)
    # 非敏感字段应当仍然可见，否则排障时 repr 毫无用处
    assert "db.internal" in repr(info)


def test_connection_info_repr_hides_the_password_even_when_it_is_none() -> None:
    """None 也要走同一条掩码路径，不能出现 password=None 与 password=*** 两种形状——
    形状不同就等于告诉读者「这个数据源没设密码」。
    """
    assert repr(_info(password=None)) == repr(_info())


def test_connection_info_is_frozen() -> None:
    """驱动拿到的连接信息不可改：改了之后「这条查询连的是哪个库」就说不清了。"""
    info = _info()

    with pytest.raises(Exception):  # noqa: B017 —— dataclasses 抛 FrozenInstanceError
        info.host = "evil.internal"


def test_truncate_reports_truncation_only_when_there_is_an_extra_row() -> None:
    """多取一行来判断——靠 len(rows) == max_rows 猜会在恰好等于上限时误报。"""
    rows = tuple((i,) for i in range(11))

    kept, truncated = truncate(rows, 10)

    assert len(kept) == 10
    assert truncated is True


def test_truncate_does_not_report_truncation_at_exactly_the_limit() -> None:
    rows = tuple((i,) for i in range(10))

    kept, truncated = truncate(rows, 10)

    assert len(kept) == 10
    assert truncated is False


def test_truncate_handles_fewer_rows_than_the_limit() -> None:
    kept, truncated = truncate(((1,), (2,)), 10)

    assert kept == ((1,), (2,))
    assert truncated is False


def test_every_driver_exception_is_a_driver_error() -> None:
    """执行器要能用一个 except 兜住驱动的全部失败，不然新增异常类型时会漏。"""
    for exc_type in (ConnectionFailed, QueryTimeout, QueryCancelled, QueryFailed):
        assert issubclass(exc_type, DriverError)


def test_connection_failed_message_carries_no_address() -> None:
    """spec §4.4：CONNECTION_ERROR 的用户可见文案不回显地址端口。

    驱动构造这个异常时只能传通用消息；地址端口进服务端日志，由调用方记。
    """
    exc = ConnectionFailed()

    text = str(exc)
    assert "db.internal" not in text
    assert "5432" not in text
    assert text  # 但不能是空字符串，否则日志里只剩一个类名
```

新建 `apps/api/tests/test_registry.py`：

```python
"""注册表。重点是惰性 import——协议层必须能在没装驱动包的环境里工作。"""

import pytest

from chatbi.datasources.registry import UnknownDriver, get_driver
from chatbi.db.models import DATASOURCE_KINDS


def test_every_supported_kind_is_registered() -> None:
    """DATASOURCE_KINDS 里有的 kind，注册表必须都认。

    否则「数据源建得出来但连不上」这个组合会一直存在——CHECK 约束放行了 kind，
    而运行时才发现没有对应驱动。
    """
    from chatbi.datasources.registry import registered_kinds

    assert set(registered_kinds()) == set(DATASOURCE_KINDS)


def test_unknown_kind_raises_a_typed_error() -> None:
    with pytest.raises(UnknownDriver) as exc_info:
        get_driver("oracle")

    # 消息里要带上收到的 kind，否则排障时不知道是谁传错了
    assert "oracle" in str(exc_info.value)


def test_registered_kinds_does_not_import_the_driver_modules() -> None:
    """列出 kind 不该触发 import。

    否则没装 clickhouse-connect 的环境里，任何调用 registered_kinds() 的代码路径
    都会炸——而 P2c/P3/P4 的开发者不该为了跑别的测试去装三个数据库驱动。
    """
    import sys

    from chatbi.datasources.registry import registered_kinds

    for module in list(sys.modules):
        if module.startswith("chatbi.datasources.drivers."):
            del sys.modules[module]

    registered_kinds()

    assert not [m for m in sys.modules if m.startswith("chatbi.datasources.drivers.")]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd apps/api
uv run pytest tests/test_driver_base.py tests/test_registry.py -v
```

预期：两个文件都在收集期 `ModuleNotFoundError`（`chatbi.datasources.drivers.base` / `chatbi.datasources.registry`）。

- [ ] **Step 3: 加错误码与两个配置项**

`apps/api/src/chatbi/errors.py` 追加一行（503 而不是 502：连不上外部依赖对本服务是「暂时不可用」，语义比「上游返回了坏响应」准）：

```python
CONNECTION_ERROR = ("CONNECTION_ERROR", "无法连接到数据库，请检查地址、端口与网络", 503)
```

文案照 spec §4.4 原样抄，**不回显地址端口**——那句「请检查地址、端口与网络」是提示用户去看，不是把值打出来。

`apps/api/src/chatbi/config.py` 的 `Settings` 加两个字段（照 spec §4.3 的默认值）：

```python
    query_timeout_seconds: int = 60
    max_result_rows: int = 1000
```

放 config 而不是写死在驱动里：spec §4.3 明说这两个值「可配」。驱动的 `execute()` 仍然把它们作为**显式参数**接收，不自己去读 `get_settings()`——驱动不该有隐式全局依赖，否则契约测要靠改环境变量才能测超时。

- [ ] **Step 4: 写 base.py**

新建 `apps/api/src/chatbi/datasources/drivers/__init__.py`（空文件），然后 `base.py`。**这个文件只 import 标准库**：

```python
"""驱动协议与值对象。

只 import 标准库——连 psycopg 都不 import。这保证协议层在没装任何数据库驱动包的
环境里也能 import 成功，registry 的惰性加载依赖这一点。
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


class DriverError(Exception):
    """驱动层全部失败的共同基类。执行器用一个 except 兜住它。"""


class ConnectionFailed(DriverError):
    """连不上数据源。

    消息恒为通用文案：spec §4.4 要求 CONNECTION_ERROR 不回显地址端口。
    地址端口由调用方写进服务端日志，不经由异常传播。
    """

    def __init__(self) -> None:
        super().__init__("无法连接到数据库")


class QueryTimeout(DriverError):
    """超过语句超时。"""


class QueryCancelled(DriverError):
    """被 cancel() 掐掉。与超时分开：前者是用户主动，后者是策略生效。"""


class QueryFailed(DriverError):
    """库侧拒绝执行（语法错、权限不足、表不存在）。

    带上库的原始消息——这条会回显给分析师，他要靠它改 SQL。但**只在这一类**
    异常里带原文：连接类错误的原文可能含地址端口。
    """


@dataclass(frozen=True)
class ConnectionInfo:
    """连一个数据源所需的全部信息。

    由调用方从 Datasource 模型 + read_password() 组装（Task 5 的 /test 与 P3 的
    执行器）。驱动不认识 ORM，所以这里是纯值对象。
    """

    kind: str
    host: str
    port: int
    database: str
    username: str
    password: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """恒掩码 password。

        无论 password 是不是 None 都打同样的 ***：形状不同就等于告诉读者
        「这个数据源没设密码」。
        """
        return (
            f"ConnectionInfo(kind={self.kind!r}, host={self.host!r}, port={self.port!r}, "
            f"database={self.database!r}, username={self.username!r}, "
            f"password='***', options={self.options!r})"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    data_type: str          # 库的原始类型名，原样保留（P2c 的注释 UI 要显示它）
    is_nullable: bool = True
    is_numeric: bool = False  # 前端选图要用（spec §2.3 的 result 事件）
    comment: str | None = None


@dataclass(frozen=True)
class TableSchema:
    name: str
    schema_name: str
    columns: tuple[ColumnSchema, ...] = ()
    comment: str | None = None


@dataclass(frozen=True)
class SchemaSnapshot:
    tables: tuple[TableSchema, ...] = ()


@dataclass(frozen=True)
class ProbeResult:
    reachable: bool
    server_version: str
    can_write: bool
    """账号是否具备写权限。true 时调用方要告警并把 is_readonly_verified 置 false
    （spec §4.3 闸 1），但**不阻止保存**。"""


@dataclass(frozen=True)
class QueryHandle:
    """取消一条正在跑的查询所需的全部信息。

    token 的含义各库不同：ClickHouse 是自己生成的 query_id、Postgres 是 backend pid、
    MySQL 是 connection id。取消**必须另开一条连接**发出——原连接正被查询占住。
    """

    token: str


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[ColumnSchema, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    truncated: bool


def truncate(
    rows: tuple[tuple[Any, ...], ...], max_rows: int
) -> tuple[tuple[tuple[Any, ...], ...], bool]:
    """截到 max_rows 并报告是否发生了截断。

    调用方必须取 max_rows + 1 行再交给这里：靠 len(rows) == max_rows 判断会在
    结果恰好等于上限时误报「已截断」，而那会让用户以为还有更多数据。
    """
    if len(rows) > max_rows:
        return rows[:max_rows], True
    return rows, False


class Driver(Protocol):
    """一个外部数据库的驱动。

    实现放 drivers/<kind>.py，各自 ≤200 行（spec §1.4）。
    所有方法都是同步阻塞的——异步化由调用方用线程池处理（P3 的执行器），
    因为三个库的 DBAPI 里只有一个有靠得住的 asyncio 支持，在这一层假装统一
    只会让取消语义更难推理。
    """

    kind: str
    default_port: int

    def probe(self, info: ConnectionInfo) -> ProbeResult:
        """连通性 + 版本 + 账号是否可写。探测必须是只读的——不能真去建表。"""
        ...

    def reflect(self, info: ConnectionInfo) -> SchemaSnapshot:
        """拉取表结构。P2c 的 schema_cache 存的就是它的输出。"""
        ...

    def execute(
        self,
        info: ConnectionInfo,
        sql: str,
        *,
        timeout_seconds: int,
        max_rows: int,
        on_start: "Callable[[QueryHandle], None] | None" = None,
    ) -> QueryResult:
        """跑一条**已被 guard 批准**的语句。

        这里不做任何 SQL 检查：闸 2（AST 校验）与闸 3（LIMIT 注入）在 guard，
        重复校验只会让人以为驱动也是一道防线，从而放松那一道。

        on_start 在语句真正下发**之前**被调用，把 QueryHandle 交给调用方——
        这是取消能力的唯一入口。回调抛异常视为放弃执行。
        """
        ...

    def cancel(self, info: ConnectionInfo, handle: QueryHandle) -> None:
        """取消 handle 对应的查询。另开连接发出，幂等：查询已结束时静默返回。"""
        ...
```

`Callable` 要从 `collections.abc` import；写成字符串标注是为了让上面那段能独立读懂，实现时按 ruff 的要求放到 import 段。

- [ ] **Step 5: 写 registry.py**

新建 `apps/api/src/chatbi/datasources/registry.py`：

```python
"""kind → 驱动 的映射。外界取用驱动的唯一入口。

惰性 import：get_driver("mysql") 时才去 import mysql 模块。否则没装
clickhouse-connect 的环境里，连 import chatbi.main 都会炸——而 P2c/P3/P4 的
开发者不该为了跑前端或管线测试去装三个数据库驱动包。
"""

from functools import lru_cache
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chatbi.datasources.drivers.base import Driver

# kind → (模块路径, 类名)。新增驱动只改这张表；值是字符串，所以这里不触发 import。
_DRIVERS: dict[str, tuple[str, str]] = {
    "postgres": ("chatbi.datasources.drivers.postgres", "PostgresDriver"),
    "mysql": ("chatbi.datasources.drivers.mysql", "MySQLDriver"),
    "clickhouse": ("chatbi.datasources.drivers.clickhouse", "ClickHouseDriver"),
}


class UnknownDriver(ValueError):
    """没有这个 kind 对应的驱动。"""


def registered_kinds() -> tuple[str, ...]:
    """已登记的 kind。**不触发任何 import**——测试钉住了这条。"""
    return tuple(_DRIVERS)


@lru_cache
def get_driver(kind: str) -> "Driver":
    """取驱动实例。驱动无状态，所以共享一个实例（lru_cache）。"""
    try:
        module_path, class_name = _DRIVERS[kind]
    except KeyError as exc:
        raise UnknownDriver(
            f"没有 kind={kind!r} 的驱动，已登记的是 {sorted(_DRIVERS)}"
        ) from exc
    return getattr(import_module(module_path), class_name)()
```

`_DRIVERS` 的值是**字符串**而不是类对象——这是惰性的全部实现，写成 `{"mysql": MySQLDriver}` 就需要在模块顶部 import 三个驱动，惰性当场失效。

- [ ] **Step 6: 加 skip 计数上报**

`apps/api/tests/conftest.py` 末尾追加（spec §5.1 的硬要求：CI 输出里 skip 数必须显式打印）：

```python
def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """把 skip 数显式打印在末尾，并单独列出驱动契约测的 skip。

    v1 就是因为「无本地库 → skip」被当成绿灯，MySQL/PG 驱动到重写前一次真库都
    没跑过。让这行永远出现，比指望人记得去翻 -rs 输出可靠。
    """
    skipped = terminalreporter.stats.get("skipped", [])
    contract = [report for report in skipped if report.nodeid.startswith("tests/drivers/")]

    terminalreporter.write_sep("=", f"skip 合计 {len(skipped)}，其中驱动契约测 {len(contract)}")

    reasons: dict[str, int] = {}
    for report in contract:
        # longrepr 是 (path, lineno, reason) 三元组；reason 形如 "Skipped: ..."
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else "未知原因"
        reasons[reason] = reasons.get(reason, 0) + 1
    for reason, count in sorted(reasons.items()):
        terminalreporter.write_line(f"  {count} × {reason}")

    if contract:
        terminalreporter.write_line(
            "  驱动契约测存在 skip：spec §5.1 要求真库全绿、skip 数为 0 才算验收通过"
        )
```

- [ ] **Step 7: 跑全量确认通过**

```bash
cd apps/api
uv run pytest -q && uv run ruff check src tests
```

预期：`145 passed`（P2a 结束时的 134 + 本任务 11 条：`test_driver_base.py` 8 条 + `test_registry.py` 3 条）。末尾应出现 `skip 合计 0，其中驱动契约测 0` 那一行——**这一行现在就要看到**，别等到 Task 2 有了契约测才发现钩子写错了。

- [ ] **Step 8: 反向验证六条（两个方向都要跑）**

1. 删掉 `ConnectionInfo.__repr__` 与 `__str__` → `test_connection_info_repr_hides_the_password` 与 `..._even_when_it_is_none` 必须双双 FAIL。
2. `truncate` 的 `len(rows) > max_rows` 改成 `>=` → **只有** `test_truncate_does_not_report_truncation_at_exactly_the_limit` FAIL，另两条 truncate 测试仍绿。这条测试的全部价值就在这个边界上：没有它，「恰好等于上限时误报已截断」这个 off-by-one 会被另两条放过。
3. `_DRIVERS` 里删掉 `clickhouse` 一项 → `test_every_supported_kind_is_registered` 必须 FAIL。
4. `registered_kinds()` 改成 `tuple(get_driver(k).kind for k in _DRIVERS)` → `test_registered_kinds_does_not_import_the_driver_modules` 必须 FAIL。**注意它此时会以 `ModuleNotFoundError` 而不是断言失败告终**（三个驱动模块还没写），这恰好演示了惰性的必要性；但要确认失败信息里是 import 相关而不是别的，否则说明测试写歪了。
5. `QueryTimeout` 改成直接继承 `Exception` → `test_every_driver_exception_is_a_driver_error` 必须 FAIL。
6. `ConnectionFailed.__init__` 的消息改成 `"无法连接到 db.internal:5432"` → `test_connection_failed_message_carries_no_address` 必须 FAIL。

- [ ] **Step 9: 提交**

```bash
git add apps/api/src/chatbi apps/api/tests
git commit -m "$(cat <<'EOF'
feat(drivers): Driver protocol, value objects, lazy registry

The protocol layer imports only the standard library so it works without any
database driver package installed; the registry maps kind to a module path
string and imports on demand. Skip counts are now printed on every run.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 契约测套件 + Postgres 驱动

契约套件和第一个真驱动一起诞生：套件先对一个**真库**变绿，才有资格当另两个驱动的标准。反过来先写一个没跑过任何真库的套件，等于把三个驱动押在一堆未验证的断言上。

本任务的契约测**在本机能真跑**（原生 Postgres 16）。Task 3、4 只往 `CONTRACT_KINDS` 里加一项，用例一行不改。

**Files:**
- Create: `apps/api/tests/drivers/__init__.py`（空）
- Create: `apps/api/tests/drivers/conftest.py`
- Create: `apps/api/tests/drivers/test_driver_contract.py`
- Create: `apps/api/src/chatbi/datasources/drivers/postgres.py`

**Interfaces:**
- Consumes: Task 1 的全部值对象、异常、`Driver` 协议、`registry.get_driver`
- Produces:
```python
chatbi.datasources.drivers.postgres.PostgresDriver
#   kind = "postgres" · default_port = 5432
#   probe / reflect / execute / cancel 四个方法，签名照 Driver 协议

# 契约测的公共设施，Task 3、4 消费：
tests.drivers.conftest.CONTRACT_KINDS: tuple[str, ...]   # Task 3、4 各加一项
tests.drivers.conftest.DSN_ENV: dict[str, str]           # kind → 环境变量名
tests.drivers.conftest.Dialect                           # 方言差异的载体
tests.drivers.conftest.DIALECTS: dict[str, Dialect]      # Task 3、4 各加一项
driver_target  # 夹具，返回 (driver, ConnectionInfo, Dialect)；缺 DSN 则 skip 并计数
seeded_table   # 夹具，建一张固定形状的表并在结束时删掉，返回表名
```

- [ ] **Step 1: 写契约测夹具**

新建 `apps/api/tests/drivers/__init__.py`（空），然后 `apps/api/tests/drivers/conftest.py`：

```python
"""驱动契约测的夹具。

与应用库测试**规则相反**：这里允许 skip（spec §5.1），因为 MySQL/ClickHouse 需要
Docker 起真库。但 skip 必须被计数上报——上一层 conftest.py 的
pytest_terminal_summary 负责打印。别照抄那边 pytest.fail 的写法。
"""

import os
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import pytest

from chatbi.datasources.drivers.base import ConnectionInfo

# kind → 提供 DSN 的环境变量名
DSN_ENV = {
    "postgres": "CHATBI_TEST_PG_DSN",
    "mysql": "CHATBI_TEST_MYSQL_DSN",
    "clickhouse": "CHATBI_TEST_CLICKHOUSE_DSN",
}

# 参与契约测的 kind。**Task 3 加 "mysql"、Task 4 加 "clickhouse"，这是那两个任务
# 对本文件的唯一改动。**
CONTRACT_KINDS: tuple[str, ...] = ("postgres",)


@dataclass(frozen=True)
class Dialect:
    """同一套契约在三个引擎上的语法差异。

    只放**测试需要**的差异，不放驱动实现的差异——驱动的差异属于它自己的文件。
    """

    sleep_sql: str
    """一条会跑很久的语句，用来测超时与取消。必须能被语句超时打断。"""

    rows_sql: str
    """生成 N 行的语句，带一个 {n} 占位符。用来测行截断。"""

    create_table_sql: str
    """建一张固定形状的表：id 整数非空、label 文本可空、amount 数值。带 {table}。"""

    drop_table_sql: str
    """带 {table}。用 IF EXISTS，夹具的清理不能因为建表失败而连带报错。"""

    insert_row_sql: str
    """插一行，带 {table}。"""


DIALECTS: dict[str, Dialect] = {
    "postgres": Dialect(
        sleep_sql="select pg_sleep(30)",
        rows_sql="select i from generate_series(1, {n}) as i",
        create_table_sql=(
            "create table {table} ("
            "id integer not null, label text, amount numeric(12, 2))"
        ),
        drop_table_sql="drop table if exists {table}",
        insert_row_sql="insert into {table} (id, label, amount) values (1, '甲', 12.34)",
    ),
}


def _info_from_dsn(kind: str, dsn: str) -> ConnectionInfo:
    """把 DSN 解析成 ConnectionInfo。

    自己解析而不是把 DSN 直接交给驱动：驱动的输入契约是 ConnectionInfo，
    让测试走一条「和生产不同的入口」等于没测生产那条路。
    """
    parsed = urlparse(dsn)
    if parsed.hostname is None or parsed.port is None:
        raise ValueError(f"{DSN_ENV[kind]} 必须形如 scheme://user:pw@host:port/db，收到 {dsn!r}")
    return ConnectionInfo(
        kind=kind,
        host=parsed.hostname,
        port=parsed.port,
        database=parsed.path.lstrip("/"),
        username=unquote(parsed.username or ""),
        password=unquote(parsed.password) if parsed.password else None,
    )


@pytest.fixture(params=CONTRACT_KINDS)
def driver_target(request) -> tuple[object, ConnectionInfo, Dialect]:
    """(driver, info, dialect)。缺 DSN 就 skip，理由里带上环境变量名。

    skip 理由必须写清「设哪个变量能让它跑起来」——只写「no database」的 skip
    会被当成环境问题忽略掉，那就是 v1 的老路。
    """
    from chatbi.datasources.registry import get_driver

    kind = request.param
    env = DSN_ENV[kind]
    dsn = os.environ.get(env)
    if not dsn:
        pytest.skip(f"{env} 未设置，跳过 {kind} 驱动契约测（设置它即可真跑）")
    return get_driver(kind), _info_from_dsn(kind, dsn), DIALECTS[kind]


@pytest.fixture
def seeded_table(driver_target) -> str:
    """建一张固定形状的表，测试结束删掉。返回表名。

    表名带随机后缀：契约测会对同一个库并发跑多个 kind（将来），共用表名会互删。
    用 uuid 而不是测试名——测试名里的参数化后缀含中括号，不是合法标识符。
    """
    import uuid

    driver, info, dialect = driver_target
    table = f"chatbi_contract_{uuid.uuid4().hex[:12]}"
    driver.execute(
        info, dialect.create_table_sql.format(table=table), timeout_seconds=30, max_rows=1
    )
    driver.execute(
        info, dialect.insert_row_sql.format(table=table), timeout_seconds=30, max_rows=1
    )
    try:
        yield table
    finally:
        driver.execute(
            info, dialect.drop_table_sql.format(table=table), timeout_seconds=30, max_rows=1
        )
```

**注意 `seeded_table` 用 `execute()` 跑 DDL**——`execute()` 刻意不做 SQL 检查（闸 2 在 `guard`，是 P3 的事），所以这是可行的，而且顺带证明了「驱动本身不是一道防线」这个设计事实。如果将来有人在驱动里加了 SELECT-only 检查，这个夹具会立刻炸——那正是我们想要的信号，因为那意味着有人把安全边界放错了层。

- [ ] **Step 2: 写契约用例（三驱动共用）**

新建 `apps/api/tests/drivers/test_driver_contract.py`。**新增驱动不改本文件**——只往 conftest 的 `CONTRACT_KINDS` 与 `DIALECTS` 各加一项。如果某个驱动需要在这里加 `if kind == ...` 分支，说明协议没抽对，回去改协议：

```python
"""三个驱动共用的契约用例（spec §5.1）。

覆盖：连通性、schema 反射、类型映射、语句超时、真取消、行截断。
"""

import threading
from dataclasses import replace

import pytest

from chatbi.datasources.drivers.base import (
    ConnectionFailed,
    QueryCancelled,
    QueryFailed,
    QueryHandle,
    QueryTimeout,
)


def test_probe_reports_reachable_and_a_version(driver_target) -> None:
    driver, info, _ = driver_target

    result = driver.probe(info)

    assert result.reachable is True
    assert result.server_version  # 非空——排障时要知道对面是什么版本


def test_probe_detects_a_writable_account(driver_target) -> None:
    """契约测用的账号是库主，所以 can_write 必须是 True。

    这条不是「希望账号可写」，而是钉住探测**真的在探**：一个恒返回 False 的实现
    在只读账号上看起来完全正确，只有拿一个已知可写的账号才能证伪它。
    spec §4.3 闸 1 的告警完全依赖这个判断，它错了用户会以为自己配了只读账号。
    """
    driver, info, _ = driver_target

    assert driver.probe(info).can_write is True


def test_probe_does_not_write_anything(driver_target, seeded_table) -> None:
    """探测必须是只读的——不能真去建一张表试试。

    这种实现会在用户的生产库里攒垃圾表，而且在只读账号上会把「探测失败」
    误报成「账号不可写」。
    """
    driver, info, _ = driver_target
    count_sql = f"select count(*) from {seeded_table}"
    before = driver.execute(info, count_sql, timeout_seconds=30, max_rows=10)

    driver.probe(info)

    after = driver.execute(info, count_sql, timeout_seconds=30, max_rows=10)
    assert before.rows == after.rows


def test_wrong_password_raises_connection_failed(driver_target) -> None:
    """并且异常里不能带地址、端口、密码（spec §4.4）。"""
    driver, info, _ = driver_target
    if info.password is None:
        pytest.skip("该 DSN 未带密码（trust 认证），无法构造「密码错误」")
    bad = replace(info, password="definitely-not-the-password")

    with pytest.raises(ConnectionFailed) as exc_info:
        driver.probe(bad)

    text = str(exc_info.value)
    assert info.host not in text
    assert str(info.port) not in text
    assert "definitely-not-the-password" not in text


def test_reflect_finds_the_seeded_table(driver_target, seeded_table) -> None:
    driver, info, _ = driver_target

    snapshot = driver.reflect(info)

    assert seeded_table in {table.name for table in snapshot.tables}


def test_reflect_describes_the_seeded_columns(driver_target, seeded_table) -> None:
    """列名、可空性、数值性三项都要对。

    is_numeric 决定前端能不能给这列画柱状图（spec §2.3 的 result 事件），
    错了表现是「图表选项里少了一列」，很难追到驱动这一层。
    """
    driver, info, _ = driver_target

    table = next(t for t in driver.reflect(info).tables if t.name == seeded_table)
    columns = {column.name: column for column in table.columns}

    assert set(columns) == {"id", "label", "amount"}
    assert columns["id"].is_nullable is False
    assert columns["label"].is_nullable is True
    assert columns["id"].is_numeric is True
    assert columns["amount"].is_numeric is True
    assert columns["label"].is_numeric is False
    assert columns["id"].data_type  # 原始类型名原样保留，P2c 的注释 UI 要显示
```

同一个文件继续追加（执行、截断、超时、取消）：

```python
def test_execute_returns_columns_and_rows(driver_target, seeded_table) -> None:
    driver, info, _ = driver_target

    result = driver.execute(
        info, f"select id, label, amount from {seeded_table}", timeout_seconds=30, max_rows=100
    )

    assert [column.name for column in result.columns] == ["id", "label", "amount"]
    assert result.row_count == 1
    assert result.truncated is False
    assert result.rows[0][0] == 1
    assert result.rows[0][1] == "甲"  # 非 ASCII 往返：编码配错时这里先炸


def test_execute_truncates_at_max_rows(driver_target) -> None:
    driver, info, dialect = driver_target

    result = driver.execute(info, dialect.rows_sql.format(n=50), timeout_seconds=30, max_rows=10)

    assert len(result.rows) == 10
    assert result.row_count == 10
    assert result.truncated is True


def test_execute_does_not_report_truncation_when_the_result_fits_exactly(driver_target) -> None:
    """结果恰好等于上限时不能报截断。只有「多取一行」的实现过得了这条。"""
    driver, info, dialect = driver_target

    result = driver.execute(info, dialect.rows_sql.format(n=10), timeout_seconds=30, max_rows=10)

    assert len(result.rows) == 10
    assert result.truncated is False


def test_execute_raises_query_failed_on_a_bad_statement(driver_target) -> None:
    driver, info, _ = driver_target

    with pytest.raises(QueryFailed):
        driver.execute(
            info, "select * from a_table_that_does_not_exist_x9", timeout_seconds=30, max_rows=10
        )


def test_execute_raises_query_timeout(driver_target) -> None:
    """超时必须由**库侧**生效（statement_timeout / MAX_EXECUTION_TIME /
    max_execution_time），不是客户端等够了就断开连接——只断开的话查询还在对面
    继续跑，而 spec §4.3 闸 4 要的正是「别把用户的生产库拖垮」。
    """
    driver, info, dialect = driver_target

    with pytest.raises(QueryTimeout):
        driver.execute(info, dialect.sleep_sql, timeout_seconds=1, max_rows=10)


def test_cancel_stops_a_running_query(driver_target) -> None:
    """spec §2.3：只关流不取消后端查询是错的。

    在线程里跑一条长语句，从 on_start 拿到 handle，主线程调 cancel。
    这条是整套契约里最容易「假绿」的一条——见 Step 6 的反向验证第 4 条。
    """
    driver, info, dialect = driver_target
    handles: list[QueryHandle] = []
    started = threading.Event()
    outcome: list[BaseException | None] = []

    def run() -> None:
        def on_start(handle: QueryHandle) -> None:
            handles.append(handle)
            started.set()

        try:
            driver.execute(
                info,
                dialect.sleep_sql,
                timeout_seconds=60,
                max_rows=10,
                on_start=on_start,
            )
            outcome.append(None)
        except BaseException as exc:  # noqa: BLE001 —— 要看清到底抛了什么
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    assert started.wait(timeout=10), "on_start 未在 10s 内被调用——取消能力没有入口"

    driver.cancel(info, handles[0])
    worker.join(timeout=20)

    assert not worker.is_alive(), "cancel 之后查询仍在跑"
    assert isinstance(outcome[0], QueryCancelled), f"期望 QueryCancelled，实际 {outcome[0]!r}"


def test_cancel_is_idempotent_after_the_query_finished(driver_target, seeded_table) -> None:
    """查询早已结束时再取消必须静默返回。

    执行器在「客户端断开」时会无条件调一次 cancel，那一刻查询可能刚好跑完；
    这里抛异常会把一次正常完成变成一条错误日志，还会盖掉真正的结果。
    """
    driver, info, _ = driver_target
    handles: list[QueryHandle] = []

    driver.execute(
        info,
        f"select 1 from {seeded_table}",
        timeout_seconds=30,
        max_rows=10,
        on_start=handles.append,
    )

    driver.cancel(info, handles[0])  # 不抛异常就算通过
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd apps/api
export CHATBI_TEST_PG_DSN=postgresql://chatbi:chatbi@localhost:5432/chatbi_test
uv run pytest tests/drivers -v
```

预期：13 条全部 ERROR 在夹具上——`get_driver("postgres")` 抛 `ModuleNotFoundError`（`postgres.py` 还没写）。

**顺便验证 skip 机制**：把 `CHATBI_TEST_PG_DSN` 取消设置再跑一次，应当看到 13 skipped，且末尾出现 `skip 合计 13，其中驱动契约测 13` 与 `13 × Skipped: CHATBI_TEST_PG_DSN 未设置...`。这一步是在真驱动存在之前唯一能单独验证计数钩子的时机。

- [ ] **Step 4: 写 postgres.py**

新建 `apps/api/src/chatbi/datasources/drivers/postgres.py`：

```python
"""Postgres 驱动。

两条不显然的地方，改之前先读注释：
1. 超时与取消在 Postgres 里是**同一个 SQLSTATE(57014)**，只有消息文本不同，
   而消息受 lc_messages 影响。这里用耗时判断来区分，不匹配字符串。
2. 类型名有两套拼法：information_schema 给 "integer"，游标描述给 "int4"。
   _NUMERIC_TYPES 同时收了两套，别只留一套。

每次调用开一条新连接。V2-1 不做连接池：池化会让「取消」的语义复杂得多
（要保证 kill 的是本次查询占的那条连接），而私有化部署的并发量不需要池。
"""

import time
from collections.abc import Callable

import psycopg

from chatbi.datasources.drivers.base import (
    ColumnSchema,
    ConnectionFailed,
    ConnectionInfo,
    ProbeResult,
    QueryCancelled,
    QueryFailed,
    QueryHandle,
    QueryResult,
    QueryTimeout,
    SchemaSnapshot,
    TableSchema,
    truncate,
)

_CONNECT_TIMEOUT_SECONDS = 10

# 两套拼法都要在：information_schema.columns.data_type 与 pg_type.typname
_NUMERIC_TYPES = frozenset(
    {
        "smallint", "integer", "bigint", "numeric", "decimal", "real", "double precision",
        "int2", "int4", "int8", "float4", "float8",
    }
)

_REFLECT_SQL = """
select c.table_schema, c.table_name, c.column_name, c.data_type, c.is_nullable
from information_schema.columns c
join information_schema.tables t
  on t.table_schema = c.table_schema and t.table_name = c.table_name
where c.table_schema not in ('pg_catalog', 'information_schema')
  and t.table_type = 'BASE TABLE'
order by c.table_schema, c.table_name, c.ordinal_position
"""

# 只读地问权限，而不是试着建表。CREATE 与「任意现存表可 INSERT」都算可写：
# 只读账号的典型配置是 CONNECT + USAGE + SELECT，两者都拿不到。
_CAN_WRITE_SQL = """
select
  has_database_privilege(current_user, current_database(), 'CREATE')
  or coalesce(bool_or(has_table_privilege(current_user, c.oid, 'INSERT')), false)
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where c.relkind = 'r' and n.nspname not in ('pg_catalog', 'information_schema')
"""


class PostgresDriver:
    kind = "postgres"
    default_port = 5432

    def _connect(self, info: ConnectionInfo) -> psycopg.Connection:
        try:
            return psycopg.connect(
                host=info.host,
                port=info.port,
                dbname=info.database,
                user=info.username,
                password=info.password,
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                **info.options,
            )
        except psycopg.OperationalError as exc:
            # ConnectionFailed 的消息恒为通用文案（spec §4.4）。原始异常挂在
            # __cause__ 上，只会进服务端日志，不会进 HTTP 响应。
            raise ConnectionFailed() from exc

    def probe(self, info: ConnectionInfo) -> ProbeResult:
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute("select version()")
            version = str(cur.fetchone()[0])
            cur.execute(_CAN_WRITE_SQL)
            can_write = bool(cur.fetchone()[0])
        return ProbeResult(reachable=True, server_version=version, can_write=can_write)

    def reflect(self, info: ConnectionInfo) -> SchemaSnapshot:
        grouped: dict[tuple[str, str], list[ColumnSchema]] = {}
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute(_REFLECT_SQL)
            for schema_name, table_name, column_name, data_type, is_nullable in cur.fetchall():
                grouped.setdefault((schema_name, table_name), []).append(
                    ColumnSchema(
                        name=column_name,
                        data_type=data_type,
                        is_nullable=is_nullable == "YES",
                        is_numeric=data_type in _NUMERIC_TYPES,
                    )
                )
        tables = tuple(
            TableSchema(name=table, schema_name=schema, columns=tuple(columns))
            for (schema, table), columns in sorted(grouped.items())
        )
        return SchemaSnapshot(tables=tables)

    def execute(
        self,
        info: ConnectionInfo,
        sql: str,
        *,
        timeout_seconds: int,
        max_rows: int,
        on_start: Callable[[QueryHandle], None] | None = None,
    ) -> QueryResult:
        with self._connect(info) as conn, conn.cursor() as cur:
            # 库侧超时。客户端等够了就断开不算超时——查询会继续在对面跑。
            cur.execute("set statement_timeout = %s", (timeout_seconds * 1000,))
            if on_start is not None:
                cur.execute("select pg_backend_pid()")
                on_start(QueryHandle(token=str(cur.fetchone()[0])))

            started = time.monotonic()
            try:
                cur.execute(sql)
            except psycopg.errors.QueryCanceled as exc:
                # 见文件头注释 1：靠耗时而不是消息文本区分两者。
                if time.monotonic() - started >= timeout_seconds:
                    raise QueryTimeout("查询超过语句超时") from exc
                raise QueryCancelled("查询已取消") from exc
            except psycopg.Error as exc:
                # 只有这一类异常带库的原文——分析师要靠它改 SQL（spec §2.6）
                raise QueryFailed(str(exc)) from exc

            if cur.description is None:
                # DDL / INSERT 之类没有结果集。契约测的 seeded_table 夹具走这条路。
                return QueryResult(columns=(), rows=(), row_count=0, truncated=False)

            fetched = tuple(tuple(row) for row in cur.fetchmany(max_rows + 1))
            rows, truncated = truncate(fetched, max_rows)
            columns = tuple(_column_from_description(item) for item in cur.description)
        return QueryResult(
            columns=columns, rows=rows, row_count=len(rows), truncated=truncated
        )

    def cancel(self, info: ConnectionInfo, handle: QueryHandle) -> None:
        """另开一条连接发 pg_cancel_backend。

        幂等：backend 已经退出时它返回 false 而不报错，正是我们要的语义。
        """
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute("select pg_cancel_backend(%s)", (int(handle.token),))


def _column_from_description(item) -> ColumnSchema:
    """把游标描述里的 OID 翻成类型名。取不到就退回 OID 的字符串形式。"""
    type_info = psycopg.postgres.types.get(item.type_code)
    type_name = type_info.name if type_info is not None else str(item.type_code)
    return ColumnSchema(
        name=item.name, data_type=type_name, is_numeric=type_name in _NUMERIC_TYPES
    )
```

- [ ] **Step 5: 跑测试确认通过（真库）**

```bash
cd apps/api
export CHATBI_TEST_PG_DSN=postgresql://chatbi:chatbi@localhost:5432/chatbi_test
uv run pytest tests/drivers -v && uv run pytest -q && uv run ruff check src tests
```

预期：契约测 13 passed（**全部对真 Postgres 跑**，不是 skip），全量 `158 passed`（Task 1 后的 145 + 13）。末尾那行应是 `skip 合计 0，其中驱动契约测 0`。

**如果契约测显示 skipped 而不是 passed，先解决它再往下走**——那说明 `CHATBI_TEST_PG_DSN` 没进到 pytest 进程，而不是驱动写对了。这正是 v1 的失败模式。

- [ ] **Step 6: 反向验证七条（两个方向都要跑）**

1. `_CAN_WRITE_SQL` 整个换成 `select false` → `test_probe_detects_a_writable_account` 必须 FAIL。这条证明探测**真的在探**而不是恒返回一个值。
2. `fetchmany(max_rows + 1)` 改成 `fetchmany(max_rows)` → `test_execute_truncates_at_max_rows` 必须 FAIL（`truncated` 变成 False），而 `..._fits_exactly` 仍绿。「多取一行」这个技巧的全部价值在这一对上。
3. 删掉 `set statement_timeout` 那两行 → `test_execute_raises_query_timeout` 必须 FAIL。**这条要等约 30s**（`pg_sleep(30)` 会跑完然后成功返回），别以为是卡死。
4. `cancel()` 的方法体换成 `pass` → `test_cancel_stops_a_running_query` 必须 FAIL（`worker.is_alive()` 仍为真）。spec §2.3 直接点名了这个错误：只关流不取消后端查询，私有化部署里一条跑飞的查询能拖垮用户的生产库。
5. 删掉 `execute` 里 `on_start` 那三行 → 同一条测试必须 FAIL 在 `started.wait(timeout=10)` 上，且 `test_cancel_is_idempotent_after_the_query_finished` 会以 `IndexError` 报错。取消能力只有这一个入口，堵上它就没有别的路。
6. `_column_from_description` 与 `reflect` 里的 `is_numeric` 都写死成 `False` → `test_reflect_describes_the_seeded_columns` 必须 FAIL。
7. 把 `QueryCanceled` 的两个分支**对调**（跑够超时抛 `QueryCancelled`、否则抛 `QueryTimeout`）→ `test_execute_raises_query_timeout` 与 `test_cancel_stops_a_running_query` 必须**双双** FAIL。只有一条红说明另一条路径根本没被走到，回头看是不是 `sleep_sql` 太短或超时值太大。

- [ ] **Step 7: 提交**

```bash
git add apps/api/src/chatbi apps/api/tests
git commit -m "$(cat <<'EOF'
feat(drivers): shared contract suite and the Postgres driver

The suite covers reachability, reflection, type mapping, statement timeout,
real cancellation and row truncation, and runs against a live Postgres.
Timeout and cancellation share SQLSTATE 57014, so they are told apart by
elapsed time rather than by matching a locale-dependent message.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: MySQL 驱动

**本机没有 MySQL**，所以本任务的契约测会 skip 并计数。这不是放宽验收——「三库全绿、skip 数为 0」是下游那份的收尾门禁任务，不过门禁 P2b 就不算完。按契约写、按 skip 交，是排期选择。

MySQL 和 Postgres 有一处关键差别值得先说：**MySQL 用不同的 errno 区分超时（3024）与被杀（1317）**，所以这个驱动不需要 Postgres 那个耗时启发式。别照抄过来。

**Files:**
- Create: `apps/api/src/chatbi/datasources/drivers/mysql.py`
- Modify: `apps/api/pyproject.toml`（加 `pymysql>=1.1`）
- Modify: `apps/api/tests/drivers/conftest.py`（`CONTRACT_KINDS` 与 `DIALECTS` 各加一项）

**Interfaces:**
- Consumes: Task 1 的值对象与协议、Task 2 的契约套件
- Produces: `chatbi.datasources.drivers.mysql.MySQLDriver`（`kind = "mysql"` · `default_port = 3306`）

- [ ] **Step 1: 装依赖并把 mysql 接进契约套件**

```bash
cd apps/api
```

`pyproject.toml` 的 `dependencies` 加一行 `"pymysql>=1.1",`，然后 `uv sync`。

`apps/api/tests/drivers/conftest.py` 改两处——**这是本任务对测试的唯一改动**，契约用例文件一行不动：

```python
CONTRACT_KINDS: tuple[str, ...] = ("postgres", "mysql")
```

```python
    "mysql": Dialect(
        sleep_sql="select sleep(30)",
        # MySQL 没有 generate_series，用 8.0 的递归 CTE。默认
        # cte_max_recursion_depth = 1000，契约测只要 50 行，够。
        rows_sql=(
            "with recursive s(i) as ("
            "select 1 union all select i + 1 from s where i < {n}) select i from s"
        ),
        create_table_sql=(
            "create table {table} ("
            "id int not null, label varchar(64) null, amount decimal(12, 2))"
        ),
        drop_table_sql="drop table if exists {table}",
        insert_row_sql="insert into {table} (id, label, amount) values (1, '甲', 12.34)",
    ),
```

- [ ] **Step 2: 跑测试确认 skip 被计数**

```bash
uv run pytest tests/drivers -v
```

预期：postgres 的 13 条仍 passed，mysql 的 13 条 **skipped**，末尾出现 `skip 合计 13，其中驱动契约测 13` 与 `13 × Skipped: CHATBI_TEST_MYSQL_DSN 未设置...`。

**看到这一行才算这一步通过。** 如果 skip 数没打印出来，说明 Task 1 的钩子在 `tests/drivers/` 这个子目录上失效了（`nodeid` 前缀判断写错），现在修比等到门禁那天修便宜得多。

- [ ] **Step 3: 写 mysql.py**

新建 `apps/api/src/chatbi/datasources/drivers/mysql.py`：

```python
"""MySQL 驱动。

与 Postgres 的三处差别：
1. 超时与被杀有**不同的 errno**（3024 / 1317），不需要 Postgres 那个耗时启发式。
2. `max_execution_time` **只对只读 SELECT 生效**。这对我们没问题——能到执行器的
   语句都已过 guard 的 SELECT-only 校验；但契约测里的 DDL 不受它约束，别因此
   以为超时没设上。
3. `autocommit=True`：MySQL 的 DDL 隐式提交，而 INSERT 不会。驱动是读多写无的，
   开着 autocommit 比在每条路径上记得 commit 可靠。
"""

import time
from collections.abc import Callable

import pymysql

from chatbi.datasources.drivers.base import (
    ColumnSchema,
    ConnectionFailed,
    ConnectionInfo,
    ProbeResult,
    QueryCancelled,
    QueryFailed,
    QueryHandle,
    QueryResult,
    QueryTimeout,
    SchemaSnapshot,
    TableSchema,
    truncate,
)

_CONNECT_TIMEOUT_SECONDS = 10
_ER_QUERY_INTERRUPTED = 1317
_ER_QUERY_TIMEOUT = 3024

_NUMERIC_TYPES = frozenset(
    {
        "tinyint", "smallint", "mediumint", "int", "integer", "bigint",
        "decimal", "numeric", "float", "double", "real", "bit",
    }
)

# 只看当前库。information_schema 里别的库的表不属于这个数据源的可见范围。
_REFLECT_SQL = """
select c.table_name, c.column_name, c.data_type, c.is_nullable, c.column_comment
from information_schema.columns c
join information_schema.tables t
  on t.table_schema = c.table_schema and t.table_name = c.table_name
where c.table_schema = database() and t.table_type = 'BASE TABLE'
order by c.table_name, c.ordinal_position
"""

# 只读地问权限。information_schema.user_privileges / schema_privileges 都是视图，
# 查它们不产生任何写入。
_CAN_WRITE_SQL = """
select exists (
  select 1 from information_schema.user_privileges
  where grantee = concat('''', replace(current_user(), '@', '''@'''), '''')
    and privilege_type in ('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER')
) or exists (
  select 1 from information_schema.schema_privileges
  where table_schema = database()
    and privilege_type in ('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER')
)
"""
```

`_CAN_WRITE_SQL` 里那串引号拼接看着别扭，但 `user_privileges.grantee` 存的是 `'root'@'%'` 这种带引号的形式，而 `current_user()` 返回 `root@%`——不补引号会永远匹配不上，`can_write` 恒为 false，而那正是反向验证第 1 条要抓的形状。**实施时先在真库上单独跑一次这条 SQL 确认它返回 1**，再往下写。

同一个文件，接着写类体：

```python
class MySQLDriver:
    kind = "mysql"
    default_port = 3306

    def _connect(self, info: ConnectionInfo) -> pymysql.connections.Connection:
        try:
            return pymysql.connect(
                host=info.host,
                port=info.port,
                database=info.database,
                user=info.username,
                password=info.password or "",
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                # utf8mb4 而不是 utf8：后者在 MySQL 里是三字节残废编码，存不了 emoji，
                # 而契约测的 '甲' 虽然能过，真实数据里迟早撞上四字节字符
                charset="utf8mb4",
                autocommit=True,
                **info.options,
            )
        except pymysql.err.OperationalError as exc:
            raise ConnectionFailed() from exc

    def probe(self, info: ConnectionInfo) -> ProbeResult:
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute("select version()")
            version = str(cur.fetchone()[0])
            cur.execute(_CAN_WRITE_SQL)
            can_write = bool(cur.fetchone()[0])
        return ProbeResult(reachable=True, server_version=version, can_write=can_write)

    def reflect(self, info: ConnectionInfo) -> SchemaSnapshot:
        grouped: dict[str, list[ColumnSchema]] = {}
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute(_REFLECT_SQL)
            for table_name, column_name, data_type, is_nullable, comment in cur.fetchall():
                grouped.setdefault(table_name, []).append(
                    ColumnSchema(
                        name=column_name,
                        data_type=data_type,
                        is_nullable=is_nullable == "YES",
                        is_numeric=data_type in _NUMERIC_TYPES,
                        comment=comment or None,
                    )
                )
        tables = tuple(
            TableSchema(name=table, schema_name=info.database, columns=tuple(columns))
            for table, columns in sorted(grouped.items())
        )
        return SchemaSnapshot(tables=tables)

    def execute(
        self,
        info: ConnectionInfo,
        sql: str,
        *,
        timeout_seconds: int,
        max_rows: int,
        on_start: Callable[[QueryHandle], None] | None = None,
    ) -> QueryResult:
        with self._connect(info) as conn, conn.cursor() as cur:
            # 只对只读 SELECT 生效（见文件头注释 2）。单位是毫秒。
            cur.execute("set session max_execution_time = %s", (timeout_seconds * 1000,))
            if on_start is not None:
                cur.execute("select connection_id()")
                on_start(QueryHandle(token=str(cur.fetchone()[0])))

            try:
                cur.execute(sql)
            except pymysql.err.OperationalError as exc:
                # errno 直接区分，不猜消息、不看耗时
                code = exc.args[0] if exc.args else None
                if code == _ER_QUERY_TIMEOUT:
                    raise QueryTimeout("查询超过语句超时") from exc
                if code == _ER_QUERY_INTERRUPTED:
                    raise QueryCancelled("查询已取消") from exc
                raise QueryFailed(str(exc)) from exc
            except pymysql.Error as exc:
                raise QueryFailed(str(exc)) from exc

            if cur.description is None:
                return QueryResult(columns=(), rows=(), row_count=0, truncated=False)

            fetched = tuple(tuple(row) for row in cur.fetchmany(max_rows + 1))
            rows, truncated = truncate(fetched, max_rows)
            columns = tuple(
                ColumnSchema(name=item[0], data_type="", is_numeric=False)
                for item in cur.description
            )
        return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)

    def cancel(self, info: ConnectionInfo, handle: QueryHandle) -> None:
        """`KILL QUERY <id>` 只掐当前语句，保留连接；`KILL CONNECTION` 会连坐。

        幂等：连接已不存在时 MySQL 报 errno 1094（unknown thread id），
        这不是错误，静默吞掉。
        """
        with self._connect(info) as conn, conn.cursor() as cur:
            try:
                cur.execute(f"kill query {int(handle.token)}")
            except pymysql.err.OperationalError as exc:
                if (exc.args[0] if exc.args else None) != 1094:
                    raise
```

**`execute` 返回的 `columns` 里 `data_type` 是空串、`is_numeric` 恒 False**，这与 Postgres 驱动不同，是一处**已知的不对等**：pymysql 的 `cursor.description` 只给 type_code 数字，翻成名字要自己维护一张 `FIELD_TYPE` 映射表。契约测没有断言 `execute` 结果里的类型（只断言 `reflect` 的），所以这里不会红。

**这是个坦白的缺口，不要当成已完成**：P3 的前端选图依赖 `is_numeric`，走的是 `reflect` 的输出还是 `execute` 的输出，到 P3 必须定下来。如果 P3 决定用 `execute` 的输出，这里就得补 `pymysql.constants.FIELD_TYPE` 的映射，并给契约套件加一条断言 `execute` 列类型的用例——那条用例现在没有，因为三个库的类型名根本不可能对齐，硬写会变成三份 if。已记入本份末尾的交接清单。

- [ ] **Step 4: 跑测试（预期仍 skip）**

```bash
uv run pytest -q && uv run ruff check src tests
```

预期：`158 passed`、`13 skipped`（passed 数不变——mysql 的 13 条全 skip），ruff 无告警。**`import pymysql` 必须能成功**，否则 `registry.get_driver("mysql")` 在门禁那天才炸。用一句话确认：

```bash
uv run python -c "from chatbi.datasources.registry import get_driver; d = get_driver('mysql'); print(d.kind, d.default_port)"
```

- [ ] **Step 5: 反向验证两条（能在无真库时做的部分）**

无真库时契约测全 skip，所以驱动逻辑的反向验证**只能推到门禁任务**。现在能做且必须做的是这两条：

1. `registry._DRIVERS` 里把 mysql 的类名改成 `"MySqlDriver"`（大小写错） → 上面那句 `get_driver('mysql')` 必须以 `AttributeError` 失败。这条挡的是「注册表写错名字，直到有真库才发现」。
2. `CONTRACT_KINDS` 里去掉 `"mysql"` → skip 数从 13 变 0。这条确认 mysql **真的进了参数表**，而不是「看起来加了但没生效」——参数化写错时 skip 数不会变，那时你会以为 mysql 已覆盖。

**门禁任务里要补做的**（写进下游那份）：Step 3 的 errno 分支对调、`max_execution_time` 删掉、`kill query` 改 `pass` 三条，每条都要对真 MySQL 跑。

- [ ] **Step 6: 提交**

```bash
git add apps/api/pyproject.toml apps/api/uv.lock apps/api/src/chatbi apps/api/tests
git commit -m "$(cat <<'EOF'
feat(drivers): MySQL driver behind the shared contract suite

Timeout and cancellation are told apart by errno (3024 / 1317) rather than
by the elapsed-time heuristic Postgres needs. Contract cases skip until a
real MySQL is up; the skip count is printed on every run.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: ClickHouse 驱动

同 Task 3：本机没有 ClickHouse，契约测 skip 并计数，驱动逻辑的反向验证推到门禁任务。

ClickHouse 有四处和前两个库都不一样，写之前先读完：

1. **`sleep()` 单次上限 3 秒**——`select sleep(30)` 会直接报错而不是睡 30 秒，用它测超时会得到一条假的 `QueryFailed`。要用 `select sleepEachRow(1) from numbers(30)`。
2. **类型名必须前缀匹配，不能集合匹配**。`Decimal(12, 2)`、`Nullable(Int32)`、`LowCardinality(String)` 都是复合写法，`data_type in _NUMERIC_TYPES` 这种查表法在这里必然漏。
3. **可空性写在类型里**：`Nullable(T)` 而不是一个 `is_nullable` 列。
4. **`query_id` 由客户端生成**——这反而是三个库里最干净的取消：不需要先问库拿 pid/connection_id，自己造一个 id 就能 `KILL QUERY WHERE query_id = ...`。

**Files:**
- Create: `apps/api/src/chatbi/datasources/drivers/clickhouse.py`
- Modify: `apps/api/pyproject.toml`（加 `clickhouse-connect>=0.8`）
- Modify: `apps/api/tests/drivers/conftest.py`（`CONTRACT_KINDS` 与 `DIALECTS` 各加一项）

**Interfaces:**
- Consumes: Task 1 的值对象与协议、Task 2 的契约套件
- Produces: `chatbi.datasources.drivers.clickhouse.ClickHouseDriver`（`kind = "clickhouse"` · `default_port = 8123`）

- [ ] **Step 1: 装依赖并接进契约套件**

`pyproject.toml` 加 `"clickhouse-connect>=0.8",`，`uv sync`。

`apps/api/tests/drivers/conftest.py` 改两处：

```python
CONTRACT_KINDS: tuple[str, ...] = ("postgres", "mysql", "clickhouse")
```

```python
    "clickhouse": Dialect(
        # sleep() 单次上限 3 秒，用 sleepEachRow 累加出 30 秒
        sleep_sql="select sleepEachRow(1) from numbers(30)",
        rows_sql="select number from numbers({n})",
        # 必须带 ENGINE 与 ORDER BY，MergeTree 是最通用的选择
        create_table_sql=(
            "create table {table} ("
            "id Int32, label Nullable(String), amount Decimal(12, 2)) "
            "engine = MergeTree order by id"
        ),
        drop_table_sql="drop table if exists {table}",
        insert_row_sql="insert into {table} (id, label, amount) values (1, '甲', 12.34)",
    ),
```

- [ ] **Step 2: 写纯函数的失败测试**

`_unwrap` 与 `_is_numeric` 是纯字符串函数，却承载了 ClickHouse `is_numeric` 的全部正确性——而契约测在无真库时全 skip。不给它们单测，这块逻辑到门禁那天之前一行验证都没有。

新建 `apps/api/tests/test_clickhouse_types.py`：

```python
"""ClickHouse 类型名解析。纯字符串函数，不需要真库——所以没有理由不测。"""

import pytest

from chatbi.datasources.drivers.clickhouse import _is_numeric, _unwrap


@pytest.mark.parametrize(
    ("type_name", "inner", "nullable"),
    [
        ("Int32", "Int32", False),
        ("Nullable(Int32)", "Int32", True),
        ("Decimal(12, 2)", "Decimal(12, 2)", False),
        ("Nullable(Decimal(12, 2))", "Decimal(12, 2)", True),
        ("LowCardinality(String)", "String", False),
        ("LowCardinality(Nullable(String))", "String", True),
    ],
)
def test_unwrap(type_name: str, inner: str, nullable: bool) -> None:
    assert _unwrap(type_name) == (inner, nullable)


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [
        ("Int8", True),
        ("UInt64", True),
        ("Float32", True),
        ("Decimal(12, 2)", True),
        ("Nullable(Int32)", True),
        ("String", False),
        ("LowCardinality(String)", False),
        ("DateTime64(3)", False),
        ("Array(Int32)", False),
    ],
)
def test_is_numeric(type_name: str, expected: bool) -> None:
    assert _is_numeric(type_name) is expected
```

`DateTime64(3)` 与 `Array(Int32)` 两条是这组用例的重点：前者含数字却不是数值列，后者内层是数值但整列不是。**集合匹配和天真的「含 Int 就算数值」都过不了这两条。**

- [ ] **Step 3: 跑测试确认失败与 skip 计数**

```bash
uv run pytest tests/test_clickhouse_types.py -v
uv run pytest tests/drivers -v
```

预期：
- `test_clickhouse_types.py` 在收集期 `ModuleNotFoundError: chatbi.datasources.drivers.clickhouse`（15 条参数化用例一条都跑不起来）。
- 契约测：postgres 13 passed、mysql 13 skipped、clickhouse 13 skipped，末尾 `skip 合计 26，其中驱动契约测 26`，且两条 `13 × Skipped: ...` 分别点名两个环境变量。

- [ ] **Step 4: 写 clickhouse.py**

新建 `apps/api/src/chatbi/datasources/drivers/clickhouse.py`：

```python
"""ClickHouse 驱动。

与前两个驱动的差别见 Task 4 开头那四条。最要紧的一条：类型名用**前缀匹配**，
因为 Decimal(12, 2) / Nullable(Int32) / LowCardinality(String) 都是复合写法。
"""

import uuid
from collections.abc import Callable

import clickhouse_connect
from clickhouse_connect.driver.exceptions import ClickHouseError, OperationalError

from chatbi.datasources.drivers.base import (
    ColumnSchema,
    ConnectionFailed,
    ConnectionInfo,
    ProbeResult,
    QueryCancelled,
    QueryFailed,
    QueryHandle,
    QueryResult,
    QueryTimeout,
    SchemaSnapshot,
    TableSchema,
    truncate,
)

_CONNECT_TIMEOUT_SECONDS = 10
# 服务端错误码：超时与被杀各有其一，不用猜消息也不用看耗时
_TIMEOUT_EXCEEDED = 159
_QUERY_WAS_CANCELLED = 394

# 前缀匹配用。剥掉 Nullable(...) / LowCardinality(...) 之后比这些前缀。
_NUMERIC_PREFIXES = ("Int", "UInt", "Float", "Decimal")
_WRAPPERS = ("Nullable(", "LowCardinality(")


def _unwrap(type_name: str) -> tuple[str, bool]:
    """剥掉包装类型，返回 (内层类型名, 是否可空)。

    ClickHouse 把可空性写在类型里而不是单独一列，而包装可以嵌套
    （LowCardinality(Nullable(String)) 是合法的），所以要循环剥。
    """
    nullable = False
    current = type_name.strip()
    while True:
        for wrapper in _WRAPPERS:
            if current.startswith(wrapper) and current.endswith(")"):
                nullable = nullable or wrapper == "Nullable("
                current = current[len(wrapper) : -1].strip()
                break
        else:
            return current, nullable


def _is_numeric(type_name: str) -> bool:
    inner, _ = _unwrap(type_name)
    return inner.startswith(_NUMERIC_PREFIXES)
```

同一个文件，接着写类体：

```python
class ClickHouseDriver:
    kind = "clickhouse"
    default_port = 8123

    def _client(self, info: ConnectionInfo, **settings):
        try:
            return clickhouse_connect.get_client(
                host=info.host,
                port=info.port,
                database=info.database or "default",
                username=info.username or "default",
                password=info.password or "",
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                settings=settings or None,
                **info.options,
            )
        except (OperationalError, OSError) as exc:
            raise ConnectionFailed() from exc

    def probe(self, info: ConnectionInfo) -> ProbeResult:
        client = self._client(info)
        try:
            version = str(client.command("select version()"))
            can_write = bool(int(client.command(_CAN_WRITE_SQL)))
        except ClickHouseError as exc:
            raise ConnectionFailed() from exc
        finally:
            client.close()
        return ProbeResult(reachable=True, server_version=version, can_write=can_write)

    def reflect(self, info: ConnectionInfo) -> SchemaSnapshot:
        client = self._client(info)
        try:
            result = client.query(
                "select table, name, type, comment from system.columns "
                "where database = currentDatabase() order by table, position"
            )
            rows = result.result_rows
        finally:
            client.close()

        grouped: dict[str, list[ColumnSchema]] = {}
        for table_name, column_name, type_name, comment in rows:
            _, nullable = _unwrap(type_name)
            grouped.setdefault(table_name, []).append(
                ColumnSchema(
                    name=column_name,
                    data_type=type_name,  # 原样保留复合写法，P2c 的 UI 要显示它
                    is_nullable=nullable,
                    is_numeric=_is_numeric(type_name),
                    comment=comment or None,
                )
            )
        tables = tuple(
            TableSchema(name=table, schema_name=info.database, columns=tuple(columns))
            for table, columns in sorted(grouped.items())
        )
        return SchemaSnapshot(tables=tables)

    def execute(
        self,
        info: ConnectionInfo,
        sql: str,
        *,
        timeout_seconds: int,
        max_rows: int,
        on_start: Callable[[QueryHandle], None] | None = None,
    ) -> QueryResult:
        # query_id 自己生成——这是三个库里最干净的取消：不用先问库拿 pid
        query_id = f"chatbi-{uuid.uuid4().hex}"
        client = self._client(
            info, max_execution_time=timeout_seconds, max_result_rows=max_rows + 1
        )
        if on_start is not None:
            on_start(QueryHandle(token=query_id))
        try:
            result = client.query(sql, settings={"query_id": query_id})
        except ClickHouseError as exc:
            code = getattr(exc, "code", None)
            if code == _TIMEOUT_EXCEEDED:
                raise QueryTimeout("查询超过语句超时") from exc
            if code == _QUERY_WAS_CANCELLED:
                raise QueryCancelled("查询已取消") from exc
            raise QueryFailed(str(exc)) from exc
        finally:
            client.close()

        if not result.column_names:
            return QueryResult(columns=(), rows=(), row_count=0, truncated=False)
        fetched = tuple(tuple(row) for row in result.result_rows)
        rows, truncated = truncate(fetched, max_rows)
        columns = tuple(
            ColumnSchema(name=name, data_type=type_name, is_numeric=_is_numeric(type_name))
            for name, type_name in zip(result.column_names, result.column_types, strict=True)
        )
        return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)

    def cancel(self, info: ConnectionInfo, handle: QueryHandle) -> None:
        """KILL QUERY 是异步的：它只标记，不等查询真的停下。

        契约测的 worker.join(timeout=20) 给了足够余量。幂等：没有匹配的 query_id
        时 ClickHouse 返回空结果集而不报错。
        """
        client = self._client(info)
        try:
            client.command(
                "kill query where query_id = %(qid)s", parameters={"qid": handle.token}
            )
        finally:
            client.close()
```

`result.column_types` 的元素是 clickhouse-connect 的类型对象而不是字符串，实施时确认要不要 `str(...)` 一下（`_is_numeric` 收的是 `str`）。这是**必须在真库上核实**的一处，别照抄了就算完。

- [ ] **Step 5: `can_write` 的探测——这一处很可能要改**

上面留了 `_CAN_WRITE_SQL` 没写。初版这样写：

```python
# 只读地问权限。system.grants 是视图，查它不产生任何写入。
_CAN_WRITE_SQL = """
select toUInt8(count() > 0) from system.grants
where user_name = currentUser()
  and access_type in ('INSERT', 'ALTER', 'CREATE TABLE', 'DROP TABLE', 'TRUNCATE')
"""
```

**这条大概率在 `default` 用户上返回 0，而 `default` 通常是全权限的。** 原因是 ClickHouse 对内置的全权限用户不一定在 `system.grants` 里留显式记录。三个库里这是唯一一处我无法在写计划时验证的判断。

门禁任务的第一件事就是**先手工确认它**：

```sql
select currentUser();
select * from system.grants where user_name = currentUser();
show grants;
```

如果 `system.grants` 对当前用户是空的，改用 `show grants` 的文本输出判断（找 `GRANT ALL` 或上述 access_type），或退一步：ClickHouse 上把 `can_write` 恒置 `True` 并在注释里写明理由——**宁可误报「账号可写」也不能误报「已验证只读」**，因为 spec §4.3 闸 1 的告警是给用户看的安全提示，漏报比误报危险得多。这个取舍要写进代码注释，不是留个 TODO。

- [ ] **Step 6: 跑测试（预期仍 skip）**

```bash
uv run pytest -q && uv run ruff check src tests
uv run python -c "from chatbi.datasources.registry import get_driver; d = get_driver('clickhouse'); print(d.kind, d.default_port)"
```

预期：`173 passed`、`26 skipped`（Task 3 后的 158 + `test_clickhouse_types.py` 的 15 条参数化用例），ruff 无告警，最后那句打印 `clickhouse 8123`。

- [ ] **Step 7: 反向验证四条（无真库时能做的）**

1. `registry._DRIVERS` 里把 clickhouse 的类名写错 → `get_driver('clickhouse')` 必须 `AttributeError`。
2. `CONTRACT_KINDS` 去掉 `"clickhouse"` → skip 数从 26 变 13。
3. **`_is_numeric` 改成 `inner.startswith("Int")`**（只认一个前缀）→ `test_clickhouse_types.py` 里 `UInt64` / `Float32` / `Decimal(12, 2)` 三条必须 FAIL。
4. **`_unwrap` 的 `while` 改成只剥一层**（把循环换成一次 `if`）→ `LowCardinality(Nullable(String))` 那条必须 FAIL。嵌套包装是 ClickHouse 的常见写法，只剥一层会让这类列的可空性判断反过来。

- [ ] **Step 8: 提交**

```bash
git add apps/api/pyproject.toml apps/api/uv.lock apps/api/src/chatbi apps/api/tests
git commit -m "$(cat <<'EOF'
feat(drivers): ClickHouse driver behind the shared contract suite

Type names are matched by prefix after unwrapping Nullable/LowCardinality,
which set membership cannot do for Decimal(12, 2) or Array(Int32). The
client generates its own query_id, so cancellation needs no round trip.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 交接清单（下游三份要消费的签名）

**签名全表**
```python
# 值对象与异常（chatbi.datasources.drivers.base）
ConnectionInfo(kind, host, port, database, username, password=None, options={})  # repr 恒掩码
ColumnSchema(name, data_type, is_nullable=True, is_numeric=False, comment=None)
TableSchema(name, schema_name, columns=(), comment=None)
SchemaSnapshot(tables=())
ProbeResult(reachable, server_version, can_write)
QueryHandle(token)
QueryResult(columns, rows, row_count, truncated)
DriverError · ConnectionFailed · QueryTimeout · QueryCancelled · QueryFailed
truncate(rows, max_rows) -> (rows, truncated)

# 协议（四个方法，全部同步阻塞）
Driver.probe(info) -> ProbeResult
Driver.reflect(info) -> SchemaSnapshot
Driver.execute(info, sql, *, timeout_seconds, max_rows, on_start=None) -> QueryResult
Driver.cancel(info, handle) -> None

# 注册表
chatbi.datasources.registry.get_driver(kind) -> Driver      # 惰性 import，lru_cache
chatbi.datasources.registry.registered_kinds() -> tuple[str, ...]
chatbi.datasources.registry.UnknownDriver

# 配置
Settings.query_timeout_seconds: int = 60 · Settings.max_result_rows: int = 1000

# 错误码
chatbi.errors.CONNECTION_ERROR = ("CONNECTION_ERROR", "无法连接到数据库，请检查地址、端口与网络", 503)
```

**[P2b `/test` 与示例库](2026-08-18-chatbi-v2-1-p2b-test-endpoint-and-demo.md)（Task 5–7）**
- `ConnectionInfo` 的组装是**它的**活：从 `Datasource` 模型取字段 + `read_password(datasource)` 取明文。驱动不认识 ORM，别想着给驱动传模型。
- `/test` 调 `probe()`，把 `can_write` 取反写进 `is_readonly_verified`，**不阻止保存**（spec §4.3 闸 1）。
- 捕 `ConnectionFailed` → `ApiError(*CONNECTION_ERROR)`。异常的 `__cause__` 里有地址端口，**只能进服务端日志**。
- 收尾门禁任务要补做的反向验证已在 Task 3 Step 5、Task 4 Step 4/6 里逐条列明，照着做。

**P2c F-201 元数据接入**
- `schema_cache.payload` 存 `reflect()` 输出的 JSON 序列化。`SchemaSnapshot` 是 frozen dataclass，序列化要自己写（`dataclasses.asdict` 可用）。
- `column_notes` 与 `ColumnSchema.comment` 是**两个来源**：后者是库里的原生注释，前者是人工补的。合并策略（人工优先？并列显示？）P2c 定，spec §2.5 只说了「注释单独存，refresh 不能覆盖人工补的」。

**P3 执行器**
- `execute()` 是同步阻塞的。异步化用线程池（`asyncio.to_thread`），**不要**改驱动——三个库里只有一个有靠得住的 asyncio 支持，在驱动层假装统一会让取消语义更难推理。
- 取消流程：`on_start` 回调里拿到 `QueryHandle` 存进 run 的上下文 → 客户端断开或 `DELETE .../execute` 时从另一个线程调 `driver.cancel(info, handle)`。`cancel` 幂等，可以无条件调。
- `QueryTimeout` → `QUERY_TIMEOUT`、`QueryCancelled` → `QUERY_CANCELLED`、`QueryFailed` → 按内容映射、`ConnectionFailed` → `CONNECTION_ERROR`。这三个错误码本段**没有**定义（只有 `CONNECTION_ERROR`），P3 加。
- **`execute()` 不做任何 SQL 检查**。闸 2（AST）与闸 3（LIMIT 注入）在 `guard`，`execute` 只接 `ApprovedStatement` 里那条已批准的语句。契约测里用 `execute()` 跑 DDL 正是这个事实的证据——别因此以为驱动漏了防线。

**一个留给 P3 定的缺口（不是遗漏，是没有依据现在定）**
- `execute()` 返回的 `columns` 里，Postgres 与 ClickHouse 给了真实类型名与 `is_numeric`，**MySQL 给的是空串与恒 False**（pymysql 的 `cursor.description` 只有 type_code 数字，翻名字要自己维护 `FIELD_TYPE` 映射表）。
- 前端选图依赖 `is_numeric`（spec §2.3 的 `result` 事件）。P3 要定它取自 `reflect()` 还是 `execute()`：取 `reflect()` 则三个库都已可用，MySQL 这个缺口无关；取 `execute()` 则必须先补 MySQL 的映射表，并给契约套件加一条断言 `execute` 列类型的用例。
- 那条用例现在**故意没有**：三个库的类型名不可能对齐，硬写会退化成三份 `if kind == ...`，而那正是 Task 2 开头禁止的形状。

---

## 自查记录

**spec 覆盖核对**（只核本份承担的）

| spec 条目 | 落在哪 |
|---|---|
| §1.2 `datasources/registry.py` + `drivers/` 一库一文件 | Task 1（registry）、Task 2–4（三个驱动各一文件） |
| §1.4 驱动按库分文件、共用协议默认实现、不出现 600 行 `drivers.py` | Task 1 的 `base.py` + 三个各 ≤200 行的实现 |
| §2.3 取消要**调驱动的取消能力**（`pg_cancel_backend` / `KILL QUERY` / `KILL QUERY WHERE query_id=`） | Task 2/3/4 的 `cancel()`，三种原语各一处；契约测 `test_cancel_stops_a_running_query` |
| §4.3 闸 1 只读账号探测（探到可写要告警，不阻止保存） | Task 1 的 `ProbeResult.can_write` + 三个驱动的只读探测；「不阻止保存」在下游那份 |
| §4.3 闸 4 语句超时 + 真取消（默认 60s，可配） | `Settings.query_timeout_seconds` + 三个驱动的库侧超时设置 |
| §4.3 闸 2/3（AST 校验、LIMIT 注入） | **不在本段**，属 `guard`/P3。`execute()` 刻意不做 SQL 检查 |
| §4.4 错误消息不回显地址端口 | `ConnectionFailed` 恒通用文案 + 契约测的泄露扫描 + `ConnectionInfo.repr()` 掩码 |
| §5.1 三驱动跑**同一套**契约用例（连通性/反射/类型映射/超时/取消/截断） | Task 2 的 `test_driver_contract.py`，参数化跑，六项各有用例 |
| §5.1 skip 允许但必须计数上报，CI 输出显式打印 | Task 1 的 `pytest_terminal_summary` 钩子；Task 3/4 的 Step 2 专门验证它 |
| §2.6 `CONNECTION_ERROR` | Task 1 Step 3 |

**本份不覆盖**：`/test` 与 `/schema` 端点、`is_readonly_verified` 的写入、`demo_sales`、`compose.test.yml`、真库门禁 → 下游那份；`schema_cache`/`column_notes` → P2c；`QUERY_TIMEOUT`/`QUERY_CANCELLED` 两个错误码与执行器 → P3。

**占位符扫描**：无 TBD / TODO / 「类似 Task N」/ 无代码的「写测试」步骤。唯一一处「留待确认」是 Task 4 Step 4 的 `_CAN_WRITE_SQL`——那不是占位符，是**已给出初版实现 + 明确的验证步骤 + 两条备选方案与取舍方向**，因为它依赖一台我现在拿不到的 ClickHouse 服务器。

**写作过程中的回改**

1. **契约测套件从 Task 1 挪到 Task 2**。初稿把它放 Task 1，但那时三个驱动模块都不存在，`get_driver("postgres")` 会在收集期抛 `ModuleNotFoundError`——套件根本跑不起来，「先写失败的测试」这一步会退化成「先写一个连导入都过不了的文件」。挪到 Task 2 与第一个真驱动一起诞生，套件从一开始就是对着真库变绿的。File Structure 表里的任务归属已同步。
2. **`test_clickhouse_types.py` 是写 Task 4 时才加的**，并回填进了 File Structure。原因：`_unwrap` / `_is_numeric` 是纯字符串函数却承载了 `is_numeric` 的全部正确性，而契约测在无真库时全 skip——如果不给它们单测，ClickHouse 的类型映射在门禁那天之前一行验证都没有。
3. **超时与取消的区分方式三个库各不同，没有强行统一**。Postgres 只能靠耗时（同一个 SQLSTATE 57014，消息受 `lc_messages` 影响），MySQL 与 ClickHouse 有各自的错误码。初稿想在 `base.py` 里抽一个公共判别函数，写到 MySQL 时发现那会退化成「传一堆参数进去再 if」，不如各自三行。
4. **`ConnectionInfo` 的 `repr` 对 `password=None` 也打 `***`**。初稿只在非 None 时掩码，写测试时意识到形状不同本身就是信息泄露——`password=None` 等于告诉读者「这个数据源没设密码」。
5. **`can_write` 的语义定成「宁可误报可写」**。Task 4 Step 4 写明了这个取舍方向：spec §4.3 闸 1 的告警是给用户看的安全提示，「误报账号可写」只是多一条告警，「误报已验证只读」会让用户以为自己安全。

**已知的松散端与取舍**

- **MySQL 的 `execute()` 不返回列类型**（空串 + `is_numeric` 恒 False）。已在交接清单里作为「留给 P3 定的缺口」写明，不是遗漏。
- **ClickHouse 的 `_CAN_WRITE_SQL` 未经真库验证**，大概率要改。门禁任务的第一件事就是它。
- **每次调用开一条新连接，不做连接池**。池化会让取消语义复杂得多（要保证 kill 的是本次查询占的那条连接），私有化部署的并发量不需要。P3 若要加池，得先想清楚 `QueryHandle` 与连接的绑定关系。
- **MySQL 的 `max_execution_time` 只对只读 SELECT 生效**。对生产路径没问题（能到执行器的语句都过了 guard 的 SELECT-only 校验），但契约测里的 DDL 不受它约束——别因此以为超时没设上。
- **`Driver` 是 `Protocol` 而非 ABC**，所以「某个驱动漏实现一个方法」不会在 import 时报错，只会在契约测里红。这是有意的（Protocol 不需要驱动 import 基类），代价是三个驱动都必须真的跑过契约测——门禁任务不过就等于这一层没有类型保障。
- **契约测会在目标库里建/删表**（`seeded_table` 夹具）。表名带 uuid 后缀，但**目标库必须是能写的测试库**，别把 `CHATBI_TEST_PG_DSN` 指向生产。DSN 名字里带 `_test` 不像应用库那样有守卫——加一个守卫会挡住 ClickHouse 的 `default` 库这种合法情况。
- **不能加 `pytest-xdist`**（沿用 P1 §10.4，且契约测的建表并发会互相干扰）。

**类型一致性核对**

`ConnectionInfo` 的字段名与 `Datasource` 模型的列名一一对应（`kind`/`host`/`port`/`database`/`username`/`options`），所以下游组装时不需要改名映射——只有 `password` 是从 `read_password()` 来的，模型上没有同名字段（模型是 `secret_ciphertext`/`secret_nonce`），这处不对称是有意的。`truncate(rows, max_rows) -> (rows, truncated)` 的返回顺序在三个驱动里的解包写法一致。`QueryHandle.token` 三处都是 `str`（Postgres 是 pid 的字符串形式、MySQL 是 connection id 的字符串形式、ClickHouse 是自造的 `chatbi-<hex>`），`cancel` 里两处 `int(handle.token)` 的转换只在前两个驱动里出现。`on_start` 的签名 `Callable[[QueryHandle], None]` 在协议、三个实现、契约测四处一致。`Dialect` 的五个字段名与 `DIALECTS` 三个条目、`seeded_table` 夹具的 `.format(table=...)` 调用一致（`rows_sql` 用 `{n}`，其余四个用 `{table}`）。

无「Task N 定义、Task M 改名」的情况。
