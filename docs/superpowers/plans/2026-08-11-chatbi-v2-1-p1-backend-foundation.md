# Chat-BI V2-1 · P1 后端基座与认证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 v1 全部代码，建起 Python + FastAPI + Postgres 的后端基座，交付一个可登录、可鉴权、带角色控制的 API。

**Architecture:** 单体 FastAPI 应用，模块按领域切分（`auth` / `db` / `api`），依赖方向单向向下（`api` → 领域模块 → `db`）。认证走 `IdentityProvider` 抽象，V2-1 只实现本地账号；会话状态存 Postgres 而非无状态 JWT，使登出与禁用账号立即生效。

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · pydantic-settings · argon2-cffi · psycopg 3 · pytest · Docker Compose

**上游 spec:** [2026-08-11-chatbi-v2-1-design.md](../specs/2026-08-11-chatbi-v2-1-design.md)（§0.4 技术取舍、§1 模块边界、§2.5 数据模型、§4.1–4.2 认证与授权、§5 测试策略）

## Global Constraints

每个任务的要求都隐含包含本节。数值全部照 spec 原样抄。

**版本与依赖**
- Python 3.12。依赖用 `pyproject.toml` + `uv`（`uv sync` / `uv run`）。
- 后端依赖只允许：`fastapi`、`uvicorn[standard]`、`sqlalchemy>=2.0`、`alembic`、`psycopg[binary]>=3.1`、`pydantic-settings`、`argon2-cffi`、`python-multipart`、`typer`。测试额外：`pytest`、`pytest-asyncio`、`httpx`。
- **V2-1 不装 pgvector**——没有向量检索需求，扩展随 V2-2 的 migration 进（spec §0.4）。

**数据库**
- 应用库 Postgres 16。所有表结构变更走 Alembic，不用 `create_all()`。
- 每个 migration 必须过 up/down 双向测试（spec §5.3）。
- 测试库通过环境变量 `TEST_DATABASE_URL` 指定，且**库名必须以 `_test` 结尾**，否则测试夹具直接报错退出——防止误指向真库后被 `downgrade base` 清空。
- 应用库测试**不允许 skip**。缺库就是失败：没有应用库这个后端没有任何功能可测。（spec §5.1 的「skip 要计数上报」针对的是外部数据源驱动，见 P2。）

**认证与会话**
- 密码哈希用 argon2id（`argon2-cffi` 的 `PasswordHasher` 默认即 argon2id）。
- 会话 cookie 名 `chatbi_session`，`httponly=True`、`samesite="lax"`、`secure` 由 `settings.cookie_secure` 控制（生产 true）。**不用 localStorage 存令牌**（spec §4.1）。
- 会话状态存 `sessions` 表，登出与禁用账号立即失效。默认有效期 12 小时。
- 角色只有三个：`admin`（管数据源与用户）/ `analyst`（问数、改 SQL、执行）/ `viewer`（只看历史，不能执行）。
- **不做注册页面**，首次启动用 CLI 创建 admin（spec §4.1）。

**安全**
- 主密钥从 `CHATBI_SECRET_KEY` 环境变量或 `CHATBI_SECRET_KEY_FILE` 指向的文件读取。**不入库、不入日志、不进任何错误消息**（spec §4.4）。任何承载它的对象 `repr()` 必须脱敏。
- 登录失败不区分「用户不存在」与「密码错误」，统一返回同一个 401 与同一句文案——防用户名枚举。
- Pydantic 响应模型**不声明**敏感字段（而不是靠序列化时记得排除）。

**错误码**（spec §2.6 的 P1 相关子集，前端按码渲染文案，不透传后端消息原文）
- `INVALID_CREDENTIALS`（401）· `NOT_AUTHENTICATED`（401）· `PERMISSION_DENIED`（403）· `USER_NOT_FOUND`（404）· `EMAIL_ALREADY_EXISTS`（409）
- 响应体统一形状：`{"code": "<CODE>", "message": "<中文可读文案>"}`

**契约**
- Pydantic 模型是 OpenAPI 唯一真相源（spec §0.4）。P1 不生成前端类型（P4 才有前端），但路由必须带完整的 `response_model` 与 `responses` 声明，否则 P4 生成的类型会缺字段。

## 本机环境（2026-08-11 实测，实施时照此执行）

工具链已装好：Python 3.12.10、uv 0.12.2、Docker CLI 29.6.2、PostgreSQL 16.14。

**Docker 守护进程在本机尚不可用**——Docker Desktop 已安装，但 WSL2 无发行版、功能未启用，需要管理员跑 `wsl --install` + 重启 + 手动首次启动接受许可。因此：

- `docker/compose.yml` 照 Task 1 Step 2 **写出来但不要运行**，也不要在 P1 里验证它。它服务于部署与 P2 的三驱动契约测。
- P1 的应用库用**本机原生 PostgreSQL 16**，监听 `5432`，账号 `chatbi` / 密码 `chatbi`，`chatbi` 与 `chatbi_test` 两个库已建好并验证可连。
- 因此本计划所有开发/测试命令用 **5432**，而 compose 保持映射 **5433**（有意错开：宿主 5432 已被原生实例占用）。`config.py` 的默认 `database_url` 指向 5432 以贴合本机；P2 起 Docker 后改用环境变量覆盖即可。

```bash
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
```

**流程**
- TDD：每个任务先写失败的测试，跑一次确认失败，再写最小实现，跑一次确认通过，然后提交。
- 提交信息用 `feat:` / `test:` / `chore:` / `docs:` 前缀，末尾带 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`。
- 当前分支 `feature_v2.0`，不切新分支。

---

## File Structure

### 要删除的 v1 文件（Task 1）

整个 `apps/backend/`（64 个跟踪文件）、`apps/frontend/`（60 个）、`packages/shared/`（11 个），以及根上的 JS 工程配置 `package.json`、`package-lock.json`、`tsconfig.base.json`、`vitest.workspace.ts`。共 139 个跟踪文件。未跟踪的 `node_modules/`、`data/`、`.tmp-run/` 一并从工作树移除。

`docs/`、`.gitignore`、`README.md`、`.claude/`、`.superpowers/` 保留（README 内容在 Task 1 重写）。

### P1 创建的文件

| 文件 | 职责 |
|---|---|
| `apps/api/pyproject.toml` | 依赖与工具配置（pytest、ruff） |
| `apps/api/alembic.ini` | Alembic 配置，指向 `migrations/` |
| `apps/api/migrations/env.py` | Alembic 运行时，从 `settings` 读 DB URL |
| `apps/api/migrations/versions/0001_users_sessions.py` | 建 `users`、`sessions` |
| `apps/api/src/chatbi/__init__.py` | 包标记 |
| `apps/api/src/chatbi/main.py` | FastAPI 装配：生命周期、异常处理器、路由挂载 |
| `apps/api/src/chatbi/config.py` | `Settings`（pydantic-settings）+ 主密钥加载 |
| `apps/api/src/chatbi/errors.py` | `ApiError` 异常与错误码常量，统一响应形状 |
| `apps/api/src/chatbi/db/base.py` | `Base`、引擎与 `SessionLocal` 工厂 |
| `apps/api/src/chatbi/db/models.py` | `User`、`Session` 的 SQLAlchemy 模型 |
| `apps/api/src/chatbi/auth/hashing.py` | argon2id 哈希与校验 |
| `apps/api/src/chatbi/auth/identity.py` | `IdentityProvider` 协议 + `LocalIdentityProvider` |
| `apps/api/src/chatbi/auth/sessions.py` | 会话的建/查/删 |
| `apps/api/src/chatbi/auth/deps.py` | `current_user`、`require_role` FastAPI 依赖 |
| `apps/api/src/chatbi/auth/schemas.py` | 登录请求与用户响应的 Pydantic 模型 |
| `apps/api/src/chatbi/api/auth_router.py` | `/api/auth/login`、`/logout`、`/me` |
| `apps/api/src/chatbi/cli.py` | `create-admin` 等管理命令（typer） |
| `apps/api/tests/conftest.py` | 测试库夹具、`_test` 库名守卫、事务回滚、`client` |
| `apps/api/tests/test_health.py` | `/health` |
| `apps/api/tests/test_config.py` | 配置与主密钥加载 |
| `apps/api/tests/test_migrations.py` | up/down 双向 |
| `apps/api/tests/test_hashing.py` | 哈希 |
| `apps/api/tests/test_identity.py` | 认证语义 |
| `apps/api/tests/test_sessions.py` | 会话生命周期 |
| `apps/api/tests/test_auth_router.py` | 登录端点与 cookie |
| `apps/api/tests/test_deps.py` | 角色控制 |
| `apps/api/tests/test_cli.py` | CLI 建号 |
| `docker/compose.yml` | `app-postgres`（含 `chatbi` 与 `chatbi_test` 两个库）、`ollama` |
| `README.md` | 重写：V2-1 定位、起服务、跑测试 |

### 边界说明

`auth/` 内四个文件各司一职，互不越界：`hashing` 只做密码学、不碰 DB；`identity` 只回答「这对凭据属于哪个启用中的用户」、不管 cookie；`sessions` 只管会话记录的生命周期、不认识密码；`deps` 只做 FastAPI 依赖装配、不含判断逻辑。`api/auth_router.py` 只做 HTTP 编排（读 cookie、设 cookie、转错误码），业务判断全在上述模块里——这样认证语义能脱离 HTTP 测（spec §1.3 规则 2）。

---

### Task 1: 清空 v1 并搭起 Python 骨架

**Files:**
- Delete: `apps/backend/`、`apps/frontend/`、`packages/`、`package.json`、`package-lock.json`、`tsconfig.base.json`、`vitest.workspace.ts`
- Create: `apps/api/pyproject.toml`、`apps/api/src/chatbi/__init__.py`、`apps/api/src/chatbi/main.py`、`apps/api/tests/test_health.py`、`docker/compose.yml`、`docker/initdb/01-create-test-db.sql`
- Modify: `README.md`（整体重写）、`.gitignore`（加 Python 相关忽略项）

**Interfaces:**
- Consumes: 无（本计划第一个任务）
- Produces: `chatbi.main.app`（`fastapi.FastAPI` 实例）；可跑的 `pytest`；docker compose 服务 `app-postgres`（宿主端口 **5433**）与 `ollama`（11434）

- [ ] **Step 1: 删除 v1 代码**

```bash
git rm -r --quiet apps/backend apps/frontend packages package.json package-lock.json tsconfig.base.json vitest.workspace.ts
rm -rf node_modules data .tmp-run
```

删除后 `git status --short` 应只剩这些删除项，`docs/` 与 `.claude/` 未受影响。

- [ ] **Step 2: 建 docker compose**

创建 `docker/compose.yml`：

```yaml
services:
  app-postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: chatbi
      POSTGRES_PASSWORD: chatbi
      POSTGRES_DB: chatbi
    ports: ["5433:5432"]
    volumes:
      - ./initdb:/docker-entrypoint-initdb.d
      - app-pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U chatbi"]
      interval: 5s
      retries: 10

  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes:
      - ollama:/root/.ollama

volumes:
  app-pgdata:
  ollama:
```

宿主端口用 5433 而非 5432，避免与开发机上已有的原生 Postgres 抢端口。

> **本任务只写这个文件，不要运行 `docker compose up`。** 本机 Docker 守护进程尚不可用（见「本机环境」），P1 用原生 Postgres。这个文件到 P2 才会被真正跑起来。

创建 `docker/initdb/01-create-test-db.sql`：

```sql
CREATE DATABASE chatbi_test OWNER chatbi;
```

- [ ] **Step 3: 建 Python 工程**

创建 `apps/api/pyproject.toml`：

```toml
[project]
name = "chatbi-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0",
    "alembic>=1.14",
    "psycopg[binary]>=3.1",
    "pydantic-settings>=2.6",
    "argon2-cffi>=23.1",
    "python-multipart>=0.0.12",
    "typer>=0.15",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "httpx>=0.28", "ruff>=0.8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/chatbi"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

创建空的 `apps/api/src/chatbi/__init__.py`，然后装依赖：

```bash
cd apps/api && uv sync
```

- [ ] **Step 4: 写失败的测试**

创建 `apps/api/tests/test_health.py`：

```python
from fastapi.testclient import TestClient

from chatbi.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 5: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_health.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'chatbi.main'`

- [ ] **Step 6: 写最小实现**

创建 `apps/api/src/chatbi/main.py`：

```python
from fastapi import FastAPI

app = FastAPI(title="Chat-BI API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_health.py -v`
Expected: PASS（1 passed）

- [ ] **Step 8: 更新 .gitignore 与 README**

`.gitignore` 追加：

```
__pycache__/
*.pyc
.venv/
.pytest_cache/
.ruff_cache/
```

`README.md` 重写为 V2-1 内容：产品定位一段（分析师 AI 副驾，SQL 看得见/改得了/存得下）、四段路线图表（V2-1 到 V2-3，标注当前进度 P1）、本地起服务步骤（原生 Postgres 或 compose、`cd apps/api && uv sync`、`uv run uvicorn chatbi.main:app --reload`）、跑测试步骤（含 `TEST_DATABASE_URL` 的导出命令）。不要保留任何 v1 的 npm 命令说明。

- [ ] **Step 9: 提交**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore: 删除 v1 全部代码，搭起 Python/FastAPI 骨架

v1 定位为业务人员自助工具，V2-1 换为分析师 AI 副驾并换栈到
Python，无可增量演进的部分。v1 代码可从本次提交的父节点恢复。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 配置与主密钥加载

**Files:**
- Create: `apps/api/src/chatbi/config.py`、`apps/api/tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `chatbi.config.Settings`：字段 `database_url: str`、`secret_key: SecretStr`、`secret_key_file: Path | None`、`cookie_secure: bool`、`session_ttl_hours: int`
  - `chatbi.config.get_settings() -> Settings`（`lru_cache` 缓存；测试里改环境变量后必须调 `get_settings.cache_clear()`）
  - 环境变量前缀 `CHATBI_`，即 `CHATBI_DATABASE_URL`、`CHATBI_SECRET_KEY`、`CHATBI_SECRET_KEY_FILE`、`CHATBI_COOKIE_SECURE`、`CHATBI_SESSION_TTL_HOURS`

- [ ] **Step 1: 写失败的测试**

创建 `apps/api/tests/test_config.py`：

```python
import pytest
from pydantic import ValidationError

from chatbi.config import Settings


def test_secret_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATBI_SECRET_KEY", "s3cret-from-env")

    settings = Settings()

    assert settings.secret_key.get_secret_value() == "s3cret-from-env"


def test_secret_key_from_file(monkeypatch, tmp_path) -> None:
    key_file = tmp_path / "master.key"
    key_file.write_text("  s3cret-from-file\n", encoding="utf-8")
    monkeypatch.delenv("CHATBI_SECRET_KEY", raising=False)
    monkeypatch.setenv("CHATBI_SECRET_KEY_FILE", str(key_file))

    settings = Settings()

    assert settings.secret_key.get_secret_value() == "s3cret-from-file"


def test_missing_secret_key_is_a_clear_error(monkeypatch) -> None:
    monkeypatch.delenv("CHATBI_SECRET_KEY", raising=False)
    monkeypatch.delenv("CHATBI_SECRET_KEY_FILE", raising=False)

    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert "CHATBI_SECRET_KEY" in str(excinfo.value)


def test_empty_key_file_is_rejected(monkeypatch, tmp_path) -> None:
    key_file = tmp_path / "empty.key"
    key_file.write_text("   \n", encoding="utf-8")
    monkeypatch.delenv("CHATBI_SECRET_KEY", raising=False)
    monkeypatch.setenv("CHATBI_SECRET_KEY_FILE", str(key_file))

    with pytest.raises(ValidationError):
        Settings()


def test_repr_does_not_leak_the_secret(monkeypatch) -> None:
    monkeypatch.setenv("CHATBI_SECRET_KEY", "do-not-print-me")

    settings = Settings()

    assert "do-not-print-me" not in repr(settings)
```

> `tests/test_config.py` 里不要用 `conftest.py` 的自动夹具设置的环境变量，`monkeypatch.delenv` 已显式清理。Task 3 建 `conftest.py` 时会给 `CHATBI_SECRET_KEY` 设默认值，这四个测试用 `monkeypatch` 覆盖，互不干扰。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_config.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'chatbi.config'`

- [ ] **Step 3: 写最小实现**

创建 `apps/api/src/chatbi/config.py`：

```python
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。主密钥永不出现在 repr 或日志中（SecretStr 负责脱敏）。"""

    model_config = SettingsConfigDict(env_prefix="CHATBI_", extra="ignore")

    database_url: str = "postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi"
    secret_key: SecretStr | None = None
    secret_key_file: Path | None = None
    cookie_secure: bool = False
    session_ttl_hours: int = 12

    @model_validator(mode="after")
    def _resolve_secret_key(self) -> "Settings":
        if self.secret_key is not None:
            return self
        if self.secret_key_file is None:
            raise ValueError("主密钥未配置：请设置 CHATBI_SECRET_KEY 或 CHATBI_SECRET_KEY_FILE")
        if not self.secret_key_file.is_file():
            raise ValueError(f"CHATBI_SECRET_KEY_FILE 指向的文件不存在：{self.secret_key_file}")
        text = self.secret_key_file.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("CHATBI_SECRET_KEY_FILE 指向的文件为空")
        self.secret_key = SecretStr(text)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_config.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/api/src/chatbi/config.py apps/api/tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(config): Settings 与主密钥加载

主密钥支持环境变量或密钥文件两种来源，缺失时给出中文可读错误；
用 SecretStr 保证 repr 不泄露明文。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 应用库、模型与 Alembic

**Files:**
- Create: `apps/api/src/chatbi/db/__init__.py`、`apps/api/src/chatbi/db/base.py`、`apps/api/src/chatbi/db/models.py`、`apps/api/alembic.ini`、`apps/api/migrations/env.py`、`apps/api/migrations/script.py.mako`、`apps/api/migrations/versions/0001_users_sessions.py`、`apps/api/tests/conftest.py`、`apps/api/tests/test_migrations.py`

**Interfaces:**
- Consumes: `chatbi.config.get_settings`
- Produces:
  - `chatbi.db.base.Base`（DeclarativeBase）、`get_engine()`、`get_session_factory()`、`get_db() -> Iterator[Session]`（FastAPI 依赖）
  - `chatbi.db.models.User`：`id: uuid.UUID`、`email: str`、`display_name: str`、`password_hash: str`、`role: str`、`is_active: bool`、`created_at: datetime`
  - `chatbi.db.models.UserSession`（表名 `sessions`）：`id: uuid.UUID`、`user_id: uuid.UUID`、`expires_at: datetime`、`created_at: datetime`
  - `chatbi.db.models.ROLES: tuple[str, str, str] = ("admin", "analyst", "viewer")`
  - pytest 夹具：`db_session: Session`（每测试事务回滚）、`client: TestClient`（已把 `get_db` 覆盖到 `db_session`）

> **email 用 `String` + 应用层小写规范化，不用 citext。** spec §2.5 原写 `citext`，落地时改掉：citext 要额外建扩展，且 SQLAlchemy 的 CITEXT 类型有版本门槛，收益只是省一次 `.lower()`。规范化在 `LocalIdentityProvider`（Task 5）与 CLI（Task 9）两处入口做。spec 已同步更新。

- [ ] **Step 1: 写模型与 db 基座**

创建 `apps/api/src/chatbi/db/__init__.py`（空文件）与 `apps/api/src/chatbi/db/base.py`：

```python
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from chatbi.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每请求一个会话，异常时回滚。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

创建 `apps/api/src/chatbi/db/models.py`：

```python
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from chatbi.db.base import Base

ROLES: tuple[str, str, str] = ("admin", "analyst", "viewer")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(sa.String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    role: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class UserSession(Base):
    """会话记录。类名不叫 Session 以免与 sqlalchemy.orm.Session 混淆。"""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
```

- [ ] **Step 2: 初始化 Alembic 并接上 settings**

```bash
cd apps/api && uv run alembic init migrations
```

然后对生成的文件做三处修改：

`alembic.ini` —— 删掉 `sqlalchemy.url = ...` 那一行（URL 由 `env.py` 从 settings 注入），并把 `script_location` 确认为 `migrations`。

`migrations/env.py` —— 在 `config = context.config` 之后插入：

```python
from chatbi.config import get_settings
from chatbi.db import models  # noqa: F401  导入以注册模型元数据
from chatbi.db.base import Base

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
```

并把文件里原有的 `target_metadata = None` 删掉。

`migrations/versions/` —— 手写 migration，不用 `--autogenerate`：autogenerate 会把开发机上的偏差写进版本文件，手写更可预测。

- [ ] **Step 3: 写 0001 migration**

创建 `apps/api/migrations/versions/0001_users_sessions.py`：

```python
"""users and sessions

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("role in ('admin','analyst','viewer')", name="ck_users_role"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
```

- [ ] **Step 4: 写测试夹具**

创建 `apps/api/tests/conftest.py`：

```python
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _test_env() -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL 未设置。应用库测试不允许 skip——没有应用库这个后端无功能可测。\n"
            "  export TEST_DATABASE_URL="
            "postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test",
            pytrace=False,
        )
    db_name = url.rsplit("/", 1)[-1].split("?")[0]
    if not db_name.endswith("_test"):
        pytest.fail(
            f"TEST_DATABASE_URL 的库名必须以 _test 结尾，当前是 {db_name!r}。"
            "夹具会执行 downgrade base，指向真库会清空数据。",
            pytrace=False,
        )
    os.environ["CHATBI_DATABASE_URL"] = url
    os.environ.setdefault("CHATBI_SECRET_KEY", "test-secret-key-not-for-production")


@pytest.fixture(scope="session", autouse=True)
def _migrated(_test_env: None) -> None:
    subprocess.run(["uv", "run", "alembic", "downgrade", "base"], cwd=API_ROOT, check=True)
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=API_ROOT, check=True)


@pytest.fixture
def db_session(_migrated: None) -> Iterator[Session]:
    """每个测试跑在一个最终回滚的事务里，测试之间互不可见。"""
    engine = create_engine(os.environ["CHATBI_DATABASE_URL"])
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    from chatbi.db.base import get_db
    from chatbi.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
```

创建 `apps/api/tests/test_migrations.py`：

```python
import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, inspect

API_ROOT = Path(__file__).resolve().parents[1]


def _alembic(*args: str) -> None:
    subprocess.run(["uv", "run", "alembic", *args], cwd=API_ROOT, check=True)


def _table_names() -> set[str]:
    engine = create_engine(os.environ["CHATBI_DATABASE_URL"])
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migrations_roundtrip(_migrated: None) -> None:
    """从 head 出发 down 到底再 up 回 head，结束时状态与开始时一致。"""
    assert {"users", "sessions"} <= _table_names()

    _alembic("downgrade", "base")
    assert not {"users", "sessions"} & _table_names()

    _alembic("upgrade", "head")
    assert {"users", "sessions"} <= _table_names()
```

> 这个测试会短暂把库降到空表，因此**不能与其他测试并行跑**。pytest 默认串行，不要给这个仓库加 `pytest-xdist`；若将来要加，必须给本模块打独占标记。

- [ ] **Step 5: 跑测试确认通过**

```bash
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
cd apps/api && uv run pytest -v
```

Expected: PASS（Task 1–3 的全部测试，6 passed 以上）

- [ ] **Step 6: 验证守卫生效**

```bash
cd apps/api && TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi uv run pytest -x
```

Expected: 立即失败并打印「库名必须以 `_test` 结尾」，**且 `chatbi` 库未被改动**。跑完把环境变量改回 `chatbi_test`。

- [ ] **Step 7: 提交**

```bash
git add apps/api/src/chatbi/db apps/api/alembic.ini apps/api/migrations apps/api/tests
git commit -m "$(cat <<'EOF'
feat(db): 应用库基座、users/sessions 模型与 Alembic

migration 手写不用 autogenerate；测试夹具用事务回滚做隔离，
并守卫测试库名必须以 _test 结尾，防止误指真库被 downgrade 清空。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 密码哈希

**Files:**
- Create: `apps/api/src/chatbi/auth/__init__.py`、`apps/api/src/chatbi/auth/hashing.py`、`apps/api/tests/test_hashing.py`

**Interfaces:**
- Consumes: 无（纯密码学，不碰 DB）
- Produces: `chatbi.auth.hashing.hash_password(plaintext: str) -> str`、`verify_password(plaintext: str, hashed: str) -> bool`

- [ ] **Step 1: 写失败的测试**

创建 `apps/api/tests/test_hashing.py`：

```python
from chatbi.auth.hashing import hash_password, verify_password


def test_hash_is_not_the_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$argon2id$")


def test_verify_accepts_the_right_password() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_rejects_the_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("Correct Horse Battery Staple", hashed) is False


def test_verify_rejects_a_malformed_hash_without_raising() -> None:
    assert verify_password("anything", "not-a-hash") is False


def test_same_password_hashes_differently() -> None:
    assert hash_password("same") != hash_password("same")
```

最后一条测的是盐随机性——两次哈希同一密码必须不同，否则相同密码的用户在库里可被识别出来。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_hashing.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'chatbi.auth'`

- [ ] **Step 3: 写最小实现**

创建空的 `apps/api/src/chatbi/auth/__init__.py`，以及 `apps/api/src/chatbi/auth/hashing.py`：

```python
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

_hasher = PasswordHasher()  # 默认算法即 argon2id


def hash_password(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """密码是否匹配。哈希串损坏时返回 False 而不是抛异常——
    调用方在登录路径上，不该因为库里一条脏数据就 500。"""
    try:
        return _hasher.verify(hashed, plaintext)
    except (Argon2Error, InvalidHashError):
        return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_hashing.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/api/src/chatbi/auth apps/api/tests/test_hashing.py
git commit -m "$(cat <<'EOF'
feat(auth): argon2id 密码哈希

哈希串损坏时 verify 返回 False 而不抛异常，避免一条脏数据把
登录路径打成 500。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: IdentityProvider 与本地账号认证

**Files:**
- Create: `apps/api/src/chatbi/auth/identity.py`、`apps/api/tests/test_identity.py`

**Interfaces:**
- Consumes: `chatbi.auth.hashing.verify_password`、`chatbi.db.models.User`、夹具 `db_session`
- Produces:
  - `chatbi.auth.identity.IdentityProvider`（`typing.Protocol`）：`authenticate(session: Session, email: str, password: str) -> User | None`
  - `chatbi.auth.identity.LocalIdentityProvider`：实现上述协议
  - `chatbi.auth.identity.normalize_email(email: str) -> str`（`strip()` + `lower()`）
  - P2/P3 通过 `get_identity_provider() -> IdentityProvider` 取实现，不直接实例化

- [ ] **Step 1: 写失败的测试**

创建 `apps/api/tests/test_identity.py`：

```python
import uuid

import pytest
from sqlalchemy.orm import Session

from chatbi.auth.hashing import hash_password
from chatbi.auth.identity import LocalIdentityProvider, normalize_email
from chatbi.db.models import User


def _make_user(session: Session, *, email: str, password: str, is_active: bool = True) -> User:
    user = User(
        id=uuid.uuid4(),
        email=normalize_email(email),
        display_name="测试用户",
        password_hash=hash_password(password),
        role="analyst",
        is_active=is_active,
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def provider() -> LocalIdentityProvider:
    return LocalIdentityProvider()


def test_authenticates_a_valid_user(db_session: Session, provider) -> None:
    _make_user(db_session, email="ann@example.com", password="pw-12345678")

    result = provider.authenticate(db_session, "ann@example.com", "pw-12345678")

    assert result is not None
    assert result.email == "ann@example.com"


def test_email_matching_ignores_case_and_whitespace(db_session: Session, provider) -> None:
    _make_user(db_session, email="ann@example.com", password="pw-12345678")

    result = provider.authenticate(db_session, "  Ann@Example.COM ", "pw-12345678")

    assert result is not None


def test_rejects_a_wrong_password(db_session: Session, provider) -> None:
    _make_user(db_session, email="ann@example.com", password="pw-12345678")

    assert provider.authenticate(db_session, "ann@example.com", "wrong-password") is None


def test_rejects_an_unknown_email(db_session: Session, provider) -> None:
    assert provider.authenticate(db_session, "nobody@example.com", "pw-12345678") is None


def test_rejects_a_disabled_account(db_session: Session, provider) -> None:
    _make_user(db_session, email="gone@example.com", password="pw-12345678", is_active=False)

    assert provider.authenticate(db_session, "gone@example.com", "pw-12345678") is None


def test_unknown_email_and_wrong_password_are_indistinguishable(
    db_session: Session, provider
) -> None:
    """两种失败都返回 None，调用方无法据此判断账号是否存在（防用户名枚举）。"""
    _make_user(db_session, email="ann@example.com", password="pw-12345678")

    assert provider.authenticate(db_session, "ann@example.com", "wrong") is None
    assert provider.authenticate(db_session, "nobody@example.com", "wrong") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_identity.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'chatbi.auth.identity'`

- [ ] **Step 3: 写最小实现**

创建 `apps/api/src/chatbi/auth/identity.py`：

```python
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from chatbi.auth.hashing import hash_password, verify_password
from chatbi.db.models import User

# 邮箱不存在时也走一次哈希校验，让成功与失败路径耗时接近，不泄露账号是否存在
_DUMMY_HASH = hash_password("timing-equalizer")


def normalize_email(email: str) -> str:
    return email.strip().lower()


class IdentityProvider(Protocol):
    """身份来源抽象。V2-1 只有本地账号；OIDC/LDAP 换实现不改调用方。"""

    def authenticate(self, session: Session, email: str, password: str) -> User | None: ...


class LocalIdentityProvider:
    def authenticate(self, session: Session, email: str, password: str) -> User | None:
        user = session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is None:
            verify_password(password, _DUMMY_HASH)
            return None
        if not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user


def get_identity_provider() -> IdentityProvider:
    return LocalIdentityProvider()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_identity.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/api/src/chatbi/auth/identity.py apps/api/tests/test_identity.py
git commit -m "$(cat <<'EOF'
feat(auth): IdentityProvider 抽象与本地账号认证

邮箱在应用层小写规范化；账号不存在时也走一次哈希校验以拉平
耗时，两种失败对调用方不可区分，防用户名枚举。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 会话生命周期

**Files:**
- Create: `apps/api/src/chatbi/auth/sessions.py`、`apps/api/tests/test_sessions.py`

**Interfaces:**
- Consumes: `chatbi.db.models.UserSession`、`chatbi.db.models.User`、`chatbi.config.get_settings`
- Produces:
  - `create_session(session: Session, user: User) -> UserSession`
  - `lookup_session(session: Session, session_id: str) -> User | None`（过期或不存在都返回 `None`）
  - `delete_session(session: Session, session_id: str) -> None`
  - `purge_expired(session: Session) -> int`（返回清掉的条数）

- [ ] **Step 1: 写失败的测试**

创建 `apps/api/tests/test_sessions.py`：

```python
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from chatbi.auth.hashing import hash_password
from chatbi.auth.sessions import create_session, delete_session, lookup_session, purge_expired
from chatbi.db.models import User, UserSession


def _make_user(session: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        display_name="测试用户",
        password_hash=hash_password("pw-12345678"),
        role="analyst",
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def test_create_session_sets_a_future_expiry(db_session: Session) -> None:
    user = _make_user(db_session)

    record = create_session(db_session, user)

    assert record.user_id == user.id
    assert record.expires_at > datetime.now(UTC)


def test_lookup_returns_the_user(db_session: Session) -> None:
    user = _make_user(db_session)
    record = create_session(db_session, user)

    found = lookup_session(db_session, str(record.id))

    assert found is not None
    assert found.id == user.id


def test_lookup_rejects_an_expired_session(db_session: Session) -> None:
    user = _make_user(db_session)
    record = create_session(db_session, user)
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    assert lookup_session(db_session, str(record.id)) is None


def test_lookup_rejects_an_unknown_id(db_session: Session) -> None:
    assert lookup_session(db_session, str(uuid.uuid4())) is None


def test_lookup_rejects_a_malformed_id(db_session: Session) -> None:
    """cookie 内容是客户端可控的，非 UUID 不能让查询抛异常。"""
    assert lookup_session(db_session, "../../etc/passwd") is None


def test_lookup_rejects_a_session_whose_user_was_disabled(db_session: Session) -> None:
    user = _make_user(db_session)
    record = create_session(db_session, user)
    user.is_active = False
    db_session.flush()

    assert lookup_session(db_session, str(record.id)) is None


def test_delete_session_takes_effect_immediately(db_session: Session) -> None:
    user = _make_user(db_session)
    record = create_session(db_session, user)

    delete_session(db_session, str(record.id))

    assert lookup_session(db_session, str(record.id)) is None


def test_purge_expired_removes_only_expired_rows(db_session: Session) -> None:
    user = _make_user(db_session)
    alive = create_session(db_session, user)
    stale = create_session(db_session, user)
    stale.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.flush()

    removed = purge_expired(db_session)

    assert removed == 1
    assert db_session.get(UserSession, alive.id) is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_sessions.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'chatbi.auth.sessions'`

- [ ] **Step 3: 写最小实现**

创建 `apps/api/src/chatbi/auth/sessions.py`：

```python
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from chatbi.config import get_settings
from chatbi.db.models import User, UserSession


def _parse_id(session_id: str) -> uuid.UUID | None:
    """cookie 内容由客户端控制，非 UUID 一律当作无效会话。"""
    try:
        return uuid.UUID(session_id)
    except (ValueError, AttributeError, TypeError):
        return None


def create_session(session: Session, user: User) -> UserSession:
    record = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=get_settings().session_ttl_hours),
    )
    session.add(record)
    session.flush()
    return record


def lookup_session(session: Session, session_id: str) -> User | None:
    parsed = _parse_id(session_id)
    if parsed is None:
        return None
    record = session.get(UserSession, parsed)
    if record is None or record.expires_at <= datetime.now(UTC):
        return None
    user = session.get(User, record.user_id)
    if user is None or not user.is_active:
        return None
    return user


def delete_session(session: Session, session_id: str) -> None:
    parsed = _parse_id(session_id)
    if parsed is None:
        return
    session.execute(delete(UserSession).where(UserSession.id == parsed))
    session.flush()


def purge_expired(session: Session) -> int:
    result = session.execute(
        delete(UserSession).where(UserSession.expires_at <= datetime.now(UTC))
    )
    session.flush()
    return result.rowcount or 0
```

> `purge_expired` 在 P1 **不接任何调用方**（没有调度器）。P2 在登录成功路径上顺手调一次即可，不引定时任务框架。这是有意留的一个未接线函数，不是漏做。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_sessions.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/api/src/chatbi/auth/sessions.py apps/api/tests/test_sessions.py
git commit -m "$(cat <<'EOF'
feat(auth): 会话建查删与过期清理

cookie 内容客户端可控，非 UUID 一律当无效会话而不抛异常；
禁用账号的既有会话立即失效。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 登录、登出、当前用户端点

**Files:**
- Create: `apps/api/src/chatbi/errors.py`、`apps/api/src/chatbi/auth/schemas.py`、`apps/api/src/chatbi/auth/deps.py`、`apps/api/src/chatbi/api/__init__.py`、`apps/api/src/chatbi/api/auth_router.py`、`apps/api/tests/test_auth_router.py`
- Modify: `apps/api/src/chatbi/main.py`（挂路由与异常处理器）、`apps/api/tests/conftest.py`（加 `make_user` 夹具）、`apps/api/tests/test_identity.py` 与 `apps/api/tests/test_sessions.py`（改用共享夹具，删掉各自的 `_make_user`）

**Interfaces:**
- Consumes: `LocalIdentityProvider`、`create_session`/`delete_session`/`lookup_session`、`get_db`、`get_settings`
- Produces:
  - `chatbi.errors.ApiError(code, message, status_code)` 与错误码常量 `INVALID_CREDENTIALS`、`NOT_AUTHENTICATED`、`PERMISSION_DENIED`、`USER_NOT_FOUND`、`EMAIL_ALREADY_EXISTS`（均为 `(code, message, status)` 三元组，用 `raise ApiError(*CONST)` 抛出）
  - `chatbi.errors.api_error_handler`（注册到 app 后，所有 `ApiError` 统一序列化成 `{"code", "message"}`）
  - `chatbi.auth.schemas.LoginRequest`、`UserResponse`、`ErrorResponse`
  - `chatbi.auth.deps.SESSION_COOKIE = "chatbi_session"`、`current_user`（FastAPI 依赖，返回 `User`）
  - 端点 `POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`
  - pytest 夹具 `make_user(email=..., password=..., role="analyst", is_active=True) -> User`

- [ ] **Step 1: 写共享的 make_user 夹具**

在 `apps/api/tests/conftest.py` 末尾追加：

```python
@pytest.fixture
def make_user(db_session: Session):
    """建一个测试用户。默认 analyst 角色、启用状态。"""
    import uuid

    from chatbi.auth.hashing import hash_password
    from chatbi.auth.identity import normalize_email
    from chatbi.db.models import User

    def _make(
        *,
        email: str | None = None,
        password: str = "pw-12345678",
        display_name: str = "测试用户",
        role: str = "analyst",
        is_active: bool = True,
    ) -> User:
        user = User(
            id=uuid.uuid4(),
            email=normalize_email(email or f"u-{uuid.uuid4().hex[:8]}@example.com"),
            display_name=display_name,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _make
```

然后把 `tests/test_identity.py` 与 `tests/test_sessions.py` 里各自的 `_make_user` 删掉，改用 `make_user` 夹具（调用处从 `_make_user(db_session, email=..., password=...)` 改成 `make_user(email=..., password=...)`）。跑一次 `uv run pytest -v` 确认这两个模块仍全绿再往下走。

- [ ] **Step 2: 写失败的测试**

创建 `apps/api/tests/test_auth_router.py`：

```python
from fastapi.testclient import TestClient

from chatbi.auth.deps import SESSION_COOKIE


def test_login_succeeds_and_sets_an_httponly_cookie(client: TestClient, make_user) -> None:
    make_user(email="ann@example.com", password="pw-12345678")

    response = client.post(
        "/api/auth/login", json={"email": "ann@example.com", "password": "pw-12345678"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "ann@example.com"
    cookie_header = response.headers["set-cookie"]
    assert SESSION_COOKIE in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header.replace("samesite", "SameSite")


def test_login_response_never_contains_the_password_hash(client: TestClient, make_user) -> None:
    make_user(email="ann@example.com", password="pw-12345678")

    response = client.post(
        "/api/auth/login", json={"email": "ann@example.com", "password": "pw-12345678"}
    )

    assert "password_hash" not in response.text
    assert "argon2" not in response.text


def test_wrong_password_and_unknown_email_return_the_same_error(
    client: TestClient, make_user
) -> None:
    """两者响应完全一致，攻击者无法据此枚举账号。"""
    make_user(email="ann@example.com", password="pw-12345678")

    wrong_password = client.post(
        "/api/auth/login", json={"email": "ann@example.com", "password": "nope"}
    )
    unknown_email = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "nope"}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["code"] == "INVALID_CREDENTIALS"


def test_disabled_account_cannot_log_in(client: TestClient, make_user) -> None:
    make_user(email="gone@example.com", password="pw-12345678", is_active=False)

    response = client.post(
        "/api/auth/login", json={"email": "gone@example.com", "password": "pw-12345678"}
    )

    assert response.status_code == 401


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"


def test_me_returns_the_logged_in_user(client: TestClient, make_user) -> None:
    make_user(email="ann@example.com", password="pw-12345678", display_name="安妮")
    client.post("/api/auth/login", json={"email": "ann@example.com", "password": "pw-12345678"})

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["display_name"] == "安妮"


def test_logout_invalidates_the_session_immediately(client: TestClient, make_user) -> None:
    make_user(email="ann@example.com", password="pw-12345678")
    client.post("/api/auth/login", json={"email": "ann@example.com", "password": "pw-12345678"})

    logout = client.post("/api/auth/logout")

    assert logout.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_a_forged_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.set(SESSION_COOKIE, "not-a-session-id")

    assert client.get("/api/auth/me").status_code == 401
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_auth_router.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'chatbi.auth.deps'`

- [ ] **Step 4: 写错误类型与响应模型**

创建 `apps/api/src/chatbi/errors.py`：

```python
from fastapi import Request
from fastapi.responses import JSONResponse

# (code, message, http_status)。message 是给用户看的中文文案，
# 不含地址、端口、库结构或凭据——spec §4.4。
INVALID_CREDENTIALS = ("INVALID_CREDENTIALS", "邮箱或密码不正确", 401)
NOT_AUTHENTICATED = ("NOT_AUTHENTICATED", "请先登录", 401)
PERMISSION_DENIED = ("PERMISSION_DENIED", "无权限", 403)
USER_NOT_FOUND = ("USER_NOT_FOUND", "用户不存在", 404)
EMAIL_ALREADY_EXISTS = ("EMAIL_ALREADY_EXISTS", "该邮箱已存在", 409)


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        status_code=exc.status_code, content={"code": exc.code, "message": exc.message}
    )
```

创建 `apps/api/src/chatbi/auth/schemas.py`：

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class UserResponse(BaseModel):
    """故意不声明 password_hash——敏感字段不进模型，而不是靠序列化时记得排除。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime


class ErrorResponse(BaseModel):
    code: str
    message: str
```

- [ ] **Step 5: 写依赖与路由**

创建 `apps/api/src/chatbi/auth/deps.py`：

```python
from typing import Annotated

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from chatbi.auth.sessions import lookup_session
from chatbi.db.base import get_db
from chatbi.db.models import User
from chatbi.errors import NOT_AUTHENTICATED, PERMISSION_DENIED, ApiError

SESSION_COOKIE = "chatbi_session"


def current_user(
    db: Annotated[Session, Depends(get_db)],
    chatbi_session: Annotated[str | None, Cookie()] = None,
) -> User:
    if not chatbi_session:
        raise ApiError(*NOT_AUTHENTICATED)
    user = lookup_session(db, chatbi_session)
    if user is None:
        raise ApiError(*NOT_AUTHENTICATED)
    return user


def require_role(*allowed: str):
    """返回一个只放行 allowed 中角色的依赖。用法：Depends(require_role("admin"))"""

    def dependency(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in allowed:
            raise ApiError(*PERMISSION_DENIED)
        return user

    return dependency
```

> `Cookie()` 的参数名必须与 cookie 名一致，因此形参叫 `chatbi_session`，不要改名。

创建空的 `apps/api/src/chatbi/api/__init__.py` 与 `apps/api/src/chatbi/api/auth_router.py`：

```python
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response
from sqlalchemy.orm import Session

from chatbi.auth.deps import SESSION_COOKIE, current_user
from chatbi.auth.identity import get_identity_provider
from chatbi.auth.schemas import ErrorResponse, LoginRequest, UserResponse
from chatbi.auth.sessions import create_session, delete_session
from chatbi.config import get_settings
from chatbi.db.base import get_db
from chatbi.db.models import User
from chatbi.errors import INVALID_CREDENTIALS, ApiError

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserResponse, responses={401: {"model": ErrorResponse}})
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    user = get_identity_provider().authenticate(db, payload.email, payload.password)
    if user is None:
        raise ApiError(*INVALID_CREDENTIALS)
    record = create_session(db, user)
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        str(record.id),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    return user


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    chatbi_session: Annotated[str | None, Cookie()] = None,
) -> None:
    if chatbi_session:
        delete_session(db, chatbi_session)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserResponse, responses={401: {"model": ErrorResponse}})
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user
```

把 `apps/api/src/chatbi/main.py` 改为：

```python
from fastapi import FastAPI

from chatbi.api.auth_router import router as auth_router
from chatbi.errors import ApiError, api_error_handler

app = FastAPI(title="Chat-BI API", version="0.1.0")
app.add_exception_handler(ApiError, api_error_handler)
app.include_router(auth_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd apps/api && uv run pytest -v`
Expected: PASS（含 test_auth_router 的 8 条，全套 30 条以上）

- [ ] **Step 7: 提交**

```bash
git add apps/api/src apps/api/tests
git commit -m "$(cat <<'EOF'
feat(auth): 登录/登出/me 端点与统一错误响应

会话 cookie httpOnly + SameSite=Lax；密码错与账号不存在返回
完全一致的响应；UserResponse 不声明 password_hash 字段。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 角色控制

**Files:**
- Create: `apps/api/tests/test_deps.py`
- Modify: 无（`require_role` 已在 Task 7 写好，本任务补齐它的测试与行为验证）

**Interfaces:**
- Consumes: `chatbi.auth.deps.require_role`、`chatbi.errors.api_error_handler`、夹具 `db_session` / `make_user`
- Produces: 无新接口。确立 P2/P3 挂管理端点的用法：`Depends(require_role("admin"))`

> 本任务不新增生产代码，只把 `require_role` 的行为钉死。P2 的数据源写操作端点、P3 的执行端点都要靠它，行为错了会在两段之后才被发现。

- [ ] **Step 1: 写失败的测试**

创建 `apps/api/tests/test_deps.py`：

```python
from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chatbi.auth.deps import SESSION_COOKIE, require_role
from chatbi.auth.sessions import create_session
from chatbi.db.base import get_db
from chatbi.db.models import User
from chatbi.errors import ApiError, api_error_handler


@pytest.fixture
def role_client(db_session: Session) -> Iterator[TestClient]:
    """一个只挂了受角色保护路由的最小 app，避免依赖 P1 尚不存在的业务端点。"""
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)

    @app.get("/admin-only")
    def admin_only(user: Annotated[User, Depends(require_role("admin"))]) -> dict[str, str]:
        return {"role": user.role}

    @app.get("/can-execute")
    def can_execute(
        user: Annotated[User, Depends(require_role("admin", "analyst"))],
    ) -> dict[str, str]:
        return {"role": user.role}

    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _login_as(client: TestClient, db_session: Session, user: User) -> None:
    record = create_session(db_session, user)
    client.cookies.set(SESSION_COOKIE, str(record.id))


def test_admin_passes_an_admin_only_route(role_client, db_session, make_user) -> None:
    _login_as(role_client, db_session, make_user(role="admin"))

    response = role_client.get("/admin-only")

    assert response.status_code == 200
    assert response.json() == {"role": "admin"}


def test_analyst_is_denied_an_admin_only_route(role_client, db_session, make_user) -> None:
    _login_as(role_client, db_session, make_user(role="analyst"))

    response = role_client.get("/admin-only")

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_viewer_cannot_execute(role_client, db_session, make_user) -> None:
    """viewer 只看历史，不能执行——spec §4.2。"""
    _login_as(role_client, db_session, make_user(role="viewer"))

    assert role_client.get("/can-execute").status_code == 403


def test_analyst_can_execute(role_client, db_session, make_user) -> None:
    _login_as(role_client, db_session, make_user(role="analyst"))

    assert role_client.get("/can-execute").status_code == 200


def test_unauthenticated_gets_401_not_403(role_client) -> None:
    """未登录是 401，登录但角色不够才是 403——两者不能混。"""
    response = role_client.get("/admin-only")

    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"
```

- [ ] **Step 2: 跑测试确认通过或失败**

Run: `cd apps/api && uv run pytest tests/test_deps.py -v`
Expected: 5 passed。若 `test_unauthenticated_gets_401_not_403` 失败（拿到 403），说明 `require_role` 里 `current_user` 的异常被吞掉了，回 Task 7 的 `deps.py` 修——未登录必须先于角色判断抛出。

- [ ] **Step 3: 提交**

```bash
git add apps/api/tests/test_deps.py
git commit -m "$(cat <<'EOF'
test(auth): 钉死 require_role 的角色与未登录语义

viewer 不能执行；未登录是 401 而非 403。P2/P3 的端点依赖这两条。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: 用户开号（provisioning + CLI）

**Files:**
- Create: `apps/api/src/chatbi/auth/provisioning.py`、`apps/api/src/chatbi/cli.py`、`apps/api/tests/test_provisioning.py`、`apps/api/tests/test_cli.py`
- Modify: `README.md`（补首次部署建 admin 的步骤）

**Interfaces:**
- Consumes: `hash_password`、`normalize_email`、`ROLES`、`ApiError`、`EMAIL_ALREADY_EXISTS`
- Produces:
  - `chatbi.auth.provisioning.create_user(session, *, email, display_name, password, role) -> User`
  - `chatbi.cli.app`（typer 应用）；命令 `create-user`；入口 `python -m chatbi.cli`
  - `chatbi.cli._session_scope()`（上下文管理器，测试里被 monkeypatch 替换成测试会话）

- [ ] **Step 1: 写失败的测试**

创建 `apps/api/tests/test_provisioning.py`：

```python
import pytest
from sqlalchemy.orm import Session

from chatbi.auth.hashing import verify_password
from chatbi.auth.provisioning import create_user
from chatbi.errors import ApiError


def test_creates_a_user_with_a_hashed_password(db_session: Session) -> None:
    user = create_user(
        db_session,
        email="Boss@Example.COM",
        display_name="老板",
        password="pw-12345678",
        role="admin",
    )

    assert user.email == "boss@example.com"
    assert user.password_hash != "pw-12345678"
    assert verify_password("pw-12345678", user.password_hash) is True


def test_rejects_a_duplicate_email_case_insensitively(db_session: Session) -> None:
    create_user(
        db_session, email="boss@example.com", display_name="老板", password="pw-12345678", role="admin"
    )

    with pytest.raises(ApiError) as excinfo:
        create_user(
            db_session,
            email="BOSS@example.com",
            display_name="冒名者",
            password="pw-87654321",
            role="admin",
        )

    assert excinfo.value.code == "EMAIL_ALREADY_EXISTS"


def test_rejects_an_unknown_role(db_session: Session) -> None:
    with pytest.raises(ValueError, match="role"):
        create_user(
            db_session,
            email="x@example.com",
            display_name="X",
            password="pw-12345678",
            role="superuser",
        )


def test_rejects_a_short_password(db_session: Session) -> None:
    with pytest.raises(ValueError, match="密码"):
        create_user(
            db_session, email="x@example.com", display_name="X", password="short", role="admin"
        )
```

创建 `apps/api/tests/test_cli.py`：

```python
from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from chatbi import cli
from chatbi.db.models import User


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> CliRunner:
    """把 CLI 的会话来源换成测试事务，避免命令真的往库里提交。"""

    @contextmanager
    def _scope():
        yield db_session

    monkeypatch.setattr(cli, "_session_scope", _scope)
    return CliRunner()


def test_create_user_command_creates_an_admin(runner: CliRunner, db_session: Session) -> None:
    result = runner.invoke(
        cli.app,
        ["create-user", "boss@example.com", "老板", "--role", "admin"],
        input="pw-12345678\npw-12345678\n",
    )

    assert result.exit_code == 0
    user = db_session.scalar(select(User).where(User.email == "boss@example.com"))
    assert user is not None
    assert user.role == "admin"


def test_create_user_command_reports_a_duplicate_email(
    runner: CliRunner, db_session: Session, make_user
) -> None:
    make_user(email="boss@example.com")

    result = runner.invoke(
        cli.app,
        ["create-user", "boss@example.com", "老板", "--role", "admin"],
        input="pw-12345678\npw-12345678\n",
    )

    assert result.exit_code == 1
    assert "已存在" in result.output


def test_create_user_command_does_not_echo_the_password(
    runner: CliRunner, db_session: Session
) -> None:
    result = runner.invoke(
        cli.app,
        ["create-user", "boss@example.com", "老板", "--role", "admin"],
        input="pw-12345678\npw-12345678\n",
    )

    assert "pw-12345678" not in result.output
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_provisioning.py tests/test_cli.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'chatbi.auth.provisioning'`

- [ ] **Step 3: 写 provisioning**

创建 `apps/api/src/chatbi/auth/provisioning.py`：

```python
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from chatbi.auth.hashing import hash_password
from chatbi.auth.identity import normalize_email
from chatbi.db.models import ROLES, User
from chatbi.errors import EMAIL_ALREADY_EXISTS, ApiError

MIN_PASSWORD_LENGTH = 8


def create_user(
    session: Session, *, email: str, display_name: str, password: str, role: str
) -> User:
    if role not in ROLES:
        raise ValueError(f"role 必须是 {ROLES} 之一，收到 {role!r}")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")

    normalized = normalize_email(email)
    if session.scalar(select(User).where(User.email == normalized)) is not None:
        raise ApiError(*EMAIL_ALREADY_EXISTS)

    user = User(
        id=uuid.uuid4(),
        email=normalized,
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user
```

- [ ] **Step 4: 写 CLI**

创建 `apps/api/src/chatbi/cli.py`：

```python
from collections.abc import Iterator
from contextlib import contextmanager

import typer
from sqlalchemy.orm import Session

from chatbi.auth.provisioning import create_user
from chatbi.db.base import get_session_factory
from chatbi.errors import ApiError

app = typer.Typer(help="Chat-BI 管理命令")


@contextmanager
def _session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@app.command("create-user")
def create_user_command(
    email: str,
    display_name: str,
    role: str = typer.Option("admin", help="admin / analyst / viewer"),
    password: str = typer.Option(
        ..., prompt="密码", confirmation_prompt="再输一次", hide_input=True
    ),
) -> None:
    """创建账号。私有化部署里账号由管理员发，不开放注册页面。

    失败消息走 stdout 而非 stderr：Click 8.2 起 CliRunner 不再默认把 stderr
    并入 output，走 stdout 能让断言在各版本下都稳定。退出码才是失败的载体。
    """
    try:
        with _session_scope() as session:
            user = create_user(
                session, email=email, display_name=display_name, password=password, role=role
            )
            typer.echo(f"已创建 {user.email}（{user.role}）")
    except ApiError as exc:
        typer.echo(f"失败：{exc.message}")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"失败：{exc}")
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest -v`
Expected: PASS（全套，约 42 条）

- [ ] **Step 6: 真跑一次 CLI**

```bash
cd apps/api
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
uv run alembic upgrade head
uv run python -m chatbi.cli create-user admin@local 管理员 --role admin
```

Expected: 提示两次输密码（输入不回显），输出「已创建 admin@local（admin）」。然后起服务用真实登录验一次：

```bash
uv run uvicorn chatbi.main:app --port 8000 &
curl -i -X POST localhost:8000/api/auth/login -H 'content-type: application/json' \
  -d '{"email":"admin@local","password":"<刚设的密码>"}'
```

Expected: 200，响应头含 `set-cookie: chatbi_session=...; HttpOnly`，响应体不含 `password_hash`。

- [ ] **Step 7: 补 README 并提交**

`README.md` 的部署步骤里加上「首次部署创建管理员」一节，内容为 Step 6 的前四条命令（不含 `&` 后台起服务那条）。

```bash
git add apps/api/src/chatbi/auth/provisioning.py apps/api/src/chatbi/cli.py apps/api/tests README.md
git commit -m "$(cat <<'EOF'
feat(auth): 用户开号与 create-user CLI

私有化部署不开放注册页面，账号由管理员用 CLI 发。密码不回显、
不进输出；重复邮箱按 EMAIL_ALREADY_EXISTS 退出码 1。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 交接清单（P2 要消费的签名）

P2「数据源与三驱动」直接依赖以下签名，改动它们要回头改 P2 计划。

**配置**
```python
chatbi.config.Settings          # 字段：database_url, secret_key(SecretStr), secret_key_file,
                                #       cookie_secure, session_ttl_hours
chatbi.config.get_settings() -> Settings          # lru_cache；改环境变量后需 cache_clear()
```

**数据库**
```python
chatbi.db.base.Base                               # 所有模型继承它
chatbi.db.base.get_engine() -> Engine
chatbi.db.base.get_session_factory() -> sessionmaker[Session]
chatbi.db.base.get_db() -> Iterator[Session]      # FastAPI 依赖；测试里被 override
```

**认证与授权**
```python
chatbi.auth.identity.normalize_email(email: str) -> str
chatbi.auth.identity.IdentityProvider             # Protocol
chatbi.auth.identity.get_identity_provider() -> IdentityProvider
chatbi.auth.deps.SESSION_COOKIE = "chatbi_session"
chatbi.auth.deps.current_user                     # 依赖，返回 User
chatbi.auth.deps.require_role(*allowed: str)      # 用法 Depends(require_role("admin"))
chatbi.auth.sessions.purge_expired(session) -> int  # P1 未接线，P2 在登录路径上调
chatbi.auth.provisioning.create_user(session, *, email, display_name, password, role) -> User
```

**错误**
```python
chatbi.errors.ApiError(code, message, status_code)
chatbi.errors.api_error_handler                   # 已注册到 app
# 三元组常量：INVALID_CREDENTIALS NOT_AUTHENTICATED PERMISSION_DENIED
#            USER_NOT_FOUND EMAIL_ALREADY_EXISTS
# P2 要新增：CONNECTION_ERROR DATASOURCE_NOT_FOUND（照 spec §2.6 的文案）
```

**测试夹具**（`apps/api/tests/conftest.py`）
```python
db_session      # Session，每测试事务回滚
client          # TestClient，get_db 已覆盖到 db_session
make_user(*, email=None, password="pw-12345678", display_name="测试用户",
          role="analyst", is_active=True) -> User
```

**P2 起步须知**
- 新模型放 `chatbi/db/models.py`，migration 编号从 `0002` 起，`down_revision = "0001"`。
- 新增的每个 migration 都要跑一次 up/down（把 `test_migrations.py` 的断言扩到新表）。
- 数据源凭据加密要用 `settings.secret_key.get_secret_value()`，并且 `datasources` 的 Pydantic 响应模型**不声明**任何密码字段。
- 驱动契约测的 skip 规则与应用库不同：**允许 skip 但必须计数上报**（spec §5.1），别照抄 `conftest.py` 里 `pytest.fail` 的写法。

---

## 自查记录

**spec 覆盖核对**（只核 P1 承担的部分）

| spec 条目 | 落在哪 |
|---|---|
| §0.4 Python + FastAPI、Postgres、不装 pgvector | Task 1、Task 3、Global Constraints |
| §1.1 仓库结构（`apps/api` + `docker/`） | Task 1 |
| §1.2 `db` / `auth` / `api` 模块 | Task 3、4–7 |
| §1.3 规则 2「`api/` 不含业务逻辑」 | Task 7（判断在 identity/sessions，router 只编排） |
| §1.3 规则 4「`db` 是叶子」 | Task 3（领域模块经仓储函数访问） |
| §2.5 `users` / `sessions` 表 | Task 3 |
| §2.6 错误码（P1 子集） | Task 7 |
| §4.1 argon2id、cookie 三属性、DB 会话、CLI 建号、不做注册页 | Task 4、6、7、9 |
| §4.2 三角色 RBAC | Task 8 |
| §4.4 主密钥不入库/日志/错误消息、响应模型不声明敏感字段 | Task 2、7 |
| §5.3 Alembic up/down 双向 | Task 3 |
| §5.1「skip 不能当绿灯」 | Task 3（应用库直接 fail，不 skip） |

P1 不覆盖、留给后续段的 spec 条目：`datasources` / `guard` / `execution` / `llm` / `semantics` / `pipeline` / `runs` 六个模块（P2、P3）、两条 SSE（P3）、审计与 `run_events`（P3）、OpenAPI 漂移校验（P4 有前端后才有意义）、`demo_sales`（P2）。

**写作过程中的回改**

1. **`users.email` 从 `citext` 改成 `text` + 应用层 `normalize_email`**（Task 3）。citext 要额外建扩展、SQLAlchemy 的 CITEXT 类型有版本门槛，收益只是省一次 `.lower()`。spec §2.5 与 §9 已同步更新。
2. **`server_default=sa.true()` 改成 `sa.text("true")`**（Task 3 migration）。前者在部分 Alembic 版本下渲染不稳。
3. **CLI 失败消息从 stderr 改到 stdout**（Task 9）。Click 8.2 起 `CliRunner` 不再默认把 stderr 并入 `result.output`，走 stdout 让断言跨版本稳定；失败仍由退出码 1 承载。
4. **`make_user` 提到 conftest 共享**（Task 7 Step 1）。Task 5、6 各自写了局部 `_make_user`，到 Task 7 已是三份重复，因此在 Task 7 里统一并删掉前两份——这一步写进了 Task 7 的 Step 1，不要跳过。
5. **`sessions.py` 删掉未用的 `select` import**（Task 6）。ruff 会以 F401 拦下。

**已知的松散端**

- `purge_expired` 在 P1 无调用方，P2 在登录路径上接（Task 6 已标注）。
- `test_migrations.py` 会短暂把库降到空表，因此这个仓库**不能加 `pytest-xdist`**，否则并行跑会互相清表。已写在 Task 3 Step 4 的提示里。
- `sessions` 表没有「一个用户最多几个活跃会话」的上限。私有化单机场景下不做限制，`purge_expired` 足够；若将来暴露到公网需要补。

**类型一致性核对**：`normalize_email` / `make_user` / `create_session` / `SESSION_COOKIE` / `require_role` / `ROLES` / `ApiError.code` 在跨任务引用处的名称与签名已逐一对齐，无 Task N 定义、Task M 改名的情况。
