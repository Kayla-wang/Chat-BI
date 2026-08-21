"""chart_spec 规则推断（上游 spec §3.5，P3b 设计 §8）。纯函数，无夹具。

规则是 spec §3.5 定的：1 维度 + 1 度量 → 柱状；含时间维度 → 折线；2 度量 → 散点；
单值 → 大数字卡。本文件钉住的是**判定顺序**与 spec 没覆盖的边界。
"""

import pytest

from chatbi.datasources.drivers.base import ColumnSchema
from chatbi.execution.charts import infer_chart_spec


def _col(name: str, data_type: str = "text", *, numeric: bool = False) -> ColumnSchema:
    return ColumnSchema(name=name, data_type=data_type, is_numeric=numeric)


_MONTH = _col("month", "timestamp with time zone")
_CITY = _col("city", "text")
_AMOUNT = _col("amount", "numeric", numeric=True)
_QTY = _col("qty", "integer", numeric=True)


def test_no_rows_is_a_table() -> None:
    """0 行没有数据可画。spec 没覆盖这条边界。"""
    spec = infer_chart_spec((_CITY, _AMOUNT), row_count=0)

    assert spec.type == "table"
    assert spec.reason


def test_a_single_numeric_value_is_a_metric_card() -> None:
    """spec §3.5「单值 → 大数字卡」。"""
    spec = infer_chart_spec((_AMOUNT,), row_count=1)

    assert spec.type == "metric"
    assert spec.x is None
    assert spec.y == ("amount",)


def test_a_dimension_and_a_measure_is_a_bar() -> None:
    """spec §3.5「1 维度 + 1 度量 → 柱状」。"""
    spec = infer_chart_spec((_CITY, _AMOUNT), row_count=20)

    assert spec.type == "bar"
    assert spec.x == "city"
    assert spec.y == ("amount",)


def test_a_time_column_makes_it_a_line() -> None:
    """spec §3.5「含时间维度 → 折线」。

    **这条才是守判定顺序的那一条**（设计 §8.1）：1 时间 + 1 度量同时满足规则 3（时间）
    与规则 4（1 维度 + 1 度量），所以把时间规则挪到 4 之后，它就会变成 bar。

    反向验证时发现 test_line_carries_every_measure 守不住顺序（见那条的文档），所以顺序
    的守卫只有这一条 + 六条方言参数化。
    """
    spec = infer_chart_spec((_MONTH, _AMOUNT), row_count=12)

    assert spec.type == "line"
    assert spec.x == "month"
    assert spec.y == ("amount",)


def test_line_carries_every_measure() -> None:
    """1 时间 + 2 度量 → 折线，且 y 含**全部**度量（两条线）。

    **这条守不住判定顺序**，尽管它一度被当成顺序的守卫（原名
    test_time_wins_over_the_number_of_measures）。原因是这个输入
    （1 个非数值列 + 2 个数值列）**既不满足规则 4**（要求 measures == 1）**也不满足
    规则 5**（要求 not dimensions），所以时间规则放在任何位置它都是 line——反向验证
    把时间规则挪到最后时，这条依然绿。

    它真正守的是 `y = 全部度量` 这个行为：一个只取第一个度量的实现会让它红。
    """
    spec = infer_chart_spec((_MONTH, _AMOUNT, _QTY), row_count=12)

    assert spec.type == "line"
    assert spec.x == "month"
    assert spec.y == ("amount", "qty")


def test_two_measures_without_a_dimension_is_a_scatter() -> None:
    """spec §3.5「2 度量 → 散点」。"""
    spec = infer_chart_spec((_AMOUNT, _QTY), row_count=50)

    assert spec.type == "scatter"
    assert spec.x == "amount"
    assert spec.y == ("qty",)


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param((_CITY,), id="只有一个文本列"),
        pytest.param((_CITY, _col("segment")), id="两个文本列"),
        pytest.param((_CITY, _col("segment"), _AMOUNT, _QTY), id="多维度多度量"),
        pytest.param((_AMOUNT, _QTY, _col("ratio", "numeric", numeric=True)), id="三个度量"),
    ],
)
def test_everything_else_falls_back_to_a_table(columns) -> None:
    """兜底。画不出有意义的图时给表格，而不是硬选一个图型——错的图比没有图更误导。"""
    spec = infer_chart_spec(columns, row_count=10)

    assert spec.type == "table"
    assert spec.x is None
    assert spec.y == ()


@pytest.mark.parametrize(
    "data_type",
    ["date", "timestamp", "timestamp with time zone", "DateTime", "datetime64", "Date32"],
)
def test_time_columns_are_recognised_across_dialects(data_type: str) -> None:
    """三个驱动给的类型名拼法各不相同（Postgres 的 timestamp with time zone、ClickHouse 的
    DateTime / Date32、MySQL 的 datetime），所以判定是**大小写不敏感的子串匹配**。

    已知会误判 `timezone_name` 这类文本列（设计 §8.1 写明了这个取舍）：后果只是图型选错，
    而 spec §3.5 明写用户可手动改类型与字段（F-402 AC2）——有出口。不为它给驱动协议加
    is_temporal 字段。
    """
    spec = infer_chart_spec((_col("t", data_type), _AMOUNT), row_count=5)

    assert spec.type == "line"


def test_a_single_row_that_is_not_a_lone_number_is_not_a_metric() -> None:
    """1 行但有两列 → 不是大数字卡。规则 2 的条件是「1 行 **1 列** 且是数值」。

    只判行数会让「一行两列」也变成 metric，而那时 y 该取哪一列没有答案。
    """
    spec = infer_chart_spec((_CITY, _AMOUNT), row_count=1)

    assert spec.type != "metric"


def test_a_single_text_value_is_not_a_metric() -> None:
    """1 行 1 列但不是数值 → 表格。大数字卡上放一个字符串没有意义。"""
    spec = infer_chart_spec((_CITY,), row_count=1)

    assert spec.type == "table"
