# Chat-BI V2-1 · P2b `/test` 端点、示例库与真库门禁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把驱动接到 HTTP 上（`POST /api/datasources/{id}/test`，含只读探测与 `is_readonly_verified` 写入）、灌一个开箱即跑的 `demo_sales` 示例库并注册成数据源，最后过掉「三库契约测全绿、skip 数为 0」这道门禁。

**Architecture:** `/test` 是驱动的第一个生产调用方，所以本段要定下「模型 → `ConnectionInfo`」这条组装路径（`datasources/connection.py`）与「驱动作为可覆盖依赖」这个接缝（`deps.driver_for`）——后者直接沿用 P1 遗留 2 的教训：不做成 `Depends()` 的东西，测试里就换不掉。示例库走 CLI 而不是 migration 自动注册，理由见 Global Constraints。

**Tech Stack:** Python 3.12 · FastAPI · psycopg 3 · pymysql · clickhouse-connect · typer · Docker Compose · pytest

**上游 spec:** [2026-08-11-chatbi-v2-1-design.md](../specs/2026-08-11-chatbi-v2-1-design.md)（§2.4 `/test`、§2.5 `demo_sales`、§4.3 闸 1、§4.4 脱敏、§5.1 skip 计数、§8.1/§8.2 验收）
**上游计划:** [P2b 驱动协议与三驱动](2026-08-18-chatbi-v2-1-p2b-drivers.md)（末尾交接清单 = 本份消费的签名）· [P2a HTTP 层](2026-08-13-chatbi-v2-1-p2a-datasource-api.md)（`_Db` / `_Admin` / `_Target` 与 responses 常量）
**下游计划:** P2c F-201 元数据接入 · P3 可控链路

**任务编号延续上游那份**（Task 1–4 是协议与三驱动），本份是 Task 5–7。

## Global Constraints

上游那份的 Global Constraints 全部仍然有效（不新增依赖、驱动边界、四道闸的分工、行截断语义、skip 计数、错误消息不回显地址端口）。下面只列本段特有的。

**不新增 Python 依赖。** 三个驱动包在上游那份已装齐，本段只加一个 `docker/compose.test.yml` 与一条 CLI 命令。

**`/test` 端点（spec §2.4 + §4.3 闸 1）**
- 只有 `admin` 能调——它会写 `is_readonly_verified`，是写操作。
- 探到账号可写就**告警并把 `is_readonly_verified` 置 false，但不阻止保存**。这是 spec §4.3 明写的：有些环境拿不到只读账号，但要让用户知道。
- 连不上 → `CONNECTION_ERROR`(503)，用户可见文案是通用的那句，**不回显地址端口**。地址端口进服务端日志。
- 响应里可以有 `server_version`（排障要用），**不能有**密码、密文、nonce、以及任何形式的连接串。

**示例库（spec §2.5 末）**
- `migration 0003` 只建 `demo_sales` schema 与表、灌数据。**它不 INSERT 任何 datasource 行、不 import `chatbi.datasources.crypto`。** 理由：注册数据源必须 seal 密码，而 seal 需要主密钥——让 `alembic upgrade` 依赖 `CHATBI_SECRET_KEY` 意味着任何一次迁移（包括 CI 里只想验证 schema 的场合）都要先配好密钥。
- 数据源注册由 CLI `seed-demo` 完成，走 `create_datasource()` 正常加密。
- **示例数据源必须用一个只能读 `demo_sales` 的专用角色**，不能复用应用库账号。应用库里有 `users` 表（含 `password_hash`）与 `datasources` 表（含密文）——把应用账号封成一个数据源，等于给任何被授权该数据源的 analyst 一条 `select * from users` 的路。这一条是本段的安全红线，Task 6 有测试钉它。

**门禁（spec §5.1 + §8.1）**
- 「三类驱动对真库跑通契约测，全套用例通过，**skip 数为 0**」是 V2-1 的验收项，也是本段的退出标准。
- 上游那份因为本机无 Docker 而推迟的反向验证（MySQL 的 errno 分支与 `KILL QUERY`、ClickHouse 的 `_CAN_WRITE_SQL` 与错误码）在 Task 7 补做，**每条都要对真库跑**。
- 门禁不过，P2b 不算完——不允许用「代码写完了」代替「真库跑过了」。

## 本机环境（2026-08-18 实测）

- 原生 PostgreSQL 16 可用（`localhost:5432`，`chatbi`/`chatbi`）。
- **Docker 守护进程不可用**：Docker Desktop 已装，`wsl -l -v` 无任何发行版，`docker version` 连不上 npipe。`docker/` 下只有 `compose.yml` 与 `initdb/`。
- **Task 7 有一步需要你（人）操作**：管理员权限跑 `wsl --install`、重启、首次启动发行版并接受许可。这一步无法自动化，也无法绕过——ClickHouse 没有官方支持的原生 Windows 版。
- 环境变量同上游那份。**起点基线：`173 passed`、`26 skipped`**（上游 Task 4 结束时的值）。开工前先跑一次确认。

---

## File Structure

### 本份创建的文件

| 文件 | 职责 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/datasources/connection.py` | `connection_info(datasource) -> ConnectionInfo`：模型 + `read_password` → 驱动的输入。**唯一**一处把明文密码从仓储交给驱动 | 5 |
| `apps/api/tests/test_connection_assembly.py` | 组装的字段映射与「明文不进 repr」 | 5 |
| `apps/api/tests/test_datasource_test_endpoint.py` | `/test` 的鉴权、探测结果落库、`CONNECTION_ERROR`、响应无凭据 | 5 |
| `apps/api/migrations/versions/0003_demo_sales.py` | 建 `demo_sales` schema、三张表、灌数据、建只读角色 | 6 |
| `apps/api/tests/test_demo_sales.py` | 表与数据就位、只读角色**读不到应用表**、`seed-demo` 幂等 | 6 |
| `docker/compose.test.yml` | 契约测用的 postgres / mysql / clickhouse | 7 |

### 本份修改的文件

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/datasources/deps.py` | 加 `driver_for`（可被 `dependency_overrides` 替换的驱动依赖） | 5 |
| `apps/api/src/chatbi/datasources/schemas.py` | 加 `DatasourceTestResult` | 5 |
| `apps/api/src/chatbi/api/datasource_router.py` | 加 `POST /{datasource_id}/test` | 5 |
| `apps/api/src/chatbi/cli.py` | 加 `seed-demo` 命令 | 6 |
| `apps/api/tests/test_migrations.py` | 断言集合加 `demo_sales` 的表 | 6 |
| `apps/api/tests/drivers/conftest.py` | 无改动——三个 kind 已在上游那份接齐 | 7 |

### 边界说明

`connection.py` 是**唯一**同时认识 `repository.read_password` 与 `drivers.base.ConnectionInfo` 的文件。放一个单独的模块而不是塞进 `repository.py`：仓储的职责是持久化，而这里是「把持久化的东西翻译成驱动的输入」，两者的变更理由不同（前者跟着表结构变，后者跟着驱动协议变）。

`deps.driver_for` 存在的唯一理由是**可测**——`/test` 的端点测试不该需要一台真数据库。这是 P1 遗留 2 的同一课：`get_identity_provider` 当初不是依赖，测试里就换不掉，到 P2a Task 1 才补。这次一开始就做成依赖。

`migration 0003` 不 import 任何 `chatbi.*` 业务模块（只用 `alembic.op` 与 `sqlalchemy`），所以它跑得起来不需要主密钥、不需要 `Settings` 里的 LLM 配置——CI 只想验 schema 时能干净地跑。

---

### Task 5: `POST /api/datasources/{id}/test`

**Files:**
- Create: `apps/api/src/chatbi/datasources/connection.py`
- Create: `apps/api/tests/test_connection_assembly.py`
- Create: `apps/api/tests/test_datasource_test_endpoint.py`
- Modify: `apps/api/src/chatbi/datasources/deps.py`（加 `driver_for`）
- Modify: `apps/api/src/chatbi/datasources/schemas.py`（加 `DatasourceTestResult`）
- Modify: `apps/api/src/chatbi/api/datasource_router.py`（加一条路由）

**Interfaces:**
- Consumes：上游交接清单的 `ConnectionInfo` / `ProbeResult` / `ConnectionFailed` / `registry.get_driver` · P2a 的 `read_password` / `require_datasource` / `_Db` / `_Admin` / `_Target` / `_TARGET` · `chatbi.errors.CONNECTION_ERROR`
- Produces:
```python
chatbi.datasources.connection.connection_info(datasource: Datasource) -> ConnectionInfo
chatbi.datasources.deps.driver_for(datasource) -> Driver   # FastAPI 依赖，可被 override
chatbi.datasources.schemas.DatasourceTestResult
#   reachable: bool · server_version: str · can_write: bool · is_readonly_verified: bool
#   —— 不含任何凭据、不含连接串
POST /api/datasources/{datasource_id}/test -> 200 DatasourceTestResult
#   401 / 403 / 404 / 503(CONNECTION_ERROR)
```

- [ ] **Step 1: 写组装层的失败测试**

新建 `apps/api/tests/test_connection_assembly.py`：

```python
"""模型 → ConnectionInfo 的组装。这是明文密码从仓储走向驱动的唯一一段路。"""

from chatbi.datasources.connection import connection_info


def test_connection_info_carries_the_model_fields(make_datasource) -> None:
    datasource = make_datasource(
        kind="mysql", host="mysql.internal", port=3306, database="sales", username="reader"
    )

    info = connection_info(datasource)

    assert info.kind == "mysql"
    assert info.host == "mysql.internal"
    assert info.port == 3306
    assert info.database == "sales"
    assert info.username == "reader"


def test_connection_info_carries_the_decrypted_password(make_datasource) -> None:
    """组装必须解密——驱动拿到密文是连不上的，而那种 bug 表现为「密码错误」，
    会让人去查凭据配置而不是查这一行。
    """
    datasource = make_datasource(password="ds-pw-123456")

    assert connection_info(datasource).password == "ds-pw-123456"


def test_connection_info_has_no_password_when_none_is_stored(make_datasource) -> None:
    datasource = make_datasource(password=None)

    assert connection_info(datasource).password is None


def test_connection_info_passes_options_through(make_datasource) -> None:
    """options 原样透传给驱动（sslmode 之类）。P2a 不校验内容，驱动自己认。"""
    datasource = make_datasource(options={"sslmode": "require"})

    assert connection_info(datasource).options == {"sslmode": "require"}


def test_the_assembled_info_hides_the_password_in_repr(make_datasource) -> None:
    """上游的 ConnectionInfo 已经掩码了，这条钉的是「组装没绕过它」——
    比如有人图省事返回了一个普通 dataclass 或 dict。
    """
    datasource = make_datasource(password="ds-pw-123456")

    assert "ds-pw-123456" not in repr(connection_info(datasource))
```

- [ ] **Step 2: 写端点的失败测试**

新建 `apps/api/tests/test_datasource_test_endpoint.py`。用**假驱动**（覆盖 `driver_for` 依赖），所以这些测试一台真数据库都不需要——真库验证在契约测那边，这里测的是编排：

```python
"""POST /api/datasources/{id}/test。

用假驱动覆盖 driver_for，因此不依赖任何外部数据库。这里测的是编排：
鉴权、探测结果落库、错误映射、响应脱敏、OpenAPI 声明。
"""

import pytest
from fastapi.testclient import TestClient

from chatbi.datasources.drivers.base import ConnectionFailed, ProbeResult


class _FakeDriver:
    """只实现 probe——/test 端点只调它。别的方法缺失会以 AttributeError 暴露，
    那正好说明端点调了它不该调的东西。
    """

    kind = "fake"
    default_port = 1234

    def __init__(self, *, can_write: bool = False, fail: bool = False) -> None:
        self._can_write = can_write
        self._fail = fail
        self.calls: list[str] = []

    def probe(self, info):
        self.calls.append(info.host)
        if self._fail:
            raise ConnectionFailed()
        return ProbeResult(
            reachable=True, server_version="FakeDB 1.2.3", can_write=self._can_write
        )


@pytest.fixture
def with_driver(admin_client: TestClient):
    """把假驱动装进依赖。返回一个 (driver) -> client 的函数。"""
    from chatbi.datasources.deps import driver_for
    from chatbi.main import app

    def _install(driver: _FakeDriver) -> TestClient:
        app.dependency_overrides[driver_for] = lambda: driver
        return admin_client

    yield _install
    app.dependency_overrides.pop(driver_for, None)


def test_admin_gets_a_probe_result(with_driver, make_datasource) -> None:
    datasource = make_datasource()
    client = with_driver(_FakeDriver())

    response = client.post(f"/api/datasources/{datasource.id}/test")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is True
    assert body["server_version"] == "FakeDB 1.2.3"
    assert body["can_write"] is False
    assert body["is_readonly_verified"] is True


def test_a_read_only_account_persists_the_verified_flag(with_driver, make_datasource) -> None:
    """落库，不只是响应里说一声——下次列表要显示这个状态。"""
    datasource = make_datasource(is_readonly_verified=False)
    client = with_driver(_FakeDriver(can_write=False))

    client.post(f"/api/datasources/{datasource.id}/test")

    assert client.get(f"/api/datasources/{datasource.id}").json()["is_readonly_verified"] is True


def test_a_writable_account_clears_the_flag_but_still_returns_200(
    with_driver, make_datasource
) -> None:
    """spec §4.3 闸 1：探到可写要告警并把标记置 false，**但不阻止保存**。

    有些环境拿不到只读账号，把它变成一个错误会让这些用户没法用产品；
    但不告警又等于假装安全。所以是 200 + can_write=true + 标记 false。
    """
    datasource = make_datasource(is_readonly_verified=True)
    client = with_driver(_FakeDriver(can_write=True))

    response = client.post(f"/api/datasources/{datasource.id}/test")

    assert response.status_code == 200
    assert response.json()["can_write"] is True
    assert response.json()["is_readonly_verified"] is False
    assert client.get(f"/api/datasources/{datasource.id}").json()["is_readonly_verified"] is False


def test_connection_failure_maps_to_connection_error(with_driver, make_datasource) -> None:
    datasource = make_datasource(host="db.internal", port=5432, username="ro_user")
    client = with_driver(_FakeDriver(fail=True))

    response = client.post(f"/api/datasources/{datasource.id}/test")

    assert response.status_code == 503
    assert response.json()["code"] == "CONNECTION_ERROR"
    # spec §4.4：不回显地址、端口、库名、用户名
    for leak in ("db.internal", "5432", "analytics", "ro_user"):
        assert leak not in response.text


def test_a_failed_probe_does_not_touch_the_verified_flag(with_driver, make_datasource) -> None:
    """连不上时不能把 is_readonly_verified 改成 false。

    「连不上」和「账号可写」是两件事；混在一起会让一次网络抖动把一个已验证
    只读的数据源降级，而用户不会再去点一次 /test。
    """
    datasource = make_datasource(is_readonly_verified=True)
    client = with_driver(_FakeDriver(fail=True))

    failed = client.post(f"/api/datasources/{datasource.id}/test")

    # 下限：没有这句，路由不存在时的 404 也让标记「保持为 True」，测试空洞通过
    assert failed.status_code == 503
    assert client.get(f"/api/datasources/{datasource.id}").json()["is_readonly_verified"] is True


def test_the_response_carries_no_credentials(with_driver, make_datasource) -> None:
    datasource = make_datasource(password="ds-pw-123456")
    client = with_driver(_FakeDriver())

    response = client.post(f"/api/datasources/{datasource.id}/test")

    assert response.status_code == 200  # 下限：404 的响应体也「不含密码」
    assert "ds-pw-123456" not in response.text
    for key in ("password", "secret_ciphertext", "secret_nonce"):
        assert key not in response.json()


def test_analyst_cannot_test_even_a_granted_datasource(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    """写操作专属 admin：/test 会改 is_readonly_verified。

    名字里的 granted 是功能性的——不授权的话 403 来自可见性判定，
    删掉 admin 闸门这条测试照样绿（P2a Task 5 踩过）。
    """
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    assert client.post(f"/api/datasources/{datasource.id}/test").status_code == 403


def test_unknown_datasource_returns_404(admin_client: TestClient) -> None:
    import uuid

    response = admin_client.post(f"/api/datasources/{uuid.uuid4()}/test")

    assert response.status_code == 404
    assert response.json()["code"] == "DATASOURCE_NOT_FOUND"


def test_the_test_route_declares_its_error_envelope() -> None:
    from chatbi.main import app

    responses = app.openapi()["paths"]["/api/datasources/{datasource_id}/test"]["post"][
        "responses"
    ]

    assert {"200", "401", "403", "404", "503"} <= set(responses)
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd apps/api
uv run pytest tests/test_connection_assembly.py tests/test_datasource_test_endpoint.py -v
```

预期：前者收集期 `ModuleNotFoundError: chatbi.datasources.connection`；后者在 `from chatbi.datasources.deps import driver_for` 上 `ImportError`。

**只做否定断言的测试都已配了状态码下限**（`test_the_response_carries_no_credentials` 的 200、`test_a_failed_probe_does_not_touch_the_verified_flag` 的 503）。P2a Task 5、6 各因为漏了这个下限而出现过「路由还不存在就绿了」的测试。跑失败这一步仍要逐条看失败原因：**任何一条「提前通过」都说明它缺下限**，当场补，别留到实现写完——那时它已经没机会暴露自己没有鉴别力了。

- [ ] **Step 4: 写 connection.py 与 driver_for**

新建 `apps/api/src/chatbi/datasources/connection.py`：

```python
"""模型 → ConnectionInfo 的组装。

这是明文密码从仓储走向驱动的**唯一**一段路。放单独一个模块而不是塞进 repository：
仓储跟着表结构变，这里跟着驱动协议变，两者的变更理由不同。
"""

from chatbi.datasources.drivers.base import ConnectionInfo
from chatbi.datasources.repository import read_password
from chatbi.db.models import Datasource


def connection_info(datasource: Datasource) -> ConnectionInfo:
    """组装驱动的输入。返回值的 repr 已由 ConnectionInfo 掩码。

    调用方只有 /test 与 P3 的执行器。**不要**把返回值整体写进日志——掩码只挡住了
    password，host/port 仍在里面（那是允许进服务端日志的，但不允许进 HTTP 响应）。
    """
    return ConnectionInfo(
        kind=datasource.kind,
        host=datasource.host,
        port=datasource.port,
        database=datasource.database,
        username=datasource.username,
        password=read_password(datasource),
        options=dict(datasource.options or {}),
    )
```

`dict(datasource.options or {})` 拷一份：`options` 是 JSONB 映射出来的**可变** dict，直接塞进 frozen dataclass 会让「不可变的连接信息」名不副实——驱动那边 `**info.options` 展开时若有人改过它，行为就不可复现。

`apps/api/src/chatbi/datasources/deps.py` 追加（import 段加 `registry.get_driver` 与 `drivers.base.Driver`）：

```python
def driver_for(datasource: Annotated[Datasource, Depends(require_datasource)]) -> Driver:
    """按数据源的 kind 取驱动。

    做成依赖**只为可测**：/test 的端点测试要能塞进假驱动而不需要真数据库。
    P1 遗留 2 就是反例——get_identity_provider 当初不是依赖，测试里换不掉，
    拖到 P2a Task 1 才补上。这次一开始就做成依赖。
    """
    return get_driver(datasource.kind)
```

- [ ] **Step 5: 加响应模型与路由**

`apps/api/src/chatbi/datasources/schemas.py` 追加：

```python
class DatasourceTestResult(BaseModel):
    """/test 的结果。

    故意不含任何凭据、也不含连接串——排障需要的是「通不通、什么版本、账号能不能写」，
    地址端口是用户自己填的，不需要回显（spec §4.4）。
    """

    reachable: bool
    server_version: str
    can_write: bool
    is_readonly_verified: bool
```

`apps/api/src/chatbi/api/datasource_router.py` 追加路由（import 段加 `logging`、`connection_info`、`driver_for`、`DatasourceTestResult`、`ConnectionFailed`、`Driver`、`CONNECTION_ERROR`）：

```python
logger = logging.getLogger(__name__)

_Driver = Annotated[Driver, Depends(driver_for)]
_UNAVAILABLE = {503: {"model": ErrorResponse}}


@router.post(
    "/{datasource_id}/test",
    response_model=DatasourceTestResult,
    responses=_TARGET | _UNAVAILABLE,
)
def test_connection(
    datasource: _Target, driver: _Driver, db: _Db, _admin: _Admin
) -> DatasourceTestResult:
    """就地测连，并探测账号是否具备写权限（spec §2.4、§4.3 闸 1）。"""
    try:
        result = driver.probe(connection_info(datasource))
    except ConnectionFailed as exc:
        # 地址端口进**服务端日志**，不进 HTTP 响应（spec §4.4）
        logger.warning(
            "数据源 %s 连接失败：%s:%s/%s",
            datasource.id,
            datasource.host,
            datasource.port,
            datasource.database,
        )
        raise ApiError(*CONNECTION_ERROR) from exc

    # 探到可写就把「已验证只读」置 false 并告警，但**不阻止保存**（spec §4.3 闸 1）
    datasource.is_readonly_verified = not result.can_write
    if result.can_write:
        logger.warning("数据源 %s 的账号具备写权限，已标记为未通过只读验证", datasource.id)
    return DatasourceTestResult(
        reachable=result.reachable,
        server_version=result.server_version,
        can_write=result.can_write,
        is_readonly_verified=datasource.is_readonly_verified,
    )
```

**没有 `db.commit()`**：`get_db` 在请求正常结束时提交（P2a Global Constraints）。`ApiError` 那条路径会被 `get_db` 回滚，所以「连不上时不动标记」是免费得到的——但那条测试仍然要有，因为这是**行为承诺**而不是实现细节，将来有人给这个端点加显式 commit 时它会红。

`db` 参数在函数体里没用到（改的是已在会话里的 `datasource` 对象），保留它是让「这个端点会写库」在签名上可见。ruff 默认规则集不查未用参数。

- [ ] **Step 6: 跑测试确认通过**

```bash
cd apps/api
uv run pytest -q && uv run ruff check src tests
```

预期：`187 passed`、`26 skipped`（起点 173 + 本任务 14 条：`test_connection_assembly.py` 5 条 + `test_datasource_test_endpoint.py` 9 条）。**实测不符就停下核对，别往下加。**

- [ ] **Step 7: 反向验证六条（两个方向都要跑）**

1. `datasource.is_readonly_verified = not result.can_write` 改成无条件 `= True` → `test_a_writable_account_clears_the_flag_but_still_returns_200` 必须 FAIL。
2. 同一行改成无条件 `= False` → `test_a_read_only_account_persists_the_verified_flag` 必须 FAIL。第 1、2 条互为对照，**两条都跑**才证明两个分支各有覆盖；只跑一条会漏掉「另一个分支恒不可达」。
3. 删掉整个 `except ConnectionFailed` 块（让异常冒成 500） → `test_connection_failure_maps_to_connection_error` 必须 FAIL。
4. 把 host/port 从 `logger.warning` 挪进错误消息（`ApiError("CONNECTION_ERROR", f"无法连接到 {datasource.host}:{datasource.port}", 503)`） → 同一条测试的泄露扫描必须 FAIL。这条钉的正是「地址端口进日志、不进响应」这条分界线。
5. 路由的 `_admin: _Admin` 参数删掉 → `test_analyst_cannot_test_even_a_granted_datasource` 必须 FAIL。
6. `connection.py` 里 `password=read_password(datasource)` 改成 `password=None` → `test_connection_info_carries_the_decrypted_password` 必须 FAIL，而端点测试**全部仍绿**（假驱动不看密码）。这一对说明端点测试覆盖不到组装层——两个测试文件都必须存在，删掉任一个都会留下一个无人看守的缺口。

- [ ] **Step 8: 提交**

```bash
git add apps/api/src/chatbi apps/api/tests
git commit -m "$(cat <<'EOF'
feat(api): datasource /test endpoint with read-only probing

The driver is injected as an overridable dependency so endpoint tests need no
live database. A writable account clears is_readonly_verified and warns but
still saves; address and port go to the server log, never to the response.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `demo_sales` 示例库与 `seed-demo`

spec §2.5 要求示例库「与应用表**同库不同 schema**」，§0.4 的理由是「保住开箱即跑，不要求用户先接数据源」。同库带来一个必须解决的问题：

**应用库里有 `users`（含 `password_hash`）与 `datasources`（含密文）。把应用账号封成一个数据源，等于给任何被授权该数据源的 analyst 一条 `select * from users` 的路。** 所以示例数据源必须用一个**只能读 `demo_sales`** 的专用角色。这是本任务的红线，Step 3 有测试钉它。

**已实测的前置**：本机 `chatbi` 账号 `rolsuper=false`、`rolcreaterole=false`（只有 `CREATEDB`），**建不了角色**。Step 1 是一次性运维动作，绕不过——换个库来绕会违反 spec §2.5 的「同库」。

**Files:**
- Create: `apps/api/migrations/versions/0003_demo_sales.py`
- Create: `apps/api/tests/test_demo_sales.py`
- Modify: `apps/api/src/chatbi/cli.py`（加 `seed-demo`）
- Modify: `apps/api/tests/test_migrations.py`（断言集合加 demo 表）

**Interfaces:**
- Consumes: `chatbi.auth.provisioning.create_user` 的同款写法 · `chatbi.datasources.repository.create_datasource` · `chatbi.datasources.schemas.DatasourceCreate` · `chatbi.db.base.get_session_factory`
- Produces:
```python
# CLI
uv run python -m chatbi.cli seed-demo [--password <pw>] [--reuse-app-account]
#   建只读角色 → 授权 → 注册名为「示例销售库」的数据源；幂等
chatbi.cli.DEMO_DATASOURCE_NAME = "示例销售库"
chatbi.cli.DEMO_SCHEMA = "demo_sales"
chatbi.cli.DEMO_ROLE = "chatbi_demo_ro"
# migration 0003：demo_sales.customers / products / orders 三张表 + 数据 + 注释
```

- [ ] **Step 1: 一次性运维前置（人工，需要超级用户）**

用超级用户（通常是 `postgres`）执行一次：

```sql
alter role chatbi createrole;
```

验证：

```bash
cd apps/api
uv run python -c "
import psycopg
c = psycopg.connect('postgresql://chatbi:chatbi@localhost:5432/chatbi')
cur = c.cursor()
cur.execute('select rolcreaterole from pg_roles where rolname = current_user')
print('createrole:', cur.fetchone()[0])
"
```

必须打印 `createrole: True` 才往下走。

**拿不到这个权限怎么办**：`seed-demo` 提供 `--reuse-app-account`，用应用账号注册示例数据源并在 stdout 打一条醒目告警。**这不是等价方案**——它把「analyst 能否读到 `password_hash`」从「不能」降级成「只要他被授权示例库就能」。只在本地把玩时用，别在部署里用。Step 3 的红线测试在这个模式下会失败，这是刻意的：那条测试守的是部署形态，不该为了让 `--reuse-app-account` 变绿而放宽它。

- [ ] **Step 2: 写失败的测试**

新建 `apps/api/tests/test_demo_sales.py`：

```python
"""demo_sales 示例库与 seed-demo。

这个文件里最重要的一条是 test_the_demo_role_cannot_read_application_tables——
它守的是「同库示例数据源不会把 password_hash 暴露给被授权的 analyst」。
"""

import os

import psycopg
import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from chatbi.cli import DEMO_DATASOURCE_NAME, DEMO_ROLE, DEMO_SCHEMA, app

runner = CliRunner()


def _demo_dsn(password: str) -> str:
    """用 demo 只读角色连**同一个库**。"""
    url = os.environ["CHATBI_DATABASE_URL"]
    tail = url.split("@", 1)[1]
    return f"postgresql://{DEMO_ROLE}:{password}@{tail.replace('+psycopg', '')}"


def test_the_demo_schema_has_the_three_tables(db_session) -> None:
    rows = db_session.execute(
        text(
            "select table_name from information_schema.tables "
            "where table_schema = :schema order by table_name"
        ),
        {"schema": DEMO_SCHEMA},
    ).scalars()

    assert list(rows) == ["customers", "orders", "products"]


def test_the_demo_orders_have_enough_rows_to_chart(db_session) -> None:
    """至少几十行、跨多个月份——只有 3 行的示例库画不出有意义的趋势图，
    而「开箱即跑」的第一印象就是那张图（spec §0.4）。
    """
    count = db_session.execute(text(f"select count(*) from {DEMO_SCHEMA}.orders")).scalar()
    months = db_session.execute(
        text(f"select count(distinct date_trunc('month', ordered_at)) from {DEMO_SCHEMA}.orders")
    ).scalar()

    assert count >= 50
    assert months >= 3


def test_the_demo_tables_carry_comments(db_session) -> None:
    """注释进 LLM prompt（spec §4.5），没有注释的示例库生成质量会差一档。"""
    missing = db_session.execute(
        text(
            "select c.table_name || '.' || c.column_name "
            "from information_schema.columns c "
            "where c.table_schema = :schema "
            "  and col_description("
            "        format('%I.%I', c.table_schema, c.table_name)::regclass::oid,"
            "        c.ordinal_position) is null"
        ),
        {"schema": DEMO_SCHEMA},
    ).scalars()

    assert list(missing) == []
```

同一个文件继续（`seed-demo` 与那条红线）：

```python
def test_seed_demo_registers_the_datasource(db_session) -> None:
    from chatbi.datasources.repository import list_visible
    from chatbi.db.models import User

    result = runner.invoke(app, ["seed-demo", "--password", "demo-pw-12345678"])

    assert result.exit_code == 0, result.output
    admin = db_session.query(User).filter(User.role == "admin").first()
    names = {d.name for d in list_visible(db_session, admin)} if admin else set()
    assert DEMO_DATASOURCE_NAME in names


def test_seed_demo_is_idempotent(db_session) -> None:
    """跑第二次不能报错、也不能出现第二个同名数据源。

    「开箱即跑」的脚本一定会被重复执行（换机器、重装、写进 Makefile），
    第二次炸掉等于把一次误操作变成一个必须手工清理的库。
    """
    first = runner.invoke(app, ["seed-demo", "--password", "demo-pw-12345678"])
    second = runner.invoke(app, ["seed-demo", "--password", "demo-pw-12345678"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output


def test_the_registered_datasource_stores_an_encrypted_password(db_session) -> None:
    from sqlalchemy import select

    from chatbi.datasources.repository import read_password
    from chatbi.db.models import Datasource

    runner.invoke(app, ["seed-demo", "--password", "demo-pw-12345678"])

    datasource = db_session.scalar(
        select(Datasource).where(Datasource.name == DEMO_DATASOURCE_NAME)
    )
    assert datasource is not None
    assert datasource.secret_ciphertext is not None
    assert b"demo-pw-12345678" not in datasource.secret_ciphertext
    assert read_password(datasource) == "demo-pw-12345678"


def test_the_demo_role_can_read_demo_sales() -> None:
    runner.invoke(app, ["seed-demo", "--password", "demo-pw-12345678"])

    with psycopg.connect(_demo_dsn("demo-pw-12345678")) as conn, conn.cursor() as cur:
        cur.execute(f"select count(*) from {DEMO_SCHEMA}.orders")
        assert cur.fetchone()[0] >= 50


def test_the_demo_role_cannot_read_application_tables() -> None:
    """本任务的红线。

    示例库与应用表同库（spec §2.5），所以「示例数据源的账号读不到 users」不是
    自动成立的——它完全依赖 seed-demo 建的那个只读角色。这条测试失败意味着：
    任何被授权示例数据源的 analyst 都能拿到全部 password_hash 与数据源密文。

    用 --reuse-app-account 模式跑时这条**必然失败**，那是刻意的：它守的是部署
    形态，不该为了让逃生开关变绿而放宽。
    """
    runner.invoke(app, ["seed-demo", "--password", "demo-pw-12345678"])

    with psycopg.connect(_demo_dsn("demo-pw-12345678")) as conn, conn.cursor() as cur:
        for table in ("users", "sessions", "datasources", "datasource_grants"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(f"select * from public.{table} limit 1")
            conn.rollback()  # 权限错误会让事务不可用，下一张表要新事务
```

**`conn.rollback()` 那一行是必需的**：Postgres 在权限错误后会把事务标成 aborted，不回滚的话第二张表的查询会以 `InFailedSqlTransaction` 失败——那也是 `psycopg.Error` 的子类，`pytest.raises` 会照样通过，于是**后三张表实际上没被测到**。这正是「测试看起来绿但只测了第一项」的典型形状。

- [ ] **Step 3: 跑测试确认失败**

```bash
cd apps/api
uv run pytest tests/test_demo_sales.py -v
```

预期：全部失败——前三条因为 `demo_sales` schema 不存在，后五条因为 `chatbi.cli` 里没有 `seed-demo` 与那三个常量（收集期 `ImportError`）。

- [ ] **Step 4: 写 migration 0003**

新建 `apps/api/migrations/versions/0003_demo_sales.py`。**不 import 任何 `chatbi.*` 业务模块**——它跑起来不需要主密钥：

```python
"""demo_sales example schema

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_TABLES = """
create schema if not exists demo_sales;

create table demo_sales.customers (
    id integer primary key,
    name text not null,
    city text not null,
    segment text not null
);
comment on table demo_sales.customers is '客户';
comment on column demo_sales.customers.id is '客户 ID';
comment on column demo_sales.customers.name is '客户名称';
comment on column demo_sales.customers.city is '所在城市';
comment on column demo_sales.customers.segment is '客户分层：企业 / 中小 / 个人';

create table demo_sales.products (
    id integer primary key,
    name text not null,
    category text not null,
    unit_price numeric(12, 2) not null
);
comment on table demo_sales.products is '商品';
comment on column demo_sales.products.id is '商品 ID';
comment on column demo_sales.products.name is '商品名称';
comment on column demo_sales.products.category is '商品类目';
comment on column demo_sales.products.unit_price is '单价（元）';

create table demo_sales.orders (
    id integer primary key,
    customer_id integer not null references demo_sales.customers(id),
    product_id integer not null references demo_sales.products(id),
    quantity integer not null,
    amount numeric(12, 2) not null,
    ordered_at timestamptz not null
);
comment on table demo_sales.orders is '订单';
comment on column demo_sales.orders.id is '订单 ID';
comment on column demo_sales.orders.customer_id is '客户 ID';
comment on column demo_sales.orders.product_id is '商品 ID';
comment on column demo_sales.orders.quantity is '数量';
comment on column demo_sales.orders.amount is '订单金额（元）= 数量 × 单价';
comment on column demo_sales.orders.ordered_at is '下单时间';
"""

# 用 generate_series 造数而不是写几百行 INSERT：migration 文件要能被读完。
# 金额与数量用确定性表达式，不用 random()——随机数会让「示例库的截图和文档
# 对不上」，也会让基于示例库的测试无法断言具体数值。
_SEED = """
insert into demo_sales.customers (id, name, city, segment)
select i,
       '客户' || i,
       (array['北京', '上海', '广州', '深圳', '成都'])[1 + (i % 5)],
       (array['企业', '中小', '个人'])[1 + (i % 3)]
from generate_series(1, 20) as i;

insert into demo_sales.products (id, name, category, unit_price)
select i,
       '商品' || i,
       (array['硬件', '软件', '服务'])[1 + (i % 3)],
       (100 + i * 37 % 900)::numeric(12, 2)
from generate_series(1, 12) as i;

insert into demo_sales.orders (id, customer_id, product_id, quantity, amount, ordered_at)
select i,
       1 + (i % 20),
       1 + (i % 12),
       1 + (i % 5),
       ((1 + (i % 5)) * (100 + (1 + (i % 12)) * 37 % 900))::numeric(12, 2),
       timestamptz '2026-01-01 09:00:00+08' + (i * interval '7 hours')
from generate_series(1, 240) as i;
"""


def upgrade() -> None:
    op.execute(_TABLES)
    op.execute(_SEED)


def downgrade() -> None:
    # 角色不在这里删——它是 seed-demo 建的，而且是集群级对象，
    # 一个库的 downgrade 去删集群级角色会影响同集群的其他库。
    op.execute("drop schema if exists demo_sales cascade")
```

240 行订单跨约 70 天（`i * 7 hours`），满足测试要求的「≥50 行、≥3 个月份」吗？——**70 天只跨 3 个月份边界，刚好够但没余量**。实施时如果 `months >= 3` 断言失败，把步长改成 `i * interval '12 hours'`（跨约 120 天）而不是去改断言。

- [ ] **Step 5: 写 `seed-demo`**

`apps/api/src/chatbi/cli.py` 追加。三个常量放模块级（测试要 import）：

```python
DEMO_DATASOURCE_NAME = "示例销售库"
DEMO_SCHEMA = "demo_sales"
DEMO_ROLE = "chatbi_demo_ro"
```

```python
@app.command()
def seed_demo(
    password: str = typer.Option(..., help=f"{DEMO_ROLE} 只读角色的密码"),
    reuse_app_account: bool = typer.Option(
        False,
        "--reuse-app-account",
        help="拿不到 CREATEROLE 时的逃生开关：用应用账号注册示例数据源（不安全）",
    ),
) -> None:
    """把 demo_sales 注册成一个数据源。幂等，可重复执行。

    前置：migration 0003 已 upgrade（表与数据由它建），且库里已有至少一个 admin。
    """
    import psycopg
    from psycopg import sql as pgsql
    from sqlalchemy import select

    from chatbi.datasources.repository import create_datasource, update_datasource
    from chatbi.datasources.schemas import DatasourceCreate, DatasourceUpdate
    from chatbi.db.base import get_session_factory
    from chatbi.db.models import Datasource, User

    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    parsed = urlparse(dsn)
    host, port, database = parsed.hostname, parsed.port or 5432, parsed.path.lstrip("/")

    if reuse_app_account:
        typer.echo(
            "警告：--reuse-app-account 用应用账号注册示例数据源。任何被授权该数据源的"
            "用户都能读到 users.password_hash 与数据源密文。仅供本地把玩，不要用于部署。"
        )
        username, secret = parsed.username, unquote(parsed.password or "")
    else:
        with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("select rolcreaterole from pg_roles where rolname = current_user")
            row = cur.fetchone()
            if not (row and row[0]):
                typer.echo(
                    f"当前账号没有 CREATEROLE，建不了 {DEMO_ROLE}。请用超级用户执行一次 "
                    "`alter role <应用账号> createrole;`，或用 --reuse-app-account（不安全）。"
                )
                raise typer.Exit(code=1)

            cur.execute("select 1 from pg_roles where rolname = %s", (DEMO_ROLE,))
            action = "alter" if cur.fetchone() else "create"
            # DDL 不接受绑定参数，密码只能作为**字面量**拼进语句。用 psycopg.sql.Literal
            # 转义，别用 f-string——密码里一个单引号就能改写这条 DDL。
            cur.execute(
                pgsql.SQL("{} role {} login password {}").format(
                    pgsql.SQL(action), pgsql.Identifier(DEMO_ROLE), pgsql.Literal(password)
                )
            )
            # 只授 demo_sales。应用表不需要显式 revoke——表级权限默认不授予 PUBLIC，
            # 所以新角色本来就读不到 users；我们要做的是**不要多授**。
            for statement, target in (
                ("grant connect on database {} to {}", database),
                ("grant usage on schema {} to {}", DEMO_SCHEMA),
                ("grant select on all tables in schema {} to {}", DEMO_SCHEMA),
                # 将来往 demo_sales 加表时不用重跑授权
                ("alter default privileges in schema {} grant select on tables to {}", DEMO_SCHEMA),
            ):
                cur.execute(
                    pgsql.SQL(statement).format(
                        pgsql.Identifier(target), pgsql.Identifier(DEMO_ROLE)
                    )
                )
        username, secret = DEMO_ROLE, password

    session = get_session_factory()()
    try:
        admin = session.scalar(select(User).where(User.role == "admin"))
        if admin is None:
            typer.echo(
                "库里没有 admin，先跑 `create-user <email> <名字> --role admin --password ...`"
            )
            raise typer.Exit(code=1)

        existing = session.scalar(
            select(Datasource).where(Datasource.name == DEMO_DATASOURCE_NAME)
        )
        if existing is None:
            create_datasource(
                session,
                payload=DatasourceCreate(
                    name=DEMO_DATASOURCE_NAME,
                    kind="postgres",
                    host=host,
                    port=port,
                    database=database,
                    username=username,
                    password=secret,
                ),
                created_by=admin.id,
            )
            typer.echo(f"已注册数据源「{DEMO_DATASOURCE_NAME}」")
        else:
            # 幂等：第二次跑把凭据同步过去（角色密码可能刚被重置）
            update_datasource(
                session, existing, DatasourceUpdate(username=username, password=secret)
            )
            typer.echo(f"数据源「{DEMO_DATASOURCE_NAME}」已存在，已同步凭据")
        session.commit()
    finally:
        session.close()
```

`urlparse` 与 `unquote` 要在 `cli.py` 顶部 import。`--password` 是**必填而不是自动生成**：生成的密码得打印出来才能用，而打印到终端的密码会进 shell history 与 CI 日志；让操作者自己给，责任边界清楚。

- [ ] **Step 6: 把 demo 表加进 migration 双向断言**

`get_table_names()` 默认只看默认 schema，所以 demo 表要单独断言。`apps/api/tests/test_migrations.py` 改成：

```python
DEMO_TABLES = {"customers", "orders", "products"}


def _table_names(schema: str | None = None) -> set[str]:
    engine = create_engine(os.environ["CHATBI_DATABASE_URL"])
    try:
        return set(inspect(engine).get_table_names(schema=schema))
    finally:
        engine.dispose()
```

三个断言处各加一行：

```python
    assert TABLES <= _table_names()
    assert DEMO_TABLES <= _table_names("demo_sales")

    _alembic("downgrade", "base")
    assert not TABLES & _table_names()
    assert not DEMO_TABLES & _table_names("demo_sales")

    _alembic("upgrade", "head")
    assert TABLES <= _table_names()
    assert DEMO_TABLES <= _table_names("demo_sales")
```

`downgrade base` 之后 `demo_sales` 整个不存在，`get_table_names("demo_sales")` 应返回空集而不是报错。**实施时确认这一点**——若当前 SQLAlchemy 版本对不存在的 schema 抛异常，改成先查 `information_schema.schemata`，别把断言删掉。

- [ ] **Step 7: 跑全量确认通过**

```bash
cd apps/api
uv run pytest -q && uv run ruff check src tests
```

预期：`195 passed`、`26 skipped`（Task 5 后的 187 + 本任务 8 条）。

**`test_the_demo_role_cannot_read_application_tables` 必须是 passed 而不是 error。** 它 error 通常意味着 Step 1 的 `CREATEROLE` 没给——那时 `seed-demo` 以退出码 1 失败，红线测试拿不到能连的角色。**别把它改成 skip**：它守的是 `password_hash` 不外泄。

- [ ] **Step 8: 反向验证五条（两个方向都要跑）**

1. 删掉 `grant select on all tables in schema demo_sales` 那一项 → `test_the_demo_role_can_read_demo_sales` 必须 FAIL。
2. 在授权循环里追加一项 `grant select on all tables in schema public to {}` → **`test_the_demo_role_cannot_read_application_tables` 必须 FAIL**。这条证明红线测试真的在守 `users`，而不是靠「反正没授权」碰巧成立。
3. 红线测试里的 `conn.rollback()` 删掉 → 该测试**仍然通过**，但只有第一张表真被测到（后三张以 `InFailedSqlTransaction` 满足 `pytest.raises`）。**这条没法用「必须 FAIL」验证**，改用观察：把循环里第一张表临时换成 `datasources`，若删掉 rollback 后仍绿，就证明了后续表没被覆盖。这是本任务唯一一条靠观察而非「必须红」确认的验证。
4. `existing is None` 分支改成无条件 `create_datasource` → `test_seed_demo_is_idempotent` 必须 FAIL（第二次撞唯一名 409）。
5. migration 里删掉几条 `comment on column` → `test_the_demo_tables_carry_comments` 必须 FAIL，并在失败信息里列出缺注释的列名。

- [ ] **Step 9: 提交**

```bash
git add apps/api/src/chatbi apps/api/migrations apps/api/tests
git commit -m "$(cat <<'EOF'
feat(demo): demo_sales example schema and the seed-demo command

The migration only builds the schema and data, so alembic upgrade never needs
the master key. seed-demo creates a read-only role scoped to demo_sales and
registers the datasource with it: the example library shares a database with
users.password_hash, so reusing the application account would hand every
granted analyst a path to it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 真库门禁——三库契约测 skip 数为 0

这是 P2b 的退出标准，也是 v1 的历史欠账（spec §5.1、§8.1）：**「代码写完了」不能代替「真库跑过了」**。上游那份因无 Docker 而推迟的反向验证在这里补做。

**Files:**
- Create: `docker/compose.test.yml`
- Modify: 视核实结果可能要改 `drivers/clickhouse.py` 的 `_CAN_WRITE_SQL`（上游 Task 4 Step 4 已预告）

- [ ] **Step 1: 装 WSL2（人工，需要管理员 + 重启）**

本机 `wsl -l -v` 无任何发行版，`docker version` 连不上 npipe。无法自动化，也无法绕过——ClickHouse 没有官方支持的原生 Windows 版。

```powershell
# 管理员 PowerShell
wsl --install
# 重启，然后首次启动发行版并接受许可，再启动 Docker Desktop
```

验证（三条都要过）：

```bash
wsl -l -v                 # 至少一个发行版，State = Running
docker version            # Server 段有版本号
docker compose version
```

- [ ] **Step 2: 写 `docker/compose.test.yml`**

```yaml
# 契约测专用的三个库。端口刻意与本机原生 Postgres(5432) 及 compose.yml(5433) 错开，
# 三者可以同时跑——门禁那天不需要先停掉开发库。
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: chatbi
      POSTGRES_PASSWORD: chatbi
      POSTGRES_DB: chatbi_test
    ports: ["5434:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U chatbi -d chatbi_test"]
      interval: 3s
      retries: 20

  mysql:
    image: mysql:8.4
    environment:
      MYSQL_ROOT_PASSWORD: chatbi
      MYSQL_DATABASE: chatbi_test
    ports: ["3307:3306"]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-pchatbi"]
      interval: 3s
      retries: 30

  clickhouse:
    image: clickhouse/clickhouse-server:24.8
    environment:
      CLICKHOUSE_DB: chatbi_test
      CLICKHOUSE_USER: chatbi
      CLICKHOUSE_PASSWORD: chatbi
      # 不给这个的话 chatbi 用户没有建表权限，契约测的 seeded_table 夹具会 403
      CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: 1
    ports: ["8124:8123"]
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://127.0.0.1:8123/ping"]
      interval: 3s
      retries: 30
```

MySQL 用 8.4 而不是 5.7：契约套件的 `rows_sql` 用了递归 CTE（8.0+），而 `max_execution_time` 需要 5.7.8+。ClickHouse 固定小版本而不是 `latest`——门禁的意义在可复现。

- [ ] **Step 3: 起库并确认三个都能连**

```bash
cd docker
docker compose -f compose.test.yml up -d
docker compose -f compose.test.yml ps        # 三个都要 healthy，别只看 running
```

- [ ] **Step 4: 跑契约测，skip 必须为 0**

```bash
cd ../apps/api
export CHATBI_TEST_PG_DSN=postgresql://chatbi:chatbi@localhost:5434/chatbi_test
export CHATBI_TEST_MYSQL_DSN=mysql://root:chatbi@localhost:3307/chatbi_test
export CHATBI_TEST_CLICKHOUSE_DSN=clickhouse://chatbi:chatbi@localhost:8124/chatbi_test
uv run pytest tests/drivers -v
```

预期：**39 passed、0 skipped**（13 条 × 3 个 kind），末尾那行是 `skip 合计 0，其中驱动契约测 0`。

**这一步大概率不会一次通过**，预期要处理的几类问题：

- **ClickHouse 的 `can_write`**：上游 Task 4 Step 4 已预告它很可能返回 0。先手工核实再改代码：

```bash
curl "http://localhost:8124/?user=chatbi&password=chatbi" --data-binary "select currentUser()"
curl "http://localhost:8124/?user=chatbi&password=chatbi" --data-binary \
  "select * from system.grants where user_name = currentUser() format Vertical"
curl "http://localhost:8124/?user=chatbi&password=chatbi" --data-binary "show grants"
```

若 `system.grants` 对该用户为空而它实际可写，按上游 Task 4 Step 4 给的两条备选改：用 `show grants` 的文本判断，或恒置 `True` 并在注释里写明「宁可误报可写，不能误报已验证只读」。**改完要把结论回填进上游那份的 Task 4**，别只改代码。
- **MySQL 的 `_CAN_WRITE_SQL`**：上游 Task 3 Step 3 提示过 `grantee` 的引号形式（`'root'@'%'` vs `root@%`）。先单独跑那条 SQL 确认它返回 1。
- **ClickHouse 的 `result.column_types`**：上游 Task 4 提示过元素可能不是字符串，`_is_numeric` 收的是 `str`。
- **`sleepEachRow` 的超时**：若 `test_execute_raises_query_timeout` 在 ClickHouse 上不红，检查 `max_execution_time` 是否真作为 setting 传进去了（clickhouse-connect 的 `settings=` 在 `get_client` 与 `query` 两处都能传，语义不同）。

每修一处都要**重跑该 kind 的全部 13 条**，而不是只跑刚修的那条——驱动内部共用 `_client`/`_connect`，改一处常常影响别的。

- [ ] **Step 5: 补做 MySQL 的三条反向验证（对真库）**

上游 Task 3 Step 5 因无真库而推迟的三条，现在必须做。每条改完跑 `-k mysql` 的 13 条：

1. **errno 分支对调**（3024 抛 `QueryCancelled`、1317 抛 `QueryTimeout`）→ `test_execute_raises_query_timeout` 与 `test_cancel_stops_a_running_query` 必须**双双** FAIL。只有一条红说明另一条路径没走到。
2. **删掉 `set session max_execution_time`** → `test_execute_raises_query_timeout` 必须 FAIL（`sleep(30)` 会跑完，等约 30s）。
3. **`cancel()` 方法体换成 `pass`** → `test_cancel_stops_a_running_query` 必须 FAIL（worker 仍活着）。

- [ ] **Step 6: 补做 ClickHouse 的三条反向验证（对真库）**

1. **`_CAN_WRITE_SQL` 换成恒 `select 0`** → `test_probe_detects_a_writable_account` 必须 FAIL。**若它本来就是 FAIL 状态，先按 Step 4 修好再做这条**——在一条已经红的测试上做反向验证什么也证明不了。
2. **错误码分支对调**（159 抛 `QueryCancelled`、394 抛 `QueryTimeout`）→ 超时与取消两条必须双双 FAIL。
3. **`cancel()` 换成 `pass`** → `test_cancel_stops_a_running_query` 必须 FAIL。注意 ClickHouse 的 `KILL QUERY` 是**异步**的（只标记，不等查询停），所以这条测试依赖 `worker.join(timeout=20)` 的余量；若它在未打补丁时就不稳定（偶尔超时），把 join 的余量调大并在上游那份记一条，别把断言放宽成「不检查 outcome」。

- [ ] **Step 7: 全量 + 记录门禁结果**

```bash
cd apps/api
uv run pytest -q && uv run ruff check src tests
```

预期：**`221 passed`、`0 skipped`**（Task 6 后的 195 passed + 26 条原本 skip 的契约测）。末尾必须是 `skip 合计 0，其中驱动契约测 0`。

把三个库的实际版本记进上游那份的「实施期的偏差」一节（`select version()` / `select version()` / `select version()` 三条的输出），P2c 与 P3 排查行为差异时要用。

- [ ] **Step 8: 收尾与提交**

```bash
cd ../docker
docker compose -f compose.test.yml down -v   # -v 一并删卷，下次门禁从干净状态起
cd ../apps/api
```

```bash
cd /c/project/Chat-BI
git add docker apps/api/src/chatbi apps/api/tests docs/superpowers/plans
git commit -m "$(cat <<'EOF'
test(drivers): gate P2b on all three engines with zero skips

compose.test.yml brings up Postgres, MySQL and ClickHouse on ports that do not
clash with the dev instances. The deferred reverse verifications for MySQL and
ClickHouse are done against live servers, and the ClickHouse can_write probe is
settled against a real grants table rather than guessed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

**门禁不过就不要提交这一条。** 「skip 数为 0」是 spec §8.1 的验收项，一条绿色的提交信息配一份还在 skip 的测试套件，比留着 skip 更糟——下一个人会以为这里已经验过了。

---

## 交接清单（P2c 与 P3 要消费的签名）

```python
# 本份新增
chatbi.datasources.connection.connection_info(datasource) -> ConnectionInfo
#   模型 + read_password → 驱动的输入。P3 的执行器直接用它，别自己拼
chatbi.datasources.deps.driver_for(datasource) -> Driver
#   FastAPI 依赖，可被 dependency_overrides 替换。P2c 的 /schema 与 P3 的执行端点复用它
chatbi.datasources.schemas.DatasourceTestResult
POST /api/datasources/{datasource_id}/test -> 200 | 401 | 403 | 404 | 503

# 示例库
chatbi.cli.DEMO_DATASOURCE_NAME = "示例销售库" · DEMO_SCHEMA = "demo_sales" · DEMO_ROLE = "chatbi_demo_ro"
# demo_sales.customers(20 行) / products(12 行) / orders(240 行，跨约 70 天)
# 全部列都有中文注释——LLM prompt 要用（spec §4.5）

# 上游那份的签名（Driver 协议、值对象、registry）见
# 2026-08-18-chatbi-v2-1-p2b-drivers.md 的交接清单
```

**P2c F-201 元数据接入**
- `/schema` 端点复用 `driver_for` 与 `connection_info`，调 `reflect()`。**不要**再写一条组装路径。
- `schema_cache.payload` 存 `SchemaSnapshot` 的 JSON。它是 frozen dataclass，`dataclasses.asdict()` 可用。
- 示例库的列注释已经在 `ColumnSchema.comment` 里（`reflect()` 会带出来），所以 P2c 的「人工补注释」在示例库上一开始就有对照：库里的原生注释 vs `column_notes` 里人工补的，合并策略要能演示这两者的区别。
- `demo_sales` 是 P2c 唯一不需要 Docker 就能验的数据源——它在应用库里。

**P3 执行器**
- 用 `connection_info(datasource)` + `driver_for` 拿到输入与驱动，然后 `asyncio.to_thread` 包 `execute()`。
- `on_start` 拿到的 `QueryHandle` 要存进 run 的上下文，客户端断开时调 `driver.cancel(info, handle)`。
- `QUERY_TIMEOUT` / `QUERY_CANCELLED` 两个错误码由 P3 新增（本段只有 `CONNECTION_ERROR`）。
- `/test` 是 `probe()` 的唯一调用方，`execute()` 在 P2b 结束时**没有生产调用方**——只有契约测。这与 P2a 的 `read_password` 同形，是有意的：它的消费方是 P3。别当成新发现的死代码。

**运维前置（写进部署文档）**
- 应用账号需要一次性的 `CREATEROLE`（`alter role <应用账号> createrole;`）才能跑 `seed-demo`。拿不到就只能用 `--reuse-app-account`，而那会让被授权示例库的用户读到 `users.password_hash`——**这不是可接受的部署形态**。
- `seed-demo` 的 `--password` 必填，不自动生成。

---

## 自查记录

**spec 覆盖核对**

| spec 条目 | 落在哪 |
|---|---|
| §2.4 `POST /api/datasources/{id}/test`「就地测连，并探测账号是否具备写权限」 | Task 5 |
| §4.3 闸 1「探到就告警并把 `is_readonly_verified` 置 false，不阻止保存」 | Task 5 Step 5 + 反向验证第 1、2 条 |
| §4.4 `CONNECTION_ERROR` 通用文案、地址端口进日志不进响应 | Task 5 Step 5 的 `logger.warning` + 反向验证第 4 条 |
| §4.4 响应模型不声明凭据字段 | `DatasourceTestResult` 只有四个布尔/字符串字段 + `test_the_response_carries_no_credentials` |
| §2.5「`demo_sales` 与应用表同库不同 schema，由独立 migration 建表灌数」 | Task 6 的 migration 0003 |
| §2.5「并自动注册成一个名为『示例销售库』的数据源」 | Task 6 的 `seed-demo`。**偏离**：不是 migration 自动注册，见下 |
| §4.5「prompt 里放 schema 元数据与注释」 | Task 6 的全列中文注释 + `test_the_demo_tables_carry_comments` |
| §5.1「三驱动跑同一套契约用例」「skip 允许但必须计数」 | 上游那份；本份 Task 7 把 skip 清零 |
| §5.3 Alembic up/down 双向 | Task 6 Step 6（demo 表单独断言，因为不在默认 schema） |
| §8.1「三类驱动对真库跑通契约测，skip 数为 0」 | Task 7 —— 本段的退出标准 |

**一处对 spec 的有意偏离**：§2.5 说示例库「由一个独立 migration 建表灌数，并**自动注册**成一个数据源」。本段把注册拆到 CLI，migration 只建表灌数。理由是注册必须 seal 密码而 seal 需要主密钥，让 `alembic upgrade` 依赖 `CHATBI_SECRET_KEY` 会把「跑迁移」和「持有主密钥」永久绑死（CI 只想验 schema 时也得配密钥）。「开箱即跑」的承诺仍然成立，只是多一条命令。**这条要同步进 spec §2.5 的措辞。**

**占位符扫描**：无 TBD / TODO / 「类似 Task N」/ 无代码的「写测试」步骤。Task 7 Step 4 的「大概率不会一次通过」列的是**具体的四类问题 + 各自的诊断命令**，不是「遇到问题再说」。

**写作过程中的回改**

1. **两条只做否定断言的测试补了状态码下限**（`test_the_response_carries_no_credentials` 的 200、`test_a_failed_probe_does_not_touch_the_verified_flag` 的 503）。初稿只写了「注意它们会提前变绿」的警告——但警告不是防御。P2a Task 5、6 各因此出现过空洞通过的测试，这次直接把下限写进代码。
2. **`CREATEROLE` 前置是实测出来的，不是猜的**。写 Task 6 时查了本机：`chatbi` 的 `rolsuper=false`、`rolcreaterole=false`、`rolcreatedb=true`。因为有 `CREATEDB`，一度想改用「示例库单独一个数据库」来绕开建角色——但 spec §2.5 明写「同库不同 schema」，绕开等于改 spec。最终保留同库 + 只读角色，把权限缺口作为一次性运维前置写明，并给了 `--reuse-app-account` 逃生开关 + 明确的「这不是等价方案」。
3. **红线测试里的 `conn.rollback()` 是写完才补的**。第一版循环四张表逐个 `pytest.raises`，但 Postgres 在权限错误后事务变 aborted，后三张会以 `InFailedSqlTransaction` 满足 `pytest.raises`——**测试全绿但只测了第一张表**。这个形状值得记住：`pytest.raises(基类)` + 循环 = 后续迭代可能被另一种异常满足。
4. **Task 5 的测试条数从 12 改成 14**。初稿在 Interfaces 里估了 12，写完数出来是 5 + 9。计划里两处都改了，并在 Step 6 写明「实测不符就停下核对」。

**已知的松散端与取舍**

- **`--reuse-app-account` 会让红线测试失败，这是刻意的**。逃生开关不该反过来削弱守卫。用它的人得接受一条红。
- **示例数据源的凭据是明文给的**（`--password` 必填）。自动生成要打印出来才能用，而那会进 shell history 与 CI 日志。
- **`demo_sales` 的 240 行订单只跨约 70 天**，刚好满足「≥3 个月份」但没余量。Task 6 Step 4 写了失败时的正确反应（改步长而不是改断言）。
- **migration 0003 的 downgrade 不删 `chatbi_demo_ro` 角色**：角色是集群级对象，一个库的 downgrade 去删它会影响同集群其他库。代价是 `downgrade base` 后角色残留，`seed-demo` 会 `alter` 它而不是 `create`——幂等路径已覆盖。
- **`/test` 的 `db` 参数没被函数体使用**，保留它是让「这个端点会写库」在签名上可见。ruff 默认规则不查未用参数；若将来开了 `ARG`，加 `# noqa: ARG001` 而不是删参数。
- **Task 7 依赖一次人工操作**（装 WSL2 + 重启）。这是本段唯一无法自动化的一步，且它在**最后**——前六个任务全部可以在没有 Docker 的机器上完成，这是排期上的有意安排。
- **ClickHouse 的 `can_write` 到门禁那天才能定**。上游那份已给初版实现、诊断命令与两条备选方案，并写明了取舍方向（宁可误报可写）。这是全套计划里唯一一处「实现待真库定稿」的地方。

**类型一致性核对**

`connection_info()` 的返回值字段与上游 `ConnectionInfo` 的构造参数逐一对应；`ProbeResult` 的三个字段（`reachable` / `server_version` / `can_write`）与 `DatasourceTestResult` 的前三个同名同序，第四个 `is_readonly_verified` 来自模型而非探测结果——这处不对称是有意的，响应要同时告诉前端「探到什么」和「库里现在记的是什么」。`driver_for` 的返回类型 `Driver` 与 `_Driver` 注解别名、假驱动 `_FakeDriver`（只实现 `probe`）三处一致；假驱动缺其余三个方法是**故意**的，端点若调了它不该调的方法会以 `AttributeError` 暴露。`DEMO_DATASOURCE_NAME` / `DEMO_SCHEMA` / `DEMO_ROLE` 三个常量在 `cli.py` 定义、`test_demo_sales.py` import，无字面量重复。`seed-demo` 传给 `DatasourceCreate` 的字段名与 P2a 的模型一致（`name`/`kind`/`host`/`port`/`database`/`username`/`password`）。

无「Task N 定义、Task M 改名」的情况。跨文件引用（上游的 `Driver` 协议、`ConnectionFailed`、`registry.get_driver`、P2a 的 `_Target`/`_Admin`/`_TARGET`）在上游两份的交接清单里均已列明。
