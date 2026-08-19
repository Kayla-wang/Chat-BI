"""登录/登出的持久化承诺需要用一个真正提交的会话才能验证——所有其它测试
用的 db_session 夹具会在测试结束时整体回滚，永远看不出 get_db 事后提交
这件事本身是否发生。

本文件故意绕开 db_session，直接用一个 commit-on-exit 的会话覆盖 get_db，
再从另一条全新的连接确认行确实落盘/确实消失。因为它是真提交，它不能借
db_session 的自动回滚来清理，必须自己在 finally 里删干净。
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from chatbi.auth.hashing import hash_password
from chatbi.auth.identity import normalize_email
from chatbi.db.base import get_db
from chatbi.db.models import User, UserSession
from chatbi.main import app


@pytest.fixture
def _durable_session_factory(_migrated: None) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(os.environ["CHATBI_DATABASE_URL"])
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _session_row_count(factory: sessionmaker[Session], user_id: uuid.UUID) -> int:
    """从一条全新的连接读取，确保看到的是真正落盘的数据而非同一会话的缓存。"""
    verify_engine = create_engine(os.environ["CHATBI_DATABASE_URL"])
    try:
        with verify_engine.connect() as conn, Session(bind=conn) as verify_session:
            rows = (
                verify_session.execute(select(UserSession).where(UserSession.user_id == user_id))
                .scalars()
                .all()
            )
            return len(rows)
    finally:
        verify_engine.dispose()


def test_login_commits_the_session_row_and_logout_commits_its_removal(
    _durable_session_factory: sessionmaker[Session],
) -> None:
    def _get_db() -> Iterator[Session]:
        session = _durable_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    user_id: uuid.UUID | None = None
    try:
        setup_session = _durable_session_factory()
        try:
            user = User(
                id=uuid.uuid4(),
                email=normalize_email("durable@example.com"),
                display_name="持久化测试",
                password_hash=hash_password("pw-12345678"),
                role="analyst",
                is_active=True,
            )
            setup_session.add(user)
            setup_session.commit()
            user_id = user.id
        finally:
            setup_session.close()

        client = TestClient(app)

        login = client.post(
            "/api/auth/login",
            json={"email": "durable@example.com", "password": "pw-12345678"},
        )
        assert login.status_code == 200
        # 从一条全新连接看，会话行必须已经真正落盘——不是靠 get_db 事后提交
        # 才碰巧持久化，而是 login 自己在返回响应之前就 commit 过。
        assert _session_row_count(_durable_session_factory, user_id) == 1

        logout = client.post("/api/auth/logout")
        assert logout.status_code == 204
        # 同理：失效必须在响应离开之前就落盘。
        assert _session_row_count(_durable_session_factory, user_id) == 0
    finally:
        app.dependency_overrides.clear()
        if user_id is not None:
            cleanup_session = _durable_session_factory()
            try:
                cleanup_session.execute(
                    UserSession.__table__.delete().where(UserSession.user_id == user_id)
                )
                cleanup_session.execute(User.__table__.delete().where(User.id == user_id))
                cleanup_session.commit()
            finally:
                cleanup_session.close()
