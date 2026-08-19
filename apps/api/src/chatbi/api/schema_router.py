"""/api/datasources/{id}/schema 的 HTTP 编排。

只做「校验 → 调领域层 → 返回模型」。合并在 schema_view、持久化在 metadata，这里不
出现 select()、不出现 col_id 的拼接规则（spec §1.3 规则 2、4）。

单独一个 router 而不是塞进 datasource_router：那个文件已 160 行，且职责是数据源
CRUD。元数据跟着 SchemaSnapshot（驱动协议的产物）变，两者变更理由不同。
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from chatbi.auth.deps import current_user
from chatbi.auth.schemas import ErrorResponse
from chatbi.datasources.connection import connection_info
from chatbi.datasources.deps import driver_for, require_datasource
from chatbi.datasources.drivers.base import ConnectionFailed, Driver
from chatbi.datasources.metadata import (
    list_notes,
    payload_to_snapshot,
    read_cache,
    upsert_note,
    write_cache,
)
from chatbi.datasources.schema_view import column_view, merge_schema, resolve_column_id
from chatbi.datasources.schemas import ColumnNoteUpdate, ColumnSchemaResponse, SchemaResponse
from chatbi.db.base import get_db
from chatbi.db.models import Datasource, SchemaCache, User
from chatbi.errors import COLUMN_NOT_FOUND, CONNECTION_ERROR, ApiError

logger = logging.getLogger(__name__)

# 与 datasource_router 同一个 prefix，不同 tags：OpenAPI 里元数据自成一组，而路径
# 仍然是 spec §2.4 定的那两条
router = APIRouter(prefix="/api/datasources", tags=["schema"])

_Db = Annotated[Session, Depends(get_db)]
_CurrentUser = Annotated[User, Depends(current_user)]
_Target = Annotated[Datasource, Depends(require_datasource)]
_Driver = Annotated[Driver, Depends(driver_for)]

# responses 声明必须完整，否则 P4 生成的前端类型会缺 {code, message} 分支
_TARGET = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}
_UNAVAILABLE = {503: {"model": ErrorResponse}}
_CONFLICT = {409: {"model": ErrorResponse}}


def _fetch_and_cache(db: Session, datasource: Datasource, driver: Driver) -> SchemaCache:
    try:
        snapshot = driver.reflect(connection_info(datasource))
    except ConnectionFailed as exc:
        # 地址端口进**服务端日志**，不进 HTTP 响应（spec §4.4）
        logger.warning(
            "数据源 %s 拉取元数据失败：%s:%s/%s",
            datasource.id,
            datasource.host,
            datasource.port,
            datasource.database,
        )
        raise ApiError(*CONNECTION_ERROR) from exc
    return write_cache(db, datasource.id, snapshot)


def _notes_map(db: Session, datasource_id: uuid.UUID) -> dict[tuple[str, str, str], str]:
    """ORM 行 → (schema, table, column) → note 的映射。

    schema_view 不 import sqlalchemy，所以这一步转换留在 router。只此一处，没有重复。
    """
    return {
        (note.schema_name, note.table_name, note.column_name): note.note
        for note in list_notes(db, datasource_id)
    }


@router.get(
    "/{datasource_id}/schema",
    response_model=SchemaResponse,
    responses=_TARGET | _UNAVAILABLE,
)
def get_schema(
    datasource: _Target, driver: _Driver, db: _Db, refresh: bool = False
) -> SchemaResponse:
    """走缓存；缓存为空则首次自动拉取；?refresh=1 强制重拉（spec §2.4）。

    「缓存为空时自动拉一次」是为了让首次调用可用——否则前端要先发一个必然失败的 GET
    再发一个 ?refresh=1，把实现细节暴露成协议。

    不设 TTL：响应带 fetched_at，新鲜度交给界面展示（见 SchemaResponse）。
    不写 db.commit()：get_db 在请求正常结束时提交；503 那条路径会被它回滚，所以
    「拉取失败不动缓存」是免费得到的。
    """
    cache = None if refresh else read_cache(db, datasource.id)
    if cache is None:
        cache = _fetch_and_cache(db, datasource, driver)
    return merge_schema(
        payload_to_snapshot(cache.payload),
        _notes_map(db, datasource.id),
        fetched_at=cache.fetched_at,
    )


@router.patch(
    "/{datasource_id}/schema/columns/{col_id}",
    response_model=ColumnSchemaResponse,
    responses=_TARGET | _CONFLICT,
)
def patch_column_note(
    col_id: str,
    payload: ColumnNoteUpdate,
    datasource: _Target,
    db: _Db,
    user: _CurrentUser,
) -> ColumnSchemaResponse:
    """人工补注释（F-201 AC1）。

    **analyst 也能改**——require_datasource 只要 can_query 授权，这里刻意不加
    require_role("admin")。知道某列在业务上意味着什么的人是分析师。

    签名里**没有** driver：PATCH 不连外部库。缓存为空时返回 404 而不是顺带拉一次，
    否则一次注释编辑会因为数据源临时不可达而失败。
    """
    cache = read_cache(db, datasource.id)
    if cache is None:
        raise ApiError(*COLUMN_NOT_FOUND)
    snapshot = payload_to_snapshot(cache.payload)
    schema_name, table_name, column_name = resolve_column_id(snapshot, col_id)
    note = upsert_note(
        db,
        datasource_id=datasource.id,
        schema_name=schema_name,
        table_name=table_name,
        column_name=column_name,
        note=payload.note,
        updated_by=user.id,
    )
    return column_view(
        snapshot,
        schema_name=schema_name,
        table_name=table_name,
        column_name=column_name,
        note=note.note,
    )
