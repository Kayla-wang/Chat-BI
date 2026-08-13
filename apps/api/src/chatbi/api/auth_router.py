from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response
from sqlalchemy.orm import Session

from chatbi.auth.deps import SESSION_COOKIE, current_user
from chatbi.auth.identity import get_identity_provider
from chatbi.auth.schemas import ErrorResponse, LoginRequest, UserResponse
from chatbi.auth.sessions import create_session, delete_session
from chatbi.config import get_settings
from chatbi.db.base import get_db
from chatbi.db.models import User
from chatbi.errors import INVALID_CREDENTIALS, ApiError

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserResponse, responses={401: {"model": ErrorResponse}})
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    chatbi_session: Annotated[str | None, Cookie()] = None,
) -> User:
    user = get_identity_provider().authenticate(db, payload.email, payload.password)
    if user is None:
        raise ApiError(*INVALID_CREDENTIALS)
    # 防会话固定：调用方带来的旧会话（可能是攻击者预置的）作废，
    # 避免它在新登录之后仍作为第二个有效凭据存在。
    if chatbi_session:
        delete_session(db, chatbi_session)
    record = create_session(db, user)
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        str(record.id),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    # 交给客户端的 cookie 必须先落盘，而不是靠 get_db 事后提交才碰巧持久化。
    db.commit()
    return user


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    chatbi_session: Annotated[str | None, Cookie()] = None,
) -> None:
    if chatbi_session:
        delete_session(db, chatbi_session)
        # 承诺给客户端的失效必须先落盘，而不是靠 get_db 事后提交才碰巧持久化。
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserResponse, responses={401: {"model": ErrorResponse}})
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user
