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
