"""schema 元数据的 API 形状：col_id 的生成与反解、快照 × 注释 → 响应模型。

**纯函数**——不 import sqlalchemy、不 import fastapi，所以合并与 col_id 反解可以脱离
库与 HTTP 测（tests/test_schema_view.py 一个夹具都不需要）。只 import
errors.ApiError，那是错误契约不是框架依赖，与 repository.py 文件头写明的是同一条约定
（errors.py 自身 import fastapi，这一点在 P2a 就已接受）。

col_id 的生成与反解**必须留在同一个文件里**：两侧共用一条拼接规则，分开写必然漂移。
"""

from collections.abc import Mapping
from datetime import datetime

from chatbi.datasources.drivers.base import SchemaSnapshot
from chatbi.datasources.schemas import (
    ColumnSchemaResponse,
    SchemaResponse,
    TableSchemaResponse,
)
from chatbi.errors import COLUMN_ID_AMBIGUOUS, COLUMN_NOT_FOUND, ApiError

_SEPARATOR = "."


def column_id(schema_name: str, table_name: str, column_name: str) -> str:
    """三段点分。服务端在 GET /schema 里发出，客户端原样回传。"""
    return _SEPARATOR.join((schema_name, table_name, column_name))


def resolve_column_id(snapshot: SchemaSnapshot, col_id: str) -> tuple[str, str, str]:
    """把 col_id 反查成 (schema_name, table_name, column_name)。

    **反查而不 split(_SEPARATOR)**：标识符本身可以含点（Postgres 里
    `create table "a.b"` 完全合法），解析会把它切错。两侧用同一个 column_id() 拼接
    规则，所以含点的标识符只会让某些 col_id 无法唯一定位，那正是 409 要说的话。

    命中 0 → 404（也覆盖「缓存为空」：调用方传进来的快照那时是空的）。
    命中 ≥2 → 409。后者现实中几乎不会发生，但它防的失败与「唯一键加 schema_name」
    是同一个：静默把注释挂到错的列上。一个「取第一个匹配」的实现会通过其余全部测试。
    """
    matches = [
        (table.schema_name, table.name, column.name)
        for table in snapshot.tables
        for column in table.columns
        if column_id(table.schema_name, table.name, column.name) == col_id
    ]
    if not matches:
        raise ApiError(*COLUMN_NOT_FOUND)
    if len(matches) > 1:
        raise ApiError(*COLUMN_ID_AMBIGUOUS)
    return matches[0]


def merge_schema(
    snapshot: SchemaSnapshot,
    notes: Mapping[tuple[str, str, str], str],
    *,
    fetched_at: datetime,
) -> SchemaResponse:
    """快照 × 注释 → 响应。

    comment（库原生）与 note（人工）**并存**，谁都不覆盖谁——见
    ColumnSchemaResponse 的文档字符串。

    notes 收 (schema, table, column) → note 的映射而不是 ORM 对象列表，是为了让本模块
    不 import sqlalchemy。调用方一行推导式就能构造它。
    """
    return SchemaResponse(
        fetched_at=fetched_at,
        tables=[
            TableSchemaResponse(
                schema_name=table.schema_name,
                name=table.name,
                comment=table.comment,
                columns=[
                    ColumnSchemaResponse(
                        col_id=column_id(table.schema_name, table.name, column.name),
                        name=column.name,
                        data_type=column.data_type,
                        is_nullable=column.is_nullable,
                        is_numeric=column.is_numeric,
                        comment=column.comment,
                        note=notes.get((table.schema_name, table.name, column.name)),
                    )
                    for column in table.columns
                ],
            )
            for table in snapshot.tables
        ],
    )


def column_view(
    snapshot: SchemaSnapshot,
    *,
    schema_name: str,
    table_name: str,
    column_name: str,
    note: str | None,
) -> ColumnSchemaResponse:
    """单列的合并结果，给 PATCH 的响应用。

    PATCH 返回那一列的新形态而不是整个 schema：一张 200 列的表整份回传只为确认一条
    注释写成功太重，而返回空体会逼前端要么自己拼状态、要么再发一次 GET。

    next() 不带 default：调用方必须先 resolve_column_id() 成功，所以这一列必然存在。
    真的抛 StopIteration 说明调用方跳过了反解那一步——那是编程错误，应该以异常暴露，
    不该退化成一个 None。
    """
    column = next(
        column
        for table in snapshot.tables
        if table.schema_name == schema_name and table.name == table_name
        for column in table.columns
        if column.name == column_name
    )
    return ColumnSchemaResponse(
        col_id=column_id(schema_name, table_name, column_name),
        name=column.name,
        data_type=column.data_type,
        is_nullable=column.is_nullable,
        is_numeric=column.is_numeric,
        comment=column.comment,
        note=note,
    )
