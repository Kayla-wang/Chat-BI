from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response
from sqlalchemy.orm import Session

from chatbi.auth.deps import SESSION_COOKIE, current_user
from chatbi.auth.identity import IdentityProvider, get_identity_provider
from chatbi.auth.schemas import ErrorResponse, LoginRequest, UserResponse
from chatbi.auth.sessions import create_session, delete_session, purge_expired
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
    identity: Annotated[IdentityProvider, Depends(get_identity_provider)],
    chatbi_session: Annotated[str | None, Cookie()] = None,
) -> User:
    user = identity.authenticate(db, payload.email, payload.password)
    if user is None:
        raise ApiError(*INVALID_CREDENTIALS)
    # 过期会话在这里回收。放在认证成功之后：未认证的请求不该驱动写事务，
    # 否则任何人都能靠刷登录接口制造 DELETE 负载。
    purge_expired(db)
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
    # 删除指令要重述设置时的属性，否则部分浏览器会把它当成另一个 cookie 而不删
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
    )


@router.get("/me", response_model=UserResponse, responses={401: {"model": ErrorResponse}})
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user
