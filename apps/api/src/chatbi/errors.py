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
