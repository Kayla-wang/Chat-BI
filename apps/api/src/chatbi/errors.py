from fastapi import Request
from fastapi.responses import JSONResponse

# (code, message, http_status)。message 是给用户看的中文文案，
# 不含地址、端口、库结构或凭据——spec §4.4。
INVALID_CREDENTIALS = ("INVALID_CREDENTIALS", "邮箱或密码不正确", 401)
NOT_AUTHENTICATED = ("NOT_AUTHENTICATED", "请先登录", 401)
PERMISSION_DENIED = ("PERMISSION_DENIED", "无权限", 403)
USER_NOT_FOUND = ("USER_NOT_FOUND", "用户不存在", 404)
EMAIL_ALREADY_EXISTS = ("EMAIL_ALREADY_EXISTS", "该邮箱已存在", 409)
DATASOURCE_NOT_FOUND = ("DATASOURCE_NOT_FOUND", "数据源不存在", 404)
DATASOURCE_NAME_EXISTS = ("DATASOURCE_NAME_EXISTS", "该数据源名称已存在", 409)
# 503 而不是 502：连不上外部依赖对本服务是「暂时不可用」，
# 语义比「上游返回了坏响应」准。文案照 spec §4.4，不回显地址端口。
CONNECTION_ERROR = ("CONNECTION_ERROR", "无法连接到数据库，请检查地址、端口与网络", 503)
# 两条文案都不含 schema 名、表名、列名——spec §4.4「错误信息不泄露结构」。用户知道
# 自己传的是什么，不需要回显。
#
# COLUMN_NOT_FOUND 把「列不存在」与「元数据尚未拉取」合在一句，因为端点确实用同一个码
# 覆盖这两种情况（PATCH 在缓存为空时也返回它，不为 PATCH 触发一次对外部库的连接）。
# 分成两个码会让前端多一条它无法采取不同行动的分支。
COLUMN_NOT_FOUND = ("COLUMN_NOT_FOUND", "列不存在或元数据尚未拉取", 404)
COLUMN_ID_AMBIGUOUS = ("COLUMN_ID_AMBIGUOUS", "该列标识不唯一，无法定位", 409)


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        status_code=exc.status_code, content={"code": exc.code, "message": exc.message}
    )
