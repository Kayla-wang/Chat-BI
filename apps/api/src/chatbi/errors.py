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
# 闸 2（上游 spec §4.3、§2.6）。三个都是 400 而不是 403：被拒的原因是「这条语句不允许
# 执行」，不是「你没权限」——403 会让前端渲染成权限问题，而用户改一下 SQL 就能过。
# PERMISSION_DENIED(403) 留给真正的授权失败，那在 require_datasource 里。
#
# reason 里可以带用户自己写的 SQL 的信息（哪一类写操作、解析失败的行列号），那不是结构
# 泄露；但**不带表名与列名**——那部分可能来自被污染的 LLM 输出或库结构。
WRITE_BLOCKED = ("WRITE_BLOCKED", "该语句不允许执行", 400)
SQL_PARSE_ERROR = ("SQL_PARSE_ERROR", "SQL 无法解析", 400)
# 从 WRITE_BLOCKED 里分出来（上游 §2.6 把两者归在一起）：用户动作不同，一个要改掉写
# 操作，一个要删掉分号后面的部分。合成一个码前端只能给一句笼统的话。
MULTIPLE_STATEMENTS = ("MULTIPLE_STATEMENTS", "一次只能执行一条语句", 400)
# 闸 4 与执行流（上游 spec §2.6、§4.3）。前三个只出现在 SSE 的 error 事件载荷里，
# **不作为 HTTP 状态返回**——流本身已经是 200 了。状态码那一位在这里只用于让 ApiError
# 元组的形状一致，以及万一将来有非 SSE 的调用方。
QUERY_TIMEOUT = ("QUERY_TIMEOUT", "查询超时，请缩小时间范围或增加过滤条件", 504)
# 499 是 nginx 的扩展码而非标准 HTTP，见上：它不会真的被当成状态码发出去
QUERY_CANCELLED = ("QUERY_CANCELLED", "查询已取消", 499)
# **message 里会带库的原始错误文本**（由调用方拼）。这与 §4.4「错误消息不含结构信息」
# 不冲突：那条针对连接类错误（可能含地址端口），而这里的原文是用户自己写的 SQL 在库上
# 的报错，正是他改 SQL 需要看到的（P2b 的 QueryFailed 刻意保留了原文）。别在某次安全
# 评审里把它抹掉。
QUERY_FAILED = ("QUERY_FAILED", "数据库拒绝执行该查询", 400)
# 一个 run 恰好执行一次（P3b 设计 §5）：非 drafted 一律 409。顺带成为双击运行按钮的防护
RUN_NOT_EXECUTABLE = ("RUN_NOT_EXECUTABLE", "该查询已执行过或正在执行", 409)
RUN_NOT_FOUND = ("RUN_NOT_FOUND", "查询记录不存在", 404)


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
