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


class GrantRequest(BaseModel):
    user_id: uuid.UUID
    can_query: bool = True


class GrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    datasource_id: uuid.UUID
    user_id: uuid.UUID
    can_query: bool
