import pytest
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


def test_login_invalidates_a_pre_existing_session(client: TestClient, make_user) -> None:
    """登录要作废调用方带来的旧会话，否则被预置的 cookie 会成为第二个有效凭据。"""
    make_user(email="ann@example.com", password="pw-12345678")
    first = client.post(
        "/api/auth/login", json={"email": "ann@example.com", "password": "pw-12345678"}
    )
    old_cookie = first.cookies[SESSION_COOKIE]

    client.post("/api/auth/login", json={"email": "ann@example.com", "password": "pw-12345678"})

    client.cookies.set(SESSION_COOKIE, old_cookie)
    assert client.get("/api/auth/me").status_code == 401


def test_secure_attribute_is_set_when_configured(
    client: TestClient, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生产配置下 cookie 必须带 Secure。测试环境默认关掉它，
    因为 TestClient 走 http，带 Secure 的 cookie 客户端不会回传。"""
    from chatbi.config import get_settings

    make_user(email="ann@example.com", password="pw-12345678")
    monkeypatch.setenv("CHATBI_COOKIE_SECURE", "1")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/auth/login", json={"email": "ann@example.com", "password": "pw-12345678"}
        )
        assert "Secure" in response.headers["set-cookie"]
    finally:
        get_settings.cache_clear()
