import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from chatbi.db.base import Base

ROLES: tuple[str, str, str] = ("admin", "analyst", "viewer")
DATASOURCE_KINDS: tuple[str, str, str] = ("postgres", "mysql", "clickhouse")
# 与 migration 0006 的 ck_runs_status 一致（那边是字面量，migration 是历史快照）。
# 两者一致由 tests/test_run_models.py 钉住。
RUN_STATUSES: tuple[str, ...] = (
    "generating",  # 草稿正在生成（P3c）。放第一个：它是 run 的起点状态
    "drafted",
    "blocked",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(sa.String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    role: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class UserSession(Base):
    """会话记录。类名不叫 Session 以免与 sqlalchemy.orm.Session 混淆。"""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class Datasource(Base):
    """一个外部数据库的连接定义。密码以 AES-GCM 密文存两列，见 datasources/crypto.py。

    表级 CHECK（kind 取值、secret 两列成对）只写在 migration 0002 里，与 P1 的
    users.role 一致：建表永远走 Alembic，模型的 __table_args__ 根本不会被执行，
    写两份只会得到两份不同步的约束。
    """

    __tablename__ = "datasources"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    host: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    port: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    database: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    username: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    # 两列同时为空 = 未存密码，同时非空 = 已存。没有第三种状态（CHECK 在 migration 里）
    secret_ciphertext: Mapped[bytes | None] = mapped_column(sa.LargeBinary(), nullable=True)
    secret_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary(), nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False, default=dict)
    is_readonly_verified: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    @property
    def has_password(self) -> bool:
        """给响应模型用的派生标记。返回 bool 而不是任何密钥材料，所以放在 db 层
        不算业务逻辑——它只是那两列的一个只读视图。
        """
        return self.secret_ciphertext is not None


class DatasourceGrant(Base):
    """谁能查哪个数据源。复合主键——授权是「有/无」，不是可累积的列表。

    故意不定义 relationship：`db` 是叶子模块（spec §1.3 规则 4），
    联表由 repository 显式写 select，不让 ORM 在属性访问时偷偷发查询。
    """

    __tablename__ = "datasource_grants"

    datasource_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("datasources.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    can_query: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)


class SchemaCache(Base):
    """一个数据源的表结构快照。payload 是 SchemaSnapshot 的 JSON。

    表级约束只写在 migration 里，与 Datasource 一致：建表永远走 Alembic，模型的
    __table_args__ 根本不会被执行，写两份只会得到两份不同步的约束。
    """

    __tablename__ = "schema_cache"

    datasource_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("datasources.id", ondelete="CASCADE"), primary_key=True
    )
    fetched_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)


class ColumnNote(Base):
    """人工补的列注释。与 schema_cache 分开存，因为 refresh 整行覆盖 payload。

    唯一键是四列（含 schema_name），比 spec §2.5 多一列——理由见 migration 0004
    里的注释。故意不定义 relationship：db 是叶子模块（spec §1.3 规则 4）。这也意味着
    SQLAlchemy 不知道 DB 级的 ON DELETE CASCADE，测试里别用 session.get() 去验删除。
    """

    __tablename__ = "column_notes"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("datasources.id", ondelete="CASCADE"), nullable=False
    )
    schema_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    table_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    column_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    note: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class Conversation(Base):
    """一次多轮问答的容器（上游 spec §2.2：省略 conversation_id 时新建）。

    title 可空：P3c 决定它怎么来（截取问题或让 LLM 起名），本段不做。
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("datasources.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class Run(Base):
    """一次问答 + 执行的完整记录。审计的主体（上游 spec §4.6）。

    三个 SQL 列的分工是 F-302 AC2 的 diff 两侧 + 实际下发：
      generated_sql  LLM 原始生成版（左侧）
      final_sql      用户批准的版本（右侧）
      effective_sql  guard 注入 LIMIT/策略后真正下发的语句
    三者都可空：drafted 时只有 generated_sql，blocked 时可能只有 final_sql。

    status 的 CHECK 只在 migration 里，与 Datasource.kind 一致。
    """

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("datasources.id", ondelete="RESTRICT"), nullable=False
    )
    question: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    chips: Mapped[list[Any] | None] = mapped_column(JSONB(), nullable=True)
    generated_sql: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    final_sql: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    effective_sql: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    row_count: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    executed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class RunEvent(Base):
    """append-only 的事件流（上游 spec §2.5、§4.6，F-304）。

    **仓储层只暴露 append 与 list，没有 UPDATE/DELETE 路径。** 别在这里加 relationship，
    也别给它写 update 方法——F-304 的可审计承诺全靠这一点。

    回放按 seq 排序，**不按 at**：同毫秒内的事件顺序不确定。
    """

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    step: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)
    at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class RunResultPreview(Base):
    """结果摘要，只存前 100 行（上游 spec §2.5）。回放时重跑取全量。"""

    __tablename__ = "run_result_previews"

    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    columns: Mapped[list[Any]] = mapped_column(JSONB(), nullable=False)
    rows: Mapped[list[Any]] = mapped_column(JSONB(), nullable=False)
    truncated: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.text("false")
    )
