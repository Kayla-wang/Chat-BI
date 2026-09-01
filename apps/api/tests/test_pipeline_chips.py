"""chips 匹配与中文时间词（P3c 设计 §4）。无夹具——纯函数。

**today 是显式参数**，所以跨年、跨月、闰年边界都能穷举。读系统时钟的实现测不了这些。
"""

from datetime import date

import pytest

from chatbi.datasources.drivers.base import ColumnSchema, SchemaSnapshot, TableSchema
from chatbi.pipeline.chips import match_chips, resolve_time_phrase

_TODAY = date(2026, 8, 24)  # 周一


@pytest.mark.parametrize(
    ("question", "start", "end"),
    [
        ("今天卖了多少", date(2026, 8, 24), date(2026, 8, 24)),
        ("昨天卖了多少", date(2026, 8, 23), date(2026, 8, 23)),
        ("本周的订单", date(2026, 8, 24), date(2026, 8, 30)),
        ("上周的订单", date(2026, 8, 17), date(2026, 8, 23)),
        ("本月营收", date(2026, 8, 1), date(2026, 8, 31)),
        ("上个月营收", date(2026, 7, 1), date(2026, 7, 31)),
        ("上月营收", date(2026, 7, 1), date(2026, 7, 31)),
        ("本季度营收", date(2026, 7, 1), date(2026, 9, 30)),
        ("上季度营收", date(2026, 4, 1), date(2026, 6, 30)),
        ("今年营收", date(2026, 1, 1), date(2026, 12, 31)),
        ("去年营收", date(2025, 1, 1), date(2025, 12, 31)),
        ("最近 7 天的订单", date(2026, 8, 18), date(2026, 8, 24)),
        ("最近7天的订单", date(2026, 8, 18), date(2026, 8, 24)),
        ("近 30 天的订单", date(2026, 7, 26), date(2026, 8, 24)),
        ("最近 3 个月", date(2026, 6, 1), date(2026, 8, 31)),
    ],
)
def test_the_time_phrases_resolve_to_absolute_ranges(question, start, end) -> None:
    """**「最近 7 天」含今天**（设计 §4.4）：用户说「最近 7 天」时期望里有今天，
    否则他会问「过去一周」。这类差一天的问题在数字对不上时极难排查，所以钉死。
    """
    resolved = resolve_time_phrase(question, today=_TODAY)

    assert resolved is not None, f"{question!r} 没识别出时间词"
    _label, actual_start, actual_end = resolved
    assert (actual_start, actual_end) == (start, end)


def test_the_label_keeps_the_original_words() -> None:
    """label 存原词、value 存绝对区间（设计 §4.4）。**回放要用 value**——一个月后
    「上个月」的含义已经变了。
    """
    label, start, end = resolve_time_phrase("上个月各城市营收", today=_TODAY)

    assert label == "上个月"
    assert (start, end) == (date(2026, 7, 1), date(2026, 7, 31))


def test_a_question_without_a_time_phrase_resolves_to_none() -> None:
    assert resolve_time_phrase("各城市营收", today=_TODAY) is None


@pytest.mark.parametrize(
    ("question", "label"),
    [
        ("今年和上个月", "上个月"),  # 「今年」在句首，但「上个月」在表里更靠前
        ("本月和昨天", "昨天"),
        ("上个月和今年", "上个月"),  # 这个方向两条规则恰好给出同一答案
    ],
)
def test_the_earlier_table_entry_wins_not_the_earlier_word(question, label) -> None:
    """一句话里有两个时间词时，**赢的是 table 里靠前的那行，不是句子里靠前的那个词**。

    这条替代了 chips.py 里原本那句「顺序敏感是为了防子串互吃」——那个说法是错的：
    实测 table 里没有任何 label 是另一个的子串（「上月」不是「上个月」的子串，中文
    子串要连续），调换任意两行都不改变单个时间词的解析。顺序真正决定的是这里的优先级，
    而在补上这条之前它一条守卫都没有（p3c1 反向验证 3 因此全绿）。

    钉住它是因为**用户看到的 chip label 由它决定**：机器按「上个月」算而用户以为按
    「今年」算，数字对不上时没人会想到是这里。
    """
    resolved = resolve_time_phrase(question, today=_TODAY)

    assert resolved is not None
    assert resolved[0] == label


@pytest.mark.parametrize(
    ("today", "start", "end"),
    [
        (date(2026, 1, 15), date(2025, 12, 1), date(2025, 12, 31)),  # 跨年
        (date(2026, 3, 5), date(2026, 2, 1), date(2026, 2, 28)),  # 平年 2 月
        (date(2024, 3, 5), date(2024, 2, 1), date(2024, 2, 29)),  # 闰年 2 月
    ],
)
def test_last_month_handles_year_and_leap_boundaries(today, start, end) -> None:
    """**这三条是 today 必须是参数的理由**：读系统时钟的实现只能在一年里的某几天
    验到跨年，而那时问题已经在生产上了。
    """
    _label, actual_start, actual_end = resolve_time_phrase("上个月", today=today)

    assert (actual_start, actual_end) == (start, end)


def _snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        tables=(
            TableSchema(
                schema_name="demo_sales",
                name="orders",
                comment="订单",
                columns=(
                    ColumnSchema(name="id", data_type="uuid"),
                    ColumnSchema(name="city", data_type="text", comment="城市"),
                    ColumnSchema(
                        name="order_amount", data_type="numeric", is_numeric=True, comment="金额"
                    ),
                ),
            ),
            TableSchema(
                schema_name="demo_sales",
                name="customers",
                comment="客户",
                columns=(ColumnSchema(name="name", data_type="text", comment="姓名"),),
            ),
        )
    )


def test_a_table_comment_in_the_question_resolves_that_table() -> None:
    """中文注释是 V2-1 术语理解的**唯一**来源（spec §0：同义词表在 V2-2）。
    问「订单」要能命中注释为「订单」的表。
    """
    result = match_chips("上个月的订单", _snapshot(), today=_TODAY)

    assert result.resolved_tables == ("demo_sales.orders",)
    assert any(c.kind == "table" and c.label == "订单" and c.hit for c in result.chips)


def test_an_english_identifier_matches_after_underscore_splitting() -> None:
    """问题里不会带下划线，所以 order_amount 要能被「amount」命中。"""
    result = match_chips("show me the amount", _snapshot(), today=_TODAY)

    assert any(c.kind == "column" and "amount" in c.value for c in result.chips)


def test_short_identifiers_do_not_match() -> None:
    """`id` 会命中大量问题而说明不了任何事（设计 §4.2）。长度 ≤2 的纯英文标识符
    不参与匹配——**否则每个 chip 列表里都有一个没用的 id**。
    """
    result = match_chips("what did we do", _snapshot(), today=_TODAY)

    assert not [c for c in result.chips if c.value.endswith(".id")]


def test_a_time_chip_is_included_and_carries_the_absolute_range() -> None:
    result = match_chips("上个月的订单", _snapshot(), today=_TODAY)

    time_chips = [c for c in result.chips if c.kind == "time"]
    assert len(time_chips) == 1
    assert time_chips[0].label == "上个月"
    assert time_chips[0].value == "2026-07-01/2026-07-31"
    assert result.time_range == (date(2026, 7, 1), date(2026, 7, 31))


def test_nothing_matched_gives_no_resolved_tables() -> None:
    """**空的 resolved_tables 不是错误**：Task 5 的兜底（给全部表完整列）依赖这个信号。
    这里不能返回「全部表」——那会让 Task 5 分不清「命中了全部」与「一张都没命中」。
    """
    result = match_chips("讲个笑话", _snapshot(), today=_TODAY)

    assert result.resolved_tables == ()
    assert result.chips == ()


def test_a_column_note_participates_in_matching() -> None:
    """人工备注（column_notes，P2c）也是匹配来源，且优先于库注释——管理员是对着这个
    业务写的（设计 §8.3 的同一条理由）。
    """
    notes = {("demo_sales", "orders", "order_amount"): "营收"}

    result = match_chips("上个月营收", _snapshot(), today=_TODAY, notes=notes)

    assert any(c.kind == "column" and c.label == "营收" for c in result.chips)
    assert result.resolved_tables == ("demo_sales.orders",)


def test_at_most_eight_chips_but_all_tables_stay_resolved() -> None:
    """chips 上限 8 个（界面那条横排放不下更多），**但 resolved_tables 不受限**——
    上下文选表用后者，砍掉它会让模型看不见本该看见的表（设计 §4.3）。
    """
    tables = tuple(
        TableSchema(
            schema_name="s",
            name=f"table_{i}",
            comment=f"表{i}",
            columns=(ColumnSchema(name=f"col_{i}", data_type="text", comment=f"列{i}"),),
        )
        for i in range(10)
    )
    question = " ".join(f"表{i} 列{i}" for i in range(10))

    result = match_chips(question, SchemaSnapshot(tables=tables), today=_TODAY)

    assert len(result.chips) == 8
    assert len(result.resolved_tables) == 10
