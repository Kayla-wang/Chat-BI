"""QueryResult → 可存 JSONB 且可发给前端的形状（P3b 设计 §9）。

纯函数。**三个数不能混**（§9.1）：
  max_result_rows  限制从库里取回多少行（闸 3 注入 LIMIT + 驱动 truncate）
  limit（本模块）   限制存进 run_result_previews 与发给前端多少行
  truncated        **驱动那一层是否截断**，即库里其实有更多行

`truncated` 直接来自 QueryResult，**不因为预览截了 100 行而变 True**——否则一次返回 200 行
的查询会在界面上显示「已截断」，而库里就只有 200 行。
"""

import base64
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from chatbi.datasources.drivers.base import QueryResult


def _jsonable(value: Any) -> Any:
    """把驱动给的值转成 json.dumps 认识的东西。

    Decimal -> float **会丢精度，这是有意的**：预览给人看、给图表用，而 JSON 没有十进制
    类型。转成字符串的话前端要自己解析、图表库画不了。全量导出走重跑 + 流式写出（P3d），
    精度在需要它的路径上完整。

    None 保持 None（→ JSON null），不转空字符串：那会让「没有值」与「空字符串」分不开。
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode()
    # 兜底：不认识的类型转字符串而不是抛。一个陌生的列类型不该让整次执行失败——结果已经
    # 拿到了，用户能看到「某一列显示得怪」比看到 500 好得多。
    return str(value)


def to_preview(
    result: QueryResult, *, limit: int
) -> tuple[list[dict[str, Any]], list[list[Any]], bool]:
    """返回 (columns, rows, truncated)。

    columns 与 result 事件的载荷同形（上游 spec §2.3）：只有 name / type / is_numeric，
    **不含 is_nullable 与 comment**——预览是结果的摘要，不是 schema 元数据。
    """
    columns = [
        {"name": c.name, "type": c.data_type, "is_numeric": c.is_numeric} for c in result.columns
    ]
    rows = [[_jsonable(v) for v in row] for row in result.rows[:limit]]
    return columns, rows, result.truncated
