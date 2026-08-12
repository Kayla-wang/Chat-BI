import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from chatbi.auth.sessions import create_session, delete_session, lookup_session, purge_expired
from chatbi.db.models import UserSession


def test_create_session_sets_a_future_expiry(db_session: Session, make_user) -> None:
    user = make_user()

    record = create_session(db_session, user)

    assert record.user_id == user.id
    assert record.expires_at > datetime.now(UTC)


def test_lookup_returns_the_user(db_session: Session, make_user) -> None:
    user = make_user()
    record = create_session(db_session, user)

    found = lookup_session(db_session, str(record.id))

    assert found is not None
    assert found.id == user.id


def test_lookup_rejects_an_expired_session(db_session: Session, make_user) -> None:
    user = make_user()
    record = create_session(db_session, user)
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    assert lookup_session(db_session, str(record.id)) is None


def test_lookup_rejects_an_unknown_id(db_session: Session) -> None:
    assert lookup_session(db_session, str(uuid.uuid4())) is None


def test_lookup_rejects_a_malformed_id(db_session: Session) -> None:
    """cookie 内容是客户端可控的，非 UUID 不能让查询抛异常。"""
    assert lookup_session(db_session, "../../etc/passwd") is None


def test_lookup_rejects_a_session_whose_user_was_disabled(db_session: Session, make_user) -> None:
    user = make_user()
    record = create_session(db_session, user)
    user.is_active = False
    db_session.flush()

    assert lookup_session(db_session, str(record.id)) is None


def test_delete_session_takes_effect_immediately(db_session: Session, make_user) -> None:
    user = make_user()
    record = create_session(db_session, user)

    delete_session(db_session, str(record.id))

    assert lookup_session(db_session, str(record.id)) is None


def test_purge_expired_removes_only_expired_rows(db_session: Session, make_user) -> None:
    user = make_user()
    alive = create_session(db_session, user)
    stale = create_session(db_session, user)
    stale.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.flush()

    removed = purge_expired(db_session)

    assert removed == 1
    assert db_session.get(UserSession, alive.id) is not None
