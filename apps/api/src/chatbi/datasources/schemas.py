"""数据源的请求/响应模型。

DatasourceResponse 不声明任何凭据字段——spec §4.4 要求靠模型不含字段，而不是
靠序列化时记得排除。往这个模型加字段前先确认它不是密码、密文或 nonce。
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# 写成 Literal 而不是 str + validator：OpenAPI 里会出成 enum，P4 生成的前端类型
# 直接得到联合类型。与 db.models.DATASOURCE_KINDS 的一致性由测试钉住。
DatasourceKind = Literal["postgres", "mysql", "clickhouse"]


class DatasourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: DatasourceKind
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1, max_length=200)
    username: str = Field(min_length=1, max_length=200)
    # 允许不带密码：有些环境走 trust 或证书认证。两个 secret 列会一起留空
    password: str | None = Field(default=None, max_length=1024)
    options: dict[str, Any] = Field(default_factory=dict)


class DatasourceUpdate(BaseModel):
    """PATCH 语义：只改传来的字段。

    `password=None` 表示「不改密码」，所以 P2a 没有「清空已存密码」的路径——需要
    清空就删了重建。这个取舍是：让「编辑表单里省略密码」成为安全默认，比提供一个
    容易误触的清空语义重要。`is_readonly_verified` 不在这里，它由 P2b 的 /test
    端点写，不接受客户端指定——否则客户端可以自称「已验证只读」。
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: DatasourceKind | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=200)
    username: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, max_length=1024)
    options: dict[str, Any] | None = None


class DatasourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: DatasourceKind
    host: str
    port: int
    database: str
    username: str
    options: dict[str, Any]
    is_readonly_verified: bool
    has_password: bool  # 只是「有没有存密码」，不是密码本身
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class DatasourceTestResult(BaseModel):
    """/test 的结果。

    故意不含任何凭据、也不含连接串——排障需要的是「通不通、什么版本、账号能不能写」，
    地址端口是用户自己填的，不需要回显（spec §4.4）。
    """

    reachable: bool
    server_version: str
    can_write: bool
    is_readonly_verified: bool


class ColumnSchemaResponse(BaseModel):
    """一列的合并结果。

    comment 与 note **并存**，谁都不覆盖谁（设计 §4）：前端要能显示来源差异
    （「DBA 在库里写的」与「张三补的」可信度不同），P3 的 prompt 构建自己决定怎么拼。
    做成单字段会提前替 P3 做掉这个决定，且不可逆。
    """

    col_id: str
    """PATCH 时原样回传。**前端不要自己拼**——拼接规则一改两侧就漂移，而漂移的
    表现是「改注释的请求 404」，很难指向后端。"""

    name: str
    data_type: str
    is_nullable: bool
    is_numeric: bool
    comment: str | None  # 库原生注释；None = 库里没写
    note: str | None  # 人工补的注释；None = 没人补过


class TableSchemaResponse(BaseModel):
    schema_name: str
    name: str
    comment: str | None  # 库原生表注释。不做表级人工注释（F-201 AC1 只说列）
    columns: list[ColumnSchemaResponse]


class SchemaResponse(BaseModel):
    fetched_at: datetime
    """元数据是什么时候拉的。**没有 TTL**——新鲜度交给界面展示（这个时间 + 一个刷新
    按钮），不由后端猜多久算过期。私有化部署里 schema 的变更节奏差异极大，任何默认
    TTL 都会在一半环境里是错的。"""

    tables: list[TableSchemaResponse]


class ColumnNoteUpdate(BaseModel):
    note: str = Field(max_length=2000)
    """允许空字符串，语义是「清空这条注释」——保留行、note = ''，不删行。删行会让
    updated_by / updated_at 的审计痕迹消失，而「谁把注释清掉了」和「谁写了注释」
    一样值得留（spec §4.6）。
    """


class GrantRequest(BaseModel):
    user_id: uuid.UUID
    can_query: bool = True


class GrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    datasource_id: uuid.UUID
    user_id: uuid.UUID
    can_query: bool


class SqlValidateRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)
    """上限 100k 字符：一条人写或 LLM 生成的分析 SQL 远不到这个量级，而没有上限意味着
    每次按键都可能让服务端解析一个几十 MB 的字符串。"""


class SqlValidateResponse(BaseModel):
    """guard 判定的 HTTP 形态。

    **判定失败也返回 200**，ok=false 在体内——编辑器停止输入 300ms 就调一次
    （spec §2.4），用 4xx 表达「你这条 SQL 有写操作」会让前端把正常的输入过程当成错误
    流：用户打字打到一半必然产生大量语法不完整的中间态。401/403/404 仍然是真的 HTTP 错误。
    """

    ok: bool
    code: str | None
    reason: str | None
    effective_sql: str | None
    limit_applied: bool
    """**前端不要靠比较字符串判断 LIMIT 有没有被改**——sqlglot 会重写整条语句（大小写、
    引号、空白全变），字符串比较必然误报。"""

    warnings: list[str]
