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
