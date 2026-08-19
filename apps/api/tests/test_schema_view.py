"""col_id 的生成与反解、快照 × 注释的合并。

全是纯函数，所以本文件**一个夹具都不需要**、也不碰库与 HTTP。
"""

from datetime import UTC, datetime

import pytest

from chatbi.datasources.drivers.base import ColumnSchema, SchemaSnapshot, TableSchema
from chatbi.datasources.schema_view import column_id, column_view, merge_schema, resolve_column_id
from chatbi.errors import ApiError

FETCHED_AT = datetime(2026, 8, 19, 10, 30, tzinfo=UTC)


def _snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        tables=(
            TableSchema(
                name="customers",
                schema_name="demo_sales",
                comment="客户",
                columns=(
                    ColumnSchema(
                        name="id", data_type="integer", is_numeric=True, comment="客户 ID"
                    ),
                    ColumnSchema(name="city", data_type="text", comment=None),
                ),
            ),
        )
    )


def test_column_id_joins_three_segments() -> None:
    assert column_id("demo_sales", "customers", "city") == "demo_sales.customers.city"


def test_resolve_column_id_finds_the_only_match() -> None:
    assert resolve_column_id(_snapshot(), "demo_sales.customers.city") == (
        "demo_sales",
        "customers",
        "city",
    )


def test_resolve_column_id_raises_not_found_for_an_unknown_column() -> None:
    with pytest.raises(ApiError) as caught:
        resolve_column_id(_snapshot(), "demo_sales.customers.nope")

    assert caught.value.code == "COLUMN_NOT_FOUND"
    assert caught.value.status_code == 404
    # 文案不得回显 schema / 表 / 列名（spec §4.4）
    assert "customers" not in caught.value.message


def test_resolve_column_id_handles_identifiers_containing_dots() -> None:
    """Postgres 里 create table "a.b" 完全合法。split(".") 式实现会把它切错。"""
    snapshot = SchemaSnapshot(
        tables=(
            TableSchema(
                name="a.b", schema_name="s", columns=(ColumnSchema(name="c", data_type="text"),)
            ),
        )
    )

    assert resolve_column_id(snapshot, "s.a.b.c") == ("s", "a.b", "c")


def test_resolve_column_id_raises_ambiguous_when_two_columns_share_an_id() -> None:
    """两张表拼出逐字节相同的 col_id：s + "a.b" + "c" 与 s + "a" + "b.c"。

    现实中几乎不会发生，但它防的失败与「唯一键加 schema_name」是同一个：静默把注释
    挂到错的列上。一个「取第一个匹配」的实现会通过其余全部测试。
    """
    snapshot = SchemaSnapshot(
        tables=(
            TableSchema(
                name="a.b", schema_name="s", columns=(ColumnSchema(name="c", data_type="text"),)
            ),
            TableSchema(
                name="a", schema_name="s", columns=(ColumnSchema(name="b.c", data_type="text"),)
            ),
        )
    )

    with pytest.raises(ApiError) as caught:
        resolve_column_id(snapshot, "s.a.b.c")

    assert caught.value.code == "COLUMN_ID_AMBIGUOUS"
    assert caught.value.status_code == 409


def test_merge_keeps_both_the_native_comment_and_the_manual_note() -> None:
    """两个字段并存，谁都不覆盖谁（设计 §4）。

    单字段覆盖式合并会通过「note 出现在响应里」这种松散断言，所以这里必须同时
    断言 comment 还在。
    """
    notes = {("demo_sales", "customers", "id"): "业务主键，不是自增"}

    response = merge_schema(_snapshot(), notes, fetched_at=FETCHED_AT)
    columns = {column.name: column for column in response.tables[0].columns}

    assert columns["id"].comment == "客户 ID"
    assert columns["id"].note == "业务主键，不是自增"


def test_merge_leaves_note_none_when_nobody_wrote_one() -> None:
    response = merge_schema(_snapshot(), {}, fetched_at=FETCHED_AT)
    columns = {column.name: column for column in response.tables[0].columns}

    assert columns["city"].note is None
    assert columns["city"].comment is None  # 库里也没写


def test_merge_emits_a_col_id_for_every_column() -> None:
    """前端全靠这个字段发 PATCH，缺一个就有一列改不了注释。"""
    response = merge_schema(_snapshot(), {}, fetched_at=FETCHED_AT)

    assert [column.col_id for column in response.tables[0].columns] == [
        "demo_sales.customers.id",
        "demo_sales.customers.city",
    ]
    assert response.fetched_at == FETCHED_AT
    assert response.tables[0].comment == "客户"


def test_column_view_returns_that_column_with_its_note() -> None:
    """PATCH 的响应用它——返回那一列的新形态，不是整个 schema。"""
    view = column_view(
        _snapshot(),
        schema_name="demo_sales",
        table_name="customers",
        column_name="city",
        note="所在城市",
    )

    assert view.col_id == "demo_sales.customers.city"
    assert view.data_type == "text"
    assert view.note == "所在城市"
    assert view.comment is None
