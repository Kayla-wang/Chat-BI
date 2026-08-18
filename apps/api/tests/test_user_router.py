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

    assert response.status_code == 201
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
