"""QueryResult → 可存 JSONB 的 columns/rows（P3b 设计 §9）。纯函数，无夹具。

本文件最重要的是**三个数不能混**（§9.1）：
  max_result_rows(1000) 限制从库里取回多少行 —— 闸 3 与驱动的 truncate
  preview_rows(100)     限制存/发多少行 —— 本模块
  truncated             **驱动那一层是否截断**，即库里其实有 >1000 行
"""

import base64
from datetime import UTC, date, datetime
from decimal import Decimal

from chatbi.datasources.drivers.base import ColumnSchema, QueryResult
from chatbi.execution.preview import to_preview


def _result(rows, columns=None, *, truncated=False) -> QueryResult:
    columns = columns or (
        ColumnSchema(name="id", data_type="integer", is_numeric=True),
        ColumnSchema(name="label", data_type="text"),
    )
    return QueryResult(columns=columns, rows=tuple(rows), row_count=len(rows), truncated=truncated)


def test_rows_are_capped_at_the_limit_but_truncated_still_reflects_the_driver() -> None:
    """**本文件的核心一条**（设计 §9.1）。

    取回 200 行（< 1000，所以驱动没截断）→ 预览只留 100 行，但 truncated 仍是 False。

    写成「rows 被截了就报 truncated=True」会让一次返回 200 行的查询在界面上显示
    「已截断」——而实际上库里就只有 200 行，用户会以为丢了数据。
    """
    result = _result([(i, f"r{i}") for i in range(200)], truncated=False)

    columns, rows, truncated = to_preview(result, limit=100)

    assert len(rows) == 100
    assert truncated is False
    assert len(columns) == 2


def test_the_driver_truncation_flag_is_passed_through() -> None:
    """驱动截断了（库里 >1000 行）→ truncated=True，与预览的 100 行无关。"""
    result = _result([(i, "x") for i in range(1000)], truncated=True)

    _columns, rows, truncated = to_preview(result, limit=100)

    assert len(rows) == 100
    assert truncated is True


def test_fewer_rows_than_the_limit_are_all_kept() -> None:
    result = _result([(1, "a"), (2, "b")])

    _columns, rows, truncated = to_preview(result, limit=100)

    assert rows == [[1, "a"], [2, "b"]]
    assert truncated is False


def test_rows_become_lists_not_tuples() -> None:
    """JSONB 存的是 JSON 数组。tuple 能被 json 序列化成数组，但读回来是 list——存进去就
    统一成 list，免得「写进去是 tuple、读出来是 list」这种不对称。
    """
    _columns, rows, _ = to_preview(_result([(1, "a")]), limit=10)

    assert isinstance(rows, list)
    assert isinstance(rows[0], list)


def test_datetimes_become_iso_strings() -> None:
    """json.dumps 不认 datetime/date，而 JSONB 列要可序列化的值。"""
    moment = datetime(2026, 8, 21, 10, 30, tzinfo=UTC)
    result = _result([(moment, date(2026, 8, 21))])

    _columns, rows, _ = to_preview(result, limit=10)

    assert rows[0][0] == "2026-08-21T10:30:00+00:00"
    assert rows[0][1] == "2026-08-21"


def test_decimals_become_floats() -> None:
    """**丢精度是有意的**（设计 §9.2）：预览是给人看的、给图表用的，而 JSON 没有十进制
    类型；转成字符串前端又得自己解析，图表库更是画不了。

    全量导出（P3d 的 export.csv）走**重跑 + 流式写出**，不经过这里——精度在需要它的路径上
    是完整的。**别为了「精度」把这里改成字符串**，那会让图表画不出来。
    """
    _columns, rows, _ = to_preview(_result([(Decimal("12.34"),)]), limit=10)

    assert rows[0][0] == 12.34
    assert isinstance(rows[0][0], float)


def test_bytes_become_base64() -> None:
    """bytea 列。原样放进 JSON 会抛 TypeError。"""
    _columns, rows, _ = to_preview(_result([(b"\x00\x01\xff",)]), limit=10)

    assert rows[0][0] == base64.b64encode(b"\x00\x01\xff").decode()


def test_none_stays_none() -> None:
    """SQL NULL → JSON null。别转成空字符串——那会让「没有值」和「空字符串」分不开。"""
    _columns, rows, _ = to_preview(_result([(None, None)]), limit=10)

    assert rows[0] == [None, None]


def test_columns_carry_name_type_and_is_numeric_only() -> None:
    """与 result 事件的 columns 同形（上游 spec §2.3 的载荷定义）。

    **不含 is_nullable 与 comment**：预览是结果的摘要，不是 schema 元数据——那些在
    /schema 端点（P2c）。多带字段会让前端以为可以从这里读元数据。
    """
    columns, _rows, _ = to_preview(_result([(1, "a")]), limit=10)

    assert columns == [
        {"name": "id", "type": "integer", "is_numeric": True},
        {"name": "label", "type": "text", "is_numeric": False},
    ]


def test_an_empty_result_is_handled() -> None:
    """0 行不是特例，但要确认不抛。"""
    columns, rows, truncated = to_preview(_result([]), limit=100)

    assert rows == []
    assert truncated is False
    assert len(columns) == 2
