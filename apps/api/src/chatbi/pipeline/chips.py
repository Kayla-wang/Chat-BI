"""问题 → 意图 chips（P3c 设计 §4）。**纯函数，毫秒级，不调 LLM。**

为什么不调 LLM 抽实体（上游 spec §2.2 原本那么写）：本机一次 LLM 调用 20 秒（4.1
tok/s），而 chips 不影响 SQL 产出——它是给用户看的意图反馈，价值恰恰在于「在等草稿的
那 20 秒里先给点反馈」。LLM 版要等 15 秒才出来，那时用户已经在怀疑是不是挂了。
详见设计 §2.1，那里还记了第三条理由（确定性匹配能穷举测，LLM 抽实体不能）。

**不引分词器**（jieba 之类）：要装依赖，且对「订单金额」这种复合词的切法不稳定。改用
双向子串包含 + 下划线拆词，代价是同义词会漏（问「营收」而列叫 amount、注释写「金额」
时匹配不到）。这与上游 spec §0 已声明的降级一致（V2-1 的术语理解只靠 schema 注释，
同义词表在 V2-2），而漏的后果被「一张表都没命中时给全部表完整列」兜住（Task 5）。
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta

from chatbi.datasources.drivers.base import SchemaSnapshot

_RECENT_DAYS = re.compile(r"(?:最近|近|过去)\s*(\d+)\s*天")
_RECENT_MONTHS = re.compile(r"(?:最近|近|过去)\s*(\d+)\s*个?月")


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _month_end(day: date) -> date:
    return _next_month(_month_start(day)) - timedelta(days=1)


def _next_month(first: date) -> date:
    if first.month == 12:
        return first.replace(year=first.year + 1, month=1)
    return first.replace(month=first.month + 1)


def _months_back(first: date, months: int) -> date:
    """往前 months 个月的那个月 1 号。**负数是往后**（取季度末要用），整数月运算
    天然支持它——别改成 `+timedelta(days=90)`，那在跨月长度不同时会错。
    """
    total = first.year * 12 + (first.month - 1) - months
    return date(total // 12, total % 12 + 1, 1)


def resolve_time_phrase(question: str, *, today: date) -> tuple[str, date, date] | None:
    """识别一个中文时间词，返回 (原词, 起, 止)，都是**含端点**的日期。

    只认一个词，**按下面 table 的顺序取第一个命中的，不是按它在句子里的位置**。
    所以「今年和上个月」返回「上个月」（table 里 6 号）而不是句首的「今年」。正确处理
    多个时间词需要真正的语义理解，而 V2-1 声明了那在 V2-2。**这个限制要在 chip 的
    label 上体现**（用户看到「上个月」就知道机器按哪个算的）——
    test_the_earlier_table_entry_wins_not_the_earlier_word 钉住这条优先级。
    """
    if match := _RECENT_DAYS.search(question):
        days = int(match.group(1))
        return match.group(0), today - timedelta(days=days - 1), today
    if match := _RECENT_MONTHS.search(question):
        months = int(match.group(1))
        start = _months_back(_month_start(today), months - 1)
        return match.group(0), start, _month_end(today)
    week_start = today - timedelta(days=today.weekday())
    last_month_start = _months_back(_month_start(today), 1)
    quarter_start = _month_start(today).replace(month=(today.month - 1) // 3 * 3 + 1)
    table: tuple[tuple[str, date, date], ...] = (
        ("今天", today, today),
        ("昨天", today - timedelta(days=1), today - timedelta(days=1)),
        ("本周", week_start, week_start + timedelta(days=6)),
        ("上周", week_start - timedelta(days=7), week_start - timedelta(days=1)),
        ("本月", _month_start(today), _month_end(today)),
        ("上个月", last_month_start, _month_start(today) - timedelta(days=1)),
        ("上月", last_month_start, _month_start(today) - timedelta(days=1)),
        ("本季度", quarter_start, _month_end(_months_back(quarter_start, -2))),
        ("上季度", _months_back(quarter_start, 3), quarter_start - timedelta(days=1)),
        ("今年", date(today.year, 1, 1), date(today.year, 12, 31)),
        ("去年", date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)),
    )
    # 这里的顺序**不是**为了避免子串互吃——实测 table 里没有任何一个 label 是另一个的
    # 子串（尤其「上月」不是「上个月」的子串，中文子串要连续，「上个月」中间隔着「个」），
    # 所以调换任意两行都不会改变单个时间词的解析结果。p3c1 的反向验证 3 调换了
    # 「上个月」与「上月」，27 条测试**全绿**，实证了这一点。
    # 顺序真正决定的是**一句话里出现多个时间词时谁赢**：靠前的行优先。这条才是需要守的，
    # 由 test_the_earlier_table_entry_wins_not_the_earlier_word 钉住。
    for label, start, end in table:
        if label in question:
            return label, start, end
    return None


@dataclass(frozen=True)
class Chip:
    kind: str
    """table | column | time"""
    label: str
    """给用户看的词（命中的注释原文，或时间词原文）。"""
    value: str
    """机器用的值：table → "schema.table"；column → "schema.table.column"；
    time → "YYYY-MM-DD/YYYY-MM-DD"。**回放用 value 而不是 label**（设计 §4.4）。"""
    hit: bool
    """是否落到了真实的 schema 对象（时间则是识别成功）。前端用 ok 色（Figma §4.3）。
    V2-1 里它恒为 True——没命中的东西根本不会成为 chip。**保留这个字段**是因为 V2-2
    的语义层会产出「你说的这个词我不认识」的 chip，那时它才有 False。"""


@dataclass(frozen=True)
class ChipMatch:
    chips: tuple[Chip, ...] = ()
    resolved_tables: tuple[str, ...] = ()
    """"schema.table" 形式，与 known_identifiers 的第三种形式一致（Task 5 要拿它去
    断言白名单）。**不受 chips 上限影响**。"""
    time_range: tuple[date, date] | None = None


_MAX_CHIPS = 8
_MIN_ASCII_LEN = 3
"""长度 ≤2 的纯英文标识符（id / no / dt）不参与匹配：命中率高但信息量为零。"""


def _candidates(word: str) -> tuple[str, ...]:
    """一个标识符的可匹配形式：原词 + 下划线拆出的段（问题里不会带下划线）。"""
    parts = [word, *word.split("_")] if "_" in word else [word]
    return tuple(p for p in parts if not p.isascii() or len(p) >= _MIN_ASCII_LEN)


def _matches(word: str, question: str) -> bool:
    lowered = question.lower()
    return any(c.lower() in lowered for c in _candidates(word))


def match_chips(
    question: str,
    snapshot: SchemaSnapshot,
    *,
    today: date,
    notes: dict[tuple[str, str, str], str] | None = None,
) -> ChipMatch:
    """双向子串匹配（设计 §4.2）。**表 chip 优先、然后列、最后时间**（§4.3 的上限
    按这个顺序砍）。
    """
    notes = notes or {}
    table_chips: list[Chip] = []
    column_chips: list[Chip] = []
    resolved: list[str] = []

    for table in snapshot.tables:
        qualified = f"{table.schema_name}.{table.name}"
        table_hit = _matches(table.name, question) or bool(
            table.comment and table.comment in question
        )
        hit_columns: list[Chip] = []
        for column in table.columns:
            note = notes.get((table.schema_name, table.name, column.name))
            # 人工备注优先于库注释（设计 §8.3）：管理员是对着这个业务写的
            label_source = note or column.comment or column.name
            if _matches(column.name, question) or (
                label_source != column.name and label_source in question
            ):
                hit_columns.append(
                    Chip(
                        kind="column",
                        label=label_source,
                        value=f"{qualified}.{column.name}",
                        hit=True,
                    )
                )
        if table_hit or hit_columns:
            resolved.append(qualified)
            if table_hit:
                table_chips.append(
                    Chip(kind="table", label=table.comment or table.name, value=qualified, hit=True)
                )
            column_chips.extend(hit_columns)

    time_chips: list[Chip] = []
    time_range: tuple[date, date] | None = None
    if resolved_time := resolve_time_phrase(question, today=today):
        label, start, end = resolved_time
        time_range = (start, end)
        time_chips.append(
            Chip(
                kind="time",
                label=label,
                value=f"{start.isoformat()}/{end.isoformat()}",
                hit=True,
            )
        )

    chips = (*table_chips, *column_chips, *time_chips)[:_MAX_CHIPS]
    return ChipMatch(chips=chips, resolved_tables=tuple(resolved), time_range=time_range)
