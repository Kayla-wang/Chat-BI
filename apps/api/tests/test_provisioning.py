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
