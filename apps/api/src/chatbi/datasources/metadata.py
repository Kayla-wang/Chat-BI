"""schema 快照与人工注释的持久化。

不 import fastapi：序列化与 upsert 是领域逻辑，必须能脱离 HTTP 测（spec §1.3
规则 2）。也不 import 任何 drivers.<kind> 模块——只用协议层的值对象（base.py 只
import 标准库），所以本模块在没装任何数据库驱动包的环境里也 import 得动。

**payload 里绝不存人工注释。** refresh 整行覆盖 payload，注释若在里面就会跟着丢，
而 F-201 AC1 要求两者并存。注释的真相源恒为 column_notes 表，合并只发生在读路径上
（见 schema_view.merge_schema）。
"""

import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from chatbi.datasources.drivers.base import ColumnSchema, SchemaSnapshot, TableSchema
from chatbi.db.models import ColumnNote, SchemaCache


def snapshot_to_payload(snapshot: SchemaSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def payload_to_snapshot(payload: dict[str, Any]) -> SchemaSnapshot:
    """dict → frozen dataclass，逐字段显式重建。

    不能把 dict 直接展开进构造器：asdict() 把 tuple 变成 list，而三个 dataclass 都是
    frozen + tuple 字段。用 list 构造出来的快照不可哈希，且与驱动新鲜产出的快照
    **不相等**（tuple != list）——于是「缓存读出来的」和「刚 reflect 出来的」会被判定
    为不同。那会让任何基于相等性的比较静默失效，而它不报错。
    """
    return SchemaSnapshot(
        tables=tuple(
            TableSchema(
                name=table["name"],
                schema_name=table["schema_name"],
                comment=table["comment"],
                columns=tuple(
                    ColumnSchema(
                        name=column["name"],
                        data_type=column["data_type"],
                        is_nullable=column["is_nullable"],
                        is_numeric=column["is_numeric"],
                        comment=column["comment"],
                    )
                    for column in table["columns"]
                ),
            )
            for table in payload["tables"]
        )
    )


def read_cache(session: Session, datasource_id: uuid.UUID) -> SchemaCache | None:
    return session.get(SchemaCache, datasource_id)


def write_cache(
    session: Session, datasource_id: uuid.UUID, snapshot: SchemaSnapshot
) -> SchemaCache:
    """整行覆盖。没有历史版本——快照的价值在「现在的库长什么样」。

    fetched_at 用**应用时钟**（datetime.now）而不是 sa.func.now()：它的语义是「应用
    什么时候去拉的」，不是「这行什么时候被写的」。顺带的好处是返回的对象立刻可用
    ——func.now() 在 flush 后仍是一个 SQL 表达式对象，要 refresh 才拿得到 datetime，
    而调用方要把它放进响应模型。
    """
    payload = snapshot_to_payload(snapshot)
    cache = session.get(SchemaCache, datasource_id)
    if cache is None:
        cache = SchemaCache(
            datasource_id=datasource_id, fetched_at=datetime.now(UTC), payload=payload
        )
        session.add(cache)
    else:
        cache.fetched_at = datetime.now(UTC)
        cache.payload = payload
    session.flush()
    return cache


def upsert_note(
    session: Session,
    *,
    datasource_id: uuid.UUID,
    schema_name: str,
    table_name: str,
    column_name: str,
    note: str,
    updated_by: uuid.UUID,
) -> ColumnNote:
    """同一列写两次只有一行，第二次是改 note 与 updated_by。

    形状与 repository.set_grant 一致（get-then-add），不用 ON CONFLICT：注释是人手动
    编辑的，两个人在同一秒改同一列的概率与后果都远低于「refresh 并发」，而
    ON CONFLICT 的 returning 要额外处理 ORM 身份问题。撞了会是 IntegrityError 500，
    可接受。
    """
    existing = session.scalars(
        sa.select(ColumnNote).where(
            ColumnNote.datasource_id == datasource_id,
            ColumnNote.schema_name == schema_name,
            ColumnNote.table_name == table_name,
            ColumnNote.column_name == column_name,
        )
    ).one_or_none()
    if existing is None:
        existing = ColumnNote(
            id=uuid.uuid4(),
            datasource_id=datasource_id,
            schema_name=schema_name,
            table_name=table_name,
            column_name=column_name,
            note=note,
            updated_by=updated_by,
        )
        session.add(existing)
    else:
        existing.note = note
        existing.updated_by = updated_by
    session.flush()
    return existing


def list_notes(session: Session, datasource_id: uuid.UUID) -> list[ColumnNote]:
    """按数据源取全部注释。合并时一次取完，不按列逐条查——一张 200 列的表会发
    200 次查询，而注释总量本来就小到可以整批取。
    """
    statement = (
        sa.select(ColumnNote)
        .where(ColumnNote.datasource_id == datasource_id)
        .order_by(ColumnNote.schema_name, ColumnNote.table_name, ColumnNote.column_name)
    )
    return list(session.scalars(statement))


def known_identifiers(session: Session, datasource_id: uuid.UUID) -> frozenset[str]:
    """允许进 prompt 的标识符白名单（spec §4.5）。

    收三种形式：schema 名、裸表名、"schema.table"。三种都要，因为 LLM 生成的 SQL 里
    三种写法都会出现（同 schema 内可省略前缀）。少收一种就会把合法 SQL 判成注入。

    缓存为空时返回空集合——语义是「什么都不认识」，让调用方拒绝一切标识符，这是安全
    的默认。本函数在 P2c 结束时**没有生产调用方**，消费方是 P3 的 prompt 构建；这与
    P2a 的 read_password、P2b 的 execute() 同形，不是死代码。
    """
    cache = read_cache(session, datasource_id)
    if cache is None:
        return frozenset()
    identifiers: set[str] = set()
    for table in payload_to_snapshot(cache.payload).tables:
        identifiers.add(table.schema_name)
        identifiers.add(table.name)
        identifiers.add(f"{table.schema_name}.{table.name}")
    return frozenset(identifiers)
