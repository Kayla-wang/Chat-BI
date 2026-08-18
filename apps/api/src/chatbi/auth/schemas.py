import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chatbi.auth.provisioning import MIN_PASSWORD_LENGTH


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class UserResponse(BaseModel):
    """故意不声明 password_hash——敏感字段不进模型，而不是靠序列化时记得排除。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime


class UserCreateRequest(BaseModel):
    """admin 开号的请求体。

    密码长度与角色白名单的真相源在 provisioning（CLI 走同一个函数），这里的
    约束只是 HTTP 层的早退：让不合规的请求拿到 422 而不是 500。
    """

    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)
    role: Literal["admin", "analyst", "viewer"]


class ErrorResponse(BaseModel):
    code: str
    message: str
