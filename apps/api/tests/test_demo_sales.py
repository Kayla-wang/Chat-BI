"""demo_sales 示例库。

本文件目前只覆盖 migration 0003 建出来的东西。`seed-demo` 与只读角色那部分的
测试（含红线测试 test_the_demo_role_cannot_read_application_tables）要等应用账号
拿到 CREATEROLE 才能写——见计划 Task 6 Step 1。
"""

from sqlalchemy import text

DEMO_SCHEMA = "demo_sales"


def test_the_demo_schema_has_the_three_tables(db_session) -> None:
    rows = db_session.execute(
        text(
            "select table_name from information_schema.tables "
            "where table_schema = :schema order by table_name"
        ),
        {"schema": DEMO_SCHEMA},
    ).scalars()

    assert list(rows) == ["customers", "orders", "products"]


def test_the_demo_orders_have_enough_rows_to_chart(db_session) -> None:
    """至少几十行、跨多个月份——只有 3 行的示例库画不出有意义的趋势图，
    而「开箱即跑」的第一印象就是那张图（spec §0.4）。
    """
    count = db_session.execute(text(f"select count(*) from {DEMO_SCHEMA}.orders")).scalar()
    months = db_session.execute(
        text(f"select count(distinct date_trunc('month', ordered_at)) from {DEMO_SCHEMA}.orders")
    ).scalar()

    assert count >= 50
    assert months >= 3


def test_the_demo_tables_carry_comments(db_session) -> None:
    """注释进 LLM prompt（spec §4.5），没有注释的示例库生成质量会差一档。"""
    missing = db_session.execute(
        text(
            "select c.table_name || '.' || c.column_name "
            "from information_schema.columns c "
            "where c.table_schema = :schema "
            "  and col_description("
            "        format('%I.%I', c.table_schema, c.table_name)::regclass::oid,"
            "        c.ordinal_position) is null"
        ),
        {"schema": DEMO_SCHEMA},
    ).scalars()

    assert list(missing) == []
