"""表级约束的测试。

每条预期失败都包在 `begin_nested()` 里：`IntegrityError` 会让当前事务不可用，
而 `db_session` 夹具的外层事务后面还要用。savepoint 回滚只撤销内层，
外层照旧——直接 flush 出错会让同一个测试里后续的断言全部连带报错。
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from chatbi.db.models import DATASOURCE_KINDS, Datasource, DatasourceGrant


def _grant_count(session, user_id: uuid.UUID) -> int:
    return session.scalar(
        sa.select(sa.func.count())
        .select_from(DatasourceGrant)
        .where(DatasourceGrant.user_id == user_id)
    )


def test_the_supported_kinds_are_exactly_the_three_planned_drivers() -> None:
    assert DATASOURCE_KINDS == ("postgres", "mysql", "clickhouse")


def test_datasource_name_is_unique(db_session, make_datasource) -> None:
    make_datasource(name="生产只读库")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        make_datasource(name="生产只读库")


def test_kind_is_constrained_at_the_database_level(db_session, make_datasource) -> None:
    """CHECK 约束而非只靠 Pydantic：CLI 与直连 SQL 都不过 Pydantic。"""
    with pytest.raises(IntegrityError), db_session.begin_nested():
        make_datasource(kind="oracle")


def test_secret_columns_are_both_null_or_both_set(db_session, make_user) -> None:
    """半写状态（有密文没 nonce）必须进不了库：这种行既解不开也无法诊断。"""
    admin = make_user(role="admin")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            Datasource(
                id=uuid.uuid4(),
                name="半写的库",
                kind="postgres",
                host="db.internal",
                port=5432,
                database="analytics",
                username="ro_user",
                secret_ciphertext=b"\x01\x02",
                secret_nonce=None,
                created_by=admin.id,
            )
        )
        db_session.flush()


def test_a_user_gets_at_most_one_grant_row_per_datasource(
    db_session, make_user, make_datasource
) -> None:
    """复合主键：授权是「有/无」而不是可累积的列表，重复插入必须撞主键。"""
    analyst = make_user(role="analyst")
    datasource = make_datasource()
    db_session.add(DatasourceGrant(datasource_id=datasource.id, user_id=analyst.id, can_query=True))
    db_session.flush()

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            DatasourceGrant(datasource_id=datasource.id, user_id=analyst.id, can_query=False)
        )
        db_session.flush()


def test_deleting_a_datasource_cascades_to_its_grants(
    db_session, make_user, make_datasource
) -> None:
    """否则删掉再重建同名数据源会继承上一代的授权行。"""
    analyst = make_user(role="analyst")
    datasource = make_datasource()
    db_session.add(DatasourceGrant(datasource_id=datasource.id, user_id=analyst.id, can_query=True))
    db_session.flush()

    db_session.delete(datasource)
    db_session.flush()

    assert _grant_count(db_session, analyst.id) == 0


def test_deleting_a_user_cascades_to_their_grants(db_session, make_user, make_datasource) -> None:
    analyst = make_user(role="analyst")
    datasource = make_datasource()
    db_session.add(DatasourceGrant(datasource_id=datasource.id, user_id=analyst.id, can_query=True))
    db_session.flush()

    db_session.delete(analyst)
    db_session.flush()

    assert _grant_count(db_session, analyst.id) == 0


def test_deleting_the_creator_of_a_datasource_is_refused(
    db_session, make_user, make_datasource
) -> None:
    """created_by 是 RESTRICT，不是 CASCADE 也不是 SET NULL：数据源是审计对象，
    不能因为删了一个管理员就连带消失，也不该静默丢掉归属。
    """
    admin = make_user(role="admin")
    make_datasource(created_by=admin.id)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.delete(admin)
        db_session.flush()
