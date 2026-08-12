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
