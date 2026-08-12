from typing import Annotated

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from chatbi.auth.sessions import lookup_session
from chatbi.db.base import get_db
from chatbi.db.models import User
from chatbi.errors import NOT_AUTHENTICATED, PERMISSION_DENIED, ApiError

SESSION_COOKIE = "chatbi_session"


def current_user(
    db: Annotated[Session, Depends(get_db)],
    chatbi_session: Annotated[str | None, Cookie()] = None,
) -> User:
    if not chatbi_session:
        raise ApiError(*NOT_AUTHENTICATED)
    user = lookup_session(db, chatbi_session)
    if user is None:
        raise ApiError(*NOT_AUTHENTICATED)
    return user


def require_role(*allowed: str):
    """返回一个只放行 allowed 中角色的依赖。用法：Depends(require_role("admin"))"""

    def dependency(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in allowed:
            raise ApiError(*PERMISSION_DENIED)
        return user

    return dependency
