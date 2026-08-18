"""驱动协议与值对象。

只 import 标准库——连 psycopg 都不 import。这保证协议层在没装任何数据库驱动包的
环境里也能 import 成功，registry 的惰性加载依赖这一点。
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class DriverError(Exception):
    """驱动层全部失败的共同基类。执行器用一个 except 兜住它。"""


class ConnectionFailed(DriverError):
    """连不上数据源。

    消息恒为通用文案：spec §4.4 要求 CONNECTION_ERROR 不回显地址端口。
    地址端口由调用方写进服务端日志，不经由异常传播。
    """

    def __init__(self) -> None:
        super().__init__("无法连接到数据库")


class QueryTimeout(DriverError):
    """超过语句超时。"""


class QueryCancelled(DriverError):
    """被 cancel() 掐掉。与超时分开：前者是用户主动，后者是策略生效。"""


class QueryFailed(DriverError):
    """库侧拒绝执行（语法错、权限不足、表不存在）。

    带上库的原始消息——这条会回显给分析师，他要靠它改 SQL。但**只在这一类**
    异常里带原文：连接类错误的原文可能含地址端口。
    """


@dataclass(frozen=True)
class ConnectionInfo:
    """连一个数据源所需的全部信息。

    由调用方从 Datasource 模型 + read_password() 组装。驱动不认识 ORM，
    所以这里是纯值对象。
    """

    kind: str
    host: str
    port: int
    database: str
    username: str
    password: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """恒掩码 password。

        无论 password 是不是 None 都打同样的 ***：形状不同就等于告诉读者
        「这个数据源没设密码」。
        """
        return (
            f"ConnectionInfo(kind={self.kind!r}, host={self.host!r}, port={self.port!r}, "
            f"database={self.database!r}, username={self.username!r}, "
            f"password='***', options={self.options!r})"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    data_type: str  # 库的原始类型名，原样保留（P2c 的注释 UI 要显示它）
    is_nullable: bool = True
    is_numeric: bool = False  # 前端选图要用（spec §2.3 的 result 事件）
    comment: str | None = None


@dataclass(frozen=True)
class TableSchema:
    name: str
    schema_name: str
    columns: tuple[ColumnSchema, ...] = ()
    comment: str | None = None


@dataclass(frozen=True)
class SchemaSnapshot:
    tables: tuple[TableSchema, ...] = ()


@dataclass(frozen=True)
class ProbeResult:
    reachable: bool
    server_version: str
    can_write: bool
    """账号是否具备写权限。true 时调用方要告警并把 is_readonly_verified 置 false
    （spec §4.3 闸 1），但**不阻止保存**。"""


@dataclass(frozen=True)
class QueryHandle:
    """取消一条正在跑的查询所需的全部信息。

    token 的含义各库不同：ClickHouse 是自己生成的 query_id、Postgres 是 backend pid、
    MySQL 是 connection id。取消**必须另开一条连接**发出——原连接正被查询占住。
    """

    token: str


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[ColumnSchema, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    truncated: bool


def truncate(
    rows: tuple[tuple[Any, ...], ...], max_rows: int
) -> tuple[tuple[tuple[Any, ...], ...], bool]:
    """截到 max_rows 并报告是否发生了截断。

    调用方必须取 max_rows + 1 行再交给这里：靠 len(rows) == max_rows 判断会在
    结果恰好等于上限时误报「已截断」，而那会让用户以为还有更多数据。
    """
    if len(rows) > max_rows:
        return rows[:max_rows], True
    return rows, False


class Driver(Protocol):
    """一个外部数据库的驱动。

    实现放 drivers/<kind>.py，各自 ≤200 行（spec §1.4）。
    所有方法都是同步阻塞的——异步化由调用方用线程池处理（P3 的执行器），
    因为三个库的 DBAPI 里只有一个有靠得住的 asyncio 支持，在这一层假装统一
    只会让取消语义更难推理。
    """

    kind: str
    default_port: int

    def probe(self, info: ConnectionInfo) -> ProbeResult:
        """连通性 + 版本 + 账号是否可写。探测必须是只读的——不能真去建表。"""
        ...

    def reflect(self, info: ConnectionInfo) -> SchemaSnapshot:
        """拉取表结构。P2c 的 schema_cache 存的就是它的输出。"""
        ...

    def execute(
        self,
        info: ConnectionInfo,
        sql: str,
        *,
        timeout_seconds: int,
        max_rows: int,
        on_start: Callable[[QueryHandle], None] | None = None,
    ) -> QueryResult:
        """跑一条**已被 guard 批准**的语句。

        这里不做任何 SQL 检查：闸 2（AST 校验）与闸 3（LIMIT 注入）在 guard，
        重复校验只会让人以为驱动也是一道防线，从而放松那一道。

        on_start 在语句真正下发**之前**被调用，把 QueryHandle 交给调用方——
        这是取消能力的唯一入口。回调抛异常视为放弃执行。
        """
        ...

    def cancel(self, info: ConnectionInfo, handle: QueryHandle) -> None:
        """取消 handle 对应的查询。另开连接发出，幂等：查询已结束时静默返回。"""
        ...
