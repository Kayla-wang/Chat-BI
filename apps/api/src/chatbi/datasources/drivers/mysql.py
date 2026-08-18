"""MySQL 驱动。

与 Postgres 的三处差别：
1. 超时与被杀有**不同的 errno**（3024 / 1317），不需要 Postgres 那个耗时启发式。
2. `max_execution_time` **只对只读 SELECT 生效**。这对生产路径没问题——能到执行器的
   语句都已过 guard 的 SELECT-only 校验；但契约测里的 DDL 不受它约束，别因此
   以为超时没设上。
3. `autocommit=True`：MySQL 的 DDL 隐式提交，而 INSERT 不会。驱动是读多写无的，
   开着 autocommit 比在每条路径上记得 commit 可靠。
"""

from collections.abc import Callable

import pymysql

from chatbi.datasources.drivers.base import (
    ColumnSchema,
    ConnectionFailed,
    ConnectionInfo,
    ProbeResult,
    QueryCancelled,
    QueryFailed,
    QueryHandle,
    QueryResult,
    QueryTimeout,
    SchemaSnapshot,
    TableSchema,
    truncate,
)

_CONNECT_TIMEOUT_SECONDS = 10
_ER_QUERY_INTERRUPTED = 1317
_ER_QUERY_TIMEOUT = 3024
_ER_NO_SUCH_THREAD = 1094

_NUMERIC_TYPES = frozenset(
    {
        "tinyint",
        "smallint",
        "mediumint",
        "int",
        "integer",
        "bigint",
        "decimal",
        "numeric",
        "float",
        "double",
        "real",
        "bit",
    }
)

# 只看当前库。information_schema 里别的库的表不属于这个数据源的可见范围。
_REFLECT_SQL = """
select c.table_name, c.column_name, c.data_type, c.is_nullable, c.column_comment
from information_schema.columns c
join information_schema.tables t
  on t.table_schema = c.table_schema and t.table_name = c.table_name
where c.table_schema = database() and t.table_type = 'BASE TABLE'
order by c.table_name, c.ordinal_position
"""

# 只读地问权限——information_schema 的这两个都是视图，查它们不产生任何写入。
#
# grantee 存的是 'root'@'%' 这种**带引号**的形式，而 current_user() 返回 root@%，
# 所以要把引号补回去再比。不补的话永远匹配不上，can_write 恒为 false——那正是
# 「探测看起来对但其实恒返回一个值」的形状。
_CAN_WRITE_SQL = """
select
  exists (
    select 1 from information_schema.user_privileges
    where grantee = concat('''', replace(current_user(), '@', '''@'''), '''')
      and privilege_type in ('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER')
  )
  or exists (
    select 1 from information_schema.schema_privileges
    where table_schema = database()
      and privilege_type in ('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER')
  )
"""


class MySQLDriver:
    kind = "mysql"
    default_port = 3306

    def _connect(self, info: ConnectionInfo):
        try:
            return pymysql.connect(
                host=info.host,
                port=info.port,
                database=info.database,
                user=info.username,
                password=info.password or "",
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                # utf8mb4 而不是 utf8：后者在 MySQL 里是三字节残废编码，存不了 emoji
                charset="utf8mb4",
                autocommit=True,
                **info.options,
            )
        except pymysql.err.OperationalError as exc:
            raise ConnectionFailed() from exc

    def probe(self, info: ConnectionInfo) -> ProbeResult:
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute("select version()")
            version = str(cur.fetchone()[0])
            cur.execute(_CAN_WRITE_SQL)
            can_write = bool(cur.fetchone()[0])
        return ProbeResult(reachable=True, server_version=version, can_write=can_write)

    def reflect(self, info: ConnectionInfo) -> SchemaSnapshot:
        grouped: dict[str, list[ColumnSchema]] = {}
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute(_REFLECT_SQL)
            for table_name, column_name, data_type, is_nullable, comment in cur.fetchall():
                grouped.setdefault(table_name, []).append(
                    ColumnSchema(
                        name=column_name,
                        data_type=data_type,
                        is_nullable=is_nullable == "YES",
                        is_numeric=data_type in _NUMERIC_TYPES,
                        comment=comment or None,
                    )
                )
        tables = tuple(
            TableSchema(name=table, schema_name=info.database, columns=tuple(columns))
            for table, columns in sorted(grouped.items())
        )
        return SchemaSnapshot(tables=tables)

    def execute(
        self,
        info: ConnectionInfo,
        sql: str,
        *,
        timeout_seconds: int,
        max_rows: int,
        on_start: Callable[[QueryHandle], None] | None = None,
    ) -> QueryResult:
        with self._connect(info) as conn, conn.cursor() as cur:
            # 只对只读 SELECT 生效（见文件头注释 2）。单位是毫秒。
            cur.execute("set session max_execution_time = %s", (timeout_seconds * 1000,))
            if on_start is not None:
                cur.execute("select connection_id()")
                on_start(QueryHandle(token=str(cur.fetchone()[0])))

            try:
                cur.execute(sql)
            except pymysql.err.OperationalError as exc:
                # errno 直接区分，不猜消息、不看耗时
                code = exc.args[0] if exc.args else None
                if code == _ER_QUERY_TIMEOUT:
                    raise QueryTimeout("查询超过语句超时") from exc
                if code == _ER_QUERY_INTERRUPTED:
                    raise QueryCancelled("查询已取消") from exc
                raise QueryFailed(str(exc)) from exc
            except pymysql.Error as exc:
                raise QueryFailed(str(exc)) from exc

            if cur.description is None:
                return QueryResult(columns=(), rows=(), row_count=0, truncated=False)

            fetched = tuple(tuple(row) for row in cur.fetchmany(max_rows + 1))
            rows, truncated = truncate(fetched, max_rows)
            # data_type 是空串、is_numeric 恒 False：pymysql 的 description 只给
            # type_code 数字，翻名字要自己维护 FIELD_TYPE 映射表。这是一处**已知的
            # 不对等**（Postgres 驱动给了真类型名），前端选图该取 reflect() 还是
            # execute() 的输出由 P3 定；见 P2b 交接清单里那条缺口。
            columns = tuple(
                ColumnSchema(name=item[0], data_type="", is_numeric=False)
                for item in cur.description
            )
        return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)

    def cancel(self, info: ConnectionInfo, handle: QueryHandle) -> None:
        """`KILL QUERY <id>` 只掐当前语句，保留连接；`KILL CONNECTION` 会连坐。

        幂等：连接已不存在时 MySQL 报 errno 1094（unknown thread id），
        那不是错误，静默吞掉。
        """
        with self._connect(info) as conn, conn.cursor() as cur:
            try:
                cur.execute(f"kill query {int(handle.token)}")
            except pymysql.err.OperationalError as exc:
                if (exc.args[0] if exc.args else None) != _ER_NO_SUCH_THREAD:
                    raise
