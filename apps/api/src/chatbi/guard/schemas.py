"""guard 的输出。

frozen dataclass 而不是 Pydantic 模型：guard 是领域层，它的输出要能脱离 HTTP 用
（P3b 的执行器直接消费它）。HTTP 响应模型在 datasources/schemas.py 里单独声明。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GuardVerdict:
    ok: bool
    effective_sql: str | None
    """实际会下发的语句。ok=False 时为 None——被拒的语句没有「实际会跑的版本」。"""

    code: str | None
    reason: str | None
    limit_applied: bool
    """注入或收紧了行数上限。**前端不要靠比较字符串判断这件事**——sqlglot 会重写整条
    语句（大小写、引号、空白全变），字符串比较必然误报。"""

    warnings: tuple[str, ...] = ()
    """不阻止执行，但用户该知道。"""
