import pytest
from sqlalchemy.orm import Session

from chatbi.auth import identity
from chatbi.auth.identity import LocalIdentityProvider


@pytest.fixture
def provider() -> LocalIdentityProvider:
    return LocalIdentityProvider()


def test_authenticates_a_valid_user(db_session: Session, provider, make_user) -> None:
    make_user(email="ann@example.com", password="pw-12345678")

    result = provider.authenticate(db_session, "ann@example.com", "pw-12345678")

    assert result is not None
    assert result.email == "ann@example.com"


def test_email_matching_ignores_case_and_whitespace(
    db_session: Session, provider, make_user
) -> None:
    make_user(email="ann@example.com", password="pw-12345678")

    result = provider.authenticate(db_session, "  Ann@Example.COM ", "pw-12345678")

    assert result is not None


def test_rejects_a_wrong_password(db_session: Session, provider, make_user) -> None:
    make_user(email="ann@example.com", password="pw-12345678")

    assert provider.authenticate(db_session, "ann@example.com", "wrong-password") is None


def test_rejects_an_unknown_email(db_session: Session, provider) -> None:
    assert provider.authenticate(db_session, "nobody@example.com", "pw-12345678") is None


def test_rejects_a_disabled_account(db_session: Session, provider, make_user) -> None:
    make_user(email="gone@example.com", password="pw-12345678", is_active=False)

    assert provider.authenticate(db_session, "gone@example.com", "pw-12345678") is None


def test_every_failure_path_does_exactly_one_verification(
    db_session: Session, provider, monkeypatch: pytest.MonkeyPatch, make_user
) -> None:
    """三条失败路径都必须恰好做一次密码校验。

    否则某条路径会比其他路径快一个 Argon2 的时间，攻击者据此能区分
    「账号不存在」「密码错」「账号被禁用」——这正是 _DUMMY_HASH 要防的事。
    这里数调用次数而不是测耗时：计时断言必然不稳。
    """
    calls: list[str] = []
    real_verify = identity.verify_password

    def counting_verify(plaintext: str, hashed: str) -> bool:
        calls.append(hashed)
        return real_verify(plaintext, hashed)

    monkeypatch.setattr(identity, "verify_password", counting_verify)

    make_user(email="active@example.com", password="pw-12345678")
    make_user(email="disabled@example.com", password="pw-12345678", is_active=False)

    for email in ("nobody@example.com", "active@example.com", "disabled@example.com"):
        calls.clear()
        assert provider.authenticate(db_session, email, "wrong-password") is None
        assert len(calls) == 1, f"{email} 走了 {len(calls)} 次校验"
