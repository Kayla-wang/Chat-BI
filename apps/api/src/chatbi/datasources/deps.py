"""数据源的 FastAPI 依赖。

唯一同时认识 FastAPI 与 repository 的文件，只做「取 + 判定 + 抛 ApiError」。
故意不 import crypto：HTTP 层没有任何需要明文密码的理由，让它连解密函数都
看不见，比靠约定「记得别调」可靠。
"""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from chatbi.auth.deps import current_user
from chatbi.datasources.drivers.base import Driver
from chatbi.datasources.registry import get_driver
from chatbi.datasources.repository import datasource_exists, get_visible
from chatbi.db.base import get_db
from chatbi.db.models import Datasource, User
from chatbi.errors import DATASOURCE_NOT_FOUND, PERMISSION_DENIED, ApiError


def require_datasource(
    datasource_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> Datasource:
    """按路径参数取数据源，可见性不足就抛。

    参数名必须叫 datasource_id——FastAPI 按名字从路径 {datasource_id} 里取。

    404 与 403 的分界：id 不存在 → DATASOURCE_NOT_FOUND；存在但这个用户没有
    can_query 授权 → PERMISSION_DENIED。顺序不能反：先问 get_visible 再问
    datasource_exists，多出的那次查询只在「拿不到」时发生。
    """
    datasource = get_visible(db, user, datasource_id)
    if datasource is not None:
        return datasource
    if datasource_exists(db, datasource_id):
        raise ApiError(*PERMISSION_DENIED)
    raise ApiError(*DATASOURCE_NOT_FOUND)


def driver_for(datasource: Annotated[Datasource, Depends(require_datasource)]) -> Driver:
    """按数据源的 kind 取驱动。

    做成依赖**只为可测**：/test 的端点测试要能塞进假驱动而不需要真数据库。
    P1 遗留 2 就是反例——get_identity_provider 当初不是依赖，测试里换不掉，
    拖到 P2a Task 1 才补上。这次一开始就做成依赖。
    """
    return get_driver(datasource.kind)
