"""闸 2（AST 校验）与闸 3（LIMIT 注入）——上游 spec §4.3 的第二、三道闸。

**这是安全红线代码**，保持在 200 行以内、只做这一件事（spec §1.4）。不 import fastapi、
不 import sqlalchemy：输入是「一条 SQL + 方言名 + 行数上限 + 策略」，输出是一个 frozen
dataclass。

三道检查为什么分开写，见 _write_reason 里各自的注释。合成一个函数会让「哪一道漏了」无法
定位，更要紧的是它们各自的反向验证做不出来。
"""

import sqlglot
from sqlglot import exp

from chatbi.errors import MULTIPLE_STATEMENTS, SQL_PARSE_ERROR, WRITE_BLOCKED
from chatbi.guard.policy import Policy
from chatbi.guard.schemas import GuardVerdict

# 严格白名单。sqlglot 把不认识的语句兜底成 exp.Command 而**不抛 ParseError**（实测：
# vacuum / call proc() / explain select 1 都是 Command），而 Command 里可以是任何东西，
# 包括厂商特有的写语句。往这里加类型前先问「这个类型的内容是否封闭可知」——Command 的
# 答案是「不是」。
#
# exp.Union 必须在：`select a from t union select b from u` 的根是 Union 而不是 Select，
# 漏了它会把一条合法查询判成写操作。
_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.With)

# 整树扫描用。exp.Copy 与 exp.Grant 是 spec §4.3 点名要禁的；exp.Merge 是写。
_WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Merge,
    exp.Copy,
)


def validate_sql(sql: str, *, dialect: str, max_rows: int, policy: Policy) -> GuardVerdict:
    """闸 2 + 闸 3。放行时 effective_sql 是实际会下发的语句。

    max_rows 与 policy 都是显式参数，**不自己读 get_settings()**——与 P2b 驱动的
    execute() 同一条约定：安全红线代码不要隐式全局依赖，否则测试要靠改环境变量才能测
    边界值。
    """
    if not policy.is_empty:
        # V2-1 不可能走到这里（只有 EmptyPolicyResolver）。这是 V2-2 的护栏：一个非空
        # policy 被无声丢掉，等于行列级权限「看起来生效了实际没有」。
        raise NotImplementedError("行列级策略在 V2-2 实现（上游 spec §4.2）")

    try:
        statements = sqlglot.parse(sql, dialect=dialect)
    except sqlglot.errors.ParseError as exc:
        # reason 带 sqlglot 的位置信息：那是用户自己刚写的 SQL，不是库结构（上游 §2.6 的
        # 前端表现也明写「内联说明 + 报错位置」）
        return _rejected(SQL_PARSE_ERROR, str(exc).splitlines()[0])

    # parse() 而不是 parse_one()：多语句必须**能被看见然后拒绝**，而 parse_one() 在多语句
    # 上只给第一条，等于静默丢掉后面那条 drop table。
    if len(statements) != 1:
        return _rejected(MULTIPLE_STATEMENTS, f"收到 {len(statements)} 条语句")

    root = statements[0]
    if root is None:  # parse("") 会给 [None]
        return _rejected(SQL_PARSE_ERROR, "语句为空")

    blocked = _write_reason(root)
    if blocked is not None:
        return _rejected(WRITE_BLOCKED, blocked)

    effective_sql, limit_applied, warnings = _apply_limit(root, dialect=dialect, max_rows=max_rows)
    return GuardVerdict(
        ok=True,
        effective_sql=effective_sql,
        code=None,
        reason=None,
        limit_applied=limit_applied,
        warnings=warnings,
    )


def _write_reason(root: exp.Expression) -> str | None:
    """三道检查。返回拒绝理由，或 None 表示放行。

    理由里说清是哪一类写操作（用户自己写的东西，告诉他比让他猜好），但**不含表名与
    列名**——那部分可能来自被污染的 LLM 输出或库结构（spec §4.4）。
    """
    # 第一道：根节点白名单
    if not isinstance(root, _ALLOWED_ROOTS):
        return f"语句类型 {type(root).__name__} 不是查询"

    # 第二道：整树扫描。Postgres 的 data-modifying CTE
    # （with x as (insert ... returning *) select * from x）的根**就是** Select，与正常
    # CTE 无法从根节点区分——只有走遍整棵树才能看见那个 Insert。
    for node in root.walk():
        if isinstance(node, _WRITE_NODES):
            return f"语句内含 {type(node).__name__} 操作"

    # 第三道：into arg。`select * into new_t from t` 会建一张新表，但它的根是 Select、
    # 树内写节点**为空**——前两道全部放行它。三个方言下都是这个形状。删掉这两行等于给
    # 闸 2 开一个能真正写库的缺口。
    if root.args.get("into") is not None:
        return "SELECT INTO 会创建表"

    return None


def _apply_limit(
    root: exp.Expression, *, dialect: str, max_rows: int
) -> tuple[str, bool, tuple[str, ...]]:
    """闸 3。返回 (effective_sql, limit_applied, warnings)。

    exp.Union 也有 .limit()，注入会落在最外层（实测），所以这里不需要按根类型分支。
    """
    limit_node = root.args.get("limit")

    # ClickHouse 的 `LIMIT n BY x`：类型仍是 exp.Limit，但多一个 expressions（BY 的那些
    # 列）。它的语义是「每个 x 取 n 行」，总行数无上界；而 sqlglot 对同一条语句上两个
    # LIMIT 直接 ParseError，所以没有「保留 BY 又加总上限」的写法。
    #
    # 原样保留 + warning（设计 §2.2）。**这不留缺口**：驱动层取 max_rows + 1 行后
    # truncate()，返回行数在那一层是硬保证的。闸 3 的额外价值是减少库侧扫描量。
    if limit_node is not None and limit_node.args.get("expressions"):
        warning = f"该语句的库侧行数未受限，返回结果仍会被截断到 {max_rows} 行"
        return root.sql(dialect=dialect), False, (warning,)

    current = _row_cap(limit_node)
    if current is not None and current <= max_rows:
        # spec §4.3「已有 LIMIT 且更小则保留原值」。`<=` 而不是 `<`：正好等于上限的语句
        # 已经合规，重写它只会让 effective_sql 与用户写的无谓地不同。
        return root.sql(dialect=dialect), False, ()

    return root.limit(max_rows).sql(dialect=dialect), True, ()


def _row_cap(node: exp.Expression | None) -> int | None:
    """读出语句现有的行数上限。读不出来就返回 None（调用方据此收紧）。

    node 可能是 exp.Limit（数值在 args["expression"]）或 exp.Fetch（数值在
    args["count"]）——**两者都放在 args["limit"] 里**。只认 exp.Limit 会让
    `FETCH FIRST 5 ROWS ONLY` 被当成「没有上限」并覆盖掉，用户的「只要 5 行」变成
    max_rows 行。

    值不是整数字面量（例如 `LIMIT (select 5)`）时返回 None：无法静态判断它是否
    ≤ max_rows，收紧是安全的方向。
    """
    if node is None:
        return None
    value = node.args.get("expression") or node.args.get("count")
    if isinstance(value, exp.Literal) and value.is_int:
        return int(value.this)
    return None


def _rejected(code_tuple: tuple[str, str, int], reason: str) -> GuardVerdict:
    code, message, _status = code_tuple
    return GuardVerdict(
        ok=False,
        effective_sql=None,
        code=code,
        reason=f"{message}：{reason}",
        limit_applied=False,
    )
