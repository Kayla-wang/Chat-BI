"""conversations, runs, run_events, run_result_previews

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # RESTRICT 而不是 CASCADE：会话是审计对象，删用户/数据源不该静默销毁历史
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "datasource_id",
            sa.Uuid(),
            sa.ForeignKey("datasources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # run 脱离会话没有意义 -> CASCADE
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "datasource_id",
            sa.Uuid(),
            sa.ForeignKey("datasources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("chips", postgresql.JSONB(), nullable=True),
        # 三个 SQL 列都可空：drafted 时只有 generated_sql，blocked 时可能只有 final_sql
        sa.Column("generated_sql", sa.Text(), nullable=True),  # F-302 AC2 左侧
        sa.Column("final_sql", sa.Text(), nullable=True),  # 右侧
        sa.Column("effective_sql", sa.Text(), nullable=True),  # 注入 LIMIT 后实际下发
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("llm_provider", sa.String(50), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        # SET NULL（F-401 下钻）：删父 run 只断链，不连带删子 run。所以可空
        sa.Column(
            "parent_run_id",
            sa.Uuid(),
            sa.ForeignKey("runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        # CHECK 只写在 migration 里，与 users.role / datasources.kind 一致：建表永远走
        # Alembic，模型的 __table_args__ 根本不会被执行，写两份只会得到两份不同步的约束。
        # 这里用字面量而不是引用 db.models.RUN_STATUSES —— migration 是历史快照，不该在
        # 将来因为那个常量被改而改变含义。两者一致由测试钉住。
        sa.CheckConstraint(
            "status in ('drafted','blocked','running','succeeded','failed','cancelled')",
            name="ck_runs_status",
        ),
    )
    op.create_index("ix_runs_conversation_id", "runs", ["conversation_id"])
    op.create_index("ix_runs_user_id", "runs", ["user_id"])
    # P3d 的历史列表按数据源 + 状态过滤（上游 §2.4）
    op.create_index("ix_runs_datasource_id", "runs", ["datasource_id"])

    op.create_table(
        "run_events",
        # bigserial：事件量远大于其他表，且没有对外暴露 id 的需求
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # append-only 的**真正守卫**：即使有人绕过仓储直接写，重放一个已用过的 seq 也会被
    # DB 拒绝。复合唯一而不是只对 seq 唯一——否则第二个 run 记不了事件
    op.create_index("uq_run_events_seq", "run_events", ["run_id", "seq"], unique=True)

    op.create_table(
        "run_result_previews",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("rows", postgresql.JSONB(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    # 先删有外键指向别人的表。runs.parent_run_id 是自引用，drop_table("runs") 会连带
    # 删掉它，不需要单独处理。
    op.drop_table("run_result_previews")
    op.drop_index("uq_run_events_seq", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("ix_runs_datasource_id", table_name="runs")
    op.drop_index("ix_runs_user_id", table_name="runs")
    op.drop_index("ix_runs_conversation_id", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
