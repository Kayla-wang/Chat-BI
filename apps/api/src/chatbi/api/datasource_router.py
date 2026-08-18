"""/api/datasources 的 HTTP 编排。

只做「校验角色 → 调仓储 → 返回模型」。这里不出现 select()、不出现可见性判断、
不出现 seal/unseal。需要新查询就回领域层加仓储函数（spec §1.3 规则 2、4）。
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from chatbi.auth.deps import current_user, require_role
from chatbi.auth.provisioning import get_user
from chatbi.auth.schemas import ErrorResponse
from chatbi.datasources.connection import connection_info
from chatbi.datasources.deps import driver_for, require_datasource
from chatbi.datasources.drivers.base import ConnectionFailed, Driver
from chatbi.datasources.repository import (
    create_datasource,
    delete_datasource,
    list_grants,
    list_visible,
    revoke_grant,
    set_grant,
    update_datasource,
)
from chatbi.datasources.schemas import (
    DatasourceCreate,
    DatasourceResponse,
    DatasourceTestResult,
    DatasourceUpdate,
    GrantRequest,
    GrantResponse,
)
from chatbi.db.base import get_db
from chatbi.db.models import Datasource, DatasourceGrant, User
from chatbi.errors import CONNECTION_ERROR, USER_NOT_FOUND, ApiError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/datasources", tags=["datasources"])

# 注解别名：写成常量是为了让每个路由的签名短到能一眼看完
_Db = Annotated[Session, Depends(get_db)]
_CurrentUser = Annotated[User, Depends(current_user)]
_Admin = Annotated[User, Depends(require_role("admin"))]
_Target = Annotated[Datasource, Depends(require_datasource)]
_Driver = Annotated[Driver, Depends(driver_for)]

# responses 声明必须完整，否则 P4 生成的前端类型会缺 {code, message} 分支
_AUTH = {401: {"model": ErrorResponse}}
_ADMIN = _AUTH | {403: {"model": ErrorResponse}}
_TARGET = _ADMIN | {404: {"model": ErrorResponse}}
_CONFLICT = {409: {"model": ErrorResponse}}
_UNAVAILABLE = {503: {"model": ErrorResponse}}


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


@router.post(
    "/{datasource_id}/test",
    response_model=DatasourceTestResult,
    responses=_TARGET | _UNAVAILABLE,
)
def test_connection(
    datasource: _Target, driver: _Driver, db: _Db, _admin: _Admin
) -> DatasourceTestResult:
    """就地测连，并探测账号是否具备写权限（spec §2.4、§4.3 闸 1）。

    不写 db.commit()：get_db 在请求正常结束时提交。ApiError 那条路径会被 get_db
    回滚，所以「连不上时不动标记」是免费得到的——但那条测试仍然要有，因为这是
    行为承诺而不是实现细节。
    """
    try:
        result = driver.probe(connection_info(datasource))
    except ConnectionFailed as exc:
        # 地址端口进**服务端日志**，不进 HTTP 响应（spec §4.4）
        logger.warning(
            "数据源 %s 连接失败：%s:%s/%s",
            datasource.id,
            datasource.host,
            datasource.port,
            datasource.database,
        )
        raise ApiError(*CONNECTION_ERROR) from exc

    # 探到可写就把「已验证只读」置 false 并告警，但**不阻止保存**（spec §4.3 闸 1）
    datasource.is_readonly_verified = not result.can_write
    if result.can_write:
        logger.warning("数据源 %s 的账号具备写权限，已标记为未通过只读验证", datasource.id)
    return DatasourceTestResult(
        reachable=result.reachable,
        server_version=result.server_version,
        can_write=result.can_write,
        is_readonly_verified=datasource.is_readonly_verified,
    )


# ---- grants ----
# 路径比 /{datasource_id} 多一段，不会和它抢匹配，声明顺序无所谓。
# 三条都吃 _Target，所以「数据源不存在 → 404 / 无授权 → 403」自动一致。


@router.get("/{datasource_id}/grants", response_model=list[GrantResponse], responses=_TARGET)
def list_datasource_grants(datasource: _Target, db: _Db, _admin: _Admin) -> list[DatasourceGrant]:
    return list_grants(db, datasource.id)


@router.put("/{datasource_id}/grants", response_model=GrantResponse, responses=_TARGET)
def put_grant(
    payload: GrantRequest, datasource: _Target, db: _Db, _admin: _Admin
) -> DatasourceGrant:
    """PUT 而不是 POST：授权是「有/无」，重发同一份请求结果必须相同。"""
    # 这两行「取 + 判定 + 抛」留在 router 里：user_id 来自请求体而不是路径，
    # 做不成 FastAPI 依赖。形状与 login 里那两行一致，可接受。
    if get_user(db, payload.user_id) is None:
        raise ApiError(*USER_NOT_FOUND)
    return set_grant(
        db, datasource_id=datasource.id, user_id=payload.user_id, can_query=payload.can_query
    )


@router.delete("/{datasource_id}/grants/{user_id}", status_code=204, responses=_TARGET)
def delete_grant(user_id: uuid.UUID, datasource: _Target, db: _Db, _admin: _Admin) -> None:
    """幂等：授权本来就不存在也返回 204。

    这里不校验 user_id 是否存在——撤销一个不存在用户的授权，结果和撤销一个
    不存在的授权没有区别，都是「现在没有」。
    """
    revoke_grant(db, datasource_id=datasource.id, user_id=user_id)
