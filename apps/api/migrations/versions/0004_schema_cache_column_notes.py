"""schema_cache and column_notes

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schema_cache",
        # 一个数据源一行，refresh 是整行覆盖。没有历史版本——快照的价值在
        # 「现在的库长什么样」，旧快照只会让人对着过期结构写 SQL
        sa.Column(
            "datasource_id",
            sa.Uuid(),
            sa.ForeignKey("datasources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        # payload 里**绝不**存人工注释：refresh 整行覆盖它，注释会跟着丢。
        # 注释的真相源是 column_notes（spec §2.5 末尾那条注释的全部理由）
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )

    op.create_table(
        "column_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "datasource_id",
            sa.Uuid(),
            sa.ForeignKey("datasources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # schema_name 是对 spec §2.5 的有意偏离：spec 的唯一键只有三列，但 Postgres
        # 的 reflect() 返回所有非系统 schema，demo_sales.orders 与 public.orders 会
        # 撞成同一条注释——静默挂到错的列上，界面上完全看不出来
        sa.Column("schema_name", sa.String(200), nullable=False),
        sa.Column("table_name", sa.String(200), nullable=False),
        sa.Column("column_name", sa.String(200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "updated_by",
            sa.Uuid(),
            # RESTRICT 与 datasources.created_by 一致：注释是审计对象，删用户不该
            # 静默丢掉归属。现在不挡任何功能——/api/users 只有 GET 与 POST
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # 合并时按数据源一次取全部注释；这个唯一索引的前导列正是 datasource_id，
    # 所以**不再**为它单独建一个索引——重复索引只是写放大
    op.create_index(
        "uq_column_notes_column",
        "column_notes",
        ["datasource_id", "schema_name", "table_name", "column_name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_column_notes_column", table_name="column_notes")
    op.drop_table("column_notes")
    op.drop_table("schema_cache")
