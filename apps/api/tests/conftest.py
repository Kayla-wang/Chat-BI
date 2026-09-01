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
            "postgresql+psycopg://chatbi:chatbi@localhost:5433/chatbi_test",
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


@pytest.fixture
def make_datasource(db_session: Session, make_user):
    """建一个测试数据源。密码用 Task 2 的 seal 就地加密。

    id 先生成再加密：AAD 绑定数据源 id，所以顺序不能反。
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


@pytest.fixture
def login_as(client: TestClient, db_session: Session):
    """把某个用户的会话 cookie 塞进 client。返回传入的对象，方便链式写。

    走真会话表而不是伪造 cookie——current_user 会去 sessions 表查，
    伪造的 cookie 一律 401。
    """
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


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """把 skip 数显式打印在末尾，并单独列出驱动契约测的 skip。

    spec §5.1 的硬要求。v1 就是因为「无本地库 → skip」被当成绿灯，MySQL/PG 驱动
    到重写前一次真库都没跑过。让这行永远出现，比指望人记得去翻 -rs 输出可靠。
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
