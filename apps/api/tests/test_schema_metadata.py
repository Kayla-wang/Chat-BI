"""schema_cache 与 column_notes 的建模层与仓储层。

前两条是建模测试（p2c1 Task 2）：CASCADE 与那个四列唯一键。其余是 metadata.py
的仓储测试（p2c2 Task 3）。不过 HTTP——这两张表的约束与序列化都是领域层的事
（spec §1.3 规则 2）。
"""

import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from chatbi.datasources.drivers.base import ColumnSchema, SchemaSnapshot, TableSchema
from chatbi.datasources.metadata import (
    known_identifiers,
    list_notes,
    payload_to_snapshot,
    read_cache,
    snapshot_to_payload,
    upsert_note,
    write_cache,
)
from chatbi.db.models import ColumnNote, SchemaCache


def _count(session, model) -> int:
    """用 count 而不是 session.get()。

    两张表都**没有定义 relationship**（db 是叶子模块），所以 SQLAlchemy 不知道
    DB 级的 ON DELETE CASCADE。删掉数据源后 identity map 里那个 SchemaCache 对象
    还在，session.get() 会直接把它返回而根本不查库——断言就永远看不到 CASCADE
    真的生效了。count 总是打库。
    """
    return session.scalar(sa.select(sa.func.count()).select_from(model))


def test_deleting_a_datasource_takes_its_cache_and_notes(
    db_session, make_datasource, make_user
) -> None:
    """两张表都 CASCADE：缓存与注释脱离数据源都没有意义。

    写成 RESTRICT 的话删数据源会 500，而那个 500 出现在 P2a 的 DELETE 端点上，
    报错完全不指向本任务。
    """
    datasource = make_datasource()
    author = make_user()
    db_session.add(
        SchemaCache(
            datasource_id=datasource.id,
            fetched_at=datetime.now(UTC),
            payload={"tables": []},
        )
    )
    db_session.add(
        ColumnNote(
            id=uuid.uuid4(),
            datasource_id=datasource.id,
            schema_name="public",
            table_name="orders",
            column_name="amount",
            note="含税金额",
            updated_by=author.id,
        )
    )
    db_session.flush()
    assert _count(db_session, SchemaCache) == 1
    assert _count(db_session, ColumnNote) == 1

    db_session.delete(datasource)
    db_session.flush()

    assert _count(db_session, SchemaCache) == 0
    assert _count(db_session, ColumnNote) == 0


def test_the_same_table_name_in_two_schemas_can_both_have_notes(
    db_session, make_datasource, make_user
) -> None:
    """唯一键必须含 schema_name（设计 §2.1，对 spec §2.5 的有意偏离）。

    照 spec 写成三列键的话，第二条 insert 会撞唯一约束——而真实后果不是报错，
    是「注释静默挂到另一个 schema 的同名列上」，界面上完全看不出来。
    """
    datasource = make_datasource()
    author = make_user()

    def _note(schema_name: str) -> ColumnNote:
        return ColumnNote(
            id=uuid.uuid4(),
            datasource_id=datasource.id,
            schema_name=schema_name,
            table_name="orders",
            column_name="amount",
            note=f"{schema_name} 的金额",
            updated_by=author.id,
        )

    db_session.add_all([_note("public"), _note("demo_sales")])
    db_session.flush()  # 三列键会在这里炸

    notes = db_session.scalars(sa.select(ColumnNote).order_by(ColumnNote.schema_name)).all()
    assert [note.schema_name for note in notes] == ["demo_sales", "public"]

    # 反过来：同一个 schema 的同一列写两条**必须**撞唯一键。少了这半条，一个
    # 「根本没有唯一约束」的实现也能通过上半条。
    db_session.add(_note("public"))
    with pytest.raises(IntegrityError):
        db_session.flush()


# ---- metadata.py 的仓储测试（p2c2 Task 3）----


def _snapshot(*, comment: str | None = "客户") -> SchemaSnapshot:
    return SchemaSnapshot(
        tables=(
            TableSchema(
                name="customers",
                schema_name="demo_sales",
                comment=comment,
                columns=(
                    ColumnSchema(
                        name="id",
                        data_type="integer",
                        is_nullable=False,
                        is_numeric=True,
                        comment="客户 ID",
                    ),
                    ColumnSchema(name="city", data_type="text", comment=None),
                ),
            ),
        )
    )


def test_a_snapshot_survives_a_serialization_roundtrip() -> None:
    snapshot = _snapshot()

    assert payload_to_snapshot(snapshot_to_payload(snapshot)) == snapshot


def test_the_roundtrip_rebuilds_tuples_not_lists() -> None:
    """asdict() 把 tuple 变 list。直接把 dict 塞回构造器的实现会通过上一条相等性
    测试吗？不会——tuple != list。但它还会以一种更难查的方式坏掉：快照变得不可
    哈希。两条都留着，因为它们的报错指向不同的地方。
    """
    restored = payload_to_snapshot(snapshot_to_payload(_snapshot()))

    assert isinstance(restored.tables, tuple)
    assert isinstance(restored.tables[0].columns, tuple)
    hash(restored)  # frozen dataclass 必须仍可哈希；list 字段会在这里抛 TypeError


def test_write_cache_overwrites_the_previous_snapshot(db_session, make_datasource) -> None:
    """refresh 的语义是整行覆盖，不留历史版本。"""
    datasource = make_datasource()

    write_cache(db_session, datasource.id, _snapshot(comment="第一版"))
    cache = write_cache(db_session, datasource.id, _snapshot(comment="第二版"))

    assert payload_to_snapshot(cache.payload).tables[0].comment == "第二版"
    assert read_cache(db_session, datasource.id).payload == cache.payload
    assert _count(db_session, SchemaCache) == 1


def test_read_cache_returns_none_before_anything_was_fetched(db_session, make_datasource) -> None:
    assert read_cache(db_session, make_datasource().id) is None


def test_upsert_note_is_idempotent_for_the_same_column(
    db_session, make_datasource, make_user
) -> None:
    """同一列写两次只有一行，note 是后写的那个。

    写成 insert 的话第二次撞唯一键 500——而用户看到的是「改注释报错」，第一次写
    却成功了，非常容易被当成偶发问题。
    """
    datasource, author = make_datasource(), make_user()
    keys = {
        "datasource_id": datasource.id,
        "schema_name": "demo_sales",
        "table_name": "customers",
        "column_name": "city",
    }

    upsert_note(db_session, **keys, note="城市", updated_by=author.id)
    upsert_note(db_session, **keys, note="所在城市（省会优先）", updated_by=author.id)

    notes = list_notes(db_session, datasource.id)
    assert len(notes) == 1
    assert notes[0].note == "所在城市（省会优先）"


def test_upsert_note_records_who_wrote_it(db_session, make_datasource, make_user) -> None:
    """updated_by 是审计字段（spec §4.6）。analyst 能改注释，所以「谁改的」必须留。"""
    datasource, first, second = make_datasource(), make_user(), make_user()
    keys = {
        "datasource_id": datasource.id,
        "schema_name": "demo_sales",
        "table_name": "customers",
        "column_name": "city",
    }

    upsert_note(db_session, **keys, note="城市", updated_by=first.id)
    upsert_note(db_session, **keys, note="所在城市", updated_by=second.id)

    assert list_notes(db_session, datasource.id)[0].updated_by == second.id


def test_list_notes_does_not_leak_another_datasources_notes(
    db_session, make_datasource, make_user
) -> None:
    mine, theirs, author = make_datasource(), make_datasource(), make_user()
    common = {"schema_name": "public", "table_name": "orders", "column_name": "amount"}
    upsert_note(db_session, datasource_id=mine.id, **common, note="我的", updated_by=author.id)
    upsert_note(db_session, datasource_id=theirs.id, **common, note="别人的", updated_by=author.id)

    assert [note.note for note in list_notes(db_session, mine.id)] == ["我的"]


def test_known_identifiers_covers_bare_and_qualified_forms(db_session, make_datasource) -> None:
    """三种形式都要收：LLM 生成的 SQL 里 schema 名、裸表名、schema.表名都会出现
    （同 schema 内可以省略前缀）。少收一种就会把合法 SQL 判成注入（spec §4.5）。
    """
    datasource = make_datasource()
    write_cache(db_session, datasource.id, _snapshot())

    assert known_identifiers(db_session, datasource.id) == frozenset(
        {"demo_sales", "customers", "demo_sales.customers"}
    )


def test_known_identifiers_is_empty_without_a_cache(db_session, make_datasource) -> None:
    """空集合而不是抛、也不是 None：语义是「什么都不认识」，让调用方拒绝一切标识符
    ——这是安全的默认。返回 None 会逼调用方写一条额外分支，而那条分支写错就等于
    白名单被绕过。
    """
    assert known_identifiers(db_session, make_datasource().id) == frozenset()
