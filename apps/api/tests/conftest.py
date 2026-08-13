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
    # TestClient 走的是 http://testserver（纯 HTTP），带 Secure 属性的 cookie
    # 客户端不会回传，登录后的 /me 断言会假性失败。测试环境显式关闭它。
    os.environ.setdefault("CHATBI_COOKIE_SECURE", "0")


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
    session = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )()
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
