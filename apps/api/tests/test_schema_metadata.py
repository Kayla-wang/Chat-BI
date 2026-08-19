"""schema_cache 与 column_notes 的建模层与仓储层。

p2c1 Task 2 只有下面两条建模测试；p2c2 的 Task 3 往同一文件里加 metadata.py 的
仓储测试。不过 HTTP——这两张表的约束与序列化都是领域层的事（spec §1.3 规则 2）。
"""

import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

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
