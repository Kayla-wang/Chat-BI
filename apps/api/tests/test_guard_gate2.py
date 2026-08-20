"""闸 2（AST 校验）—— 上游 spec §4.3 的第二道闸。

三道检查各守一个缺口，测试按检查分组。用参数化而不是一堆独立函数：清单会长，而每条的
断言完全相同，写成独立函数只会让人不敢往里加新样本（spec §5.1 要求 guard 穷举边界）。
"""

import pytest

from chatbi.guard.policy import Policy
from chatbi.guard.validator import validate_sql


def _verdict(sql: str, dialect: str = "postgres"):
    return validate_sql(sql, dialect=dialect, max_rows=1000, policy=Policy())


# ---- 第一道：根节点白名单 + 单语句 ----

WRITE_STATEMENTS = [
    "insert into t values (1)",
    "update t set a = 1",
    "delete from t",
    "drop table t",
    "create table t (a int)",
    "alter table t add column b int",
    "truncate table t",
    "grant select on t to u",
    "copy t from '/tmp/x.csv'",
    "merge into t using s on t.id = s.id when matched then update set a = 1",
]


@pytest.mark.parametrize("sql", WRITE_STATEMENTS)
def test_write_statements_are_blocked(sql: str) -> None:
    verdict = _verdict(sql)

    assert verdict.ok is False
    assert verdict.code == "WRITE_BLOCKED"
    assert verdict.effective_sql is None  # 被拒的语句没有「实际会跑的版本」


UNKNOWN_SYNTAX = ["vacuum", "call proc()", "explain select 1"]


@pytest.mark.parametrize("sql", UNKNOWN_SYNTAX)
def test_syntax_sqlglot_does_not_understand_is_blocked(sql: str) -> None:
    """sqlglot 把不认识的语句兜底成 exp.Command 而**不抛 ParseError**（实测：vacuum /
    call proc() / explain select 1 都是 Command）。Command 里可以是任何东西，包括厂商
    特有的写语句——所以白名单必须是严格白名单。

    副作用：explain select 1 也被拒。这是有意的取舍——放行 Command 换来的「支持
    EXPLAIN」远不值得打开这个洞。要支持 EXPLAIN 就单独识别它，别放行 Command。
    """
    assert _verdict(sql).ok is False


def test_a_session_setting_is_blocked() -> None:
    """set statement_timeout = 1 的根是 exp.Set（不是 Command）。它不在白名单里，所以
    自动被拒——但要有测试，否则将来有人往白名单加节点时不会想到这条。
    """
    assert _verdict("set statement_timeout = 1").ok is False


def test_multiple_statements_are_rejected() -> None:
    verdict = _verdict("select 1; select 2")

    assert verdict.ok is False
    assert verdict.code == "MULTIPLE_STATEMENTS"


def test_a_trailing_semicolon_is_still_one_statement() -> None:
    """最容易漏的一条：`select 1;` 在 parse() 下是 **1** 条语句。把它判成多语句会让
    大量正常输入被拒——用户习惯性在末尾加分号。
    """
    assert _verdict("select 1;").ok is True


# ---- 第二道：整树扫描写节点 ----


def test_a_data_modifying_cte_is_blocked() -> None:
    """它的根节点是 Select，与正常 CTE **完全相同**（实测），只有整树扫描能区分。

    只判根节点的实现会放行一条真正在写库的语句。
    """
    verdict = _verdict("with x as (insert into t values (1) returning *) select * from x")

    assert verdict.ok is False
    assert verdict.code == "WRITE_BLOCKED"


def test_a_normal_cte_is_allowed() -> None:
    """与上一条互为对照。两者根节点相同，所以一个「见到 WITH 就拒绝」的实现会让上一条
    变绿而这一条变红——两条都要有，才能钉住「按树内容判断」而不是「按语法形状判断」。
    """
    assert _verdict("with x as (select 1 a) select * from x").ok is True


# ---- 第三道：into arg 检查 ----


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "clickhouse"])
def test_select_into_is_blocked(dialect: str) -> None:
    """SELECT INTO 会建一张新表，但它的根是 Select、树内写节点**为空**——前两道检查
    全部放行它。三个方言下都是这个形状（实测）。

    这是本份最容易被「优化」掉的一道检查：读代码的人会觉得「都扫过整树了还检查 into
    干什么」。答案是整树里没有任何写节点类可扫。
    """
    verdict = _verdict("select * into new_t from t", dialect=dialect)

    assert verdict.ok is False
    assert verdict.code == "WRITE_BLOCKED"


# ---- 绕过尝试：注释夹带、大小写、空白 ----

BYPASS_ATTEMPTS = [
    "select 1 /* c */; drop table t",
    "select 1 -- c\n; drop table t",
    "InSeRt InTo t VaLuEs (1)",
    "\n\n   insert into t values (1)   \n",
]


@pytest.mark.parametrize("sql", BYPASS_ATTEMPTS)
def test_comment_and_case_variants_do_not_bypass(sql: str) -> None:
    """注释夹带、大小写变形、空白变形全部由 AST 天然处理——**这就是上游 spec §4.3 写
    「用 AST 而不是正则」的理由**。不需要任何额外代码，但需要测试证明它成立。

    只断言 ok is False 不断言 code：前两条是多语句（MULTIPLE_STATEMENTS），后两条是
    写操作（WRITE_BLOCKED），这里要说的是「都进不来」。
    """
    assert _verdict(sql).ok is False


# ---- 解析失败 ----

PARSE_FAILURES = ["select from where", "select * from", "select * from t where", "(((("]


@pytest.mark.parametrize("sql", PARSE_FAILURES)
def test_unparseable_sql_is_rejected(sql: str) -> None:
    """上游 spec §4.3：「解析失败即拒绝，不做『看起来像 SELECT 就放过』的兜底」。"""
    verdict = _verdict(sql)

    assert verdict.ok is False
    assert verdict.code == "SQL_PARSE_ERROR"


# ---- 放行清单 ----

ALLOWED = [
    "select 1",
    "select * from t",
    "with x as (select 1 a) select * from x",
    "select a from t union select b from u",
    "select a from t union all select b from u",
    "select * from (select 1 a) s",
    "select t.a from t join u on t.id = u.id",
    "select a, row_number() over (order by b) from t",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_read_only_queries_are_allowed(sql: str) -> None:
    verdict = _verdict(sql)

    assert verdict.ok is True
    assert verdict.code is None
    assert verdict.effective_sql  # 非空


def test_a_string_literal_that_looks_like_a_write_is_allowed() -> None:
    """字面量不是节点，所以 AST 天然不会误判——而**任何正则实现都会在这条上误报**。

    这条是「用 AST 而不是正则」这个决定的直接收益，单独一个测试而不是塞进 ALLOWED
    列表，因为它证明的东西不同。
    """
    assert _verdict("select 'insert into t' as x").ok is True


def test_union_is_allowed_even_though_its_root_is_not_select() -> None:
    """union 的根节点是 exp.Union 而不是 exp.Select。白名单漏了它会把一条合法查询判成
    写操作——而 ALLOWED 列表里那两条 union 用例已经覆盖，这里单独再说一次是为了让
    「白名单有三个类型」这件事在测试名里可见。
    """
    assert _verdict("select a from t union select b from u").ok is True
