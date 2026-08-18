import uuid

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatbi.auth.hashing import hash_password
from chatbi.auth.identity import normalize_email
from chatbi.db.integrity import violated_constraint
from chatbi.db.models import ROLES, User
from chatbi.errors import EMAIL_ALREADY_EXISTS, ApiError

MIN_PASSWORD_LENGTH = 8
_EMAIL_CONSTRAINT = "ix_users_email"


def create_user(
    session: Session, *, email: str, display_name: str, password: str, role: str
) -> User:
    if role not in ROLES:
        raise ValueError(f"role 必须是 {ROLES} 之一，收到 {role!r}")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")

    user = User(
        id=uuid.uuid4(),
        email=normalize_email(email),
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    # P1 遗留 3：原来是 check-then-insert（先 select 再 insert），并发下两个请求
    # 都查到「没有」，一个成功一个 500。现在只信 DB 的唯一索引。
    # savepoint 的作用是让调用方在 409 之后还能继续用这个事务（CLI 批量建号）。
    savepoint = session.begin_nested()
    try:
        session.add(user)
        session.flush()
    except IntegrityError as exc:
        savepoint.rollback()
        if violated_constraint(exc) != _EMAIL_CONSTRAINT:
            # 不是邮箱冲突就原样抛：把别的约束违规也报成「邮箱已存在」是撒谎
            raise
        raise ApiError(*EMAIL_ALREADY_EXISTS) from exc
    savepoint.commit()
    return user


def get_user(session: Session, user_id: uuid.UUID) -> User | None:
    """按 id 取用户。grants 端点用它回答「这个 user_id 存在吗」。"""
    return session.get(User, user_id)


def list_users(session: Session) -> list[User]:
    """按 email 排序——列表要稳定，否则前端每次刷新顺序都不同。"""
    return list(session.scalars(sa.select(User).order_by(User.email)))
