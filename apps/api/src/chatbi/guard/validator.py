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

    # 闸 3 在 Task 2 接上。本任务先原样输出，limit_applied 恒 False。
    return GuardVerdict(
        ok=True,
        effective_sql=root.sql(dialect=dialect),
        code=None,
        reason=None,
        limit_applied=False,
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


def _rejected(code_tuple: tuple[str, str, int], reason: str) -> GuardVerdict:
    code, message, _status = code_tuple
    return GuardVerdict(
        ok=False,
        effective_sql=None,
        code=code,
        reason=f"{message}：{reason}",
        limit_applied=False,
    )
