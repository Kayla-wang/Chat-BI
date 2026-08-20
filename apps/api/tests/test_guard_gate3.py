"""闸 3（LIMIT 注入）—— 上游 spec §4.3 的第三道闸。

断言 effective_sql 的**内容特征**（含不含某个片段、LIMIT 值是多少）而不是整条字符串
相等：sqlglot 会规范化大小写、引号、空白，写死整条会让这些测试在升级 sqlglot 时集体
变红，而那时红的原因与闸 3 的正确性无关。
"""

import pytest

from chatbi.guard.policy import Policy
from chatbi.guard.validator import validate_sql

MAX = 1000


def _verdict(sql: str, dialect: str = "postgres", max_rows: int = MAX):
    return validate_sql(sql, dialect=dialect, max_rows=max_rows, policy=Policy())


def test_a_query_without_a_limit_gets_one() -> None:
    verdict = _verdict("select * from t")

    assert verdict.ok is True
    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is True


def test_a_smaller_limit_is_kept() -> None:
    """spec §4.3「已有 LIMIT 且更小则保留原值」。"""
    verdict = _verdict("select * from t limit 10")

    assert "LIMIT 10" in verdict.effective_sql
    assert "1000" not in verdict.effective_sql
    assert verdict.limit_applied is False


def test_a_larger_limit_is_tightened() -> None:
    verdict = _verdict("select * from t limit 5000")

    assert "LIMIT 1000" in verdict.effective_sql
    assert "5000" not in verdict.effective_sql
    assert verdict.limit_applied is True


def test_a_limit_exactly_at_the_cap_is_kept() -> None:
    """边界值。`<` 与 `<=` 写错只有这一条能看出来——而写错的方向是「把正好合规的语句
    也改写一遍」，effective_sql 看起来没问题，limit_applied 却是 True。
    """
    verdict = _verdict("select * from t limit 1000")

    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is False


def test_fetch_first_within_the_cap_is_left_alone() -> None:
    """FETCH FIRST 也存在 args["limit"] 里，但节点类型是 exp.Fetch。只认 exp.Limit 的
    实现会把它当成「没有 LIMIT」并覆盖掉——用户写的「只要 5 行」变成 1000 行。

    这里断言 FETCH 片段仍在：不改写成 LIMIT，因为它已经是一个不超上限的行数限制，改写
    只会让 effective_sql 与用户写的对不上。
    """
    verdict = _verdict("select * from t fetch first 5 rows only")

    assert "FETCH" in verdict.effective_sql.upper()
    assert "1000" not in verdict.effective_sql
    assert verdict.limit_applied is False


def test_fetch_first_over_the_cap_is_tightened() -> None:
    verdict = _verdict("select * from t fetch first 5000 rows only")

    assert "LIMIT 1000" in verdict.effective_sql
    assert "5000" not in verdict.effective_sql
    assert verdict.limit_applied is True


def test_clickhouse_limit_by_is_left_alone_with_a_warning() -> None:
    """LIMIT n BY x 的语义是「每个 x 取 n 行」，总行数无上界。理想做法是再加一个总
    LIMIT，但 sqlglot 对同一条语句上两个 LIMIT 直接 ParseError（实测），所以没有
    「不改语义又能加总上限」的写法。

    **这不留缺口**：P2b 的驱动层取 max_rows + 1 行后 truncate()，返回行数在那一层是硬
    保证的。闸 3 注入 LIMIT 的额外价值是减少库侧扫描量，对这个边缘语法放弃该优化、
    换取不篡改用户语义，是设计 §2.2 定的取舍。

    warning 让它可见，而不是悄悄放过。
    """
    verdict = _verdict("select * from t limit 3 by x", dialect="clickhouse")

    assert verdict.ok is True
    assert "BY" in verdict.effective_sql.upper()
    assert verdict.limit_applied is False
    assert verdict.warnings  # 非空


def test_a_limit_in_a_subquery_is_not_touched() -> None:
    """子查询里的 LIMIT 5 保留，外层照样注入。走错了会把内层的 5 当成外层的上限，于是
    「外层没有 LIMIT」这个事实被漏掉。
    """
    verdict = _verdict("select * from (select * from t limit 5) s")

    assert "LIMIT 5" in verdict.effective_sql
    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is True


def test_a_non_literal_limit_is_tightened() -> None:
    """LIMIT 的值不是字面量时无法静态判断它是否 ≤ max，收紧是安全的方向。"""
    verdict = _verdict("select * from t limit (select 5)")

    assert verdict.ok is True
    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is True


@pytest.mark.parametrize("sql", ["select * from t limit '5'", "select * from t limit 5.5"])
def test_a_literal_that_is_not_an_integer_is_tightened(sql: str) -> None:
    """两者都是 exp.Literal 但 is_int 为 False（实测）。

    这条守的不只是「语义正确」：`_row_cap` 里去掉 `value.is_int` 判断后，`LIMIT 5.5`
    会走到 `int("5.5")` 并抛 **ValueError**——也就是一个 500，而闸 3 是安全红线代码，
    它不该有能被一条畸形 SQL 打崩的路径。反向验证时发现「去掉 is_int 全绿」，补的就是
    这一条。
    """
    verdict = _verdict(sql)

    assert verdict.ok is True
    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is True


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "clickhouse"])
def test_the_cap_applies_in_every_dialect(dialect: str) -> None:
    verdict = _verdict("select * from t limit 5000", dialect=dialect)

    assert "LIMIT 1000" in verdict.effective_sql
    assert verdict.limit_applied is True


def test_the_cap_comes_from_the_argument_not_from_settings() -> None:
    """max_rows 是显式参数（与 P2b 驱动的 execute() 同一条约定）。若实现改成读
    get_settings()，这条会红——而那种实现让测试必须改环境变量才能测边界值。
    """
    verdict = _verdict("select * from t", max_rows=7)

    assert "LIMIT 7" in verdict.effective_sql


def test_union_gets_the_limit_at_the_outermost_level() -> None:
    """union 的根是 exp.Union，注入要作用于整个 union 而不是最后一个 select。"""
    verdict = _verdict("select a from t union select b from u")

    assert verdict.effective_sql.rstrip().upper().endswith("LIMIT 1000")


def test_a_rejected_statement_has_no_effective_sql() -> None:
    """闸 2 拒绝时不该走到闸 3。被拒的语句没有「实际会跑的版本」。"""
    verdict = _verdict("insert into t values (1)")

    assert verdict.ok is False
    assert verdict.effective_sql is None
    assert verdict.limit_applied is False
