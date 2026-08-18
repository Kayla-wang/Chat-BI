"""/api/datasources 的 HTTP 编排。

只做「校验角色 → 调仓储 → 返回模型」。这里不出现 select()、不出现可见性判断、
不出现 seal/unseal。需要新查询就回领域层加仓储函数（spec §1.3 规则 2、4）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from chatbi.auth.deps import current_user, require_role
from chatbi.auth.schemas import ErrorResponse
from chatbi.datasources.deps import require_datasource
from chatbi.datasources.repository import (
    create_datasource,
    delete_datasource,
    list_visible,
    update_datasource,
)
from chatbi.datasources.schemas import DatasourceCreate, DatasourceResponse, DatasourceUpdate
from chatbi.db.base import get_db
from chatbi.db.models import Datasource, User

router = APIRouter(prefix="/api/datasources", tags=["datasources"])

# 注解别名：写成常量是为了让每个路由的签名短到能一眼看完
_Db = Annotated[Session, Depends(get_db)]
_CurrentUser = Annotated[User, Depends(current_user)]
_Admin = Annotated[User, Depends(require_role("admin"))]
_Target = Annotated[Datasource, Depends(require_datasource)]

# responses 声明必须完整，否则 P4 生成的前端类型会缺 {code, message} 分支
_AUTH = {401: {"model": ErrorResponse}}
_ADMIN = _AUTH | {403: {"model": ErrorResponse}}
_TARGET = _ADMIN | {404: {"model": ErrorResponse}}
_CONFLICT = {409: {"model": ErrorResponse}}


@router.get("", response_model=list[DatasourceResponse], responses=_AUTH)
def list_datasources(db: _Db, user: _CurrentUser) -> list[Datasource]:
    return list_visible(db, user)


@router.post("", response_model=DatasourceResponse, status_code=201, responses=_ADMIN | _CONFLICT)
def create(payload: DatasourceCreate, db: _Db, admin: _Admin) -> Datasource:
    # 不写 db.commit()：get_db 在请求正常结束时提交
    return create_datasource(db, payload=payload, created_by=admin.id)


@router.get("/{datasource_id}", response_model=DatasourceResponse, responses=_TARGET)
def get_one(datasource: _Target) -> Datasource:
    """签名里既没有 db 也没有 user——两者都在 require_datasource 内部。"""
    return datasource


@router.patch(
    "/{datasource_id}", response_model=DatasourceResponse, responses=_TARGET | _CONFLICT
)
def patch(payload: DatasourceUpdate, datasource: _Target, db: _Db, _admin: _Admin) -> Datasource:
    """_admin 参数没有函数体内的用处，它就是那道 403 闸门。删了功能照样正常。"""
    return update_datasource(db, datasource, payload)


@router.delete("/{datasource_id}", status_code=204, responses=_TARGET)
def remove(datasource: _Target, db: _Db, _admin: _Admin) -> None:
    delete_datasource(db, datasource)
