import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from chatbi.db.base import Base

ROLES: tuple[str, str, str] = ("admin", "analyst", "viewer")
DATASOURCE_KINDS: tuple[str, str, str] = ("postgres", "mysql", "clickhouse")


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
