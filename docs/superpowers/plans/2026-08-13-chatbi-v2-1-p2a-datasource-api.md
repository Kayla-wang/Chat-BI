# Chat-BI V2-1 · P2a HTTP 层：数据源与用户端点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P2a 领域层的仓储接到 HTTP 上：`/api/datasources` 的 CRUD 与 grants、`/api/users` 的 admin 开号与列表，并清掉 P1 遗留的最后两项（3、5）。

**Architecture:** 这一段只写编排。`deps.py` 是唯一同时认识 FastAPI 与 repository 的文件，负责「按 id 取 + 判定 + 抛 `ApiError`」；两个 router 只做「校验角色 → 调仓储 → 返回 Pydantic 模型」，里面**不出现 `select()`、不出现可见性判断、不出现 `seal`/`unseal`**。任何需要判断的地方，正确反应是回 [领域层那份](2026-08-13-chatbi-v2-1-p2a-datasource-persistence.md) 加仓储函数。

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · pytest

**上游 spec:** [2026-08-11-chatbi-v2-1-design.md](../specs/2026-08-11-chatbi-v2-1-design.md)（§2.4 REST 端点、§2.6 错误码、§4.2 授权分层、§4.4 凭据与日志脱敏）
**上游计划:** [P2a 数据源持久化与凭据](2026-08-13-chatbi-v2-1-p2a-datasource-persistence.md)（Task 1–4；末尾「交接清单」= 本份消费的签名）
**下游计划:** P2b 三驱动与示例库（`2026-08-13-chatbi-v2-1-p2b-drivers-demo.md`），消费本份末尾「交接清单」。

**任务编号延续上游那份**：本份是 Task 5 与 Task 6，跨文件说「Task 3 的表」「Task 4 的仓储」不会歧义。

## Global Constraints

每个任务的要求都隐含包含本节。领域层那份的 Global Constraints 依然全部有效（版本与依赖、数据库、TDD 与双向验证、提交信息格式、分支 `feature_v2.0`），下面只列本段特有或需要重述的。

**不新增依赖。** 本段一个新包都不装：`cryptography` 已在上游装好，驱动依赖属 P2b。

**授权（spec §4.2，本段的红线）**
- 数据源的**写操作（建/改/删/授权）只有 `admin`**。`analyst` 对一个自己有 `can_query` 授权的数据源做 PATCH，照样 403。
- 数据源的**可见性**：`admin` 看全部；`analyst` / `viewer` 只看 `datasource_grants` 里 `can_query = true` 的。判定在仓储的 `_visible_where` 里，本段不重新实现。
- `/api/users` 的全部端点只有 `admin`。
- `viewer` 与 `analyst` 在本段的差别只有一处：没有。两者对数据源都是只读可见，区别在 P3 的执行权限上（spec §4.2）。别在本段提前引入差别。

**错误码**（响应体统一 `{"code": ..., "message": ...}`）
- 复用：`NOT_AUTHENTICATED`(401) · `PERMISSION_DENIED`(403) · `USER_NOT_FOUND`(404) · `EMAIL_ALREADY_EXISTS`(409)
- 上游 Task 3 已加：`DATASOURCE_NOT_FOUND`(404) · `DATASOURCE_NAME_EXISTS`(409)
- 本段**不新增**任何错误码。`USER_NOT_FOUND` 在这一段终于有调用方（P1 遗留 5）。
- `CONNECTION_ERROR` 属 P2b。

**404 与 403 的分界（照上游 Global Constraints，不重新讨论）**
- 未知 id → `DATASOURCE_NOT_FOUND`。
- 存在但无 `can_query` 授权 → `PERMISSION_DENIED`。
- 这确实让已认证用户能区分「某个 UUID 存不存在」。取舍与代价写在上游那份的自查记录里；本段照此实现，不要中途改成「两种都返 404」——那要同步改 spec §2.6 与上游的 `datasource_exists`。

**凭据（spec §4.4）**
- 响应模型不声明任何密码/密文/nonce 字段。本段有一条测试直接扫响应**原文**里有没有明文密码，不只扫 JSON 的键。
- 错误消息不回显地址、端口、库名、用户名。
- 本段不调 `read_password`：HTTP 层没有任何需要明文密码的理由。

**契约**
- 每个路由必须带完整 `response_model` 与 `responses` 声明。本段有一条测试直接读 `app.openapi()` 核对，漏声明会 FAIL——P4 生成前端类型时缺一个 `{code, message}` 分支就是一处运行时崩溃。

**事务边界（本段最容易写错的地方）**
- `get_db` 已经在请求正常结束时 `commit()`、异常时 `rollback()`（`db/base.py`）。**router 里不要写 `db.commit()`。**
- P1 的 `login`/`logout` 是显式 commit 的，别照抄：那里的理由是「交给客户端的 cookie 必须在响应发出前持久」，数据源写入没有这个约束。
- 仓储抛 `ApiError` 时它内部的 savepoint 已回滚，请求事务仍可用；随后 `get_db` 会把整个请求回滚掉，没有需要保留的部分写入。

## 本机环境

与上游那份相同，不重复。跑测试前需要的环境变量：

```bash
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
```

所有命令在 `apps/api/` 下跑。**本段的起点基线：`95 passed`**（上游 Task 4 结束时的值）。开工前先跑一次确认——如果不是 95，先回上游那份核对，别在错的基线上往下加。Docker 仍然不需要——本段不连任何外部库。

---

## File Structure

### 本份创建的文件

| 文件 | 职责 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/datasources/deps.py` | `require_datasource`：按路径 id 取 + 可见性判定 + 抛 `ApiError` | 5 |
| `apps/api/src/chatbi/api/datasource_router.py` | `/api/datasources` 的 CRUD（Task 5）与 grants（Task 6） | 5、6 |
| `apps/api/src/chatbi/api/user_router.py` | `/api/users` admin 开号与列表 | 6 |
| `apps/api/tests/test_datasource_router.py` | 端点鉴权、响应无凭据字段、错误码、OpenAPI 声明完整 | 5 |
| `apps/api/tests/test_datasource_grants.py` | 授权增删与可见性联动 | 6 |
| `apps/api/tests/test_user_router.py` | admin 开号、重复邮箱 409、非 admin 403 | 6 |

### 本份修改的文件

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/api/routers.py` | `ALL_ROUTERS` 加 `datasource_router`（Task 5）、`user_router`（Task 6） | 5、6 |
| `apps/api/tests/conftest.py` | 加 `login_as`、`admin_client` 夹具 | 5 |
| `apps/api/src/chatbi/auth/provisioning.py` | 去掉 check-then-insert，改 insert + `IntegrityError` → `EMAIL_ALREADY_EXISTS`（P1 遗留 3） | 6 |
| `apps/api/src/chatbi/auth/schemas.py` | 加 `UserCreateRequest` | 6 |

### 边界说明

`deps.py` 可以 import `fastapi` 与 `repository`，但**不能 import `crypto`**：HTTP 层没有任何需要明文密码的理由，让它连解密函数都看不见，比靠约定「记得别调」可靠。两个 router 都不 import `sqlalchemy.select`——需要新查询就回上游那份加仓储函数。`user_router` 不复制 `provisioning` 里的密码规则（长度、角色白名单）：那是领域约束，仓储与 CLI 共用同一份。

---

### Task 5: `require_datasource` 依赖与 `/api/datasources` CRUD

grants 端点留给 Task 6——它们挂在同一个 router 文件上，但可以被单独驳回：CRUD 错了 grants 也没意义，反之不成立。

**Files:**
- Create: `apps/api/src/chatbi/datasources/deps.py`
- Create: `apps/api/src/chatbi/api/datasource_router.py`
- Create: `apps/api/tests/test_datasource_router.py`
- Modify: `apps/api/src/chatbi/api/routers.py:1-6`（`ALL_ROUTERS` 加一项）
- Modify: `apps/api/tests/conftest.py`（追加 `login_as`、`admin_client`）

**Interfaces:**
- Consumes（上游交接清单）：`repository.{create_datasource, update_datasource, delete_datasource, list_visible, get_visible, datasource_exists}` · `schemas.{DatasourceCreate, DatasourceUpdate, DatasourceResponse}` · `chatbi.auth.deps.{current_user, require_role, SESSION_COOKIE}` · `chatbi.auth.sessions.create_session` · `chatbi.auth.schemas.ErrorResponse` · `chatbi.errors.{DATASOURCE_NOT_FOUND, PERMISSION_DENIED, ApiError}` · `chatbi.api.routers.ALL_ROUTERS`
- Produces:
```python
chatbi.datasources.deps.require_datasource(datasource_id, db, user) -> Datasource
# FastAPI 依赖。路径参数名必须是 datasource_id，与路由里的 {datasource_id} 对应
chatbi.api.datasource_router.router      # APIRouter(prefix="/api/datasources")
# Task 6 往同一个 router 上加 grants 路由，不新建文件

# conftest 夹具，Task 6 也用：
login_as(user: User) -> User    # 建会话并把 cookie 塞进 client，返回原对象
admin_client                    # 已登录为 admin 的 TestClient（不暴露那个 admin 对象）
```

- [ ] **Step 1: 加两个夹具**

`apps/api/tests/conftest.py` 末尾追加。`login_as` 走的是真会话表而不是伪造 cookie——`current_user` 会去 `sessions` 表查，伪造的 cookie 一律 401：

```python
@pytest.fixture
def login_as(client: TestClient, db_session: Session):
    """把某个用户的会话 cookie 塞进 client。返回传入的对象，方便链式写。"""
    from chatbi.auth.deps import SESSION_COOKIE
    from chatbi.auth.sessions import create_session

    def _login(user):
        record = create_session(db_session, user)
        client.cookies.set(SESSION_COOKIE, str(record.id))
        return user

    return _login


@pytest.fixture
def admin_client(client: TestClient, make_user, login_as) -> TestClient:
    """已登录为 admin 的 client。数据源与用户的写操作都要它。

    需要拿到那个 admin 对象本身时，别用这个夹具，直接
    `login_as(make_user(role="admin"))`——返回值就是它。
    """
    login_as(make_user(role="admin"))
    return client
```

`login_as` 依赖 `client`，而 `client` 依赖 `db_session`，所以三者共用同一个事务：测试里建的用户与会话对同一个 TestClient 可见，请求结束时 `get_db` 的 commit 落在夹具的 savepoint 内，测试结束整体回滚。

- [ ] **Step 2: 写失败的测试**

新建 `apps/api/tests/test_datasource_router.py`：

```python
"""/api/datasources 的端点测试。

全部走真 app（`client` 夹具只覆盖 get_db），所以 router 注册、异常处理器、
OpenAPI 声明都在被测范围内。P1 §10.4 接缝 ② 的教训：自建 app 的夹具会把
「真 app 上注册失效」这类问题整类掩盖掉。
"""

import uuid

from fastapi.testclient import TestClient

PAYLOAD = {
    "name": "生产只读库",
    "kind": "postgres",
    "host": "db.internal",
    "port": 5432,
    "database": "analytics",
    "username": "ro_user",
    "password": "ds-pw-123456",
}


def test_unauthenticated_listing_is_rejected(client: TestClient) -> None:
    response = client.get("/api/datasources")

    assert response.status_code == 401
    assert response.json() == {"code": "NOT_AUTHENTICATED", "message": "请先登录"}


def test_admin_creates_a_datasource(admin_client: TestClient) -> None:
    response = admin_client.post("/api/datasources", json=PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "生产只读库"
    assert body["has_password"] is True
    # 只读验证由 P2b 的 /test 端点写，建的时候必须是 false，不能默认「已验证」
    assert body["is_readonly_verified"] is False


def test_the_create_response_never_echoes_the_password(admin_client: TestClient) -> None:
    """扫响应原文，不只扫 JSON 的键。

    某天有人加一个把请求体回显进去的 detail 字段，只查键名的断言会放过它。
    """
    response = admin_client.post("/api/datasources", json=PAYLOAD)

    assert "ds-pw-123456" not in response.text
    for key in ("password", "secret_ciphertext", "secret_nonce"):
        assert key not in response.json()


def test_creating_with_a_duplicate_name_returns_409(admin_client: TestClient) -> None:
    admin_client.post("/api/datasources", json=PAYLOAD)

    response = admin_client.post("/api/datasources", json=PAYLOAD)

    assert response.status_code == 409
    assert response.json()["code"] == "DATASOURCE_NAME_EXISTS"


def test_creating_with_an_unsupported_kind_is_a_validation_error(
    admin_client: TestClient,
) -> None:
    """kind 由 Literal 守住，422 来自 Pydantic——router 里不需要自己写校验。"""
    response = admin_client.post("/api/datasources", json=PAYLOAD | {"kind": "oracle"})

    assert response.status_code == 422


def test_analyst_cannot_create(client: TestClient, make_user, login_as) -> None:
    login_as(make_user(role="analyst"))

    response = client.post("/api/datasources", json=PAYLOAD)

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_viewer_cannot_create(client: TestClient, make_user, login_as) -> None:
    login_as(make_user(role="viewer"))

    assert client.post("/api/datasources", json=PAYLOAD).status_code == 403


def test_analyst_only_lists_granted_datasources(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    granted = make_datasource(name="已授权")
    make_datasource(name="未授权")
    set_grant(db_session, datasource_id=granted.id, user_id=analyst.id, can_query=True)

    response = client.get("/api/datasources")

    assert response.status_code == 200
    assert [d["name"] for d in response.json()] == ["已授权"]


def test_getting_an_unknown_id_returns_404(admin_client: TestClient) -> None:
    response = admin_client.get(f"/api/datasources/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "DATASOURCE_NOT_FOUND"


def test_getting_an_ungranted_datasource_returns_403(
    client: TestClient, make_user, make_datasource, login_as
) -> None:
    login_as(make_user(role="analyst"))
    datasource = make_datasource()

    response = client.get(f"/api/datasources/{datasource.id}")

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"
    # 无权限的响应不回显地址、端口、库名、用户名（spec §4.4）
    for leak in ("db.internal", "5432", "analytics", "ro_user"):
        assert leak not in response.text


def test_analyst_can_get_a_granted_datasource(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    response = client.get(f"/api/datasources/{datasource.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(datasource.id)


def test_admin_patches_a_datasource(admin_client: TestClient, make_datasource) -> None:
    datasource = make_datasource(host="old.internal")

    response = admin_client.patch(
        f"/api/datasources/{datasource.id}", json={"host": "new.internal"}
    )

    assert response.status_code == 200
    assert response.json()["host"] == "new.internal"


def test_patching_the_password_does_not_echo_it(
    admin_client: TestClient, make_datasource
) -> None:
    datasource = make_datasource()

    response = admin_client.patch(
        f"/api/datasources/{datasource.id}", json={"password": "rotated-pw-9999"}
    )

    assert response.status_code == 200
    assert "rotated-pw-9999" not in response.text
    assert response.json()["has_password"] is True


def test_analyst_cannot_patch_even_a_granted_datasource(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    """写操作是 admin 专属：can_query 授权给的是读，不是写（spec §4.2）。"""
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    response = client.patch(f"/api/datasources/{datasource.id}", json={"host": "x.internal"})

    assert response.status_code == 403


def test_admin_deletes_a_datasource(admin_client: TestClient, make_datasource) -> None:
    datasource = make_datasource()

    assert admin_client.delete(f"/api/datasources/{datasource.id}").status_code == 204
    assert admin_client.get(f"/api/datasources/{datasource.id}").status_code == 404


def test_analyst_cannot_delete_even_a_granted_datasource(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    """必须先授权，否则测的是可见性而不是写权限。

    不 set_grant 的版本照样返回 403——但那个 403 来自 require_datasource 的
    可见性判定，删掉 delete 上的 admin 闸门它依然绿。授权之后，403 就只能
    来自 admin 闸门。
    """
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    assert client.delete(f"/api/datasources/{datasource.id}").status_code == 403


def test_every_route_declares_its_error_envelope() -> None:
    """Pydantic 模型是 OpenAPI 唯一真相源（Global Constraints）。

    漏一个 responses 声明，P4 生成的前端类型就不知道这个端点会返回
    {code, message}，那条分支要到运行时才崩。422 由 FastAPI 自动补，
    所以用子集比较而不是相等。
    """
    from chatbi.main import app

    expected = {
        ("/api/datasources", "get"): {"200", "401"},
        ("/api/datasources", "post"): {"201", "401", "403", "409"},
        ("/api/datasources/{datasource_id}", "get"): {"200", "401", "403", "404"},
        ("/api/datasources/{datasource_id}", "patch"): {"200", "401", "403", "404", "409"},
        ("/api/datasources/{datasource_id}", "delete"): {"204", "401", "403", "404"},
    }

    paths = app.openapi()["paths"]
    for (path, method), codes in expected.items():
        declared = set(paths[path][method]["responses"])
        assert codes <= declared, (path, method, sorted(codes - declared))
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd apps/api
uv run pytest tests/test_datasource_router.py -v
```

预期：路由还不存在，`test_unauthenticated_listing_is_rejected` 拿到 404 而不是 401，`test_every_route_declares_its_error_envelope` 抛 `KeyError: '/api/datasources'`，其余多为 404。

**这一步别只看「有没有红」**：如果某条是因为夹具报错而不是因为路由缺失才失败，先修夹具。`login_as` 写错会让所有 403 断言退化成假性通过的 401——那时测试是绿的，但测的是「没登录」而不是「登录了但没权限」。

- [ ] **Step 4: 写 deps.py**

新建 `apps/api/src/chatbi/datasources/deps.py`：

```python
"""数据源的 FastAPI 依赖。

唯一同时认识 FastAPI 与 repository 的文件，只做「取 + 判定 + 抛 ApiError」。
故意不 import crypto：HTTP 层没有任何需要明文密码的理由，让它连解密函数都
看不见，比靠约定「记得别调」可靠。
"""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from chatbi.auth.deps import current_user
from chatbi.datasources.repository import datasource_exists, get_visible
from chatbi.db.base import get_db
from chatbi.db.models import Datasource, User
from chatbi.errors import DATASOURCE_NOT_FOUND, PERMISSION_DENIED, ApiError


def require_datasource(
    datasource_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> Datasource:
    """按路径参数取数据源，可见性不足就抛。

    参数名必须叫 datasource_id——FastAPI 按名字从路径 {datasource_id} 里取。

    404 与 403 的分界：id 不存在 → DATASOURCE_NOT_FOUND；存在但这个用户没有
    can_query 授权 → PERMISSION_DENIED。顺序不能反：先问 get_visible 再问
    datasource_exists，多出的那次查询只在「拿不到」时发生。
    """
    datasource = get_visible(db, user, datasource_id)
    if datasource is not None:
        return datasource
    if datasource_exists(db, datasource_id):
        raise ApiError(*PERMISSION_DENIED)
    raise ApiError(*DATASOURCE_NOT_FOUND)
```

- [ ] **Step 5: 写 datasource_router.py**

新建 `apps/api/src/chatbi/api/datasource_router.py`：

```python
"""/api/datasources 的 HTTP 编排。

只做「校验角色 → 调仓储 → 返回模型」。这里不出现 select()、不出现可见性判断、
不出现 seal/unseal。需要新查询就回领域层那份加仓储函数（spec §1.3 规则 2、4）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from chatbi.auth.deps import current_user, require_role
from chatbi.auth.schemas import ErrorResponse
from chatbi.datasources.deps import require_datasource
from chatbi.datasources.repository import (
    create_datasource,
    delete_datasource,
    list_visible,
    update_datasource,
)
from chatbi.datasources.schemas import DatasourceCreate, DatasourceResponse, DatasourceUpdate
from chatbi.db.base import get_db
from chatbi.db.models import Datasource, User

router = APIRouter(prefix="/api/datasources", tags=["datasources"])

# 注解别名：写成常量是为了让每个路由的签名短到能一眼看完
_Db = Annotated[Session, Depends(get_db)]
_CurrentUser = Annotated[User, Depends(current_user)]
_Admin = Annotated[User, Depends(require_role("admin"))]
_Target = Annotated[Datasource, Depends(require_datasource)]

# responses 声明必须完整，否则 P4 生成的前端类型会缺 {code, message} 分支
_AUTH = {401: {"model": ErrorResponse}}
_ADMIN = _AUTH | {403: {"model": ErrorResponse}}
_TARGET = _ADMIN | {404: {"model": ErrorResponse}}
_CONFLICT = {409: {"model": ErrorResponse}}


@router.get("", response_model=list[DatasourceResponse], responses=_AUTH)
def list_datasources(db: _Db, user: _CurrentUser) -> list[Datasource]:
    return list_visible(db, user)


@router.post(
    "", response_model=DatasourceResponse, status_code=201, responses=_ADMIN | _CONFLICT
)
def create(payload: DatasourceCreate, db: _Db, admin: _Admin) -> Datasource:
    # 不写 db.commit()：get_db 在请求正常结束时提交（见 Global Constraints 的事务边界）
    return create_datasource(db, payload=payload, created_by=admin.id)


@router.get("/{datasource_id}", response_model=DatasourceResponse, responses=_TARGET)
def get_one(datasource: _Target) -> Datasource:
    """签名里既没有 db 也没有 user——两者都在 require_datasource 内部。"""
    return datasource


@router.patch(
    "/{datasource_id}", response_model=DatasourceResponse, responses=_TARGET | _CONFLICT
)
def patch(payload: DatasourceUpdate, datasource: _Target, db: _Db, _admin: _Admin) -> Datasource:
    """_admin 参数没有函数体内的用处，它就是那道 403 闸门。删了功能照样正常。"""
    return update_datasource(db, datasource, payload)


@router.delete("/{datasource_id}", status_code=204, responses=_TARGET)
def remove(datasource: _Target, db: _Db, _admin: _Admin) -> None:
    delete_datasource(db, datasource)
```

- [ ] **Step 6: 注册到 `ALL_ROUTERS`**

`apps/api/src/chatbi/api/routers.py`——这是 Task 1 建的接缝，`main.py` 不动：

```python
from fastapi import APIRouter

from chatbi.api.auth_router import router as auth_router
from chatbi.api.datasource_router import router as datasource_router

# 挂载顺序即声明顺序。新增 router 只改这一处——main.py 从此不随功能增长而变。
ALL_ROUTERS: tuple[APIRouter, ...] = (auth_router, datasource_router)
```

- [ ] **Step 7: 跑全量确认通过**

```bash
cd apps/api
uv run pytest -q && uv run ruff check src tests
```

预期：`112 passed`（起点 95 + 本任务 17 条）。`test_app_assembly.py` 的装配测试会自动覆盖新 router——它遍历 `ALL_ROUTERS` 核对真 app 上的路径，这正是 Task 1 建那个接缝的回报。

- [ ] **Step 8: 反向验证六条（两个方向都要跑）**

1. `require_datasource` 删掉 `datasource_exists` 分支，拿不到就一律抛 `DATASOURCE_NOT_FOUND` → `test_getting_an_ungranted_datasource_returns_403` 必须 FAIL。
2. 反向：一律抛 `PERMISSION_DENIED` → `test_getting_an_unknown_id_returns_404` 必须 FAIL。第 1、2 条互为对照，两条都跑才证明两个分支各有测试覆盖；只跑一条会漏掉「另一个分支恒不可达」。
3. **删掉 `patch` 的 `_admin: _Admin` 参数** → `test_analyst_cannot_patch_even_a_granted_datasource` 必须 FAIL，且**其余测试全部照样绿**。这条是本任务最重要的反向验证：删掉那道闸门后功能完全正常，只有这一条测试能发现「被授权的 analyst 可以改数据源连接串」——而那意味着他能把 host 改到自己的机器上，拿走服务账号密码。
4. `remove` 的 `_admin` 同样删掉 → `test_analyst_cannot_delete_even_a_granted_datasource` 必须 FAIL。**这条测试的名字里带 `granted` 不是修饰**：初稿写的是不授权版本，反向验证时发现删掉闸门它依然绿——因为那个 403 来自可见性判定而非 admin 闸门。授权是这条测试的鉴别力所在。
5. `list_datasources` 改成绕过仓储、自己 `db.scalars(sa.select(Datasource))` → `test_analyst_only_lists_granted_datasources` 必须 FAIL。这条同时验证了「router 不写 select()」不只是风格要求。
6. `POST` 的 `responses` 里去掉 `_CONFLICT` → `test_every_route_declares_its_error_envelope` 必须 FAIL（`409` 不在声明里）。

另外确认一次凭据红线：给 `DatasourceResponse` 加 `password: str | None = None` 且在 `create` 里回填 `payload.password` → `test_the_create_response_never_echoes_the_password` 必须 FAIL。恢复。

- [ ] **Step 9: 提交**

```bash
git add apps/api/src/chatbi apps/api/tests
git commit -m "$(cat <<'EOF'
feat(api): datasource CRUD endpoints with role and visibility gates

require_datasource folds visibility into the fetch and separates 404 from
403; writes are admin-only even for granted datasources; every route
declares its error envelope so generated frontend types stay complete.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: grants 端点、`/api/users`，清掉 P1 最后两项遗留

两件事放一个任务，因为它们共用同一条线索：**授权要指向一个真实用户**。grants 端点需要「这个 user_id 存在吗」，而回答它的函数正是开号端点要用的那个；`USER_NOT_FOUND`（P1 遗留 5，定义了没人用）也在这里第一次有调用方。

**Files:**
- Create: `apps/api/src/chatbi/api/user_router.py`
- Create: `apps/api/tests/test_datasource_grants.py`
- Create: `apps/api/tests/test_user_router.py`
- Modify: `apps/api/src/chatbi/api/datasource_router.py`（追加三条 grants 路由）
- Modify: `apps/api/src/chatbi/api/routers.py`（`ALL_ROUTERS` 加 `user_router`）
- Modify: `apps/api/src/chatbi/auth/provisioning.py`（改 insert + `IntegrityError`；加 `get_user`、`list_users`）
- Modify: `apps/api/src/chatbi/auth/schemas.py`（加 `UserCreateRequest`）

**Interfaces:**
- Consumes：`repository.{set_grant, revoke_grant, list_grants}` · `schemas.{GrantRequest, GrantResponse}` · `chatbi.db.integrity.violated_constraint` · `chatbi.auth.provisioning.{create_user, MIN_PASSWORD_LENGTH}` · `chatbi.auth.schemas.UserResponse` · `chatbi.errors.{USER_NOT_FOUND, EMAIL_ALREADY_EXISTS}` · Task 5 的 `_Db` / `_Admin` / `_Target` 注解别名与 `_AUTH` / `_ADMIN` / `_TARGET` / `_CONFLICT` responses 常量
- Produces:
```python
chatbi.auth.provisioning.get_user(session, user_id: uuid.UUID) -> User | None
chatbi.auth.provisioning.list_users(session) -> list[User]     # 按 email 排序
chatbi.auth.schemas.UserCreateRequest                          # email/display_name/password/role
chatbi.api.user_router.router                                  # APIRouter(prefix="/api/users")

# 新增端点
PUT    /api/datasources/{datasource_id}/grants            -> 200 GrantResponse（幂等 upsert）
DELETE /api/datasources/{datasource_id}/grants/{user_id}  -> 204（幂等，重复撤销一样 204）
GET    /api/datasources/{datasource_id}/grants            -> 200 list[GrantResponse]
POST   /api/users                                         -> 201 UserResponse
GET    /api/users                                         -> 200 list[UserResponse]
```

**为什么 grants 用 `PUT` 而不是 `POST`**：授权是「有/无」而不是可累积的列表（复合主键就是这么设的），同一份请求重发两次结果必须相同。`POST` 的语义是「新建一个」，那会诱使实现者去插第二行。

**为什么 DELETE 幂等返回 204**：Global Constraints 说本段不新增错误码，而「授权本来就不存在」既不是 `USER_NOT_FOUND`（用户可能好好存在）也不是 `DATASOURCE_NOT_FOUND`。硬套一个语义不对的码比幂等更糟。

- [ ] **Step 1: 写 grants 的失败测试**

新建 `apps/api/tests/test_datasource_grants.py`：

```python
"""授权端点与可见性的联动。

这些测试的重点不是「PUT 返回 200」，而是「授权之后 GET /api/datasources 的结果
真的变了」——授权表写对了但可见性查询没用上它，是这一层最容易出的错。
"""

import uuid

from fastapi.testclient import TestClient


def _names(client: TestClient) -> list[str]:
    return [d["name"] for d in client.get("/api/datasources").json()]


def test_admin_grants_and_the_analyst_immediately_sees_it(
    admin_client: TestClient, client: TestClient, db_session, make_user, make_datasource
) -> None:
    """注意 admin_client 与 client 是同一个 TestClient 实例（同一个夹具链），
    所以下面要重新登录成 analyst 才能观察 analyst 的视角。
    """
    from chatbi.auth.deps import SESSION_COOKIE
    from chatbi.auth.sessions import create_session

    datasource = make_datasource(name="生产库")
    analyst = make_user(role="analyst")

    response = admin_client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(analyst.id), "can_query": True},
    )

    assert response.status_code == 200
    assert response.json() == {
        "datasource_id": str(datasource.id),
        "user_id": str(analyst.id),
        "can_query": True,
    }

    client.cookies.set(SESSION_COOKIE, str(create_session(db_session, analyst).id))
    assert _names(client) == ["生产库"]


def test_granting_twice_keeps_a_single_row(
    admin_client: TestClient, make_user, make_datasource
) -> None:
    datasource = make_datasource()
    analyst = make_user(role="analyst")
    body = {"user_id": str(analyst.id), "can_query": True}

    admin_client.put(f"/api/datasources/{datasource.id}/grants", json=body)
    admin_client.put(f"/api/datasources/{datasource.id}/grants", json=body)

    listed = admin_client.get(f"/api/datasources/{datasource.id}/grants").json()
    assert len(listed) == 1


def test_setting_can_query_false_hides_the_datasource(
    admin_client: TestClient, client: TestClient, db_session, make_user, make_datasource
) -> None:
    from chatbi.auth.deps import SESSION_COOKIE
    from chatbi.auth.sessions import create_session

    datasource = make_datasource()
    analyst = make_user(role="analyst")
    admin_client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(analyst.id), "can_query": True},
    )
    admin_client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(analyst.id), "can_query": False},
    )

    client.cookies.set(SESSION_COOKIE, str(create_session(db_session, analyst).id))
    assert _names(client) == []


def test_revoking_a_grant_hides_the_datasource_again(
    admin_client: TestClient, client: TestClient, db_session, make_user, make_datasource
) -> None:
    from chatbi.auth.deps import SESSION_COOKIE
    from chatbi.auth.sessions import create_session

    datasource = make_datasource()
    analyst = make_user(role="analyst")
    admin_client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(analyst.id), "can_query": True},
    )

    revoked = admin_client.delete(f"/api/datasources/{datasource.id}/grants/{analyst.id}")

    assert revoked.status_code == 204
    client.cookies.set(SESSION_COOKIE, str(create_session(db_session, analyst).id))
    assert _names(client) == []


def test_revoking_twice_is_idempotent(
    admin_client: TestClient, make_user, make_datasource
) -> None:
    """本段不新增错误码，而「授权本来就不存在」没有语义正确的现成码。"""
    datasource = make_datasource()
    analyst = make_user(role="analyst")
    path = f"/api/datasources/{datasource.id}/grants/{analyst.id}"

    assert admin_client.delete(path).status_code == 204
    assert admin_client.delete(path).status_code == 204


def test_admin_lists_grants(admin_client: TestClient, make_user, make_datasource) -> None:
    datasource = make_datasource()
    first = make_user(role="analyst")
    second = make_user(role="viewer")
    for user in (first, second):
        admin_client.put(
            f"/api/datasources/{datasource.id}/grants",
            json={"user_id": str(user.id), "can_query": True},
        )

    listed = admin_client.get(f"/api/datasources/{datasource.id}/grants").json()

    assert {row["user_id"] for row in listed} == {str(first.id), str(second.id)}


def test_analyst_cannot_grant(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    """连自己已被授权的数据源也不能改授权——否则一次授权等于放开整棵权限树。"""
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    response = client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(analyst.id), "can_query": True},
    )

    assert response.status_code == 403


def test_listing_grants_requires_admin(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    assert client.get(f"/api/datasources/{datasource.id}/grants").status_code == 403


def test_granting_on_an_unknown_datasource_returns_404(
    admin_client: TestClient, make_user
) -> None:
    analyst = make_user(role="analyst")

    response = admin_client.put(
        f"/api/datasources/{uuid.uuid4()}/grants",
        json={"user_id": str(analyst.id), "can_query": True},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DATASOURCE_NOT_FOUND"


def test_granting_to_an_unknown_user_returns_404(
    admin_client: TestClient, make_datasource
) -> None:
    """P1 遗留 5：USER_NOT_FOUND 终于有调用方。

    没有这道检查，授权表会攒下指向不存在用户的行——外键会挡住，但错误表面会是
    500 而不是 404。
    """
    datasource = make_datasource()

    response = admin_client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(uuid.uuid4()), "can_query": True},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


def test_every_grant_route_declares_its_error_envelope() -> None:
    from chatbi.main import app

    expected = {
        ("/api/datasources/{datasource_id}/grants", "get"): {"200", "401", "403", "404"},
        ("/api/datasources/{datasource_id}/grants", "put"): {"200", "401", "403", "404"},
        ("/api/datasources/{datasource_id}/grants/{user_id}", "delete"): {
            "204",
            "401",
            "403",
            "404",
        },
    }

    paths = app.openapi()["paths"]
    for (path, method), codes in expected.items():
        declared = set(paths[path][method]["responses"])
        assert codes <= declared, (path, method, sorted(codes - declared))
```

- [ ] **Step 2: 写 `/api/users` 的失败测试**

新建 `apps/api/tests/test_user_router.py`：

```python
"""/api/users 的端点测试。覆盖 P1 遗留 3（重复邮箱的错误表面）与响应脱敏。"""

from typing import get_args

from fastapi.testclient import TestClient

PAYLOAD = {
    "email": "New.Analyst@Example.COM",
    "display_name": "新来的分析师",
    "password": "pw-12345678",
    "role": "analyst",
}


def test_unauthenticated_creation_is_rejected(client: TestClient) -> None:
    response = client.post("/api/users", json=PAYLOAD)

    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"


def test_admin_creates_a_user(admin_client: TestClient) -> None:
    response = admin_client.post("/api/users", json=PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    # 邮箱在应用层小写规范化（P1 的 normalize_email），响应必须是规范化后的值——
    # 否则前端拿着原样大小写去比对会对不上
    assert body["email"] == "new.analyst@example.com"
    assert body["role"] == "analyst"
    assert body["is_active"] is True


def test_the_response_never_contains_the_password_hash(admin_client: TestClient) -> None:
    response = admin_client.post("/api/users", json=PAYLOAD)

    assert "password_hash" not in response.json()
    assert "pw-12345678" not in response.text


def test_creating_a_duplicate_email_returns_409(admin_client: TestClient) -> None:
    admin_client.post("/api/users", json=PAYLOAD)

    # 大小写不同也算重复：normalize_email 之后撞同一个唯一索引
    response = admin_client.post(
        "/api/users", json=PAYLOAD | {"email": "NEW.ANALYST@example.com"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_ALREADY_EXISTS"


def test_the_duplicate_email_error_leaves_the_session_usable(admin_client: TestClient) -> None:
    """P1 遗留 3 的收益，但要说清它测的是什么。

    这条钉的是 savepoint 隔离，而它在测试里可观察是因为 `client` 夹具让三次请求
    共享同一个 session。生产环境每请求一个 session，这个失效模式本来就不会出现。
    真正需要 savepoint 的调用方是「出错后还要接着跑」的那种——CLI 批量建号、
    将来的批量导入。写这条测试是为了让 savepoint 不被当成多余代码删掉。
    """
    admin_client.post("/api/users", json=PAYLOAD)

    conflict = admin_client.post("/api/users", json=PAYLOAD)
    followup = admin_client.get("/api/users")

    assert conflict.status_code == 409
    assert followup.status_code == 200


def test_a_short_password_is_a_validation_error(admin_client: TestClient) -> None:
    response = admin_client.post("/api/users", json=PAYLOAD | {"password": "short"})

    assert response.status_code == 422


def test_an_unknown_role_is_a_validation_error(admin_client: TestClient) -> None:
    response = admin_client.post("/api/users", json=PAYLOAD | {"role": "superuser"})

    assert response.status_code == 422


def test_the_role_literal_matches_the_model_constant() -> None:
    """和 DatasourceKind 同一个理由：Literal 让 OpenAPI 出 enum，但它与 ROLES
    是两处声明，这条防漂移。
    """
    from chatbi.auth.schemas import UserCreateRequest
    from chatbi.db.models import ROLES

    annotation = UserCreateRequest.model_fields["role"].annotation

    assert set(get_args(annotation)) == set(ROLES)


def test_analyst_cannot_create_a_user(client: TestClient, make_user, login_as) -> None:
    login_as(make_user(role="analyst"))

    response = client.post("/api/users", json=PAYLOAD)

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_admin_lists_users(admin_client: TestClient, make_user) -> None:
    make_user(email="zoe@example.com", role="viewer")
    make_user(email="amy@example.com", role="analyst")

    response = admin_client.get("/api/users")

    assert response.status_code == 200
    emails = [u["email"] for u in response.json()]
    assert emails == sorted(emails)
    assert {"amy@example.com", "zoe@example.com"} <= set(emails)


def test_every_user_route_declares_its_error_envelope() -> None:
    from chatbi.main import app

    expected = {
        ("/api/users", "get"): {"200", "401", "403"},
        ("/api/users", "post"): {"201", "401", "403", "409"},
    }

    paths = app.openapi()["paths"]
    for (path, method), codes in expected.items():
        declared = set(paths[path][method]["responses"])
        assert codes <= declared, (path, method, sorted(codes - declared))
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd apps/api
uv run pytest tests/test_datasource_grants.py tests/test_user_router.py -v
```

预期：grants 与 users 的路由都不存在，多为 404 / `KeyError`；`test_the_role_literal_matches_the_model_constant` 报 `ImportError: cannot import name 'UserCreateRequest'`。

- [ ] **Step 4: 改 provisioning.py（P1 遗留 3）并加 `get_user` / `list_users`**

`apps/api/src/chatbi/auth/provisioning.py` 整文件替换：

```python
import uuid

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatbi.auth.hashing import hash_password
from chatbi.auth.identity import normalize_email
from chatbi.db.integrity import violated_constraint
from chatbi.db.models import ROLES, User
from chatbi.errors import EMAIL_ALREADY_EXISTS, ApiError

MIN_PASSWORD_LENGTH = 8
_EMAIL_CONSTRAINT = "ix_users_email"


def create_user(
    session: Session, *, email: str, display_name: str, password: str, role: str
) -> User:
    if role not in ROLES:
        raise ValueError(f"role 必须是 {ROLES} 之一，收到 {role!r}")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")

    user = User(
        id=uuid.uuid4(),
        email=normalize_email(email),
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    # P1 遗留 3：原来是 check-then-insert（先 select 再 insert），并发下两个请求
    # 都查到「没有」，一个成功一个 500。现在只信 DB 的唯一索引。
    # savepoint 的作用是让调用方在 409 之后还能继续用这个事务（CLI 批量建号）。
    savepoint = session.begin_nested()
    try:
        session.add(user)
        session.flush()
    except IntegrityError as exc:
        savepoint.rollback()
        if violated_constraint(exc) != _EMAIL_CONSTRAINT:
            # 不是邮箱冲突就原样抛：把别的约束违规也报成「邮箱已存在」是撒谎
            raise
        raise ApiError(*EMAIL_ALREADY_EXISTS) from exc
    savepoint.commit()
    return user


def get_user(session: Session, user_id: uuid.UUID) -> User | None:
    """按 id 取用户。grants 端点用它回答「这个 user_id 存在吗」。"""
    return session.get(User, user_id)


def list_users(session: Session) -> list[User]:
    """按 email 排序——列表要稳定，否则前端每次刷新顺序都不同。"""
    return list(session.scalars(sa.select(User).order_by(User.email)))
```

角色与密码长度的校验**留在这里**，不搬到 router：CLI 的 `create-user` 走的是同一个函数，规则只能有一份。Pydantic 那层的 `min_length` 是 HTTP 的早退（返回 422 而不是 500），不是真相源。

`apps/api/src/chatbi/auth/schemas.py` 末尾追加（import 段加 `Literal`）：

```python
from typing import Literal

from chatbi.auth.provisioning import MIN_PASSWORD_LENGTH


class UserCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)
    role: Literal["admin", "analyst", "viewer"]
```

从 schemas 反向 import provisioning 不成环：`provisioning` 只认识 `hashing` / `identity` / `db` / `errors`，不认识 `schemas`。这样密码长度只有一处定义。

- [ ] **Step 5: 给 `datasource_router.py` 追加三条 grants 路由**

import 段补上（`uuid`、四个仓储函数、两个模型、`USER_NOT_FOUND`）：

```python
import uuid

from chatbi.auth.provisioning import get_user
from chatbi.datasources.repository import list_grants, revoke_grant, set_grant
from chatbi.datasources.schemas import GrantRequest, GrantResponse
from chatbi.db.models import DatasourceGrant
from chatbi.errors import USER_NOT_FOUND, ApiError
```

文件末尾追加：

```python
# ---- grants ----
# 路径比 /{datasource_id} 多一段，不会和它抢匹配，声明顺序无所谓。
# 三条都吃 _Target，所以「数据源不存在 → 404 / 无授权 → 403」自动一致。


@router.get("/{datasource_id}/grants", response_model=list[GrantResponse], responses=_TARGET)
def list_datasource_grants(
    datasource: _Target, db: _Db, _admin: _Admin
) -> list[DatasourceGrant]:
    return list_grants(db, datasource.id)


@router.put("/{datasource_id}/grants", response_model=GrantResponse, responses=_TARGET)
def put_grant(
    payload: GrantRequest, datasource: _Target, db: _Db, _admin: _Admin
) -> DatasourceGrant:
    """PUT 而不是 POST：授权是「有/无」，重发同一份请求结果必须相同。"""
    # 这两行「取 + 判定 + 抛」留在 router 里：user_id 来自请求体而不是路径，
    # 做不成 FastAPI 依赖。形状与 P1 login 里那两行一致，可接受。
    if get_user(db, payload.user_id) is None:
        raise ApiError(*USER_NOT_FOUND)
    return set_grant(
        db, datasource_id=datasource.id, user_id=payload.user_id, can_query=payload.can_query
    )


@router.delete("/{datasource_id}/grants/{user_id}", status_code=204, responses=_TARGET)
def delete_grant(user_id: uuid.UUID, datasource: _Target, db: _Db, _admin: _Admin) -> None:
    """幂等：授权本来就不存在也返回 204（理由见任务开头）。

    这里不校验 user_id 是否存在——撤销一个不存在用户的授权，结果和撤销一个
    不存在的授权没有区别，都是「现在没有」。
    """
    revoke_grant(db, datasource_id=datasource.id, user_id=user_id)
```

- [ ] **Step 6: 写 user_router.py**

新建 `apps/api/src/chatbi/api/user_router.py`：

```python
"""/api/users 的 HTTP 编排。

只有 admin 开号，不做注册页——私有化部署里账号由管理员发（spec §4.1）。
密码长度与角色白名单的真相源在 provisioning，不在这里重复。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from chatbi.auth.deps import require_role
from chatbi.auth.provisioning import create_user, list_users
from chatbi.auth.schemas import ErrorResponse, UserCreateRequest, UserResponse
from chatbi.db.base import get_db
from chatbi.db.models import User

router = APIRouter(prefix="/api/users", tags=["users"])

# 与 datasource_router 里那几行同形。没有抽到公共模块：跨 router import 注解别名
# 会让两个 router 互相耦合，而这几行的成本低于那个耦合。
_Db = Annotated[Session, Depends(get_db)]
_Admin = Annotated[User, Depends(require_role("admin"))]

_ADMIN = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}}
_CONFLICT = {409: {"model": ErrorResponse}}


@router.get("", response_model=list[UserResponse], responses=_ADMIN)
def list_all(db: _Db, _admin: _Admin) -> list[User]:
    return list_users(db)


@router.post("", response_model=UserResponse, status_code=201, responses=_ADMIN | _CONFLICT)
def create(payload: UserCreateRequest, db: _Db, _admin: _Admin) -> User:
    return create_user(
        db,
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
        role=payload.role,
    )
```

- [ ] **Step 7: 注册到 `ALL_ROUTERS`**

```python
from fastapi import APIRouter

from chatbi.api.auth_router import router as auth_router
from chatbi.api.datasource_router import router as datasource_router
from chatbi.api.user_router import router as user_router

# 挂载顺序即声明顺序。新增 router 只改这一处——main.py 从此不随功能增长而变。
ALL_ROUTERS: tuple[APIRouter, ...] = (auth_router, datasource_router, user_router)
```

- [ ] **Step 8: 跑全量确认通过**

```bash
cd apps/api
uv run pytest -q && uv run ruff check src tests
```

预期：`134 passed`（Task 5 后的 112 + 本任务 22 条：grants 11 + users 11）。P1 的 `test_provisioning.py` 四条必须仍然全绿——`create_user` 换成 insert + `IntegrityError` 之后，「大小写不同的重复邮箱」仍然由 `normalize_email` + 唯一索引挡住，行为不变，只是错误来源换了。

- [ ] **Step 9: 反向验证六条（两个方向都要跑）**

1. `put_grant` 删掉 `get_user` 检查 → `test_granting_to_an_unknown_user_returns_404` 必须 FAIL（变成外键违规的 500）。
2. `list_datasource_grants` 与 `put_grant` 的 `_admin` 参数删掉 → `test_listing_grants_requires_admin` 与 `test_analyst_cannot_grant` 必须 FAIL。
3. **`create_user` 里去掉 savepoint**（退化成直接 `add` + `flush`）→ `test_the_duplicate_email_error_leaves_the_session_usable` 必须 FAIL，而 `test_creating_a_duplicate_email_returns_409` **仍然通过**。这一对结果是这条改造的全部意义：409 的表面两种写法都对，差别只在事务还能不能用。
4. `UserCreateRequest.role` 从 `Literal[...]` 改成 `str` → `test_an_unknown_role_is_a_validation_error`（422 变 500）与 `test_the_role_literal_matches_the_model_constant` 必须双双 FAIL。
5. `put_grant` 从 `PUT` 改成 `POST` 并让它每次 `session.add(DatasourceGrant(...))` → `test_granting_twice_keeps_a_single_row` 必须 FAIL（撞复合主键 500）。这条同时说明了为什么选 PUT。
6. `PUT /grants` 的 `responses` 去掉 `_TARGET` 里的 404 → `test_every_grant_route_declares_its_error_envelope` 必须 FAIL。

**两条不在列表里、且要如实记下的**：

- `create_user` 里 `violated_constraint(exc) != _EMAIL_CONSTRAINT` 那个分支**没有测试**。`users` 表上除了 `ix_users_email` 没有第二个可达的约束——`role` 的 CHECK 在它之前已被 `ROLES` 守卫拦成 `ValueError`。这个分支是为将来加列留的对称写法，不是被验证过的行为。别为它编一条测试。
- `list_users` 去掉 `order_by` 后 `test_admin_lists_users` **多半**会 FAIL（Postgres 实际常按插入序返回），但这不是硬保证——无 `ORDER BY` 时顺序未定义。这条断言的强度低于其余各条，知道就行。

- [ ] **Step 10: 提交**

```bash
git add apps/api/src/chatbi apps/api/tests
git commit -m "$(cat <<'EOF'
feat(api): datasource grants and admin user endpoints

Grants use idempotent PUT and a 204 DELETE; granting to an unknown user is
USER_NOT_FOUND, which finally gives that code a caller. create_user drops
check-then-insert for insert + IntegrityError inside a savepoint.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 交接清单（P2b 要消费的签名）

P2b「三驱动与示例库」直接依赖以下签名，改动它们要回头改 P2b 计划。

**领域层**（[上游那份](2026-08-13-chatbi-v2-1-p2a-datasource-persistence.md)，签名全表在它的交接清单里）
```python
chatbi.datasources.repository.read_password(datasource) -> str | None
# P2b 的驱动层是它的第一个生产调用方。返回值不得进日志、不得进 HTTP 响应
chatbi.db.models.Datasource        # kind/host/port/database/username/options/is_readonly_verified
chatbi.db.models.DATASOURCE_KINDS  # ("postgres", "mysql", "clickhouse")
```

**HTTP 层**（本份）
```python
chatbi.datasources.deps.require_datasource
# /test 与 /schema 直接复用它，不要再写一遍「取 + 判定 + 抛」
chatbi.api.datasource_router.router   # /test、/schema 挂到这个 router 上
chatbi.api.routers.ALL_ROUTERS        # 新 router 只改这一处
chatbi.auth.provisioning.get_user(session, user_id) -> User | None
chatbi.auth.provisioning.list_users(session) -> list[User]
# datasource_router 里的注解别名与 responses 常量可直接复用：
#   _Db · _CurrentUser · _Admin · _Target · _AUTH · _ADMIN · _TARGET · _CONFLICT
```

**P2b 起步须知**

- **`CONNECTION_ERROR` 由 P2b 新增**（spec §2.6）。文案「无法连接到数据库，请检查地址、端口与网络」，不回显地址端口；地址端口进服务端日志。本段刻意没提前定义它——P1 遗留 5 就是「定义了没人用」。
- **`is_readonly_verified` 只有 `/test` 能写**。本段建了列但从不写值，且没有任何客户端可以设置它的路径（`DatasourceUpdate` 里没有这个字段）。**别把它加进 `DatasourceUpdate`**，否则客户端可以自称「已验证只读」，spec §4.3 闸门 1 当场失效。探到写权限置 false 并告警，但**不阻止保存**。
- **`/test` 是唯一有权调 `read_password` 的 HTTP 端点**，且只把明文交给驱动，不回响应、不进日志。
- **驱动契约测的 skip 规则与应用库不同**：允许 skip 但必须计数上报（spec §5.1），别照抄 `conftest.py` 里 `pytest.fail` 的写法。
- **Docker 是 P2b 最后一个门禁任务的硬前置**（`compose.test.yml` 的 Postgres / MySQL / ClickHouse，spec §8.1 要求 skip 数为 0）。本机 Docker Desktop 已装但 **WSL2 无任何发行版，守护进程不可用**。开工第一件事就解决它，别留到最后一天——这是 v1 的历史欠账，不能再靠 skip 蒙过去。
- **测试基线：本段做完是 `134 passed`**（起点 95 + Task 5 的 17 + Task 6 的 22）。

**一个 P2b 必须先决定的问题：`demo_sales` 怎么注册成数据源**

spec §2.5 末要求示例库「由一个独立 migration 建表灌数，并自动注册成一个名为『示例销售库』的数据源」。直接照做会撞上一个矛盾：注册数据源必须 seal 密码，而 seal 需要主密钥——让 Alembic migration 依赖 `CHATBI_SECRET_KEY` 意味着任何一次 `alembic upgrade` 都要先配好密钥，包括 CI 里只想验证 schema 的场合。两条路：

1. **migration 只建 `demo_sales` schema 与数据，数据源注册交给一个 CLI 命令**（如 `seed-demo`），走 `create_datasource` 正常加密。schema 迁移与业务数据播种分离，但「自动注册」变成两步。
2. **migration 里直接 INSERT 数据源行，密码两列留空**（Task 3 的 CHECK 允许两列同时为 NULL）。示例库用 trust 认证或空密码时成立，但如果示例库需要密码就走不通。

P2b 选哪条都要在计划里写明理由，并同步 spec §2.5 的措辞。**不要在 migration 里 import `chatbi.datasources.crypto`**——那会把「跑 migration」和「持有主密钥」这两件事永久绑在一起。

---

## 实施期的偏差（执行中回填）

Task 5（commit `ff1b439`，112 passed）与 Task 6（commit `8293ae4`，134 passed）均按计划完成，六条 + 六条反向验证全部成立。三处偏差全部是**测试**的缺陷，实现代码没改：

| 测试 | 问题 | 改成 |
|---|---|---|
| `test_analyst_cannot_delete` | analyst 没被授权，拿到的 403 来自可见性判定而非 admin 闸门。**删掉 `remove` 的 `_admin` 参数它依然绿**——对「写操作只有 admin」零鉴别力 | 改名 `..._even_a_granted_datasource` 并先 `set_grant`。反向验证随即成立 |
| `test_the_create_response_never_echoes_the_password` | 路由不存在时 404 的 `{"detail":"Not Found"}` 当然不含密码，**空洞通过** | 补 `assert response.status_code == 201` 作为下限 |
| `test_granting_twice_keeps_a_single_row` · `test_setting_can_query_false_hides_the_datasource` | 同上：404 响应体的 `len()` 恰好是 1；无授权时 `_names()` 恰好是 `[]`。两条在路由不存在时都绿 | 各补 PUT 的状态码断言。顺带把 `test_revoking_a_grant_hides_the_datasource_again` 改成先断言「可见过」再撤销——验证状态迁移而不是终态恰好为空 |

**这三处都是「先跑失败」那一步抓出来的**：Step 3 报 `16 failed, 1 passed` 与 `20 failed, 2 passed`，那几条「提前通过」的就是缺下限的。**执行时不要只看红的数量对不对，要看有没有本该红却绿的**——它们是唯一能在实现写完之前暴露自己没有鉴别力的时机。

### 计划外补做的一次真跑（2026-08-18）

计划里没有这一步，但测试全程覆盖 `get_db`（`client` 夹具把它换成了夹具事务），因此**数据源写入的真实提交路径一次都没执行过**——这正是 P1 §10.4 记的接缝 ①。补了一次端到端：

`alembic upgrade head`（开发库 0001 → 0002）→ CLI 建 admin → `POST /api/auth/login` 拿 cookie → `POST /api/datasources`（201）→ `GET` 列表（200）→ `PATCH` 轮换密码（200）→ 未认证 `GET`（401 带正确信封）→ `DELETE`（204）→ 再取（404 `DATASOURCE_NOT_FOUND`）。随后直连库确认：行**已持久化**、`secret_ciphertext` 34 字节 / `secret_nonce` 12 字节、明文不在密文里、`read_password` 从真库解密往返成功。e2e 数据已清理。

一个**非缺陷**的现象记在这里免得下次误判：直接在 Git Bash 命令行里用 `curl -d '{"name":"中文名"...}'` 会拿到 `400 {"detail":"There was an error parsing the body"}`——是 Windows shell 把中文编码成了非法 UTF-8，不是应用的问题。用 Python 写出 UTF-8 文件再 `--data-binary @file` 即 201，且响应里的中文正确。P2b 做 `/test` 的真跑时照这个办法。

另外记一条与计划一致但值得复述的：`test_analyst_cannot_delete_even_a_granted_datasource` 与 `test_analyst_cannot_patch_even_a_granted_datasource` 的名字里那个 `granted` 是**功能性**的，不是修饰。将来有人「简化」掉那句 `set_grant`，这两条测试就退化成可见性测试，而 admin 闸门会变成无人看守。

---

## 自查记录（Task 5–6）

**spec 覆盖核对**

| spec 条目 | 落在哪 |
|---|---|
| §2.4 `GET/POST/PATCH/DELETE /api/datasources[/{id}]` | Task 5 |
| §2.4「含 `datasource_grants`」 | Task 6（PUT / DELETE / GET grants 三条） |
| §2.6 `PERMISSION_DENIED` 不透露结构信息 | Task 5（403 响应体只有 `{code, message}`，并有一条扫地址/端口/库名/用户名的断言） |
| §2.6 `DATASOURCE_NOT_FOUND` | Task 5（`require_datasource`） |
| §2.6 `USER_NOT_FOUND` | Task 6（`put_grant`，P1 遗留 5 至此有调用方） |
| §2.6 `EMAIL_ALREADY_EXISTS` | Task 6（`create_user` 的 `IntegrityError` 路径，P1 遗留 3） |
| §4.1 admin 开号、不做注册页 | Task 6（`user_router` 全部端点 admin-only，无匿名注册路径） |
| §4.2 三角色 RBAC、写操作只有 admin | Task 5（`_Admin` 闸门 + 反向验证第 3 条）、Task 6 |
| §4.2 未授权数据源不出现在选择器里 | Task 5（`test_analyst_only_lists_granted_datasources`）、Task 6（授权/撤销后的可见性联动） |
| §4.3 闸门 1 的 `is_readonly_verified` 不可由客户端设置 | Task 5（`DatasourceUpdate` 无此字段，创建时断言必为 false） |
| §4.4 响应永不含凭据字段 | Task 5（扫响应原文 + 扫 JSON 键两条）、Task 6（`password_hash`） |
| §4.4 错误消息不回显地址端口 | Task 5（403 的泄露扫描） |
| §1.3 规则 2「`api/` 不含业务逻辑」 | Task 5、6（router 不写 `select()`，判定在 `deps` 与仓储；`put_grant` 那两行「取+判定+抛」与 P1 `login` 同形） |
| 契约：每路由完整 `responses` | Task 5、6（三条读 `app.openapi()` 的测试） |

**本份不覆盖**：`/test`、`/schema`、`PATCH .../schema/columns/{col_id}`、`CONNECTION_ERROR`、`demo_sales`、三驱动 → P2b；`/api/sql/validate`、`/api/conversations`、`/api/runs*`、两条 SSE → P3；用户的禁用/改角色/改密码端点 → 本段只做「开号 + 列表」，spec §2.4 没要求更多，需要时再加。

**占位符扫描**：全文无 TBD / TODO / 「implement later」/「类似 Task N」/ 无代码的「写测试」步骤。每个 Step 都带可直接粘贴的完整代码或可直接执行的命令。

**写作过程中的回改（含回改上游那份）**

1. **上游 `revoke_grant` 的 docstring 改了**。它原来写「HTTP 层据此决定 204 还是 404」，但本段决定 DELETE 幂等返回 204（本段不新增错误码，而「授权本来就不存在」没有语义正确的现成码）。已回上游那份改成「HTTP 层不消费这个返回值，它存在是为了让『重复撤销确实没删到东西』可被断言」。
2. **`violated_constraint` 抽成 `chatbi/db/integrity.py`**（回改上游 Task 4）。本段的 `create_user` 要做同样的约束名判别，两处各写一份 `getattr(getattr(exc.orig, "diag", None), ...)` 必然漂移。顺带删掉了上游初稿里「取不到就退化成字符串匹配」的兜底——那会把恰好在错误文本里出现该索引名的其他错误也判成重名。
3. **`_admin` 参数用下划线前缀**。它在函数体里没有用处，就是那道 403 闸门；不加下划线读者会以为是漏用了。反向验证第 3 条专门证明它删掉之后功能照样正常、只有一条测试会红。
4. **grants 用 `PUT` 不用 `POST`**。写测试 `test_granting_twice_keeps_a_single_row` 时才想清楚：`POST` 的语义是「新建一个」，会诱使实现者去插第二行，而复合主键的设计意图正是「授权是有/无」。理由写进了任务开头与反向验证第 5 条。
5. **`MIN_PASSWORD_LENGTH` 从 schemas 反向 import provisioning**，而不是在 schemas 里再写一个 `8`。确认过不成环（`provisioning` 不认识 `schemas`）。
6. **两份的测试计数链重算过**（回改上游那份）。上游初稿的 Task 3 把 Task 2 的 10 条整段漏掉了，导致本份的起点基线一路错到底。现在链条是 53 → 58 → 68 → 76 → 95（上游）→ 112 → 134（本份），每段的条数是用 `grep -c "def test_"` 按任务区间数出来的。本份 Task 5 的 17 条、Task 6 的 22 条都不含被改写的已有测试。

**已知的松散端与取舍**

- **`create_user` 里「不是邮箱冲突就原样抛」那个分支没有测试**（Step 9 已如实标注）。`users` 表上没有第二个可达约束，`role` 的 CHECK 在它之前已被 `ROLES` 守卫拦成 `ValueError`。这是为将来加列留的对称写法，不是被验证过的行为。
- **`test_admin_lists_users` 的排序断言强度偏低**：去掉 `order_by` 后它多半 FAIL 但无硬保证（无 `ORDER BY` 时顺序未定义）。
- **`test_the_duplicate_email_error_leaves_the_session_usable` 测的是 savepoint 隔离，而它可观察是因为测试里三次请求共享一个 session**。生产每请求独立 session，这个失效模式本来就不出现；savepoint 真正的受益方是 CLI 批量建号那类「出错后还要接着跑」的调用。测试的 docstring 里写清了，别把它当成「生产会 500」的证据。
- **两个 router 各自重复了 `_Db` / `_Admin` / responses 常量四行**。没抽公共模块：跨 router import 注解别名会让两个 router 互相耦合，成本高于这四行重复。P2b 加第三个 router 时如果还是同一组，再考虑抽。
- **`login` 的 cookie 参数会进 OpenAPI**（P1 §10.4 已记）。本段新增的三条 OpenAPI 断言只查 `responses` 的状态码集合，不查参数，所以不受影响；但 P4 生成前端类型时仍会看到那个多余的可选参数。
- **`delete_grant` 不校验 `user_id` 是否存在**。撤销一个不存在用户的授权与撤销一个不存在的授权结果相同（都是「现在没有」），多一次查询换不到任何信息。
- **没有「批量授权」端点**。一次 PUT 一个用户，前端要给 N 个人授权就发 N 次请求。私有化部署的团队规模下够用；真需要再加 `PUT /grants:batch`，不要把单条那个改成收数组（会破坏已生成的前端类型）。
- **`viewer` 与 `analyst` 在本段行为完全相同**。差别在 P3 的执行权限上，Global Constraints 已明说不要提前引入差别；`test_viewer_cannot_create` 存在只是为了钉住「viewer 也不能写数据源」。
- **不能加 `pytest-xdist`**（沿用 P1 §10.4）。

**类型一致性核对**

跨任务与跨文件引用已逐一对齐：`require_datasource` 的路径参数名 `datasource_id` 与三条路由的 `/{datasource_id}` 一致（名字不符会让 FastAPI 把它当查询参数，行为是 422 而不是报错，很难查）· `_Target` / `_Db` / `_Admin` 在 Task 5 定义、Task 6 的三条 grants 路由直接复用 · `_TARGET` 等 responses 常量的名字与 Task 5 定义一致（大写是 responses 字典，首字母大写驼峰是注解别名，两套不混）· `GrantRequest.user_id: uuid.UUID` 与 `set_grant(user_id=...)` 类型一致 · `GrantResponse` 的三个字段与 `DatasourceGrant` 的三列同名，`from_attributes` 才取得到 · `UserCreateRequest` 的四个字段与 `create_user` 的四个关键字参数同名同序 · `get_user` / `list_users` 在 Task 6 定义并只在同任务消费 · 上游 `create_datasource(session, *, payload, created_by)` 的关键字形式在 Task 5 的 `create` 里按同样写法调用。

无「Task N 定义、Task M 改名」的情况。跨文件的三处引用（`violated_constraint`、`revoke_grant` 的返回值语义、`read_password` 的调用方归属）都已回上游那份同步。
