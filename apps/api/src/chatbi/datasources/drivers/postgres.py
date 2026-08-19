"""Postgres 驱动。

两条不显然的地方，改之前先读注释：
1. 超时与取消在 Postgres 里是**同一个 SQLSTATE(57014)**，只有消息文本不同，
   而消息受 lc_messages 影响。这里用耗时判断来区分，不匹配字符串。
2. 类型名有两套拼法：information_schema 给 "integer"，游标描述给 "int4"。
   _NUMERIC_TYPES 同时收了两套，别只留一套。

每次调用开一条新连接。V2-1 不做连接池：池化会让「取消」的语义复杂得多
（要保证 kill 的是本次查询占的那条连接），而私有化部署的并发量不需要池。
"""

import time
from collections.abc import Callable

import psycopg

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

# 两套拼法都要在：information_schema.columns.data_type 与 pg_type.typname
_NUMERIC_TYPES = frozenset(
    {
        "smallint",
        "integer",
        "bigint",
        "numeric",
        "decimal",
        "real",
        "double precision",
        "int2",
        "int4",
        "int8",
        "float4",
        "float8",
    }
)

# 注释在 pg_description 里，information_schema.columns **没有注释列**——这是本文件
# 到 P2c 才被发现的缺陷的根因。改回 information_schema 就会把注释丢掉。
#
# 类型名用 atttypid::regtype::text，**不要**用 format_type(atttypid, atttypmod)：后者
# 对 numeric(12,2) 返回带精度的 'numeric(12,2)'，它不在 _NUMERIC_TYPES 里，会把
# is_numeric 静默变成 False（前端据此选图，坏掉的方式是「图表选项里少了一列」，
# 不报错）。已实测 regtype 与原先 information_schema.data_type 在 integer / text /
# numeric / timestamptz 上逐一相同，所以这次换 SQL 不改变 data_type 的既有语义。
#
# attnum > 0 排除系统列（ctid 等），not attisdropped 排除已 DROP 但物理仍在的列。
# 少任何一个，快照里都会出现库里看不到的列，而那些列会进 prompt。
_REFLECT_SQL = """
select n.nspname, c.relname, a.attname,
       a.atttypid::regtype::text as data_type,
       not a.attnotnull as is_nullable,
       col_description(c.oid, a.attnum) as column_comment,
       obj_description(c.oid, 'pg_class') as table_comment
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = c.oid
where c.relkind = 'r'
  and n.nspname not in ('pg_catalog', 'information_schema')
  and a.attnum > 0 and not a.attisdropped
order by n.nspname, c.relname, a.attnum
"""

# 只读地问权限，而不是试着建表。CREATE 与「任意现存表可 INSERT」都算可写：
# 只读账号的典型配置是 CONNECT + USAGE + SELECT，两者都拿不到。
_CAN_WRITE_SQL = """
select
  has_database_privilege(current_user, current_database(), 'CREATE')
  or coalesce(bool_or(has_table_privilege(current_user, c.oid, 'INSERT')), false)
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where c.relkind = 'r' and n.nspname not in ('pg_catalog', 'information_schema')
"""


class PostgresDriver:
    kind = "postgres"
    default_port = 5432

    def _connect(self, info: ConnectionInfo) -> psycopg.Connection:
        try:
            return psycopg.connect(
                host=info.host,
                port=info.port,
                dbname=info.database,
                user=info.username,
                password=info.password,
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                **info.options,
            )
        except psycopg.OperationalError as exc:
            # ConnectionFailed 的消息恒为通用文案（spec §4.4）。原始异常挂在
            # __cause__ 上，只会进服务端日志，不会进 HTTP 响应。
            raise ConnectionFailed() from exc

    def probe(self, info: ConnectionInfo) -> ProbeResult:
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute("select version()")
            version = str(cur.fetchone()[0])
            cur.execute(_CAN_WRITE_SQL)
            can_write = bool(cur.fetchone()[0])
        return ProbeResult(reachable=True, server_version=version, can_write=can_write)

    def reflect(self, info: ConnectionInfo) -> SchemaSnapshot:
        grouped: dict[tuple[str, str], list[ColumnSchema]] = {}
        table_comments: dict[tuple[str, str], str | None] = {}
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute(_REFLECT_SQL)
            for (
                schema_name,
                table_name,
                column_name,
                data_type,
                is_nullable,
                column_comment,
                table_comment,
            ) in cur.fetchall():
                key = (schema_name, table_name)
                # 每行都带同一张表的表注释，重复赋值无害；这样只需要一次查询
                table_comments[key] = table_comment
                grouped.setdefault(key, []).append(
                    ColumnSchema(
                        name=column_name,
                        data_type=data_type,
                        # SQL 里已经 `not a.attnotnull`，这里直接是 bool——不再是
                        # information_schema 那套 `== "YES"` 的字符串比较
                        is_nullable=is_nullable,
                        is_numeric=data_type in _NUMERIC_TYPES,
                        # col_description 对没有注释的列返回 NULL → None，正是要的
                        # 语义。不加 `or None`：那会掩盖「注释是空字符串」这种情况
                        comment=column_comment,
                    )
                )
        tables = tuple(
            TableSchema(
                name=table,
                schema_name=schema,
                columns=tuple(columns),
                comment=table_comments[(schema, table)],
            )
            for (schema, table), columns in sorted(grouped.items())
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
            # 库侧超时。客户端等够了就断开不算超时——查询会继续在对面跑。
            #
            # 用 set_config() 而不是 `set statement_timeout = %s`：SET 是**工具语句**，
            # 不接受绑定参数（会报 syntax error at "$1"）。set_config 是普通函数，
            # 可以绑参，因此不需要把数值拼进 SQL 字符串。第三个参数 false = 会话级。
            cur.execute(
                "select set_config('statement_timeout', %s, false)",
                (str(timeout_seconds * 1000),),
            )
            if on_start is not None:
                cur.execute("select pg_backend_pid()")
                on_start(QueryHandle(token=str(cur.fetchone()[0])))

            started = time.monotonic()
            try:
                cur.execute(sql)
            except psycopg.errors.QueryCanceled as exc:
                # 见文件头注释 1：靠耗时而不是消息文本区分两者。
                if time.monotonic() - started >= timeout_seconds:
                    raise QueryTimeout("查询超过语句超时") from exc
                raise QueryCancelled("查询已取消") from exc
            except psycopg.Error as exc:
                # 只有这一类异常带库的原文——分析师要靠它改 SQL（spec §2.6）
                raise QueryFailed(str(exc)) from exc

            if cur.description is None:
                # DDL / INSERT 之类没有结果集。契约测的 seeded_table 夹具走这条路。
                return QueryResult(columns=(), rows=(), row_count=0, truncated=False)

            fetched = tuple(tuple(row) for row in cur.fetchmany(max_rows + 1))
            rows, truncated = truncate(fetched, max_rows)
            columns = tuple(_column_from_description(item) for item in cur.description)
        return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)

    def cancel(self, info: ConnectionInfo, handle: QueryHandle) -> None:
        """另开一条连接发 pg_cancel_backend。

        幂等：backend 已经退出时它返回 false 而不报错，正是我们要的语义。
        """
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute("select pg_cancel_backend(%s)", (int(handle.token),))


def _column_from_description(item) -> ColumnSchema:
    """把游标描述里的 OID 翻成类型名。取不到就退回 OID 的字符串形式。"""
    type_info = psycopg.postgres.types.get(item.type_code)
    type_name = type_info.name if type_info is not None else str(item.type_code)
    return ColumnSchema(name=item.name, data_type=type_name, is_numeric=type_name in _NUMERIC_TYPES)
