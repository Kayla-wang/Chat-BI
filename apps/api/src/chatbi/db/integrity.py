"""IntegrityError 的判别工具。

单独一个文件是因为「怎么从驱动异常里取约束名」是 psycopg 的细节，
不该在每个仓储里各写一遍。
"""

from sqlalchemy.exc import IntegrityError


def violated_constraint(exc: IntegrityError) -> str | None:
    """返回被违反的约束/索引名；取不到返回 None。

    psycopg 把它放在 exc.orig.diag.constraint_name 上。取不到时**返回 None 而不是
    猜**——调用方的正确反应是「不确定就原样抛」，把任何 IntegrityError 都翻成一个
    友好错误码会让真 bug 伪装成用户错误。
    """
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
