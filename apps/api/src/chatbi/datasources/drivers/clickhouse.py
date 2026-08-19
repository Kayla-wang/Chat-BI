"""ClickHouse 驱动。

与前两个驱动的四处差别：
1. `sleep()` 单次上限 3 秒——`select sleep(30)` 会直接报错而不是睡 30 秒。
   契约测用 `sleepEachRow(1) from numbers(30)`。
2. 类型名必须**前缀匹配**，不能集合匹配：`Decimal(12, 2)`、`Nullable(Int32)`、
   `LowCardinality(String)` 都是复合写法。
3. 可空性写在类型里（`Nullable(T)`），没有单独的 is_nullable 列。
4. `query_id` 由客户端生成——这反而是三个库里最干净的取消：不用先问库拿
   pid/connection_id，自己造一个 id 就能 KILL QUERY WHERE query_id = ...。
"""

import uuid
from collections.abc import Callable

import clickhouse_connect
from clickhouse_connect.driver.exceptions import ClickHouseError, OperationalError

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
# 服务端错误码：超时与被杀各有其一，不用猜消息也不用看耗时
_TIMEOUT_EXCEEDED = 159
_QUERY_WAS_CANCELLED = 394

# 前缀匹配用。剥掉 Nullable(...) / LowCardinality(...) 之后再比这些前缀。
_NUMERIC_PREFIXES = ("Int", "UInt", "Float", "Decimal")
_WRAPPERS = ("Nullable(", "LowCardinality(")

# 只读地问权限。system.grants 是视图，查它不产生任何写入。
#
# 注意：这条在 default 这类内置全权限用户上**可能返回 0**——ClickHouse 不一定为
# 它们留显式 grant 记录。门禁任务（下游那份 Task 7 Step 4）要先手工核实
# `select * from system.grants where user_name = currentUser()` 再决定是否改写。
# 取舍方向：宁可误报「账号可写」，也不能误报「已验证只读」——后者会让用户以为
# 自己安全（spec §4.3 闸 1）。
_CAN_WRITE_SQL = """
select toUInt8(count() > 0) from system.grants
where user_name = currentUser()
  and access_type in ('INSERT', 'ALTER', 'CREATE TABLE', 'DROP TABLE', 'TRUNCATE')
"""


def _unwrap(type_name: str) -> tuple[str, bool]:
    """剥掉包装类型，返回 (内层类型名, 是否可空)。

    ClickHouse 把可空性写在类型里而不是单独一列，而包装可以嵌套
    （LowCardinality(Nullable(String)) 是合法的），所以要循环剥。
    """
    nullable = False
    current = type_name.strip()
    while True:
        for wrapper in _WRAPPERS:
            if current.startswith(wrapper) and current.endswith(")"):
                nullable = nullable or wrapper == "Nullable("
                current = current[len(wrapper) : -1].strip()
                break
        else:
            return current, nullable


def _is_numeric(type_name: str) -> bool:
    inner, _ = _unwrap(type_name)
    return inner.startswith(_NUMERIC_PREFIXES)


class ClickHouseDriver:
    kind = "clickhouse"
    default_port = 8123

    def _client(self, info: ConnectionInfo, **settings):
        try:
            return clickhouse_connect.get_client(
                host=info.host,
                port=info.port,
                database=info.database or "default",
                username=info.username or "default",
                password=info.password or "",
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                settings=settings or None,
                **info.options,
            )
        except (OperationalError, OSError) as exc:
            raise ConnectionFailed() from exc

    def probe(self, info: ConnectionInfo) -> ProbeResult:
        client = self._client(info)
        try:
            version = str(client.command("select version()"))
            can_write = bool(int(client.command(_CAN_WRITE_SQL)))
        except ClickHouseError as exc:
            raise ConnectionFailed() from exc
        finally:
            client.close()
        return ProbeResult(reachable=True, server_version=version, can_write=can_write)

    def reflect(self, info: ConnectionInfo) -> SchemaSnapshot:
        client = self._client(info)
        try:
            result = client.query(
                "select table, name, type, comment from system.columns "
                "where database = currentDatabase() order by table, position"
            )
            rows = result.result_rows
            # 表注释不在 system.columns 里，只能另查一次。两条查询之间理论上可以有
            # 并发建表，所以下面用 .get() 而不是 []——拿不到表注释不该让整个
            # reflect() 抛 KeyError
            table_rows = client.query(
                "select name, comment from system.tables where database = currentDatabase()"
            ).result_rows
        finally:
            client.close()

        # ClickHouse 对「没有注释」返回空字符串而不是 NULL
        table_comments = {name: comment or None for name, comment in table_rows}
        grouped: dict[str, list[ColumnSchema]] = {}
        for table_name, column_name, type_name, comment in rows:
            _, nullable = _unwrap(type_name)
            grouped.setdefault(table_name, []).append(
                ColumnSchema(
                    name=column_name,
                    data_type=type_name,  # 原样保留复合写法，P2c 的 UI 要显示它
                    is_nullable=nullable,
                    is_numeric=_is_numeric(type_name),
                    comment=comment or None,
                )
            )
        tables = tuple(
            TableSchema(
                name=table,
                schema_name=info.database,
                columns=tuple(columns),
                comment=table_comments.get(table),
            )
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
        # query_id 自己生成——三个库里最干净的取消，不用先问库拿 pid
        query_id = f"chatbi-{uuid.uuid4().hex}"
        client = self._client(
            info, max_execution_time=timeout_seconds, max_result_rows=max_rows + 1
        )
        if on_start is not None:
            on_start(QueryHandle(token=query_id))
        try:
            result = client.query(sql, settings={"query_id": query_id})
        except ClickHouseError as exc:
            code = getattr(exc, "code", None)
            if code == _TIMEOUT_EXCEEDED:
                raise QueryTimeout("查询超过语句超时") from exc
            if code == _QUERY_WAS_CANCELLED:
                raise QueryCancelled("查询已取消") from exc
            raise QueryFailed(str(exc)) from exc
        finally:
            client.close()

        if not result.column_names:
            return QueryResult(columns=(), rows=(), row_count=0, truncated=False)
        fetched = tuple(tuple(row) for row in result.result_rows)
        rows, truncated = truncate(fetched, max_rows)
        columns = tuple(
            ColumnSchema(name=name, data_type=str(type_name), is_numeric=_is_numeric(str(type_name)))
            for name, type_name in zip(result.column_names, result.column_types, strict=True)
        )
        return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)

    def cancel(self, info: ConnectionInfo, handle: QueryHandle) -> None:
        """KILL QUERY 是异步的：它只标记，不等查询真的停下。

        契约测的 worker.join(timeout=20) 给了足够余量。幂等：没有匹配的 query_id
        时 ClickHouse 返回空结果集而不报错。
        """
        client = self._client(info)
        try:
            client.command(
                "kill query where query_id = %(qid)s", parameters={"qid": handle.token}
            )
        finally:
            client.close()
