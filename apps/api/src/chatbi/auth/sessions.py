import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from chatbi.config import get_settings
from chatbi.db.models import User, UserSession


def _parse_id(session_id: str) -> uuid.UUID | None:
    """cookie 内容由客户端控制，非 UUID 一律当作无效会话。"""
    try:
        return uuid.UUID(session_id)
    except (ValueError, AttributeError, TypeError):
        return None


def create_session(session: Session, user: User) -> UserSession:
    record = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=get_settings().session_ttl_hours),
    )
    session.add(record)
    session.flush()
    return record


def lookup_session(session: Session, session_id: str) -> User | None:
    parsed = _parse_id(session_id)
    if parsed is None:
        return None
    record = session.get(UserSession, parsed)
    if record is None or record.expires_at <= datetime.now(UTC):
        return None
    user = session.get(User, record.user_id)
    if user is None or not user.is_active:
        return None
    return user


def delete_session(session: Session, session_id: str) -> None:
    parsed = _parse_id(session_id)
    if parsed is None:
        return
    session.execute(delete(UserSession).where(UserSession.id == parsed))
    session.flush()


def purge_expired(session: Session) -> int:
    result = session.execute(
        delete(UserSession).where(UserSession.expires_at <= datetime.now(UTC))
    )
    session.flush()
    return result.rowcount or 0
