"""驱动契约测的夹具。

与应用库测试**规则相反**：这里允许 skip（spec §5.1），因为 MySQL/ClickHouse 需要
Docker 起真库。但 skip 必须被计数上报——上一层 conftest.py 的
pytest_terminal_summary 负责打印。别照抄那边 pytest.fail 的写法。
"""

import os
import uuid
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import pytest

from chatbi.datasources.drivers.base import ConnectionInfo

# kind → 提供 DSN 的环境变量名
DSN_ENV = {
    "postgres": "CHATBI_TEST_PG_DSN",
    "mysql": "CHATBI_TEST_MYSQL_DSN",
    "clickhouse": "CHATBI_TEST_CLICKHOUSE_DSN",
}

# 参与契约测的 kind。Task 3 加 "mysql"、Task 4 加 "clickhouse"。
CONTRACT_KINDS: tuple[str, ...] = ("postgres", "mysql", "clickhouse")


@dataclass(frozen=True)
class Dialect:
    """同一套契约在三个引擎上的语法差异。

    只放**测试需要**的差异，不放驱动实现的差异——后者属于它自己的文件。
    """

    sleep_sql: str
    """一条会跑很久的语句，用来测超时与取消。必须能被语句超时打断。"""

    rows_sql: str
    """生成 N 行的语句，带一个 {n} 占位符。用来测行截断。"""

    create_table_sql: str
    """建一张固定形状的表：id 整数非空、label 文本可空、amount 数值。带 {table}。"""

    drop_table_sql: str
    """带 {table}。用 IF EXISTS，夹具的清理不能因为建表失败而连带报错。"""

    insert_row_sql: str
    """插一行，带 {table}。"""

    comment_column_sql: str
    """给 {table} 的 label 列加注释「标签注释」。带 {table}。

    MySQL 的 `modify column` 语义是**重写整个列定义**，所以它必须与
    create_table_sql 里 label 的类型逐字一致（varchar(64) null）。两处不同步会
    静默改掉列类型，让 test_reflect_describes_the_seeded_columns 转红——而那条
    测试的报错完全不会指向这里。改任何一处都要同时看另一处。
    """

    comment_table_sql: str
    """给 {table} 加表注释「契约测表」。带 {table}。"""


DIALECTS: dict[str, Dialect] = {
    "postgres": Dialect(
        sleep_sql="select pg_sleep(30)",
        rows_sql="select i from generate_series(1, {n}) as i",
        create_table_sql=(
            "create table {table} (id integer not null, label text, amount numeric(12, 2))"
        ),
        drop_table_sql="drop table if exists {table}",
        insert_row_sql="insert into {table} (id, label, amount) values (1, '甲', 12.34)",
        comment_column_sql="comment on column {table}.label is '标签注释'",
        comment_table_sql="comment on table {table} is '契约测表'",
    ),
    "mysql": Dialect(
        sleep_sql="select sleep(30)",
        # MySQL 没有 generate_series，用 8.0 的递归 CTE。默认
        # cte_max_recursion_depth = 1000，契约测只要 50 行，够。
        rows_sql=(
            "with recursive s(i) as ("
            "select 1 union all select i + 1 from s where i < {n}) select i from s"
        ),
        create_table_sql=(
            "create table {table} (id int not null, label varchar(64) null, amount decimal(12, 2))"
        ),
        drop_table_sql="drop table if exists {table}",
        insert_row_sql="insert into {table} (id, label, amount) values (1, '甲', 12.34)",
        # 类型必须与上面 create_table_sql 的 label 一致——modify column 会重写整个列定义
        comment_column_sql=(
            "alter table {table} modify column label varchar(64) null comment '标签注释'"
        ),
        comment_table_sql="alter table {table} comment = '契约测表'",
    ),
    "clickhouse": Dialect(
        # sleep() 单次上限 3 秒，用 sleepEachRow 累加出 30 秒
        sleep_sql="select sleepEachRow(1) from numbers(30)",
        rows_sql="select number from numbers({n})",
        # 必须带 ENGINE 与 ORDER BY，MergeTree 是最通用的选择
        create_table_sql=(
            "create table {table} ("
            "id Int32, label Nullable(String), amount Decimal(12, 2)) "
            "engine = MergeTree order by id"
        ),
        drop_table_sql="drop table if exists {table}",
        insert_row_sql="insert into {table} (id, label, amount) values (1, '甲', 12.34)",
        comment_column_sql="alter table {table} comment column label '标签注释'",
        comment_table_sql="alter table {table} modify comment '契约测表'",
    ),
}


def _info_from_dsn(kind: str, dsn: str) -> ConnectionInfo:
    """把 DSN 解析成 ConnectionInfo。

    自己解析而不是把 DSN 直接交给驱动：驱动的输入契约是 ConnectionInfo，
    让测试走一条「和生产不同的入口」等于没测生产那条路。
    """
    parsed = urlparse(dsn)
    if parsed.hostname is None or parsed.port is None:
        raise ValueError(f"{DSN_ENV[kind]} 必须形如 scheme://user:pw@host:port/db，收到 {dsn!r}")
    return ConnectionInfo(
        kind=kind,
        host=parsed.hostname,
        port=parsed.port,
        database=parsed.path.lstrip("/"),
        username=unquote(parsed.username or ""),
        password=unquote(parsed.password) if parsed.password else None,
    )


@pytest.fixture(params=CONTRACT_KINDS)
def driver_target(request) -> tuple[object, ConnectionInfo, Dialect]:
    """(driver, info, dialect)。缺 DSN 就 skip，理由里带上环境变量名。

    skip 理由必须写清「设哪个变量能让它跑起来」——只写「no database」的 skip
    会被当成环境问题忽略掉，那就是 v1 的老路。
    """
    from chatbi.datasources.registry import get_driver

    kind = request.param
    env = DSN_ENV[kind]
    dsn = os.environ.get(env)
    if not dsn:
        pytest.skip(f"{env} 未设置，跳过 {kind} 驱动契约测（设置它即可真跑）")
    return get_driver(kind), _info_from_dsn(kind, dsn), DIALECTS[kind]


@pytest.fixture
def seeded_table(driver_target) -> str:
    """建一张固定形状的表，测试结束删掉。返回表名。

    表名带随机后缀：契约测会对同一个库跑多个 kind（将来），共用表名会互删。
    用 uuid 而不是测试名——测试名里的参数化后缀含中括号，不是合法标识符。

    注意这里用 execute() 跑 DDL：execute() 刻意不做 SQL 检查（闸 2 在 guard，
    属 P3），所以这是可行的，而且顺带证明了「驱动本身不是一道防线」这个设计事实。
    """
    driver, info, dialect = driver_target
    table = f"chatbi_contract_{uuid.uuid4().hex[:12]}"
    driver.execute(
        info, dialect.create_table_sql.format(table=table), timeout_seconds=30, max_rows=1
    )
    driver.execute(
        info, dialect.insert_row_sql.format(table=table), timeout_seconds=30, max_rows=1
    )
    try:
        yield table
    finally:
        driver.execute(
            info, dialect.drop_table_sql.format(table=table), timeout_seconds=30, max_rows=1
        )


@pytest.fixture
def commented_table(driver_target, seeded_table) -> str:
    """在 seeded_table 上补一条列注释与一条表注释，返回表名。

    单独一个夹具而不是把注释塞进 seeded_table：只有一条测试需要注释，而 MySQL
    那条语句要重写整个列定义（见 Dialect.comment_column_sql 的注释）。让 12 条用
    seeded_table 的测试都跑它，等于给它们引入一份与自己无关的风险。
    """
    driver, info, dialect = driver_target
    for template in (dialect.comment_column_sql, dialect.comment_table_sql):
        driver.execute(info, template.format(table=seeded_table), timeout_seconds=30, max_rows=1)
    return seeded_table
