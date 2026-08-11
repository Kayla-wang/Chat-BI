import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from chatbi.db.models import User

LEAK_EMAIL = "leak-probe@example.com"


def test_a_committed_write_does_not_escape_the_fixture(db_session: Session) -> None:
    """先提交一行——若隔离失效，下一个测试会看到它。"""
    db_session.add(
        User(
            id=uuid.uuid4(),
            email=LEAK_EMAIL,
            display_name="泄漏探针",
            password_hash="not-a-real-hash",
            role="analyst",
            is_active=True,
        )
    )
    db_session.commit()

    assert db_session.scalar(select(User).where(User.email == LEAK_EMAIL)) is not None


def test_the_previous_commit_left_nothing_behind(db_session: Session) -> None:
    assert db_session.scalar(select(User).where(User.email == LEAK_EMAIL)) is None
