from fastapi import Request
from fastapi.responses import JSONResponse

# (code, message, http_status)。message 是给用户看的中文文案，
# 不含地址、端口、库结构或凭据——spec §4.4。
INVALID_CREDENTIALS = ("INVALID_CREDENTIALS", "邮箱或密码不正确", 401)
NOT_AUTHENTICATED = ("NOT_AUTHENTICATED", "请先登录", 401)
PERMISSION_DENIED = ("PERMISSION_DENIED", "无权限", 403)
USER_NOT_FOUND = ("USER_NOT_FOUND", "用户不存在", 404)
EMAIL_ALREADY_EXISTS = ("EMAIL_ALREADY_EXISTS", "该邮箱已存在", 409)


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
