# Chat-BI V2-1 · P2a 数据源持久化与凭据 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P1 的认证基座上加一层数据源**领域层**：`datasources` 与 `datasource_grants` 两张表、AES-GCM 加密的连接凭据、仓储层的 CRUD 与授权可见性过滤，并清掉 P1 遗留里的六项（1、2、4、6、7、8）。HTTP 端点与剩下两项遗留（3、5）在下游那份。

**范围边界：本份结束时后端一行 HTTP 数据源代码都没有。** 这不是漏掉，而是 spec §1.3 规则 2 的验证方式——可见性判断必须能脱离 HTTP 测。

**Architecture:** `datasources/` 是新的领域模块，内部分三层——`crypto.py` 只做密钥派生与 AEAD（不碰 DB）、`repository.py` 只做持久化与可见性判断（不碰 HTTP）、`api/datasource_router.py` 只做 HTTP 编排（不含业务判断）。依赖方向照 spec §1.3：`api` → `datasources` → `db`。本段**不连接任何外部数据库**，驱动与 `/test` 端点属 P2b。

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · cryptography（AESGCM + HKDF）· pytest

**上游 spec:** [2026-08-11-chatbi-v2-1-design.md](../specs/2026-08-11-chatbi-v2-1-design.md)（§2.4 REST 端点、§2.5 数据模型、§2.6 错误码、§4.2 授权分层、§4.4 凭据与日志脱敏）
**上游计划:** [P1 后端基座与认证](2026-08-11-chatbi-v2-1-p1-backend-foundation.md)（§交接清单 = 本段消费的签名；§10.3 = 本段要清的遗留）
**下游计划:**
1. [P2a HTTP 层：数据源与用户端点](2026-08-13-chatbi-v2-1-p2a-datasource-api.md)——Task 5、6，直接消费本份末尾「交接清单」的签名。
2. P2b 三驱动与示例库（`2026-08-13-chatbi-v2-1-p2b-drivers-demo.md`），消费 HTTP 层那份末尾的交接清单。

## Global Constraints

每个任务的要求都隐含包含本节。数值全部照 spec 原样抄。

**版本与依赖**
- Python 3.12。依赖用 `pyproject.toml` + `uv`（`uv sync` / `uv run`）。
- P2a **只新增一个依赖**：`cryptography>=44`（AESGCM + HKDF）。不引入 `passlib`、不引入 `sqlalchemy-utils`、不引入任何"加密便利库"——AEAD 的正确用法是三行调用，包一层只会藏起 nonce 管理。
- 驱动依赖（`pymysql`、`clickhouse-connect`）属 P2b，本段不装。
- **V2-1 不装 pgvector**（spec §0.4）。

**数据库**
- 应用库 Postgres 16。所有表结构变更走 Alembic，不用 `create_all()`。新 migration 编号从 `0002` 起，`down_revision = "0001"`。
- 每个 migration 必须过 up/down 双向测试（spec §5.3）：扩 `tests/test_migrations.py` 的断言集合到新表。
- 测试库通过 `TEST_DATABASE_URL` 指定，库名必须以 `_test` 结尾（P1 的 `conftest.py` 守卫，不要改）。
- 应用库测试**不允许 skip**，缺库就是失败。（spec §5.1 的「skip 要计数上报」针对外部数据源驱动，属 P2b。）
- **不能加 `pytest-xdist`**：`test_migrations.py` 会短暂把库降到空表，并行会互相清表（P1 §10.4）。

**凭据与脱敏（spec §4.4，本段的红线）**
- 数据源密码用 AES-GCM 加密后存 `secret_ciphertext` + `secret_nonce` 两列。
- 主密钥从 `CHATBI_SECRET_KEY` / `CHATBI_SECRET_KEY_FILE` 读（P1 已实现），**不入库、不入日志、不进任何错误消息**。承载它的对象 `repr()` 必须脱敏。
- 数据源的 Pydantic 响应模型**不声明**任何密码/密文/nonce 字段——靠模型不含字段，而不是靠序列化时记得排除。
- 每次写入密码都换新 nonce。**nonce 绝不复用**：AES-GCM 下同密钥重用 nonce 会直接泄露明文异或与认证密钥。
- 错误消息不回显地址、端口、库名、用户名。地址端口进服务端日志，不进 HTTP 响应。

**授权（spec §4.2）**
- 角色三个：`admin`（管数据源与用户）/ `analyst`（问数、改 SQL、执行）/ `viewer`（只看历史，不能执行）。
- 数据源的**写操作（建/改/删/授权）只有 `admin`**。
- 数据源的**可见性**：`admin` 看全部；`analyst` / `viewer` 只看 `datasource_grants` 里 `can_query = true` 的。未授权数据源不出现在列表里，直接按 id 访问返回 `PERMISSION_DENIED`（spec §2.6：不列出哪些表/字段，也不透露是否存在结构信息）。
- 行级 / 列级权限本段不做，`PolicyResolver` 属 P3（spec §4.2）。

**错误码**（spec §2.6 的 P2a 子集，响应体统一 `{"code": ..., "message": ...}`）
- 复用 P1：`NOT_AUTHENTICATED`(401) · `PERMISSION_DENIED`(403) · `USER_NOT_FOUND`(404) · `EMAIL_ALREADY_EXISTS`(409)
- 本段新增：`DATASOURCE_NOT_FOUND`(404) · `DATASOURCE_NAME_EXISTS`(409)
- `CONNECTION_ERROR` 属 P2b（`/test` 端点才有连接行为），本段不加。

**契约**
- Pydantic 模型是 OpenAPI 唯一真相源。每个路由必须带完整 `response_model` 与 `responses` 声明，否则 P4 生成的前端类型会缺字段。

**流程**
- TDD：先写失败的测试 → 跑一次确认失败 → 写最小实现 → 跑一次确认通过 → 提交。
- **覆盖测试必须两个方向都验证**（P1 §10.2 的教训）：写完一条"防御性"测试后，临时把被测的防御删掉/改回旧行为，确认测试**真的失败**，再恢复。删掉防御照样通过的测试等于没测。
- 提交信息用 `feat:` / `test:` / `fix:` / `chore:` / `docs:` 前缀，末尾带 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`。
- 当前分支 `feature_v2.0`，不切新分支。

## 本机环境（2026-08-13 实测）

- 原生 PostgreSQL 16 可用：`localhost:5432`，账号 `chatbi`/`chatbi`，`chatbi` 与 `chatbi_test` 两库已建好。
- **Docker 守护进程仍不可用**：Docker Desktop 已装，但 WSL2 无任何发行版（`wsl -l -v` 只打出用法帮助）。P2a **完全不需要 Docker**——本段不连外部库。Docker 是 P2b 最后一个门禁任务的前置。
- `uv run pytest` 前需要的环境变量：

```bash
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
```

- 所有命令在 `apps/api/` 下跑（`cd apps/api`）。P1 基线：`uv run pytest` → **53 passed**。

---

## File Structure

### 本份创建的文件（Task 1–4）

| 文件 | 职责 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/api/routers.py` | router 注册接缝：`ALL_ROUTERS` 元组（消化 P1 遗留 8） | 1 |
| `apps/api/src/chatbi/datasources/__init__.py` | 包标记（空文件） | 2 |
| `apps/api/src/chatbi/datasources/crypto.py` | 主密钥派生（HKDF）+ AES-GCM 加解密。不碰 DB、不认识 ORM | 2 |
| `apps/api/migrations/versions/0002_datasources.py` | 建 `datasources`、`datasource_grants` | 3 |
| `apps/api/src/chatbi/db/integrity.py` | 从 `IntegrityError` 取违反的约束名。仓储与 Task 6 的 `provisioning` 共用 | 4 |
| `apps/api/src/chatbi/datasources/schemas.py` | 数据源与授权的请求/响应 Pydantic 模型 | 4 |
| `apps/api/src/chatbi/datasources/repository.py` | 持久化、可见性过滤、密码存取。不 import fastapi | 4 |
| `apps/api/tests/test_app_assembly.py` | 真 app 上的 router 装配与错误信封 | 1 |
| `apps/api/tests/test_crypto.py` | 加解密、nonce 唯一、篡改检测、AAD 绑定、主密钥脱敏 | 2 |
| `apps/api/tests/test_datasource_models.py` | 表级约束：唯一名、kind CHECK、secret 成对、级联 | 3 |
| `apps/api/tests/test_datasource_repository.py` | CRUD、唯一名 409、可见性过滤、密码往返与 nonce 轮换 | 4 |

### 属于 [HTTP 层那份](2026-08-13-chatbi-v2-1-p2a-datasource-api.md) 的文件（列在这里便于对照，**不在本份实施**）

| 文件 | 职责 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/datasources/deps.py` | `require_datasource`（按 id 取 + 可见性判定 + 抛 `ApiError`） | 5 |
| `apps/api/src/chatbi/api/datasource_router.py` | `/api/datasources` CRUD 与 grants 的 HTTP 编排 | 5、6 |
| `apps/api/src/chatbi/api/user_router.py` | `/api/users` admin 开号与列表（消化 P1 遗留 3、5） | 6 |
| `apps/api/tests/test_datasource_router.py` · `test_datasource_grants.py` · `test_user_router.py` | 端点鉴权、响应无凭据字段、错误码、授权联动 | 5、6 |

### 本份修改的文件（Task 1–4）

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/main.py` | 改为遍历 `ALL_ROUTERS` 挂载 | 1 |
| `apps/api/src/chatbi/api/auth_router.py` | 登录路径接 `purge_expired`；identity provider 改依赖注入；`logout` 的 `delete_cookie` 补齐属性 | 1 |
| `apps/api/src/chatbi/auth/identity.py` | `_DUMMY_HASH` 惰性化；`get_identity_provider` 加 `lru_cache` | 1 |
| `apps/api/tests/test_auth_router.py` | 追加三条（遗留 1、2、6 各一条） | 1 |
| `.gitignore` | 只删 `*.db*` 与 `data/`（P1 遗留 7） | 1 |
| `apps/api/pyproject.toml` | 加 `cryptography>=44` | 2 |
| `apps/api/src/chatbi/errors.py` | 加 `DATASOURCE_NOT_FOUND`、`DATASOURCE_NAME_EXISTS` | 3 |
| `apps/api/src/chatbi/db/models.py` | 加 `DATASOURCE_KINDS`、`Datasource`、`DatasourceGrant`（Task 3）；给 `Datasource` 加 `has_password` 属性（Task 4） | 3、4 |
| `apps/api/tests/conftest.py` | 加 `make_datasource` 夹具 | 3 |
| `apps/api/tests/test_migrations.py` | 断言集合扩到新表 | 3 |

`apps/api/src/chatbi/auth/provisioning.py`（补 `IntegrityError` → `EMAIL_ALREADY_EXISTS`，P1 遗留 3）与 `conftest.py` 的 `admin_client` 夹具属 HTTP 层那份的 Task 6——遗留 3 的错误表面只有挂到 HTTP 端点上才有意义，提前改就没有测试能证明它对。

### 边界说明

`crypto.py` 不 import 任何 `chatbi.db.*`：它的输入输出都是 `bytes` 与 `str`，这样密码学部分能脱离数据库单测，也不会在 ORM 层意外触发解密。`repository.py` 不 import `fastapi`：可见性判断（"这个用户能看见这个数据源吗"）是领域逻辑，必须能脱离 HTTP 测（spec §1.3 规则 2）。`deps.py` 是唯一同时认识 FastAPI 与 repository 的文件，只做「取 + 判定 + 抛 `ApiError`」。router 里不出现 `select()`（spec §1.3 规则 4：`db` 是叶子，领域模块经仓储函数访问）。后两条在 [HTTP 层那份](2026-08-13-chatbi-v2-1-p2a-datasource-api.md) 落地，写在这里是因为它们约束的是本份产出的仓储接口该长什么样——`get_visible` 之所以把可见性折进 SQL 并返回 `None`，就是为了让 router 无需自己判断。

---

### Task 1: 清掉 P1 遗留并搭起 router 注册接缝

先把 P1 §10.3 的遗留 1、2、4、6、7、8 一次清完，再动数据源。这些都是"改动到那个文件时顺手做"的事，攒到后面会和新代码搅在一条 diff 里，出问题时分不清是谁的锅。

**Files:**
- Create: `apps/api/src/chatbi/api/routers.py`
- Create: `apps/api/tests/test_app_assembly.py`
- Modify: `apps/api/src/chatbi/main.py:1-8`
- Modify: `apps/api/src/chatbi/api/auth_router.py:1-58`
- Modify: `apps/api/src/chatbi/auth/identity.py:9-38`
- Modify: `apps/api/tests/test_auth_router.py`（追加三条测试）
- Modify: `.gitignore:3-6`

**Interfaces:**
- Consumes（P1 交接清单）：`chatbi.auth.sessions.purge_expired(session) -> int` · `chatbi.auth.identity.get_identity_provider() -> IdentityProvider` · `chatbi.auth.deps.SESSION_COOKIE` · `chatbi.config.get_settings()`
- Produces:
```python
chatbi.api.routers.ALL_ROUTERS: tuple[APIRouter, ...]
# Task 5 与 Task 6 只往这个元组里加一项，不再改 main.py
chatbi.auth.identity.get_identity_provider
# 现在被 Depends() 消费，测试可用 app.dependency_overrides 替换
```

- [ ] **Step 1: 写失败的测试**

新建 `apps/api/tests/test_app_assembly.py`：

```python
"""针对 main.py 装配本身的测试。

P1 §10.4 接缝 ②：`role_client` 那类夹具会自己重建 app 并重新注册异常处理器，
因此真 app 上注册失效时它们照样绿。本文件只用真 app（`client` 夹具只覆盖 get_db）。
"""

from fastapi.testclient import TestClient

from chatbi.api.routers import ALL_ROUTERS


def test_all_routers_are_mounted_on_the_real_app() -> None:
    """用 OpenAPI 的 paths 而不是 app.routes 的 path 集合。

    FastAPI 0.141 起 include_router 在 app.routes 里留下的是**一个**
    `_IncludedRouter` 包装对象，不再把子路由摊平进去，因此按 route.path 收集
    会得到一个不含任何业务路径的集合。OpenAPI 的 paths 跨版本稳定，而且它
    表达的正是「对外暴露了哪些路径」。
    """
    from chatbi.main import app

    exposed = set(app.openapi()["paths"])
    for router in ALL_ROUTERS:
        for route in router.routes:
            assert getattr(route, "path", None) in exposed


def test_real_app_returns_the_error_envelope_on_401(client: TestClient) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"code": "NOT_AUTHENTICATED", "message": "请先登录"}
```

在 `apps/api/tests/test_auth_router.py` 末尾追加三条：

```python
def test_login_purges_expired_sessions(client: TestClient, db_session, make_user) -> None:
    """P1 §10.3 遗留 1：purge_expired 终于有调用方，过期行不再无限堆积。"""
    import uuid
    from datetime import UTC, datetime, timedelta

    from chatbi.db.models import UserSession

    user = make_user(email="ann@example.com", password="pw-12345678")
    stale = UserSession(
        id=uuid.uuid4(), user_id=user.id, expires_at=datetime.now(UTC) - timedelta(hours=1)
    )
    db_session.add(stale)
    db_session.flush()

    response = client.post(
        "/api/auth/login", json={"email": "ann@example.com", "password": "pw-12345678"}
    )

    assert response.status_code == 200
    # expire_all 后 get() 必然回库查一次，不会读到身份映射里的旧对象而假性通过
    db_session.expire_all()
    assert db_session.get(UserSession, stale.id) is None


def test_identity_provider_is_an_overridable_dependency(client: TestClient, make_user) -> None:
    """P1 §10.3 遗留 2：改成 Depends 之后身份来源才可替换（OIDC 的前置）。"""
    from chatbi.auth.identity import get_identity_provider
    from chatbi.main import app

    user = make_user(email="ann@example.com", password="pw-12345678")

    class AlwaysYes:
        def authenticate(self, session, email, password):
            return user

    app.dependency_overrides[get_identity_provider] = AlwaysYes
    try:
        response = client.post(
            "/api/auth/login",
            json={"email": "ann@example.com", "password": "wrong-on-purpose"},
        )
    finally:
        app.dependency_overrides.pop(get_identity_provider, None)

    assert response.status_code == 200


def test_logout_restates_the_cookie_attributes_when_deleting(
    client: TestClient, make_user
) -> None:
    """P1 §10.3 遗留 6：删除指令与设置指令的属性一致，浏览器不会各自解读。"""
    make_user(email="ann@example.com", password="pw-12345678")
    client.post("/api/auth/login", json={"email": "ann@example.com", "password": "pw-12345678"})

    header = client.post("/api/auth/logout").headers["set-cookie"].lower()

    assert "httponly" in header
    assert "samesite=lax" in header
    assert "max-age=0" in header
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd apps/api
uv run pytest tests/test_app_assembly.py tests/test_auth_router.py -v
```

预期：`test_app_assembly.py` 收集期 `ModuleNotFoundError: chatbi.api.routers`；三条新增分别在 `stale` 行仍存在、401（override 未生效）、`set-cookie` 缺 `httponly` 上失败。

- [ ] **Step 3: 建 router 注册接缝**

新建 `apps/api/src/chatbi/api/routers.py`：

```python
from fastapi import APIRouter

from chatbi.api.auth_router import router as auth_router

# 挂载顺序即声明顺序。新增 router 只改这一处——main.py 从此不随功能增长而变。
ALL_ROUTERS: tuple[APIRouter, ...] = (auth_router,)
```

`apps/api/src/chatbi/main.py` 整文件替换：

```python
from fastapi import FastAPI

from chatbi.api.routers import ALL_ROUTERS
from chatbi.errors import ApiError, api_error_handler

app = FastAPI(title="Chat-BI API", version="0.1.0")
app.add_exception_handler(ApiError, api_error_handler)
for _router in ALL_ROUTERS:
    app.include_router(_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: 惰性化 `_DUMMY_HASH`**

`apps/api/src/chatbi/auth/identity.py`——把第 9-10 行的模块级常量换成 `functools.cache` 函数，并在 `LocalIdentityProvider.authenticate` 里改成调用它；同时给 `get_identity_provider` 加 `lru_cache`（provider 无状态，共享实例即可，`dependency_overrides` 不受影响）：

```python
from functools import cache, lru_cache
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from chatbi.auth.hashing import hash_password, verify_password
from chatbi.db.models import User


@cache
def _dummy_hash() -> str:
    """邮箱不存在时也走一次哈希校验，让成功与失败路径耗时接近，不泄露账号是否存在。

    惰性算：放模块级会让每次 CLI 调用和每轮 pytest 收集都白付一次 Argon2。
    """
    return hash_password("timing-equalizer")
```

`authenticate` 里 `verify_password(password, _DUMMY_HASH)` → `verify_password(password, _dummy_hash())`。文件末尾：

```python
@lru_cache
def get_identity_provider() -> IdentityProvider:
    return LocalIdentityProvider()
```

- [ ] **Step 5: 接线 `purge_expired`、改 provider 为依赖、补 `delete_cookie` 属性**

`apps/api/src/chatbi/api/auth_router.py`——import 段加 `IdentityProvider`、`purge_expired`，`login` 签名多一个依赖：

```python
from chatbi.auth.identity import IdentityProvider, get_identity_provider
from chatbi.auth.sessions import create_session, delete_session, purge_expired
```

```python
@router.post("/login", response_model=UserResponse, responses={401: {"model": ErrorResponse}})
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[IdentityProvider, Depends(get_identity_provider)],
    chatbi_session: Annotated[str | None, Cookie()] = None,
) -> User:
    user = identity.authenticate(db, payload.email, payload.password)
    if user is None:
        raise ApiError(*INVALID_CREDENTIALS)
    # 过期会话在这里回收。放在认证成功之后：未认证的请求不该驱动写事务，
    # 否则任何人都能靠刷登录接口制造 DELETE 负载。
    purge_expired(db)
```

其余保持原样（`delete_session` → `create_session` → `set_cookie` → `db.commit()`）。`logout` 的最后一行改成：

```python
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
    )
```

- [ ] **Step 6: 清 `.gitignore`（P1 遗留 7）**

只删 SQLite 与 `data/` 三类共四行：`data/`、`*.db`、`*.db-shm`、`*.db-wal`。**保留** `node_modules/`、`dist/`（P4 要用）与 `*.key`（主密钥文件的兜底，删了等于给密钥开一条进仓库的路）。

- [ ] **Step 7: 跑全量确认通过**

```bash
cd apps/api
uv run pytest -q && uv run ruff check src tests
```

预期：`58 passed`（P1 基线 53 + 本任务 5 条：`test_app_assembly.py` 两条 + `test_auth_router.py` 追加三条），ruff 无告警。基线 53 是 2026-08-17 实测的 `--collect-only` 值。

- [ ] **Step 8: 反向验证四条防御（两个方向都要跑）**

逐条临时改回旧行为，确认对应测试**真的失败**，再恢复：

1. 注释掉 `purge_expired(db)` → `test_login_purges_expired_sessions` 必须 FAIL。
2. `login` 改回 `get_identity_provider().authenticate(...)` 并删掉 `identity` 参数 → `test_identity_provider_is_an_overridable_dependency` 必须 FAIL。
3. `delete_cookie` 改回只带 `path="/"` → `test_logout_restates_the_cookie_attributes_when_deleting` 必须 FAIL。
4. `main.py` 改回 `app.include_router(auth_router)` 但让 `ALL_ROUTERS` 多一个空 `APIRouter(prefix="/api/x")` 且带一条路由 → `test_all_routers_are_mounted_on_the_real_app` 必须 FAIL。

第 4 条的形状特殊：`ALL_ROUTERS` 只有一个元素时，"遍历挂载"和"直接挂 auth_router"行为相同，测试无鉴别力。必须临时构造第二个 router 才能证明它在测装配而不是在测 `auth_router` 存在。

- [ ] **Step 9: 提交**

```bash
git add apps/api/src/chatbi apps/api/tests .gitignore
git commit -m "$(cat <<'EOF'
chore: clear P1 leftovers and add a router registration seam

purge_expired wired into the login path, identity provider becomes an
injectable dependency, _DUMMY_HASH goes lazy, logout restates cookie
attributes, .gitignore drops the SQLite-era entries.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 主密钥派生与 AES-GCM 封装

**这个任务不碰数据库。** `crypto.py` 的输入输出只有 `bytes` 与 `str`，所以密码学部分能脱离 Postgres 单测，也不会在 ORM 属性访问时意外触发解密。

**Files:**
- Create: `apps/api/src/chatbi/datasources/__init__.py`（空文件，包标记）
- Create: `apps/api/src/chatbi/datasources/crypto.py`
- Create: `apps/api/tests/test_crypto.py`
- Modify: `apps/api/pyproject.toml:5-15`（加 `cryptography>=44`）

**Interfaces:**
- Consumes: `chatbi.config.get_settings()`（`settings.secret_key: SecretStr | None`，实例化后必非 None）
- Produces:
```python
chatbi.datasources.crypto.NONCE_BYTES: int            # 12
chatbi.datasources.crypto.SealedSecret               # frozen dataclass: ciphertext: bytes, nonce: bytes
chatbi.datasources.crypto.SecretDecryptionError      # Exception
chatbi.datasources.crypto.MasterKey                  # repr 恒为掩码
chatbi.datasources.crypto.get_master_key() -> MasterKey          # lru_cache，测试需 cache_clear()
chatbi.datasources.crypto.aad_for_datasource(datasource_id: uuid.UUID) -> bytes
chatbi.datasources.crypto.seal(plaintext: str, *, aad: bytes) -> SealedSecret
chatbi.datasources.crypto.unseal(sealed: SealedSecret, *, aad: bytes) -> str
```

- [ ] **Step 1: 装依赖**

`apps/api/pyproject.toml` 的 `dependencies` 末尾加一行 `"cryptography>=44",`，然后：

```bash
cd apps/api
uv sync
```

- [ ] **Step 2: 写失败的测试**

新建 `apps/api/tests/test_crypto.py`：

```python
"""crypto.py 的单元测试。整个文件不需要数据库——这正是把它与 repository 分开的意义。"""

import os
import uuid

import pytest

from chatbi.config import get_settings
from chatbi.datasources.crypto import (
    NONCE_BYTES,
    MasterKey,
    SealedSecret,
    SecretDecryptionError,
    aad_for_datasource,
    get_master_key,
    seal,
    unseal,
)

AAD = aad_for_datasource(uuid.UUID("11111111-1111-1111-1111-111111111111"))
OTHER_AAD = aad_for_datasource(uuid.UUID("22222222-2222-2222-2222-222222222222"))


def test_seal_then_unseal_returns_the_original_password() -> None:
    sealed = seal("p@ssw0rd 带中文", aad=AAD)

    assert unseal(sealed, aad=AAD) == "p@ssw0rd 带中文"


def test_ciphertext_never_contains_the_plaintext() -> None:
    sealed = seal("supersecret", aad=AAD)

    assert b"supersecret" not in sealed.ciphertext


def test_every_seal_uses_a_fresh_nonce() -> None:
    """AES-GCM 下同密钥重用 nonce 会直接泄露明文异或与认证密钥，这是硬红线。"""
    sealeds = [seal("same-password", aad=AAD) for _ in range(64)]

    nonces = {s.nonce for s in sealeds}
    assert len(nonces) == 64
    assert all(len(n) == NONCE_BYTES for n in nonces)
    # 相同明文 + 相同 AAD 也必须产出不同密文，否则等值密文本身就是一条侧信道
    assert len({s.ciphertext for s in sealeds}) == 64


def test_tampered_ciphertext_is_rejected() -> None:
    sealed = seal("p@ssw0rd", aad=AAD)
    flipped = bytearray(sealed.ciphertext)
    flipped[0] ^= 0x01

    with pytest.raises(SecretDecryptionError):
        unseal(SealedSecret(ciphertext=bytes(flipped), nonce=sealed.nonce), aad=AAD)


def test_tampered_nonce_is_rejected() -> None:
    sealed = seal("p@ssw0rd", aad=AAD)

    with pytest.raises(SecretDecryptionError):
        unseal(SealedSecret(ciphertext=sealed.ciphertext, nonce=os.urandom(NONCE_BYTES)), aad=AAD)


def test_ciphertext_is_bound_to_its_datasource() -> None:
    """把 A 的密文行搬到 B 上不能解开：AAD 绑定了数据源 id。

    否则一个能写库的攻击者可以把生产库的凭据密文挪到一个指向自己主机的
    数据源上，让后端拿着生产密码去连他的服务器。
    """
    sealed = seal("p@ssw0rd", aad=AAD)

    with pytest.raises(SecretDecryptionError):
        unseal(sealed, aad=OTHER_AAD)


def test_decryption_error_leaks_nothing() -> None:
    sealed = seal("supersecret", aad=AAD)

    with pytest.raises(SecretDecryptionError) as exc_info:
        unseal(sealed, aad=OTHER_AAD)

    text = str(exc_info.value)
    assert "supersecret" not in text
    assert sealed.ciphertext.hex() not in text
    assert get_settings().secret_key.get_secret_value() not in text


def test_master_key_is_masked_in_repr_and_str() -> None:
    """密钥对象会出现在异常回溯的局部变量表里，那里是日志的一条旁路。"""
    key = get_master_key()
    material = os.environ["CHATBI_SECRET_KEY"]

    assert repr(key) == "MasterKey(***)"
    assert str(key) == "MasterKey(***)"
    assert material not in repr(key)
    assert not any("material" in name and not name.startswith("_") for name in dir(key))


def test_key_derivation_is_deterministic_and_key_dependent(monkeypatch) -> None:
    """同主密钥重启后仍能解开旧密文；换主密钥则解不开（而不是解出乱码）。"""
    sealed = seal("p@ssw0rd", aad=AAD)
    original = os.environ["CHATBI_SECRET_KEY"]

    def rebuild(secret: str) -> None:
        monkeypatch.setenv("CHATBI_SECRET_KEY", secret)
        get_settings.cache_clear()
        get_master_key.cache_clear()

    rebuild(original)
    assert unseal(sealed, aad=AAD) == "p@ssw0rd"

    rebuild("a-completely-different-master-key")
    with pytest.raises(SecretDecryptionError):
        unseal(sealed, aad=AAD)

    # 缓存必须还原，否则后续测试会拿着假密钥跑
    rebuild(original)
    get_settings.cache_clear()
    get_master_key.cache_clear()


def test_master_key_rejects_wrong_length_material() -> None:
    with pytest.raises(ValueError):
        MasterKey(b"too-short")
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd apps/api
uv run pytest tests/test_crypto.py -v
```

预期：收集期 `ModuleNotFoundError: No module named 'chatbi.datasources'`。

- [ ] **Step 4: 写实现**

新建空文件 `apps/api/src/chatbi/datasources/__init__.py`，然后 `apps/api/src/chatbi/datasources/crypto.py`：

```python
"""数据源凭据的 AEAD 封装。

只认识 bytes 与 str：不 import 任何 chatbi.db.*，也不认识 ORM（spec §1.3）。
"""

import os
import uuid
from dataclasses import dataclass
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from chatbi.config import get_settings

KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12  # AES-GCM 的标准 nonce 长度；换长度会让已存密文解不开
# HKDF 的 info 做域分隔：将来别的用途（比如导出签名）从同一主密钥派生时，
# 换一个 info 就是一把互不相关的子密钥。带 :v1 是为了留轮换的余地。
HKDF_INFO = b"chatbi:datasource-secret:v1"


class SecretDecryptionError(Exception):
    """密文与主密钥或 AAD 不匹配。异常本身不携带密文、密钥或明文。"""


@dataclass(frozen=True)
class SealedSecret:
    """一条已加密的凭据。两个字段直接对应表里的两列。"""

    ciphertext: bytes
    nonce: bytes


class MasterKey:
    """派生出的 AES-256 密钥。

    repr/str 恒为掩码：这个对象会出现在异常回溯的局部变量表里，而 pytest 的
    `--showlocals`、以及大多数错误上报工具都会把局部变量原样打出来。
    密钥材料只在 aesgcm() 内部使用，不提供任何取出它的公开途径（spec §4.4）。
    """

    __slots__ = ("_material",)

    def __init__(self, material: bytes) -> None:
        if len(material) != KEY_BYTES:
            raise ValueError(f"派生密钥必须是 {KEY_BYTES} 字节，收到 {len(material)}")
        self._material = material

    def __repr__(self) -> str:
        return "MasterKey(***)"

    __str__ = __repr__

    def aesgcm(self) -> AESGCM:
        return AESGCM(self._material)


@lru_cache
def get_master_key() -> MasterKey:
    """从配置里的主密钥派生 AEAD 密钥。

    salt 恒为 None（RFC 5869 允许）：派生必须确定性，否则重启后解不开旧密文。
    改主密钥后测试里要 get_settings.cache_clear() + get_master_key.cache_clear()。
    """
    secret = get_settings().secret_key
    # 声明类型是 SecretStr | None，但 Settings 的 after-validator 保证实例化后必非 None
    assert secret is not None, "主密钥未配置——Settings 校验本应已拦下"
    material = HKDF(
        algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=HKDF_INFO
    ).derive(secret.get_secret_value().encode("utf-8"))
    return MasterKey(material)


def aad_for_datasource(datasource_id: uuid.UUID) -> bytes:
    """把密文绑定到它所属的数据源，防止密文行被搬到另一个数据源上。"""
    return f"datasource:{datasource_id}".encode()


def seal(plaintext: str, *, aad: bytes) -> SealedSecret:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = get_master_key().aesgcm().encrypt(nonce, plaintext.encode("utf-8"), aad)
    return SealedSecret(ciphertext=ciphertext, nonce=nonce)


def unseal(sealed: SealedSecret, *, aad: bytes) -> str:
    try:
        raw = get_master_key().aesgcm().decrypt(sealed.nonce, sealed.ciphertext, aad)
    except InvalidTag as exc:
        # 不用 from exc 之外的方式携带上下文：InvalidTag 本身不含明文，
        # 但消息里绝不能拼进密文或 AAD。
        raise SecretDecryptionError("凭据无法解密") from exc
    return raw.decode("utf-8")
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd apps/api
uv run pytest tests/test_crypto.py -v && uv run ruff check src tests
```

预期：`tests/test_crypto.py` 10 passed。此时跑全量是 `68 passed`（Task 1 后的 58 + 本任务 10 条）。

- [ ] **Step 6: 反向验证三条红线**

1. `seal` 里把 `nonce = os.urandom(NONCE_BYTES)` 改成 `nonce = b"\x00" * NONCE_BYTES` → `test_every_seal_uses_a_fresh_nonce` 必须 FAIL。恢复。
2. `seal`/`unseal` 里把 `aad` 参数换成 `None` 传给 AESGCM → `test_ciphertext_is_bound_to_its_datasource` 与 `test_decryption_error_leaks_nothing` 必须 FAIL。恢复。
3. 删掉 `MasterKey.__repr__` 与 `__str__`（退回默认 object repr）→ `test_master_key_is_masked_in_repr_and_str` 必须 FAIL。恢复。

第 3 条要特别跑：默认 `object.__repr__` 不打印 `__slots__` 内容，所以"密钥出现在 repr 里"这条**在本实现下天然不成立**，测试真正钉的是 `repr` 的字面形状。跑完确认它确实因为 `!= "MasterKey(***)"` 而失败——如果它是因为别的原因失败，说明断言写错了。

- [ ] **Step 7: 提交**

```bash
git add apps/api/pyproject.toml apps/api/uv.lock apps/api/src/chatbi/datasources apps/api/tests/test_crypto.py
git commit -m "$(cat <<'EOF'
feat(datasources): AES-GCM credential sealing with HKDF-derived key

Nonce is fresh per seal, ciphertext is AAD-bound to its datasource id,
and the derived key object masks itself in repr.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `datasources` 与 `datasource_grants` 两张表

表结构先落地，仓储逻辑留给 Task 4。本任务的测试全部钉**数据库约束**而不是 Python 校验：应用层的检查会被绕过（CLI、直连 psql、将来的批量导入），DB 约束不会。

一处会影响 Task 4 的设计约束：主键**必须由应用生成**（`default=uuid.uuid4`，客户端侧），不能用 DB 侧的 `gen_random_uuid()`。因为 AAD 绑的是数据源 id（Task 2 的 `aad_for_datasource`），加密时就得先知道 id——先 INSERT 拿 id 再回填密文会多一次写，且中间那一瞬是 secret 两列为空的半写行。

**Files:**
- Modify: `apps/api/src/chatbi/db/models.py:9`（追加 `DATASOURCE_KINDS` 与两个模型）
- Modify: `apps/api/src/chatbi/errors.py:9-10`（加两个错误码）
- Create: `apps/api/migrations/versions/0002_datasources.py`
- Create: `apps/api/tests/test_datasource_models.py`
- Modify: `apps/api/tests/conftest.py:103`（追加 `make_datasource` 夹具）
- Modify: `apps/api/tests/test_migrations.py:22-30`（断言集合扩到新表）

**Interfaces:**
- Consumes: `chatbi.db.base.Base` · `chatbi.db.models.User` · `chatbi.datasources.crypto.seal` · `chatbi.datasources.crypto.aad_for_datasource`（Task 2）
- Produces:
```python
chatbi.db.models.DATASOURCE_KINDS: tuple[str, str, str]   # ("postgres", "mysql", "clickhouse")
chatbi.db.models.Datasource       # 列见 Step 4；secret_ciphertext/secret_nonce 同时为空或同时非空
chatbi.db.models.DatasourceGrant  # 复合主键 (datasource_id, user_id)，can_query: bool
chatbi.errors.DATASOURCE_NOT_FOUND   = ("DATASOURCE_NOT_FOUND", "数据源不存在", 404)
chatbi.errors.DATASOURCE_NAME_EXISTS = ("DATASOURCE_NAME_EXISTS", "该数据源名称已存在", 409)
# conftest 夹具，Task 4/5/6 都用：
make_datasource(*, name=None, kind="postgres", host="db.internal", port=5432,
                database="analytics", username="ro_user", password="ds-pw-123456",
                options=None, is_readonly_verified=False, created_by=None) -> Datasource
```

- [ ] **Step 1: 写失败的测试**

先在 `apps/api/tests/conftest.py` 末尾追加夹具（`make_datasource` 是 Task 4、5、6 共用的，现在就放 conftest，别在各测试文件里各写一份——P1 §10.1 第 4 条就是攒到第三份才统一的）：

```python
@pytest.fixture
def make_datasource(db_session: Session, make_user):
    """建一个测试数据源。密码用 Task 2 的 seal 就地加密。

    id 先生成再加密：AAD 绑定数据源 id，所以顺序不能反（见 Task 3 开头）。
    created_by 默认新建一个 admin，与调用方自己的用户区分开——否则
    「删用户」类测试会撞上 created_by 的 RESTRICT 而不是测到想测的东西。
    """
    import uuid

    from chatbi.datasources.crypto import aad_for_datasource, seal
    from chatbi.db.models import Datasource

    def _make(
        *,
        name: str | None = None,
        kind: str = "postgres",
        host: str = "db.internal",
        port: int = 5432,
        database: str = "analytics",
        username: str = "ro_user",
        password: str | None = "ds-pw-123456",
        options: dict | None = None,
        is_readonly_verified: bool = False,
        created_by: uuid.UUID | None = None,
    ) -> Datasource:
        datasource_id = uuid.uuid4()
        sealed = seal(password, aad=aad_for_datasource(datasource_id)) if password else None
        datasource = Datasource(
            id=datasource_id,
            name=name or f"ds-{datasource_id.hex[:8]}",
            kind=kind,
            host=host,
            port=port,
            database=database,
            username=username,
            secret_ciphertext=sealed.ciphertext if sealed else None,
            secret_nonce=sealed.nonce if sealed else None,
            options=options if options is not None else {},
            is_readonly_verified=is_readonly_verified,
            created_by=created_by or make_user(role="admin").id,
        )
        db_session.add(datasource)
        db_session.flush()
        return datasource

    return _make
```

新建 `apps/api/tests/test_datasource_models.py`：

```python
"""表级约束的测试。

每条预期失败都包在 `begin_nested()` 里：`IntegrityError` 会让当前事务不可用，
而 `db_session` 夹具的外层事务后面还要用。savepoint 回滚只撤销内层，
外层照旧——直接 flush 出错会让同一个测试里后续的断言全部连带报错。
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from chatbi.db.models import DATASOURCE_KINDS, Datasource, DatasourceGrant


def _grant_count(session, user_id: uuid.UUID) -> int:
    return session.scalar(
        sa.select(sa.func.count())
        .select_from(DatasourceGrant)
        .where(DatasourceGrant.user_id == user_id)
    )


def test_the_supported_kinds_are_exactly_the_three_planned_drivers() -> None:
    assert DATASOURCE_KINDS == ("postgres", "mysql", "clickhouse")


def test_datasource_name_is_unique(db_session, make_datasource) -> None:
    make_datasource(name="生产只读库")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        make_datasource(name="生产只读库")


def test_kind_is_constrained_at_the_database_level(db_session, make_datasource) -> None:
    """CHECK 约束而非只靠 Pydantic：CLI 与直连 SQL 都不过 Pydantic。"""
    with pytest.raises(IntegrityError), db_session.begin_nested():
        make_datasource(kind="oracle")


def test_secret_columns_are_both_null_or_both_set(db_session, make_user) -> None:
    """半写状态（有密文没 nonce）必须进不了库：这种行既解不开也无法诊断。"""
    admin = make_user(role="admin")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            Datasource(
                id=uuid.uuid4(),
                name="半写的库",
                kind="postgres",
                host="db.internal",
                port=5432,
                database="analytics",
                username="ro_user",
                secret_ciphertext=b"\x01\x02",
                secret_nonce=None,
                created_by=admin.id,
            )
        )
        db_session.flush()


def test_a_user_gets_at_most_one_grant_row_per_datasource(
    db_session, make_user, make_datasource
) -> None:
    """复合主键：授权是「有/无」而不是可累积的列表，重复插入必须撞主键。"""
    analyst = make_user(role="analyst")
    datasource = make_datasource()
    db_session.add(
        DatasourceGrant(datasource_id=datasource.id, user_id=analyst.id, can_query=True)
    )
    db_session.flush()

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            DatasourceGrant(datasource_id=datasource.id, user_id=analyst.id, can_query=False)
        )
        db_session.flush()


def test_deleting_a_datasource_cascades_to_its_grants(
    db_session, make_user, make_datasource
) -> None:
    """否则删掉再重建同名数据源会继承上一代的授权行。"""
    analyst = make_user(role="analyst")
    datasource = make_datasource()
    db_session.add(
        DatasourceGrant(datasource_id=datasource.id, user_id=analyst.id, can_query=True)
    )
    db_session.flush()

    db_session.delete(datasource)
    db_session.flush()

    assert _grant_count(db_session, analyst.id) == 0


def test_deleting_a_user_cascades_to_their_grants(db_session, make_user, make_datasource) -> None:
    analyst = make_user(role="analyst")
    datasource = make_datasource()
    db_session.add(
        DatasourceGrant(datasource_id=datasource.id, user_id=analyst.id, can_query=True)
    )
    db_session.flush()

    db_session.delete(analyst)
    db_session.flush()

    assert _grant_count(db_session, analyst.id) == 0


def test_deleting_the_creator_of_a_datasource_is_refused(
    db_session, make_user, make_datasource
) -> None:
    """created_by 是 RESTRICT，不是 CASCADE 也不是 SET NULL：数据源是审计对象，
    不能因为删了一个管理员就连带消失，也不该静默丢掉归属。
    """
    admin = make_user(role="admin")
    make_datasource(created_by=admin.id)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.delete(admin)
        db_session.flush()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd apps/api
uv run pytest tests/test_datasource_models.py -v
```

预期：收集期 `ImportError: cannot import name 'DATASOURCE_KINDS' from 'chatbi.db.models'`。

- [ ] **Step 3: 加两个错误码**

`apps/api/src/chatbi/errors.py` 在 `EMAIL_ALREADY_EXISTS` 那行下面追加两行（文案照 spec §2.6：通用 404、不透露结构信息）：

```python
DATASOURCE_NOT_FOUND = ("DATASOURCE_NOT_FOUND", "数据源不存在", 404)
DATASOURCE_NAME_EXISTS = ("DATASOURCE_NAME_EXISTS", "该数据源名称已存在", 409)
```

`CONNECTION_ERROR` 不在这里加——P2b 才有连接行为，提前定义又是一条「定义了没人用」（P1 遗留 5 就是这么来的）。

- [ ] **Step 4: 加两个模型**

`apps/api/src/chatbi/db/models.py`——import 段补 `Any` 与 `JSONB`，文件末尾追加两个类：

```python
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
```

```python
DATASOURCE_KINDS: tuple[str, str, str] = ("postgres", "mysql", "clickhouse")


class Datasource(Base):
    """一个外部数据库的连接定义。密码以 AES-GCM 密文存两列，见 datasources/crypto.py。

    表级 CHECK（kind 取值、secret 两列成对）只写在 migration 0002 里，与 P1 的
    users.role 一致：建表永远走 Alembic，模型的 __table_args__ 根本不会被执行，
    写两份只会得到两份不同步的约束。
    """

    __tablename__ = "datasources"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    host: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    port: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    database: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    username: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    # 两列同时为空 = 未存密码，同时非空 = 已存。没有第三种状态（CHECK 在 migration 里）
    secret_ciphertext: Mapped[bytes | None] = mapped_column(sa.LargeBinary(), nullable=True)
    secret_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary(), nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False, default=dict)
    is_readonly_verified: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class DatasourceGrant(Base):
    """谁能查哪个数据源。复合主键——授权是「有/无」，不是可累积的列表。

    故意不定义 relationship：`db` 是叶子模块（spec §1.3 规则 4），
    联表由 repository 显式写 select，不让 ORM 在属性访问时偷偷发查询。
    """

    __tablename__ = "datasource_grants"

    datasource_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("datasources.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    can_query: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)
```

- [ ] **Step 5: 写 migration 0002**

新建 `apps/api/migrations/versions/0002_datasources.py`：

```python
"""datasources and datasource_grants

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datasources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database", sa.String(200), nullable=False),
        sa.Column("username", sa.String(200), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("secret_nonce", sa.LargeBinary(), nullable=True),
        sa.Column(
            "options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "is_readonly_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            # RESTRICT 而不是 CASCADE/SET NULL：数据源是审计对象，删一个管理员
            # 不该连带删掉它建的数据源，也不该静默丢掉归属
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("kind in ('postgres','mysql','clickhouse')", name="ck_datasources_kind"),
        # 「有密文没 nonce」的半写行既解不开也无法诊断，在 DB 层就排除掉
        sa.CheckConstraint(
            "(secret_ciphertext is null) = (secret_nonce is null)",
            name="ck_datasources_secret_pair",
        ),
    )
    op.create_index("ix_datasources_name", "datasources", ["name"], unique=True)
    op.create_index("ix_datasources_created_by", "datasources", ["created_by"])

    op.create_table(
        "datasource_grants",
        sa.Column(
            "datasource_id",
            sa.Uuid(),
            sa.ForeignKey("datasources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("can_query", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    # 复合主键的前导列是 datasource_id，而可见性查询按 user_id 过滤，需要自己的索引
    op.create_index("ix_datasource_grants_user_id", "datasource_grants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_datasource_grants_user_id", table_name="datasource_grants")
    op.drop_table("datasource_grants")
    op.drop_index("ix_datasources_created_by", table_name="datasources")
    op.drop_index("ix_datasources_name", table_name="datasources")
    op.drop_table("datasources")
```

`server_default` 用 `sa.text("false")` / `sa.text("'{}'::jsonb")` 而不是 `sa.false()`——P1 §10.1 第 2 条：后者在部分 Alembic 版本下渲染不稳。

- [ ] **Step 6: 把 up/down 双向断言扩到新表**

`apps/api/tests/test_migrations.py` 整个 `test_migrations_roundtrip` 替换成（并在 `_table_names` 上方加常量）：

```python
TABLES = {"users", "sessions", "datasources", "datasource_grants"}


def test_migrations_roundtrip(_migrated: None) -> None:
    """从 head 出发 down 到底再 up 回 head，结束时状态与开始时一致。"""
    assert TABLES <= _table_names()

    _alembic("downgrade", "base")
    assert not TABLES & _table_names()

    _alembic("upgrade", "head")
    assert TABLES <= _table_names()
```

`downgrade base` 会连 `0002` 一起回退，所以 `0002.downgrade()` 里漏删索引或顺序反了（先删被引用的表）都会在这里炸出来——这是本任务唯一验证 `downgrade` 的地方。

- [ ] **Step 7: 跑全量确认通过**

```bash
cd apps/api
uv run pytest -q && uv run ruff check src tests
```

预期：`76 passed`（Task 2 后的 68 + 本任务 8 条）。注意 `test_migrations.py` 里那条是**改写**已有测试，不是新增，别算成第 9 条。`_migrated` 是 session 级夹具，每次跑 pytest 都会 `downgrade base` + `upgrade head`，所以改完 migration 不需要手工重建库。

- [ ] **Step 8: 反向验证四条约束（两个方向都要跑）**

逐条临时改 `0002_datasources.py`、跑对应测试确认 FAIL、再恢复。**每次改完直接跑 pytest 即可**，夹具会重建库。

1. 删掉 `ck_datasources_kind` → `test_kind_is_constrained_at_the_database_level` 必须 FAIL。
2. 删掉 `ck_datasources_secret_pair` → `test_secret_columns_are_both_null_or_both_set` 必须 FAIL。
3. `datasource_grants.datasource_id` 的 `ondelete="CASCADE"` 整个删掉 → `test_deleting_a_datasource_cascades_to_its_grants` 必须 FAIL（删父行时抛 `IntegrityError`）。
4. `created_by` 的 `ondelete="RESTRICT"` 改成 `"CASCADE"` → `test_deleting_the_creator_of_a_datasource_is_refused` 必须 FAIL（不再抛 `IntegrityError`）。

`test_the_supported_kinds_are_exactly_the_three_planned_drivers` **不在这个列表里，因为它无法反向验证**：它是对常量的回声断言，改常量它就失败，改 migration 它不动。它挡的只是「有人加了第四个 kind 却没同步 migration」的一半——另一半由第 1 条守。这条的性质和 P1 的 `test_health.py` 一样（§10.4），知道就行。

- [ ] **Step 9: 提交**

```bash
git add apps/api/src/chatbi apps/api/migrations apps/api/tests
git commit -m "$(cat <<'EOF'
feat(datasources): datasources and datasource_grants tables

Secret columns are constrained to be null or set together, kind is checked
in the database, grants cascade from both parents while created_by is
RESTRICT so a datasource never loses its audit owner.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 仓储层——CRUD、可见性过滤、密码存取

**这个任务不 import `fastapi`。** 「这个用户能看见这个数据源吗」是领域逻辑，必须能脱离 HTTP 测（spec §1.3 规则 2）。Task 5 的 router 只会调这里的函数，不会自己写 `select()`。

两个贯穿本任务的决定：

1. **唯一名靠 insert + 捕获 `IntegrityError`，不用 check-then-insert。** P1 遗留 3 就是 check-then-insert：并发下两个请求都查到「没有」，然后一个成功一个 500。写法上必须包在 `begin_nested()` 里——`IntegrityError` 会让当前事务不可用，而 HTTP 层还要靠这个事务返回 409，savepoint 回滚只撤销内层。
2. **可见性折进 SQL，不在 Python 里过滤。** `get_visible` 一条查询同时完成「取」和「判定」，没有 TOCTOU 窗口；也不会出现「先取出来再判断」时有人手滑把未授权对象带进了日志。

**Files:**
- Create: `apps/api/src/chatbi/db/integrity.py`（从 `IntegrityError` 取违反的约束名，仓储与 Task 6 的 `provisioning` 共用）
- Create: `apps/api/src/chatbi/datasources/schemas.py`
- Create: `apps/api/src/chatbi/datasources/repository.py`
- Create: `apps/api/tests/test_datasource_repository.py`
- Modify: `apps/api/src/chatbi/db/models.py`（给 `Datasource` 加 `has_password` 属性）

**Interfaces:**
- Consumes: `chatbi.datasources.crypto.{seal, unseal, aad_for_datasource, SealedSecret}`（Task 2）· `chatbi.db.models.{Datasource, DatasourceGrant, User}`（Task 3）· `chatbi.errors.{DATASOURCE_NAME_EXISTS, ApiError}`（Task 3）
- Produces:
```python
chatbi.db.integrity.violated_constraint(exc: IntegrityError) -> str | None
# 取不到就返回 None（调用方据此决定「不确定就原样抛」）

chatbi.datasources.schemas.DatasourceKind      # Literal["postgres", "mysql", "clickhouse"]
chatbi.datasources.schemas.DatasourceCreate
chatbi.datasources.schemas.DatasourceUpdate    # 全字段可选；password=None 表示不改
chatbi.datasources.schemas.DatasourceResponse  # 不声明任何凭据字段，含 has_password: bool
chatbi.datasources.schemas.GrantRequest        # user_id: uuid.UUID, can_query: bool = True
chatbi.datasources.schemas.GrantResponse

chatbi.datasources.repository.create_datasource(
    session, *, payload: DatasourceCreate, created_by: uuid.UUID) -> Datasource
chatbi.datasources.repository.list_visible(session, user: User) -> list[Datasource]
chatbi.datasources.repository.get_visible(
    session, user: User, datasource_id: uuid.UUID) -> Datasource | None
chatbi.datasources.repository.datasource_exists(session, datasource_id: uuid.UUID) -> bool
# get_visible 对「不存在」和「无权限」都返回 None（有意的：判定折进 SQL）。
# Task 5 的 deps 要把 404 与 403 分开，就靠再问一次 datasource_exists。
chatbi.datasources.repository.update_datasource(
    session, datasource: Datasource, payload: DatasourceUpdate) -> Datasource
chatbi.datasources.repository.delete_datasource(session, datasource: Datasource) -> None
chatbi.datasources.repository.read_password(datasource: Datasource) -> str | None   # 无 session 参数
chatbi.datasources.repository.set_grant(
    session, *, datasource_id: uuid.UUID, user_id: uuid.UUID, can_query: bool) -> DatasourceGrant
chatbi.datasources.repository.revoke_grant(
    session, *, datasource_id: uuid.UUID, user_id: uuid.UUID) -> bool   # 有没删到东西
chatbi.datasources.repository.list_grants(session, datasource_id: uuid.UUID) -> list[DatasourceGrant]
```

- [ ] **Step 1: 写失败的测试**

新建 `apps/api/tests/test_datasource_repository.py`：

```python
"""仓储层测试。不起 TestClient——这一层不认识 HTTP。"""

import uuid
from typing import get_args

import pytest
from sqlalchemy.exc import IntegrityError

from chatbi.datasources.repository import (
    create_datasource,
    datasource_exists,
    delete_datasource,
    get_visible,
    list_grants,
    list_visible,
    read_password,
    revoke_grant,
    set_grant,
    update_datasource,
)
from chatbi.datasources.schemas import (
    DatasourceCreate,
    DatasourceResponse,
    DatasourceUpdate,
)
from chatbi.db.models import DATASOURCE_KINDS
from chatbi.errors import ApiError


def _payload(**overrides) -> DatasourceCreate:
    base = {
        "name": "生产只读库",
        "kind": "postgres",
        "host": "db.internal",
        "port": 5432,
        "database": "analytics",
        "username": "ro_user",
        "password": "ds-pw-123456",
    }
    return DatasourceCreate(**(base | overrides))


def test_create_stores_the_password_as_ciphertext(db_session, make_user) -> None:
    admin = make_user(role="admin")

    datasource = create_datasource(db_session, payload=_payload(), created_by=admin.id)

    assert datasource.secret_ciphertext is not None
    assert datasource.secret_nonce is not None
    assert b"ds-pw-123456" not in datasource.secret_ciphertext


def test_create_round_trips_the_password(db_session, make_user) -> None:
    admin = make_user(role="admin")

    datasource = create_datasource(db_session, payload=_payload(), created_by=admin.id)

    assert read_password(datasource) == "ds-pw-123456"


def test_create_without_a_password_leaves_both_secret_columns_null(db_session, make_user) -> None:
    admin = make_user(role="admin")

    datasource = create_datasource(
        db_session, payload=_payload(password=None), created_by=admin.id
    )

    assert datasource.secret_ciphertext is None
    assert datasource.secret_nonce is None
    assert read_password(datasource) is None
    assert datasource.has_password is False


def test_duplicate_name_raises_api_error_and_leaves_the_transaction_usable(
    db_session, make_user
) -> None:
    """这条钉的是 insert + 捕获 IntegrityError 的写法。

    check-then-insert 也能让第一个断言通过，但过不了最后一句：IntegrityError
    未被 savepoint 隔离时，同一事务后续任何语句都会抛 PendingRollbackError，
    而 HTTP 层正是要靠这个事务把 409 返回出去。
    """
    admin = make_user(role="admin")
    create_datasource(db_session, payload=_payload(name="重名库"), created_by=admin.id)

    with pytest.raises(ApiError) as exc_info:
        create_datasource(db_session, payload=_payload(name="重名库"), created_by=admin.id)

    assert exc_info.value.code == "DATASOURCE_NAME_EXISTS"
    assert exc_info.value.status_code == 409
    # 事务还能继续用
    assert len(list_visible(db_session, admin)) == 1


def test_a_non_name_integrity_error_is_not_disguised_as_a_name_conflict(db_session) -> None:
    """created_by 指向不存在的用户会撞外键。把它也翻成 409「名称已存在」是撒谎——
    应当原样抛出，让真问题以 500 暴露，而不是被伪装成一个用户能理解的错误。
    """
    with pytest.raises(IntegrityError):
        create_datasource(db_session, payload=_payload(), created_by=uuid.uuid4())


def test_admin_sees_every_datasource(db_session, make_user, make_datasource) -> None:
    admin = make_user(role="admin")
    make_datasource(name="甲")
    make_datasource(name="乙")

    names = {d.name for d in list_visible(db_session, admin)}

    assert names == {"甲", "乙"}


def test_analyst_sees_only_granted_datasources(db_session, make_user, make_datasource) -> None:
    analyst = make_user(role="analyst")
    granted = make_datasource(name="已授权")
    make_datasource(name="未授权")
    set_grant(db_session, datasource_id=granted.id, user_id=analyst.id, can_query=True)

    assert [d.name for d in list_visible(db_session, analyst)] == ["已授权"]


def test_can_query_false_does_not_grant_visibility(db_session, make_user, make_datasource) -> None:
    """授权行存在但 can_query=false 等于没授权，不是「只读可见」。"""
    viewer = make_user(role="viewer")
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=viewer.id, can_query=False)

    assert list_visible(db_session, viewer) == []
    assert get_visible(db_session, viewer, datasource.id) is None


def test_get_visible_returns_none_for_an_ungranted_datasource(
    db_session, make_user, make_datasource
) -> None:
    analyst = make_user(role="analyst")
    datasource = make_datasource()

    assert get_visible(db_session, analyst, datasource.id) is None


def test_get_visible_returns_none_for_an_unknown_id(db_session, make_user) -> None:
    admin = make_user(role="admin")

    assert get_visible(db_session, admin, uuid.uuid4()) is None


def test_datasource_exists_separates_unknown_from_unauthorized(
    db_session, make_datasource
) -> None:
    """get_visible 对两种情况都返回 None，deps 靠这个函数把 404 与 403 分开。"""
    datasource = make_datasource()

    assert datasource_exists(db_session, datasource.id) is True
    assert datasource_exists(db_session, uuid.uuid4()) is False


def test_updating_the_password_rotates_the_nonce(db_session, make_user) -> None:
    """每次写入换新 nonce。AES-GCM 下同密钥重用 nonce 直接泄露明文异或。"""
    admin = make_user(role="admin")
    datasource = create_datasource(db_session, payload=_payload(), created_by=admin.id)
    old_nonce = datasource.secret_nonce

    update_datasource(db_session, datasource, DatasourceUpdate(password="brand-new-pw"))

    assert datasource.secret_nonce != old_nonce
    assert read_password(datasource) == "brand-new-pw"


def test_update_without_a_password_leaves_the_credential_untouched(db_session, make_user) -> None:
    admin = make_user(role="admin")
    datasource = create_datasource(db_session, payload=_payload(), created_by=admin.id)
    before = (datasource.secret_ciphertext, datasource.secret_nonce)

    update_datasource(db_session, datasource, DatasourceUpdate(host="moved.internal"))

    assert (datasource.secret_ciphertext, datasource.secret_nonce) == before
    assert datasource.host == "moved.internal"
    assert read_password(datasource) == "ds-pw-123456"


def test_renaming_onto_an_existing_name_raises_api_error(db_session, make_user) -> None:
    admin = make_user(role="admin")
    create_datasource(db_session, payload=_payload(name="甲"), created_by=admin.id)
    second = create_datasource(db_session, payload=_payload(name="乙"), created_by=admin.id)

    with pytest.raises(ApiError) as exc_info:
        update_datasource(db_session, second, DatasourceUpdate(name="甲"))

    assert exc_info.value.code == "DATASOURCE_NAME_EXISTS"
    assert len(list_visible(db_session, admin)) == 2


def test_set_grant_is_idempotent(db_session, make_user, make_datasource) -> None:
    """同一 (datasource, user) 只有一行，重复授权是改 can_query 而不是插第二行。"""
    analyst = make_user(role="analyst")
    datasource = make_datasource()

    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=False)

    grants = list_grants(db_session, datasource.id)
    assert len(grants) == 1
    assert grants[0].can_query is False


def test_revoke_grant_reports_whether_anything_was_removed(
    db_session, make_user, make_datasource
) -> None:
    analyst = make_user(role="analyst")
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    assert revoke_grant(db_session, datasource_id=datasource.id, user_id=analyst.id) is True
    assert revoke_grant(db_session, datasource_id=datasource.id, user_id=analyst.id) is False
    assert list_grants(db_session, datasource.id) == []


def test_delete_removes_the_datasource_from_every_listing(
    db_session, make_user, make_datasource
) -> None:
    admin = make_user(role="admin")
    datasource = make_datasource()

    delete_datasource(db_session, datasource)

    assert list_visible(db_session, admin) == []


def test_the_response_model_declares_no_credential_fields() -> None:
    """spec §4.4 的红线：靠模型不含字段，而不是靠序列化时记得排除。"""
    forbidden = {"password", "secret", "secret_ciphertext", "secret_nonce", "ciphertext", "nonce"}

    assert not (set(DatasourceResponse.model_fields) & forbidden)


def test_the_kind_literal_matches_the_model_constant() -> None:
    """Literal 存在是为了让 OpenAPI 出 enum（P4 生成前端类型要用），
    但它和 DATASOURCE_KINDS 是两处声明，这条防它们漂移。
    """
    annotation = DatasourceCreate.model_fields["kind"].annotation

    assert set(get_args(annotation)) == set(DATASOURCE_KINDS)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd apps/api
uv run pytest tests/test_datasource_repository.py -v
```

预期：收集期 `ModuleNotFoundError: No module named 'chatbi.datasources.repository'`。

- [ ] **Step 3: 写 schemas.py**

新建 `apps/api/src/chatbi/datasources/schemas.py`：

```python
"""数据源的请求/响应模型。

DatasourceResponse 不声明任何凭据字段——spec §4.4 要求靠模型不含字段，而不是
靠序列化时记得排除。往这个模型加字段前先确认它不是密码、密文或 nonce。
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# 写成 Literal 而不是 str + validator：OpenAPI 里会出成 enum，P4 生成的前端类型
# 直接得到联合类型。与 db.models.DATASOURCE_KINDS 的一致性由测试钉住。
DatasourceKind = Literal["postgres", "mysql", "clickhouse"]


class DatasourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: DatasourceKind
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1, max_length=200)
    username: str = Field(min_length=1, max_length=200)
    # 允许不带密码：有些环境走 trust 或证书认证。两个 secret 列会一起留空
    password: str | None = Field(default=None, max_length=1024)
    options: dict[str, Any] = Field(default_factory=dict)


class DatasourceUpdate(BaseModel):
    """PATCH 语义：只改传来的字段。

    `password=None` 表示「不改密码」，所以 P2a 没有「清空已存密码」的路径——需要
    清空就删了重建。这个取舍是：让「编辑表单里省略密码」成为安全默认，比提供一个
    容易误触的清空语义重要。`is_readonly_verified` 不在这里，它由 P2b 的 /test
    端点写，不接受客户端指定——否则客户端可以自称「已验证只读」。
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: DatasourceKind | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=200)
    username: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, max_length=1024)
    options: dict[str, Any] | None = None


class DatasourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: DatasourceKind
    host: str
    port: int
    database: str
    username: str
    options: dict[str, Any]
    is_readonly_verified: bool
    has_password: bool  # 只是「有没有存密码」，不是密码本身
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class GrantRequest(BaseModel):
    user_id: uuid.UUID
    can_query: bool = True


class GrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    datasource_id: uuid.UUID
    user_id: uuid.UUID
    can_query: bool
```

`has_password` 需要 ORM 侧有对应属性（`from_attributes` 按名取）。在 `apps/api/src/chatbi/db/models.py` 的 `Datasource` 末尾加：

```python
    @property
    def has_password(self) -> bool:
        """给响应模型用的派生标记。返回 bool 而不是任何密钥材料，所以放在 db 层
        不算业务逻辑——它只是那两列的一个只读视图。
        """
        return self.secret_ciphertext is not None
```

- [ ] **Step 4: 写 repository.py**

先新建 `apps/api/src/chatbi/db/integrity.py`——从 `IntegrityError` 里取违反的约束名。抽出来是因为 Task 6 的 `provisioning.create_user`（P1 遗留 3）要做同样的判别，两处各写一份 `getattr(getattr(...))` 必然漂移：

```python
"""IntegrityError 的判别工具。

单独一个文件是因为「怎么从驱动异常里取约束名」是 psycopg 的细节，
不该在每个仓储里各写一遍。
"""

from sqlalchemy.exc import IntegrityError


def violated_constraint(exc: IntegrityError) -> str | None:
    """返回被违反的约束/索引名；取不到返回 None。

    psycopg 把它放在 exc.orig.diag.constraint_name 上。取不到时**返回 None 而不是
    猜**——调用方的正确反应是「不确定就原样抛」，把任何 IntegrityError 都翻成一个
    友好错误码会让真 bug 伪装成用户错误。
    """
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
```

再新建 `apps/api/src/chatbi/datasources/repository.py`：

```python
"""数据源与授权的持久化、可见性过滤、密码存取。

不 import fastapi：可见性判断是领域逻辑，必须能脱离 HTTP 测（spec §1.3 规则 2）。
ApiError 是错误契约不是框架依赖，可以用。
"""

import uuid
from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatbi.datasources.crypto import SealedSecret, aad_for_datasource, seal, unseal
from chatbi.datasources.schemas import DatasourceCreate, DatasourceUpdate
from chatbi.db.integrity import violated_constraint
from chatbi.db.models import Datasource, DatasourceGrant, User
from chatbi.errors import DATASOURCE_NAME_EXISTS, ApiError

# 只有 admin 无条件看全部；analyst/viewer 一律走 datasource_grants（spec §4.2）
_UNRESTRICTED_ROLES = frozenset({"admin"})
_NAME_CONSTRAINT = "ix_datasources_name"


def _visible_where(user: User):
    """加在 select(Datasource) 上的可见性条件。

    非 admin 用 EXISTS 而不是 JOIN：EXISTS 表达的是「存在一条有效授权」，语义与
    意图一致；JOIN 的行数依赖授权表不出现重复行，那是靠复合主键的间接保证。
    """
    if user.role in _UNRESTRICTED_ROLES:
        return sa.true()
    return sa.exists().where(
        DatasourceGrant.datasource_id == Datasource.id,
        DatasourceGrant.user_id == user.id,
        DatasourceGrant.can_query.is_(True),
    )


def _is_name_conflict(exc: IntegrityError) -> bool:
    """只把唯一名冲突翻成 409，别的 IntegrityError 原样抛。

    把外键或 CHECK 违规也报成「名称已存在」是撒谎，会让真 bug 伪装成用户错误。
    约束名取不到时 violated_constraint 返回 None，这里就判 False——宁可暴露一个
    500，也不谎报一个用户能理解的 409。
    """
    return violated_constraint(exc) == _NAME_CONSTRAINT


def _within_savepoint(session: Session, mutate: Callable[[], None]) -> None:
    """在 savepoint 里执行改动 + flush，把唯一名冲突翻成 409。

    改动必须发生在 savepoint **内部**：快照在 begin_nested() 那一刻拍下，之前做的
    add/赋值不会被回滚，会在下一次 flush 时原地再炸一次。
    需要 savepoint 是因为 IntegrityError 之后事务不可用，而 HTTP 层还要靠同一个
    事务把 409 发出去。不用 check-then-insert：并发下两个请求都会查到「没有」。
    """
    savepoint = session.begin_nested()
    try:
        mutate()
        session.flush()
    except IntegrityError as exc:
        savepoint.rollback()
        if not _is_name_conflict(exc):
            raise
        raise ApiError(*DATASOURCE_NAME_EXISTS) from exc
    savepoint.commit()


def _store_password(datasource: Datasource, password: str) -> None:
    """每次调用都换新 nonce（seal 内部 os.urandom）。nonce 绝不复用。"""
    sealed = seal(password, aad=aad_for_datasource(datasource.id))
    datasource.secret_ciphertext = sealed.ciphertext
    datasource.secret_nonce = sealed.nonce


def create_datasource(
    session: Session, *, payload: DatasourceCreate, created_by: uuid.UUID
) -> Datasource:
    # id 在应用侧生成：AAD 绑的是数据源 id，加密前就得知道它（见 Task 3 开头）
    datasource = Datasource(
        id=uuid.uuid4(),
        name=payload.name,
        kind=payload.kind,
        host=payload.host,
        port=payload.port,
        database=payload.database,
        username=payload.username,
        options=payload.options,
        created_by=created_by,
    )
    if payload.password is not None:
        _store_password(datasource, payload.password)
    _within_savepoint(session, lambda: session.add(datasource))
    return datasource


def update_datasource(
    session: Session, datasource: Datasource, payload: DatasourceUpdate
) -> Datasource:
    def mutate() -> None:
        for field in ("name", "kind", "host", "port", "database", "username", "options"):
            value = getattr(payload, field)
            if value is not None:
                setattr(datasource, field, value)
        if payload.password is not None:
            _store_password(datasource, payload.password)

    _within_savepoint(session, mutate)
    return datasource


def delete_datasource(session: Session, datasource: Datasource) -> None:
    session.delete(datasource)
    session.flush()


def list_visible(session: Session, user: User) -> list[Datasource]:
    statement = sa.select(Datasource).where(_visible_where(user)).order_by(Datasource.name)
    return list(session.scalars(statement))


def get_visible(session: Session, user: User, datasource_id: uuid.UUID) -> Datasource | None:
    """取 + 判定一步完成，没有「先取出来再判断」之间的窗口。

    不存在与无权限都返回 None；把 404 与 403 分开是 deps 的事（用 datasource_exists）。
    """
    statement = sa.select(Datasource).where(Datasource.id == datasource_id, _visible_where(user))
    return session.scalars(statement).one_or_none()


def datasource_exists(session: Session, datasource_id: uuid.UUID) -> bool:
    """不带可见性条件——只回答「这个 id 在不在」，给 deps 区分 404 与 403 用。"""
    count = session.scalar(
        sa.select(sa.func.count()).select_from(Datasource).where(Datasource.id == datasource_id)
    )
    return bool(count)


def read_password(datasource: Datasource) -> str | None:
    """解出明文密码。没有 session 参数——纯函数，只读 ORM 对象上的两列。

    调用方只有 P2b 的驱动层。返回值不得进日志、不得进 HTTP 响应。
    """
    if datasource.secret_ciphertext is None or datasource.secret_nonce is None:
        return None
    sealed = SealedSecret(
        ciphertext=datasource.secret_ciphertext, nonce=datasource.secret_nonce
    )
    return unseal(sealed, aad=aad_for_datasource(datasource.id))


def set_grant(
    session: Session, *, datasource_id: uuid.UUID, user_id: uuid.UUID, can_query: bool
) -> DatasourceGrant:
    """幂等：同一 (datasource, user) 只有一行，重复授权是改 can_query。"""
    grant = session.get(DatasourceGrant, {"datasource_id": datasource_id, "user_id": user_id})
    if grant is None:
        grant = DatasourceGrant(
            datasource_id=datasource_id, user_id=user_id, can_query=can_query
        )
        session.add(grant)
    else:
        grant.can_query = can_query
    session.flush()
    return grant


def revoke_grant(session: Session, *, datasource_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """撤销授权，返回是否真删到了行。

    HTTP 层的 DELETE 按 HTTP 语义幂等，**不消费**这个返回值（重复撤销一样 204）。
    它存在是因为「重复撤销不报错、且第二次确实没删到东西」这条性质要能被断言。
    """
    result = session.execute(
        sa.delete(DatasourceGrant).where(
            DatasourceGrant.datasource_id == datasource_id,
            DatasourceGrant.user_id == user_id,
        )
    )
    session.flush()
    return bool(result.rowcount)


def list_grants(session: Session, datasource_id: uuid.UUID) -> list[DatasourceGrant]:
    statement = (
        sa.select(DatasourceGrant)
        .where(DatasourceGrant.datasource_id == datasource_id)
        .order_by(DatasourceGrant.user_id)
    )
    return list(session.scalars(statement))
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd apps/api
uv run pytest -q && uv run ruff check src tests
```

预期：`95 passed`（Task 3 后的 76 + 本任务 19 条）。

- [ ] **Step 6: 反向验证七条（两个方向都要跑）**

逐条临时改 `repository.py` / `schemas.py`，跑对应测试确认 FAIL，再恢复。

1. `_visible_where` 的非 admin 分支改成 `return sa.true()` → `test_analyst_sees_only_granted_datasources`、`test_can_query_false_does_not_grant_visibility`、`test_get_visible_returns_none_for_an_ungranted_datasource` 三条必须同时 FAIL。
2. 只删 `DatasourceGrant.can_query.is_(True)` 这一行条件 → **只有** `test_can_query_false_does_not_grant_visibility` FAIL，其余仍绿。这条测试的全部鉴别力就在这里：没有它，「授权行存在即可见」这个 bug 会被前面几条测试放过。
3. `_store_password` 改成复用旧 nonce（`datasource.secret_nonce = datasource.secret_nonce or sealed.nonce`）→ `test_updating_the_password_rotates_the_nonce` 必须 FAIL。
4. `_within_savepoint` 删掉 savepoint，退化成直接 `mutate(); session.flush()` → `test_duplicate_name_raises_api_error_and_leaves_the_transaction_usable` 必须 FAIL。**注意它的前两句断言仍会通过**——只有最后那句 `list_visible` 会因 `PendingRollbackError` 炸。鉴别力全在最后一句上，别以为前两句绿了就没事。
5. 把 `session.add(datasource)` 从 lambda 里提出来、放到 `_within_savepoint` 调用**之前** → 同一条测试必须 FAIL。这条验证的是「改动必须在 savepoint 内部」那段注释：快照之前做的 add 不会被回滚，对象仍在 `session.new` 里，下一次 autoflush 原地再炸一次。
6. `_is_name_conflict` 改成 `return True` → `test_a_non_name_integrity_error_is_not_disguised_as_a_name_conflict` 必须 FAIL。
7. 给 `DatasourceResponse` 加一个 `password: str | None = None` 字段 → `test_the_response_model_declares_no_credential_fields` 必须 FAIL。

第 1 条要三条同时 FAIL 才算对。如果只有一两条 FAIL，说明剩下那条测的其实不是可见性——回头看它的夹具是不是漏了 `set_grant`。

- [ ] **Step 7: 提交**

```bash
git add apps/api/src/chatbi apps/api/tests
git commit -m "$(cat <<'EOF'
feat(datasources): repository with visibility filtering and sealed credentials

Visibility is folded into SQL so there is no fetch-then-check window, unique
name conflicts come from insert + IntegrityError inside a savepoint rather
than check-then-insert, and every password write rotates the nonce.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5 与 Task 6 在另一份文件里

HTTP 层（`deps.py`、`datasource_router.py`、grants 端点、`user_router.py`）拆到 **[P2a HTTP 层：数据源与用户端点](2026-08-13-chatbi-v2-1-p2a-datasource-api.md)**，任务编号延续本份（Task 5、Task 6），跨文件引用「Task N」不会歧义。

拆分的理由不是篇幅本身：本份到 Task 4 结束时是一个**能独立验收的交付**——领域层完整、`95 passed`、且一行 HTTP 代码都没有，正好证明了 spec §1.3 规则 2（可见性判断能脱离 HTTP 测）。HTTP 层是另一个可独立驳回的评审单元。合成一份会有 ~2600 行，超出「一份计划能被完整读一遍」的规模。

下面的「交接清单」就是那份文件要消费的签名。

---

## 交接清单（P2a HTTP 层要消费的签名）

改动这些签名要回头改 [P2a HTTP 层](2026-08-13-chatbi-v2-1-p2a-datasource-api.md)。

**装配接缝**（Task 1）
```python
chatbi.api.routers.ALL_ROUTERS: tuple[APIRouter, ...]
# Task 5 与 Task 6 各往这个元组里加一项，不再改 main.py
chatbi.auth.identity.get_identity_provider   # 已是 Depends() 消费的依赖，可被 override
```

**加密**（Task 2）
```python
chatbi.datasources.crypto.seal(plaintext: str, *, aad: bytes) -> SealedSecret
chatbi.datasources.crypto.unseal(sealed: SealedSecret, *, aad: bytes) -> str
chatbi.datasources.crypto.aad_for_datasource(datasource_id: uuid.UUID) -> bytes
chatbi.datasources.crypto.SecretDecryptionError
# get_master_key() 有 lru_cache；测试里改 CHATBI_SECRET_KEY 后要
# get_settings.cache_clear() + get_master_key.cache_clear() 两个都清
```

**表与错误码**（Task 3）
```python
chatbi.db.models.DATASOURCE_KINDS: tuple[str, str, str]   # ("postgres", "mysql", "clickhouse")
chatbi.db.models.Datasource        # 含 has_password 属性（Task 4 加的）
chatbi.db.models.DatasourceGrant   # 复合主键 (datasource_id, user_id)
chatbi.errors.DATASOURCE_NOT_FOUND   = ("DATASOURCE_NOT_FOUND", "数据源不存在", 404)
chatbi.errors.DATASOURCE_NAME_EXISTS = ("DATASOURCE_NAME_EXISTS", "该数据源名称已存在", 409)
```

**仓储与模型**（Task 4）
```python
chatbi.db.integrity.violated_constraint(exc: IntegrityError) -> str | None
# Task 6 的 provisioning.create_user（P1 遗留 3）要用它判别 ix_users_email

chatbi.datasources.schemas.DatasourceKind      # Literal["postgres","mysql","clickhouse"]
chatbi.datasources.schemas.DatasourceCreate    # password: str | None
chatbi.datasources.schemas.DatasourceUpdate    # 全字段可选；password=None 表示不改
chatbi.datasources.schemas.DatasourceResponse  # 不含凭据字段；含 has_password: bool
chatbi.datasources.schemas.GrantRequest        # user_id: uuid.UUID, can_query: bool = True
chatbi.datasources.schemas.GrantResponse

chatbi.datasources.repository.create_datasource(session, *, payload, created_by) -> Datasource
chatbi.datasources.repository.update_datasource(session, datasource, payload) -> Datasource
chatbi.datasources.repository.delete_datasource(session, datasource) -> None
chatbi.datasources.repository.list_visible(session, user) -> list[Datasource]
chatbi.datasources.repository.get_visible(session, user, datasource_id) -> Datasource | None
chatbi.datasources.repository.datasource_exists(session, datasource_id) -> bool
chatbi.datasources.repository.read_password(datasource) -> str | None
chatbi.datasources.repository.set_grant(session, *, datasource_id, user_id, can_query) -> DatasourceGrant
chatbi.datasources.repository.revoke_grant(session, *, datasource_id, user_id) -> bool
chatbi.datasources.repository.list_grants(session, datasource_id) -> list[DatasourceGrant]
```

**测试夹具**（`apps/api/tests/conftest.py`）
```python
db_session · client · make_user            # P1 就有
make_datasource(*, name=None, kind="postgres", host="db.internal", port=5432,
                database="analytics", username="ro_user", password="ds-pw-123456",
                options=None, is_readonly_verified=False, created_by=None) -> Datasource
# created_by 默认新建一个 admin，与调用方自己的用户是两个人
```

**HTTP 层起步须知**
- `create_datasource` / `update_datasource` 会抛 `ApiError(*DATASOURCE_NAME_EXISTS)`，router 不用自己判重名；已在 savepoint 里隔离过，抛出后事务仍可用。
- `get_visible` 对「不存在」和「无权限」都返回 `None`。要按 Global Constraints 区分 404 与 403，就再调一次 `datasource_exists`。
- 数据源的写操作（建/改/删/授权）只有 `admin`；可见性对 `analyst`/`viewer` 走 grants。
- `read_password` 的返回值不得进日志、不得进 HTTP 响应。P2a 里除了测试没有调用方——它是给 P2b 驱动层准备的。
- 测试基线：本份做完是 `95 passed`（P1 的 53 + Task 1 的 5 + Task 2 的 10 + Task 3 的 8 + Task 4 的 19）。

---

## 实施期的偏差（执行中回填）

### Task 1（2026-08-18 完成，commit `9a007c4`，58 passed）

| 项 | 原计划 | 改成 | 原因 |
|---|---|---|---|
| `test_all_routers_are_mounted_on_the_real_app` | 收集 `app.routes` 的 `route.path` 集合做断言 | 改用 `app.openapi()["paths"]` | **FastAPI 0.141.1 起 `include_router` 在 `app.routes` 里只留一个 `_IncludedRouter` 包装对象，不再摊平子路由**。原写法拿到的集合里一条业务路径都没有，测试第一次跑就红在 `'/api/auth/login' not in {'/health', '/docs', ...}`。路由本身工作正常（同文件那条 401 信封测试通过）。OpenAPI 的 paths 跨版本稳定，且表达的正是「对外暴露了什么」 |

实施中发现的其它两件事：

1. **`delete_cookie` 原本就带 `samesite=lax` 与 `max-age=0`**，缺的只有 `httponly` 与 `secure`。所以那条测试真正的鉴别力在 `httponly` 上——反向验证（退回只带 `path`）确认它确实因此而红。
2. **删掉 `.gitignore` 的 `data/` 与 `*.db*` 后，`apps/backend/` 从 v1 时代冒了出来**：194 个文件 / 1.2 MB，是 `dist/` 编译输出与 `data/` 下的 SQLite 开发库（v1 源码在 `d12944b` 已从 git 删除，这些文件因当时被 ignore 而留在磁盘上）。`*.key` 仍被忽略所以 `app.key` 没暴露。Task 1 的提交按计划只 add 三个路径，没带上它。**这个目录该怎么处理留给用户决定**——`data/*.db` 是从未提交过的本地数据，删了不可恢复。在它被清理之前，`git status` 会一直显示这一条，且 `git add -A` 有把 SQLite 库提交进去的风险。

---

## 自查记录（Task 1–4）

---

**spec 覆盖核对**（只核 Task 1–4 承担的部分）

| spec 条目 | 落在哪 |
|---|---|
| §1.3 规则 2「`api/` 不含业务逻辑」 | Task 4（`repository.py` 不 import fastapi，可见性脱离 HTTP 测） |
| §1.3 规则 4「`db` 是叶子」 | Task 3（不定义 relationship，联表由仓储显式写） |
| §1.4 单文件规模 | `crypto.py` ~95 行、`repository.py` ~180 行、`schemas.py` ~80 行，均在约束内 |
| §2.5 `datasources` / `datasource_grants` 两表 | Task 3 |
| §2.6 `DATASOURCE_NOT_FOUND` / `DATASOURCE_NAME_EXISTS` | Task 3 Step 3 |
| §4.2 数据源级 grants 授权、未授权不出现在列表里 | Task 4（`_visible_where`） |
| §4.2 行列级权限不做、`PolicyResolver` 属 P3 | Global Constraints 已声明，本段无对应代码 |
| §4.4 AES-GCM 两列存密文 | Task 2 + Task 3 |
| §4.4 主密钥不入库、不入日志、不进错误消息 | Task 2（`MasterKey.__repr__` 掩码、`SecretDecryptionError` 不带上下文） |
| §4.4 响应模型不声明凭据字段 | Task 4（`DatasourceResponse` + 反向验证第 7 条） |
| §5.3 Alembic up/down 双向 | Task 3 Step 6 |
| §5.1「skip 不能当绿灯」 | Global Constraints：应用库测试不允许 skip |
| P1 §10.3 遗留 1、2、4、6、7、8 | Task 1 |

**本份不覆盖、留在下游的条目**：spec §2.4 的 REST 端点与 P1 遗留 3、5 在 [HTTP 层那份](2026-08-13-chatbi-v2-1-p2a-datasource-api.md)（Task 5、6）；`/test`、`/schema`、`CONNECTION_ERROR`、`demo_sales`、三驱动在 P2b；`is_readonly_verified` 本段只建列不写值（写它的是 P2b 的 `/test`）。

**写作过程中的回改**

1. **全份的测试计数链重算过一遍**。初稿有两处错：Task 1 写「本任务 6 条」实际只有 5 条（`test_app_assembly.py` 2 条 + `test_auth_router.py` 追加 3 条）；Task 3 的预期直接从「Task 1 后的 58」往上加，**把 Task 2 的 10 条整段漏掉了**。最终链条是 53（P1 实测）→ 58 → 68 → 76 → 95，HTTP 层那份接着 112 → 134。数字是用 `grep -c "def test_"` 按任务区间数出来的，不是估的；Task 3 那 8 条里不含 `test_migrations_roundtrip`（它是改写已有测试）。**执行时每个 Step 的实测数与计划不符就停下核对**——多半是漏跑了某个反向验证的恢复步骤。
2. **Task 4 加 `datasource_exists`**。写 Interfaces 时才发现 `get_visible` 把「不存在」与「无权限」都折成 `None`，而 Global Constraints 要求 404 与 403 分开——deps 必须能再问一次。发现即回头改了 Interfaces 与测试，没攒到 Task 5。
3. **Task 4 加 `_is_name_conflict` 与对应测试**。初稿把任何 `IntegrityError` 都翻成 409，那会把 `created_by` 的外键违规谎报成「名称已存在」，让真 bug 伪装成用户错误。
4. **`_within_savepoint` 改成在 savepoint 内部做改动**。初稿是 `session.add()` 后再 `begin_nested()` + flush；savepoint 的快照在 `begin_nested()` 那一刻才拍下，之前的 add 不会被回滚，对象仍在 `session.new` 里，下一次 autoflush 会原地再炸一次。反向验证第 5 条专门钉这个形状。
5. **表级 CHECK 只写进 migration，不写 `__table_args__`**。与 P1 的 `users.role` 一致：建表永远走 Alembic，模型里的 `__table_args__` 根本不会被执行，写两份只会得到两份不同步的约束。
6. **计划从一份拆成两份**。写完 Task 4 已 1792 行，续写 Task 5、6 会到 ~2600 行。切点选在领域层与 HTTP 层之间，因为 Task 4 结束时本身就是一个能独立验收的交付。
7. **`violated_constraint` 抽成 `db/integrity.py`**。这条是写 HTTP 层那份的 Task 6 时反向暴露的：`provisioning.create_user` 消化 P1 遗留 3 要做同样的「从 `IntegrityError` 取约束名」判别，两处各写一份 `getattr(getattr(exc.orig, "diag", None), ...)` 必然漂移。回头改了 Task 4 的 Files、Interfaces、Step 4 与本份交接清单。初稿里那个「取不到就退化成字符串匹配」的兜底也一并删了——`_NAME_CONSTRAINT in str(exc.orig)` 会把恰好在错误文本里出现该索引名的其他错误也判成重名。

**已知的松散端与取舍**

- **403 与 404 可区分，会泄露「某个 UUID 是否存在」**。这是照 Global Constraints 实现的（未授权按 id 访问 → `PERMISSION_DENIED`，未知 id → `DATASOURCE_NOT_FOUND`）。私有化部署、调用方已认证、UUID 不可枚举，代价可接受。若将来要完全不可区分，改成两种都返 404 并同步 spec §2.6——`datasource_exists` 那时就可以删掉。
- **`DatasourceUpdate` 没有「清空已存密码」的路径**（`password=None` 表示不改）。要清空得删了重建。取舍写在 schema 的 docstring 里。
- **`read_password` 在 P2a 没有生产调用方**，只有测试。形状和 P1 遗留 1（`purge_expired` 无调用方）一样，但这次是有意的：消费方是 P2b 的驱动层，且往返已被测试覆盖。写在这里，免得下一段审查又把它当成新发现。
- **`options` 是自由 JSONB，本段不校验内容**。P2b 的驱动会读它（`sslmode` 之类），届时校验放驱动层——只有驱动知道自己认哪些键。
- **主密钥没有轮换路径**。换 `CHATBI_SECRET_KEY` 会让所有已存密文解不开（`test_key_derivation_is_deterministic_and_key_dependent` 正是钉这个行为，不是 bug）。`HKDF_INFO` 带 `:v1` 留了余地，真做轮换要能同时持有新旧两把密钥，属 V2-2。
- **`test_the_supported_kinds_are_exactly_the_three_planned_drivers` 是回声断言**，无法反向验证（Task 3 Step 8 已注明）。它和 P1 的 `test_health.py` 同类。
- **`Datasource.database` 用了 `database` 作列名**。Postgres 里它是非保留字，SQLAlchemy 按需加引号，不必改名；但写手写 SQL 时记得它需要引号。
- **不能加 `pytest-xdist`**（沿用 P1 §10.4）：`test_migrations.py` 会短暂把库降到空表。
- **`db_session` 夹具的 `begin_nested()` 与仓储内部的 `begin_nested()` 会嵌套两层 savepoint**。SQLAlchemy 支持嵌套 savepoint，Task 4 的重名测试正是在这个组合下跑的；但如果将来有人给 `db_session` 换成非 savepoint 的隔离方式，Task 4 的 409 路径会先失效。

**类型一致性核对**

跨任务引用的名称与签名已逐一对齐：`DATASOURCE_KINDS`（Task 3 定义，Task 4 的 Literal 一致性测试引用）· `Datasource.has_password`（Task 4 加属性，同任务的 `DatasourceResponse` 消费）· `SealedSecret(ciphertext=, nonce=)`（Task 2 定义为 frozen dataclass，Task 4 的 `read_password` 按关键字构造）· `aad_for_datasource(datasource_id)`（Task 2 定义，Task 3 夹具与 Task 4 各调一次，参数都是 `uuid.UUID`）· `seal(plaintext, *, aad)` / `unseal(sealed, *, aad)`（`aad` 是 keyword-only，三处调用都带关键字）· `ApiError(code, message, status_code)` 与三元组常量的解包写法 `ApiError(*DATASOURCE_NAME_EXISTS)`（与 P1 一致）· `make_datasource` 的参数表在 Task 3 定义、Task 4 的四条测试引用，默认 `password="ds-pw-123456"` 与断言里的字面量一致。

无「Task N 定义、Task M 改名」的情况。`set_grant` / `revoke_grant` / `list_grants` 三个函数在本份只有仓储层实现与测试，HTTP 层的消费在下游那份的交接清单里已列明签名。
