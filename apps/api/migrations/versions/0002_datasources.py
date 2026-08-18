"""datasources and datasource_grants

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datasources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database", sa.String(200), nullable=False),
        sa.Column("username", sa.String(200), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("secret_nonce", sa.LargeBinary(), nullable=True),
        sa.Column(
            "options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "is_readonly_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            # RESTRICT 而不是 CASCADE/SET NULL：数据源是审计对象，删一个管理员
            # 不该连带删掉它建的数据源，也不该静默丢掉归属
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("kind in ('postgres','mysql','clickhouse')", name="ck_datasources_kind"),
        # 「有密文没 nonce」的半写行既解不开也无法诊断，在 DB 层就排除掉
        sa.CheckConstraint(
            "(secret_ciphertext is null) = (secret_nonce is null)",
            name="ck_datasources_secret_pair",
        ),
    )
    op.create_index("ix_datasources_name", "datasources", ["name"], unique=True)
    op.create_index("ix_datasources_created_by", "datasources", ["created_by"])

    op.create_table(
        "datasource_grants",
        sa.Column(
            "datasource_id",
            sa.Uuid(),
            sa.ForeignKey("datasources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("can_query", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    # 复合主键的前导列是 datasource_id，而可见性查询按 user_id 过滤，需要自己的索引
    op.create_index("ix_datasource_grants_user_id", "datasource_grants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_datasource_grants_user_id", table_name="datasource_grants")
    op.drop_table("datasource_grants")
    op.drop_index("ix_datasources_created_by", table_name="datasources")
    op.drop_index("ix_datasources_name", table_name="datasources")
    op.drop_table("datasources")
