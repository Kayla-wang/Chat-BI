"""chart_spec 规则推断（上游 spec §3.5）。

**纯函数，不设接口。** 上游 spec §6 明写「ChartSpec 不设接口——V2-1 的规则推断是纯函数，
V2-3 要换成 LLM 选图时直接替换该函数，加一层抽象是过早的」。所以这里是一个函数 + 一个
frozen dataclass，没有 ChartInferrer 协议。

**输入只有列信息与行数，不含结果行。** 选图不需要看数据本身，而不把行传进来就使这个函数
天然不可能把结果行写进日志（上游 spec §4.6）。
"""

from dataclasses import dataclass

from chatbi.datasources.drivers.base import ColumnSchema

# 大小写不敏感的子串匹配。三个驱动给的类型名拼法不同：Postgres 的
# "timestamp with time zone"、ClickHouse 的 "DateTime" / "Date32"、MySQL 的 "datetime"。
#
# 已知会误判 timezone_name 这类文本列。后果只是图型选错，而 spec §3.5 明写用户可手动改
# 类型与字段（F-402 AC2）——有出口。**不为它给驱动协议加 is_temporal 字段**：那要改 P2b
# 的协议与三个驱动，代价远大于一个有出口的启发式。V2-3 换 LLM 选图时这段一起消失。
_TIME_HINTS = ("date", "time", "timestamp")


@dataclass(frozen=True)
class ChartSpec:
    type: str
    """table | metric | line | bar | scatter"""

    x: str | None
    y: tuple[str, ...]
    reason: str
    """为什么选这个图型。发给前端（上游 spec §2.3 的 chart_spec 载荷有这一项），让用户在
    手动改图型前知道后端是怎么想的。"""


def _is_time(column: ColumnSchema) -> bool:
    lowered = column.data_type.lower()
    return any(hint in lowered for hint in _TIME_HINTS)


def infer_chart_spec(columns: tuple[ColumnSchema, ...], row_count: int) -> ChartSpec:
    """按 spec §3.5 的规则选图型。**判定顺序即优先级**，第一个命中就返回。

    时间那一条（规则 3）**必须**在「1 维度 + 1 度量」与「2 度量」之前：spec §3.5 把
    「含时间维度」写成独立一条，而时间序列画散点几乎总是错的。挪动它的位置会让
    「1 时间 + 2 度量」从折线变成散点。
    """
    measures = tuple(c for c in columns if c.is_numeric)
    dimensions = tuple(c for c in columns if not c.is_numeric)
    time_columns = tuple(c for c in columns if _is_time(c))

    # 1. 没有数据可画
    if row_count == 0:
        return ChartSpec(type="table", x=None, y=(), reason="结果为空，没有可绘制的数据")

    # 2. 单值 → 大数字卡。条件是「1 行 **1 列** 且是数值」——只判行数会让「一行两列」
    #    也变成 metric，而那时 y 取哪一列没有答案
    if row_count == 1 and len(columns) == 1 and columns[0].is_numeric:
        return ChartSpec(type="metric", x=None, y=(columns[0].name,), reason="单个数值")

    # 3. 含时间维度 → 折线（**在 4、5 之前**，见函数文档）
    if time_columns and measures:
        return ChartSpec(
            type="line",
            x=time_columns[0].name,
            y=tuple(c.name for c in measures),
            reason="含时间维度，按时间趋势展示",
        )

    # 4. 1 维度 + 1 度量 → 柱状
    if len(dimensions) == 1 and len(measures) == 1:
        return ChartSpec(
            type="bar",
            x=dimensions[0].name,
            y=(measures[0].name,),
            reason="一个维度与一个度量",
        )

    # 5. 2 度量、无维度 → 散点
    if not dimensions and len(measures) == 2:
        return ChartSpec(
            type="scatter",
            x=measures[0].name,
            y=(measures[1].name,),
            reason="两个度量，展示相关性",
        )

    # 6. 兜底。画不出有意义的图时给表格——**错的图比没有图更误导**
    return ChartSpec(type="table", x=None, y=(), reason="列的组合不适合自动选图")
