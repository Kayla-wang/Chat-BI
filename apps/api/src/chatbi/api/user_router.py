"""/api/users 的 HTTP 编排。

只有 admin 开号，不做注册页——私有化部署里账号由管理员发（spec §4.1）。
密码长度与角色白名单的真相源在 provisioning，不在这里重复。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from chatbi.auth.deps import require_role
from chatbi.auth.provisioning import create_user, list_users
from chatbi.auth.schemas import ErrorResponse, UserCreateRequest, UserResponse
from chatbi.db.base import get_db
from chatbi.db.models import User

router = APIRouter(prefix="/api/users", tags=["users"])

# 与 datasource_router 里那几行同形。没有抽到公共模块：跨 router import 注解别名
# 会让两个 router 互相耦合，而这几行的成本低于那个耦合。
_Db = Annotated[Session, Depends(get_db)]
_Admin = Annotated[User, Depends(require_role("admin"))]

_ADMIN = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}}
_CONFLICT = {409: {"model": ErrorResponse}}


@router.get("", response_model=list[UserResponse], responses=_ADMIN)
def list_all(db: _Db, _admin: _Admin) -> list[User]:
    return list_users(db)


@router.post("", response_model=UserResponse, status_code=201, responses=_ADMIN | _CONFLICT)
def create(payload: UserCreateRequest, db: _Db, _admin: _Admin) -> User:
    return create_user(
        db,
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
        role=payload.role,
    )
