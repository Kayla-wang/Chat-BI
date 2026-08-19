# Chat-BI V2-1 · P2c1 注释修复与两张表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让三个驱动的 `reflect()` 真的带出注释，并建好存快照与人工注释的两张表——把 P2c 后半（仓储 / 合并 / 端点）需要的两块地基铺好。

**Architecture:** 两个任务，互不依赖，但都必须在 P2c2 之前完成。Task 1 修驱动层：Postgres 的 `reflect()` 查的 `information_schema.columns` 没有注释列，改走 `pg_catalog` + `col_description` / `obj_description`；MySQL 与 ClickHouse 补各自缺的表注释；并加一条共用契约测钉住三个 kind。Task 2 建 `schema_cache` 与 `column_notes`——两张分开而不是一张，因为 refresh 整行覆盖快照，人工注释若在里面就会跟着丢。

**Tech Stack:** Python 3.12 · SQLAlchemy 2.x ORM · Alembic · pytest · psycopg 3 · ruff

**设计依据：** `docs/superpowers/specs/2026-08-19-chatbi-v2-1-p2c-metadata-design.md`（commit `9ca20ff`）的 §1、§2。本计划的每处取舍都在那份里有对应小节，行文里以「设计 §N」引用。上游 spec 是 `2026-08-11-chatbi-v2-1-design.md`。

**P2c 按体量拆成两份**（单份超 ~2000 行就该拆文件）。任务编号连续，跨文件说「Task N」不歧义：

| 份 | 任务 | 交付 |
|---|---|---|
| **本份** `p2c1` | Task 1–2 | `reflect()` 带出注释 · `schema_cache` + `column_notes` 两张表 |
| `...-p2c2-api.md` | Task 3–5 | `metadata.py` 持久化 · `schema_view.py` 合并与 `col_id` · 两个端点 + F-201 AC1 红线 |

做完本份后后端**一行 HTTP 元数据代码都没有**，这是有意的：这两个任务各自独立可验收，而它们的正确性不需要端点存在就能验（契约测对真库跑、migration 双向跑）。本份末尾的「交接清单」列出 p2c2 要消费的签名。

## Global Constraints

**不新增 Python 依赖。** 本份只用已装的 psycopg / SQLAlchemy / Pydantic。

**不需要 Docker、不需要 `CREATEROLE`。** 这是 P2c 被排在 P2b 两个人工前置之前的唯一理由。全部任务在本机原生 Postgres 上可完整验收。

**`schema_cache.payload` 里绝不存人工注释**（设计 §2.3）。`refresh` 整行覆盖 `payload`，注释若在里面就会跟着丢，而 F-201 AC1 要求两者并存。注释的真相源恒为 `column_notes` 表，合并只发生在读路径上——本份不写合并，但两张表分开的理由就是这一条，改表结构前先读它。

**不改驱动协议。** `base.py` 的 `ColumnSchema.comment` 与 `TableSchema.comment` 早就存在，Task 1 只是把它们填上。往协议加字段是 P3 的事，本份出现 `base.py` 的 diff 就说明走偏了。

**契约测允许 skip 但必须计数**（上游 spec §5.1）。`tests/drivers/` 之外的测试**一律不允许 skip**——没有应用库这个后端无功能可测，`conftest.py` 里是 `pytest.fail` 而不是 `pytest.skip`，别照抄 `tests/drivers/conftest.py` 那边的写法。

**每个任务的反向验证都要两个方向跑。** 只跑正向的覆盖测试会把误报写进结论——P1 实战踩过。每条反向验证都要明确写出「哪几条转红、哪几条必须保持绿」，两者都要核对。

**`ruff` 必须干净**（`uv run ruff check . && uv run ruff format --check .`），每个任务提交前跑。

## 本机环境

```bash
# apps/api 下，每个任务开工前 export 这四个
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
export CHATBI_TEST_PG_DSN=postgresql://chatbi:chatbi@localhost:5432/chatbi_test
```

- 原生 PostgreSQL 16 可用（`localhost:5432`，`chatbi`/`chatbi`，`chatbi` + `chatbi_test` 两库）。
- **`CHATBI_TEST_MYSQL_DSN` / `CHATBI_TEST_CLICKHOUSE_DSN` 不设**——本机无 Docker（WSL2 未装）。那两个 kind 的契约测继续 skip 并计数，这是预期状态。
- **起点基线：`190 passed` / `26 skipped`**（commit `637090f`）。开工前先跑一次确认，不符就先查环境再动代码。

## File Structure

### 本份创建的文件

| 文件 | 职责 | 任务 |
|---|---|---|
| `apps/api/migrations/versions/0004_schema_cache_column_notes.py` | 建 `schema_cache` 与 `column_notes` 两张表。不 import 任何 `chatbi.*` | 2 |
| `apps/api/tests/test_schema_metadata.py` | 本份只放两条建模层测试；p2c2 的 Task 3 往同一文件里加仓储测试 | 2 |

### 本份修改的文件

| 文件 | 改动 | 任务 |
|---|---|---|
| `apps/api/src/chatbi/datasources/drivers/postgres.py` | `_REFLECT_SQL` 换 `pg_catalog` + 填列注释与表注释 | 1 |
| `apps/api/src/chatbi/datasources/drivers/mysql.py` | `_REFLECT_SQL` 加 `table_comment` + 填表注释 | 1 |
| `apps/api/src/chatbi/datasources/drivers/clickhouse.py` | 加一条 `system.tables` 查询 + 填表注释 | 1 |
| `apps/api/tests/drivers/conftest.py` | `Dialect` 加 `comment_column_sql` / `comment_table_sql`，`DIALECTS` 三份填上，加 `commented_table` 夹具 | 1 |
| `apps/api/tests/drivers/test_driver_contract.py` | 加 `test_reflect_carries_comments` | 1 |
| `apps/api/src/chatbi/db/models.py` | 加 `SchemaCache`、`ColumnNote` 两个模型 | 2 |
| `apps/api/tests/test_migrations.py` | `TABLES` 加 `schema_cache`、`column_notes` | 2 |

### 本份不碰的东西

`metadata.py` / `schema_view.py` / `schema_router.py` 三个新模块、`schemas.py` 的四个响应模型、`errors.py` 的两个错误码、`routers.py` 的接缝——**全部在 p2c2**。本份只提供它们的地基：能带出注释的 `reflect()`，与两张空表。

**为什么不在本份顺手建 `metadata.py`**：那样 Task 2 就不再是「只动 schema」，它的验收标准会从「migration 双向跑通」变成「序列化也对」，两件事的失败原因混在一次评审里。切在这里是因为 migration 的正确性可以单独验完。

### 边界说明

`migration 0004` 不 import 任何 `chatbi.*`（与 0002、0003 一致），所以它跑得起来不需要主密钥、不需要 `Settings` 里的 LLM 配置——CI 只想验 schema 时能干净地跑。

`db/models.py` 里两个新模型**不定义 relationship**：`db` 是叶子模块（上游 spec §1.3 规则 4），联表由仓储显式写 select，不让 ORM 在属性访问时偷偷发查询。表级约束只写在 migration 里，与 `Datasource` 一致——模型的 `__table_args__` 根本不会被执行，写两份只会得到两份不同步的约束。

---

### Task 1: `reflect()` 带出注释（三个驱动 + 一条共用契约测）

注释是进 LLM prompt 的唯一业务语义来源（上游 spec §4.5）。Postgres 的 `reflect()` 现在对**每一列、每一张表**都返回 `comment=None`；MySQL 与 ClickHouse 带出了列注释但都**没有表注释**。三处一起补齐，并加一条共用契约测钉住。

不先做这个，后面四个任务全部是空壳：合并出来的 `comment` 永远是 `null`，F-201 AC1 的红线测试也测不出东西。

**Files:**
- Modify: `apps/api/src/chatbi/datasources/drivers/postgres.py`（`_REFLECT_SQL` + `reflect`）
- Modify: `apps/api/src/chatbi/datasources/drivers/mysql.py`（`_REFLECT_SQL` + `reflect`，只补表注释）
- Modify: `apps/api/src/chatbi/datasources/drivers/clickhouse.py`（`reflect`，只补表注释）
- Modify: `apps/api/tests/drivers/conftest.py`（`Dialect` 加两个字段 + `commented_table` 夹具）
- Test: `apps/api/tests/drivers/test_driver_contract.py`（加一条）

**Interfaces:**
- Consumes: `base.ColumnSchema.comment` / `base.TableSchema.comment`（P2b 已定义，**不改协议**）
- Produces: `reflect()` 返回的快照里 `ColumnSchema.comment` 与 `TableSchema.comment` 在库里有注释时非 `None`。任务 3/4/5 全都依赖这条。

- [ ] **Step 1: `Dialect` 加两个字段，三份方言各填上**

改 `apps/api/tests/drivers/conftest.py`。在 `Dialect` 的 `insert_row_sql` 之后加两个字段：

```python
    comment_column_sql: str
    """给 {table} 的 label 列加注释「标签注释」。带 {table}。

    MySQL 的 `modify column` 语义是**重写整个列定义**，所以它必须与
    create_table_sql 里 label 的类型逐字一致（varchar(64) null）。两处不同步
    会静默改掉列类型，让 test_reflect_describes_the_seeded_columns 转红——
    而那条测试的报错完全不会指向这里。改任何一处都要同时看另一处。
    """

    comment_table_sql: str
    """给 {table} 加表注释「契约测表」。带 {table}。"""
```

三份 `DIALECTS` 各加两行（放在各自的 `insert_row_sql` 之后）：

```python
    # postgres
        comment_column_sql="comment on column {table}.label is '标签注释'",
        comment_table_sql="comment on table {table} is '契约测表'",

    # mysql —— 类型必须与上面 create_table_sql 的 label 一致
        comment_column_sql=(
            "alter table {table} modify column label varchar(64) null comment '标签注释'"
        ),
        comment_table_sql="alter table {table} comment = '契约测表'",

    # clickhouse
        comment_column_sql="alter table {table} comment column label '标签注释'",
        comment_table_sql="alter table {table} modify comment '契约测表'",
```

同一个文件末尾加夹具：

```python
@pytest.fixture
def commented_table(driver_target, seeded_table) -> str:
    """在 seeded_table 上补一条列注释与一条表注释，返回表名。

    单独一个夹具而不是把注释塞进 seeded_table：只有一条测试需要注释，而 MySQL
    那条语句要重写整个列定义（见 Dialect.comment_column_sql 的注释）。让 12 条
    用 seeded_table 的测试都跑它，等于给它们引入一份与自己无关的风险。
    """
    driver, info, dialect = driver_target
    for template in (dialect.comment_column_sql, dialect.comment_table_sql):
        driver.execute(
            info, template.format(table=seeded_table), timeout_seconds=30, max_rows=1
        )
    return seeded_table
```

- [ ] **Step 2: 写失败的契约测**

加进 `apps/api/tests/drivers/test_driver_contract.py`，位置紧跟 `test_reflect_describes_the_seeded_columns`：

```python
def test_reflect_carries_comments(driver_target, commented_table) -> None:
    """注释是进 LLM prompt 的唯一业务语义来源（spec §4.5），也是 F-201 的全部内容。

    这条测试的存在本身是一次教训：Postgres 的 reflect() 对每一列都返回 None
    （它查的 information_schema.columns 根本没有注释列），而 13 条契约测里没有
    任何一条断言注释，所以这个缺陷活到了 P2c。
    """
    driver, info, _ = driver_target

    table = next(t for t in driver.reflect(info).tables if t.name == commented_table)
    columns = {column.name: column for column in table.columns}

    assert columns["label"].comment == "标签注释"
    assert table.comment == "契约测表"
    # 没写注释的列必须是 None 而不是 ""：None 表示「库里没写」，空字符串会在
    # prompt 里出现一个空注释行，也会让前端分不清「没写」和「写了个空的」
    assert columns["id"].comment is None
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd apps/api
uv run pytest tests/drivers/test_driver_contract.py::test_reflect_carries_comments -v
```

预期：**postgres 那条 FAIL**（`assert None == '标签注释'`），mysql / clickhouse 两条 SKIP（无 DSN）。

失败信息若是 `fixture 'commented_table' not found`，说明 Step 1 的夹具没加进 `tests/drivers/conftest.py`（不是外层 `tests/conftest.py`）。

- [ ] **Step 4: 改 `postgres.py`**

`_REFLECT_SQL` 整条替换：

```python
# 注释在 pg_description 里，information_schema.columns **没有注释列**——这是
# 本文件到 P2c 才被发现的缺陷的根因。改回 information_schema 就会把注释丢掉。
#
# 类型名用 atttypid::regtype::text，**不要**用 format_type(atttypid, atttypmod)：
# 后者对 numeric(12,2) 返回带精度的 'numeric(12,2)'，它不在 _NUMERIC_TYPES 里，
# 会把 is_numeric 静默变成 False（前端据此选图，坏掉的方式是「图表选项里少了
# 一列」，不报错）。已实测 regtype 与原先 information_schema.data_type 在
# integer / text / numeric / timestamptz 上逐一相同，所以这次换 SQL 不改变
# data_type 的既有语义。
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
```

`a.attnum > 0 and not a.attisdropped` 两个条件都必要：前者排除系统列（`ctid` 等），后者排除已 DROP 但物理仍在的列。少任何一个，快照里都会出现库里看不到的列，而那些列会进 prompt。

`reflect()` 整个方法替换（现在要同时收集列与表注释）：

```python
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
                        is_nullable=is_nullable,
                        is_numeric=data_type in _NUMERIC_TYPES,
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
```

`is_nullable` 现在直接是 `bool`（SQL 里已经 `not a.attnotnull`），**不再**是 `is_nullable == "YES"` 的字符串比较——那是 `information_schema` 的形状。忘了改这一处会让每一列都变成 `is_nullable=False`（非空字符串 `"YES"` 与 `True` 比较…… 实际上 `True == "YES"` 是 `False`，所以全部列变成非空），`test_reflect_describes_the_seeded_columns` 会转红并指向 `label`。

`col_description` 对没有注释的列返回 SQL `NULL` → psycopg 给 `None`，正是要的语义，**不需要** `or None`（加了也无害，但会掩盖「空字符串注释」这种真实存在的情况）。

- [ ] **Step 5: 给 `mysql.py` 与 `clickhouse.py` 补表注释**

两个驱动的列注释本来就是对的，只缺表注释。**这一步在本机验不了**（无 Docker），但契约测那条 `assert table.comment == "契约测表"` 对三个 kind 都会跑——不改就是在门禁那天埋两条红。本步末尾有门禁验证清单。

`mysql.py` 的 `_REFLECT_SQL` 加一列：

```python
_REFLECT_SQL = """
select c.table_name, c.column_name, c.data_type, c.is_nullable, c.column_comment,
       t.table_comment
from information_schema.columns c
join information_schema.tables t
  on t.table_schema = c.table_schema and t.table_name = c.table_name
where c.table_schema = database() and t.table_type = 'BASE TABLE'
order by c.table_name, c.ordinal_position
"""
```

`mysql.py` 的 `reflect()`：

```python
    def reflect(self, info: ConnectionInfo) -> SchemaSnapshot:
        grouped: dict[str, list[ColumnSchema]] = {}
        table_comments: dict[str, str | None] = {}
        with self._connect(info) as conn, conn.cursor() as cur:
            cur.execute(_REFLECT_SQL)
            for (
                table_name,
                column_name,
                data_type,
                is_nullable,
                comment,
                table_comment,
            ) in cur.fetchall():
                # MySQL 对「没有注释」返回空字符串而不是 NULL，列和表都是。
                # 不 or None 的话每张表都会得到一个 "" 注释，进 prompt 就是一行空注释。
                table_comments[table_name] = table_comment or None
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
            TableSchema(
                name=table,
                schema_name=info.database,
                columns=tuple(columns),
                comment=table_comments[table],
            )
            for table, columns in sorted(grouped.items())
        )
        return SchemaSnapshot(tables=tables)
```

`clickhouse.py` 的 `reflect()`——表注释在 `system.tables`，要第二条查询：

```python
    def reflect(self, info: ConnectionInfo) -> SchemaSnapshot:
        client = self._client(info)
        try:
            rows = client.query(
                "select table, name, type, comment from system.columns "
                "where database = currentDatabase() order by table, position"
            ).result_rows
            # 表注释不在 system.columns 里，只能另查一次。两条查询之间理论上
            # 可以有并发建表，所以下面用 .get() 而不是 []——拿不到表注释不该让
            # 整个 reflect() 抛 KeyError。
            table_rows = client.query(
                "select name, comment from system.tables where database = currentDatabase()"
            ).result_rows
        finally:
            client.close()

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
```

**门禁那天（P2b Task 7）要对这两个 kind 单独核的三条**——写进 P2b 那份计划的 Task 7 Step 5、6：

1. `uv run pytest tests/drivers -k "reflect and mysql" -v` 与 `-k "reflect and clickhouse" -v` 各三条全绿。
2. MySQL 的 `comment_column_sql` 真的没改掉列类型：同一次跑里 `test_reflect_describes_the_seeded_columns` 必须仍绿（它断言 `label.is_nullable is True` 与 `is_numeric is False`）。
3. ClickHouse 的 `alter table ... modify comment` 在 24.8 上受支持；若报语法错，退回 `alter table {table} modify comment '契约测表'` 的替代写法 `alter table {table} comment '契约测表'` 前，先跑 `select comment from system.tables where name = '<表名>'` 确认注释到底有没有写进去——改测试语句之前要先知道是语法问题还是读取问题。

- [ ] **Step 6: 跑测试确认通过**

```bash
uv run pytest -q
```

预期：**191 passed / 28 skipped**。末尾那行应是 `skip 合计 28，其中驱动契约测 28`。

skip 从 26 变 28 是**预期的**：新增那条契约测在 MySQL / ClickHouse 上各 skip 一条（14 条 × 2 个无 DSN 的 kind）。实测不是 191/28 就停下核对，别改断言凑数。

- [ ] **Step 7: 反向验证四条（每条都要两个方向看）**

1. `col_description(c.oid, a.attnum)` 换成 `null` → `test_reflect_carries_comments` 的 **`columns["label"].comment` 那一行** FAIL，而 `test_reflect_describes_the_seeded_columns` **必须保持绿**。后半条同等重要：它证明两条测试测的是不同的东西，删掉新那条不会被老那条兜住。
2. `a.atttypid::regtype::text` 换成 `format_type(a.atttypid, a.atttypmod)` → `test_reflect_describes_the_seeded_columns` 的 `columns["amount"].is_numeric` FAIL，而 `test_reflect_carries_comments` **保持绿**。这条既验证了 Step 4 注释里那张对照表不是纸上推理，也暴露一件事：注释那条测试守不住类型名，两条都得有。
3. `not a.attnotnull` 换成 `a.attnotnull` → `test_reflect_describes_the_seeded_columns` 的 `is_nullable` 两行 FAIL。
4. `obj_description(c.oid, 'pg_class')` 换成 `null` → `test_reflect_carries_comments` 的 **`table.comment` 那一行** FAIL，而**同一条测试里** `columns["label"].comment` 那一行仍然通得过。这条的观察点是**断言行号**而不是「哪条测试红了」——两个断言在同一条测试里，只看红/绿区分不出列注释和表注释谁坏了。跑的时候用 `-x` 看报错行号。

- [ ] **Step 8: ruff + 提交**

```bash
uv run ruff check . && uv run ruff format --check .
git add src/chatbi/datasources/drivers/postgres.py \
        src/chatbi/datasources/drivers/mysql.py \
        src/chatbi/datasources/drivers/clickhouse.py \
        tests/drivers/conftest.py tests/drivers/test_driver_contract.py
git commit -m "fix(drivers): reflect() 带出列注释与表注释

Postgres 的 reflect() 对每一列、每一张表都返回 comment=None——它查的
information_schema.columns 没有注释列，注释在 pg_description 里。改走
pg_catalog + col_description/obj_description。MySQL 与 ClickHouse 的列
注释本来是对的，补上各自缺的表注释。

类型名用 atttypid::regtype::text 而不是 format_type()：后者对
numeric(12,2) 带精度，不在 _NUMERIC_TYPES 里，会把 is_numeric 静默
变成 False。已实测 regtype 与原先 information_schema.data_type 逐一相同。

加一条共用契约测 test_reflect_carries_comments 钉住三个 kind。这个缺陷
能活到 P2c，就是因为 13 条契约测没有一条断言注释。契约测因此变 14 条
× 3 kind：本机 skip 基线 26 → 28，门禁目标 39 → 42。"
```





---

### Task 2: `schema_cache` 与 `column_notes` 两张表（migration 0004）

**Files:**
- Create: `apps/api/migrations/versions/0004_schema_cache_column_notes.py`
- Modify: `apps/api/src/chatbi/db/models.py`（加两个模型）
- Modify: `apps/api/tests/test_migrations.py`（`TABLES` 加两张）
- Test: `apps/api/tests/test_schema_metadata.py`（本任务只放两条建模层测试，任务 3 往同一文件里加）

**Interfaces:**
- Consumes: `datasources.id`、`users.id`（P2a 已有）
- Produces:
  ```python
  db.models.SchemaCache   # datasource_id(pk) / fetched_at / payload
  db.models.ColumnNote    # id(pk) / datasource_id / schema_name / table_name /
                          # column_name / note / updated_by / updated_at
  ```
  任务 3 的 `metadata.py` 直接用这两个模型。

- [ ] **Step 1: 写失败的测试**

新建 `apps/api/tests/test_schema_metadata.py`：

```python
"""schema_cache 与 column_notes 的建模层与仓储层。

任务 2 只有下面两条建模测试；任务 3 往同一文件里加 metadata.py 的仓储测试。
不过 HTTP——这两张表的约束与序列化都是领域层的事（spec §1.3 规则 2）。
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from chatbi.db.models import ColumnNote, SchemaCache


def test_deleting_a_datasource_takes_its_cache_and_notes(
    db_session, make_datasource, make_user
) -> None:
    """两张表都 CASCADE：缓存与注释脱离数据源都没有意义。

    写成 RESTRICT 的话删数据源会 500，而那个 500 出现在 P2a 的 DELETE 端点上，
    报错完全不指向本任务。
    """
    datasource = make_datasource()
    author = make_user()
    db_session.add(
        SchemaCache(
            datasource_id=datasource.id,
            fetched_at=sa.func.now(),
            payload={"tables": []},
        )
    )
    db_session.add(
        ColumnNote(
            id=uuid.uuid4(),
            datasource_id=datasource.id,
            schema_name="public",
            table_name="orders",
            column_name="amount",
            note="含税金额",
            updated_by=author.id,
        )
    )
    db_session.flush()

    db_session.delete(datasource)
    db_session.flush()

    assert db_session.get(SchemaCache, datasource.id) is None
    assert db_session.scalar(sa.select(sa.func.count()).select_from(ColumnNote)) == 0


def test_the_same_table_name_in_two_schemas_can_both_have_notes(
    db_session, make_datasource, make_user
) -> None:
    """唯一键必须含 schema_name（设计 §2.1，对 spec §2.5 的有意偏离）。

    照 spec 写成三列键的话，第二条 insert 会撞唯一约束——而真实后果不是报错，
    是「注释静默挂到另一个 schema 的同名列上」，界面上完全看不出来。
    """
    datasource = make_datasource()
    author = make_user()

    def _note(schema_name: str) -> ColumnNote:
        return ColumnNote(
            id=uuid.uuid4(),
            datasource_id=datasource.id,
            schema_name=schema_name,
            table_name="orders",
            column_name="amount",
            note=f"{schema_name} 的金额",
            updated_by=author.id,
        )

    db_session.add_all([_note("public"), _note("demo_sales")])
    db_session.flush()  # 三列键会在这里炸

    notes = db_session.scalars(
        sa.select(ColumnNote).order_by(ColumnNote.schema_name)
    ).all()
    assert [note.schema_name for note in notes] == ["demo_sales", "public"]

    # 反过来：同一个 schema 的同一列写两条**必须**撞唯一键。少了这半条，
    # 一个「根本没有唯一约束」的实现也能通过上半条。
    db_session.add(_note("public"))
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_schema_metadata.py -v
```

预期：**两条都 ERROR**，`ImportError: cannot import name 'SchemaCache' from 'chatbi.db.models'`。

- [ ] **Step 3: 写 migration 0004**

新建 `apps/api/migrations/versions/0004_schema_cache_column_notes.py`：

```python
"""schema_cache and column_notes

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schema_cache",
        # 一个数据源一行，refresh 是整行覆盖。没有历史版本——快照的价值在
        # 「现在的库长什么样」，旧快照只会让人对着过期结构写 SQL
        sa.Column(
            "datasource_id",
            sa.Uuid(),
            sa.ForeignKey("datasources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        # payload 里**绝不**存人工注释：refresh 整行覆盖它，注释会跟着丢。
        # 注释的真相源是 column_notes（spec §2.5 末尾那条注释的全部理由）
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )

    op.create_table(
        "column_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "datasource_id",
            sa.Uuid(),
            sa.ForeignKey("datasources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # schema_name 是对 spec §2.5 的有意偏离：spec 的唯一键只有三列，但
        # Postgres 的 reflect() 返回所有非系统 schema，demo_sales.orders 与
        # public.orders 会撞成同一条注释——静默挂到错的列上
        sa.Column("schema_name", sa.String(200), nullable=False),
        sa.Column("table_name", sa.String(200), nullable=False),
        sa.Column("column_name", sa.String(200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "updated_by",
            sa.Uuid(),
            # RESTRICT 与 datasources.created_by 一致：注释是审计对象，删用户
            # 不该静默丢掉归属。现在不挡任何功能——/api/users 只有 GET 与 POST
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_column_notes_column",
        "column_notes",
        ["datasource_id", "schema_name", "table_name", "column_name"],
        unique=True,
    )
    # 合并时按数据源一次取全部注释，需要自己的索引；上面那个唯一索引的前导列
    # 正是 datasource_id，所以**不再**单独建一个——重复索引只是写放大
```

```python
def downgrade() -> None:
    op.drop_index("uq_column_notes_column", table_name="column_notes")
    op.drop_table("column_notes")
    op.drop_table("schema_cache")
```

`payload` 用 `JSONB` 而不是 `JSON`：与 `datasources.options` 一致，且 JSONB 才能被索引（本份不建那个索引，但换类型是不兼容变更，一开始就选对）。

**这个 migration 不 import 任何 `chatbi.*`**（与 0002、0003 一致）：只用 `alembic.op` 与 `sqlalchemy`，所以 CI 只想验 schema 时不需要主密钥、不需要 LLM 配置。

- [ ] **Step 4: 加两个模型**

`apps/api/src/chatbi/db/models.py` 末尾追加：

```python
class SchemaCache(Base):
    """一个数据源的表结构快照。payload 是 SchemaSnapshot 的 JSON。

    表级约束只写在 migration 里，与 Datasource 一致：建表永远走 Alembic，
    模型的 __table_args__ 根本不会被执行，写两份只会得到两份不同步的约束。
    """

    __tablename__ = "schema_cache"

    datasource_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("datasources.id", ondelete="CASCADE"), primary_key=True
    )
    fetched_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)


class ColumnNote(Base):
    """人工补的列注释。与 schema_cache 分开存，因为 refresh 整行覆盖 payload。

    唯一键是四列（含 schema_name），比 spec §2.5 多一列——见 migration 0004
    里的注释。故意不定义 relationship：db 是叶子模块（spec §1.3 规则 4）。
    """

    __tablename__ = "column_notes"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("datasources.id", ondelete="CASCADE"), nullable=False
    )
    schema_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    table_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    column_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    note: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
```

`updated_at` 带 `onupdate=sa.func.now()`：改注释要刷新时间戳。`datasources.updated_at` 是同一个写法。

- [ ] **Step 5: 迁移双向断言加两张表**

`apps/api/tests/test_migrations.py` 只改一行：

```python
TABLES = {
    "users",
    "sessions",
    "datasources",
    "datasource_grants",
    "schema_cache",
    "column_notes",
}
```

两张表都在默认 schema 里，所以**不需要**像 `DEMO_TABLES` 那样单独断言。

- [ ] **Step 6: 跑测试确认通过**

```bash
uv run pytest -q
```

预期：**193 passed / 28 skipped**（191 + 本任务两条）。

`test_migrations_roundtrip` 会真的 `downgrade base` 再 `upgrade head`，所以 0004 的 `downgrade()` 写错会在这里暴露，不需要单独测。

- [ ] **Step 7: 反向验证三条**

1. `column_notes` 的唯一索引去掉 `schema_name`（改成三列）→ `test_the_same_table_name_in_two_schemas_can_both_have_notes` 的**上半段** FAIL（第一次 `flush()` 就撞唯一键）。
2. 唯一索引整个删掉 → 同一条测试的**下半段** FAIL（`pytest.raises(IntegrityError)` 收不到异常）。这条和第 1 条方向相反，两条都要跑：只做第 1 条的话，一个「根本没有唯一约束」的实现会通过。
3. 两个 `ondelete="CASCADE"` 任一改成 `"RESTRICT"` → `test_deleting_a_datasource_takes_its_cache_and_notes` FAIL（`IntegrityError`）。改 migration 就够，模型里的 `ondelete` 不参与建表。

第 3 条要注意：**只改模型里的 `ondelete` 不会让测试变红**，因为表是 Alembic 建的。这正是模型注释里那句「写两份只会得到两份不同步的约束」的实证——想验证约束就得改 migration 并重跑 `_migrated` 夹具（`pytest` 会自动跑，因为它是 session 级 autouse）。

- [ ] **Step 8: ruff + 提交**

```bash
uv run ruff check . && uv run ruff format --check .
git add migrations/versions/0004_schema_cache_column_notes.py \
        src/chatbi/db/models.py tests/test_migrations.py tests/test_schema_metadata.py
git commit -m "feat(db): schema_cache 与 column_notes 两张表

column_notes 的唯一键是四列，比 spec §2.5 多一个 schema_name：Postgres
的 reflect() 返回所有非系统 schema，三列键会让 demo_sales.orders 与
public.orders 撞成同一条注释，且失败方式是静默挂到错的列上。

payload 里绝不存人工注释——refresh 整行覆盖它。两张表的 datasource_id
都 CASCADE，updated_by 用 RESTRICT（与 datasources.created_by 一致，
且 /api/users 现在没有删除路径）。"
```




---

## 实施期的偏差（执行中回填）

（开工前为空。每个任务做完就在这里记：实测计数与预期不符的地方、对计划的偏离及理由、反向验证里出现的意外结果。P1/P2a/P2b 三次的经验是**攒着必漏**——发现即回填，别等到最后。）

---

## 交接清单（p2c2 要消费的签名）

```python
# Task 1 之后成立的行为承诺（不是新签名，协议在 P2b 已定）
Driver.reflect(info) -> SchemaSnapshot
#   库里有注释时，ColumnSchema.comment 与 TableSchema.comment **非 None**。
#   Task 3 的序列化往返、Task 4 的合并、Task 5 的 AC1 红线全都依赖这一条。
#   Postgres 的 data_type 仍然是 information_schema 那套拼法（integer / text /
#   numeric / timestamp with time zone），换 SQL 时用 ::regtype::text 保住了它，
#   所以 _NUMERIC_TYPES 与 is_numeric 的语义没变

# Task 2 之后可用的模型（chatbi.db.models）
SchemaCache   # datasource_id(pk, cascade) / fetched_at / payload(JSONB)
ColumnNote    # id(pk) / datasource_id(cascade) / schema_name / table_name /
              # column_name / note / updated_by(restrict) / updated_at
#   唯一约束名 "uq_column_notes_column"，四列：
#   (datasource_id, schema_name, table_name, column_name)
#   —— 比上游 spec §2.5 多一个 schema_name，理由见 migration 0004 的注释
```

**p2c2 的 Task 3 起手要注意的两件事**

1. `tests/test_schema_metadata.py` 已存在（本份 Task 2 建的，含两条建模测试）。往它里面**追加**，别新建同名文件，也别覆写——那两条测试守的是 CASCADE 与四列唯一键，没有别处覆盖它们。
2. `payload` 里**绝不**存人工注释。`refresh` 整行覆盖它，注释若在里面就会跟着丢，而 F-201 AC1 要求两者并存。这条在 migration 0004 的列注释里也写了一遍，两处都别改。

**计数交接**：本份结束时应为 **193 passed / 28 skipped**。skip 从 26 变 28 是 Task 1 新增的契约测在 MySQL / ClickHouse 上各 skip 一条，是预期的，不是回退。

---

## 自查记录

**设计 spec 覆盖核对（本份负责的部分）**

| 设计条目 | 落在哪 |
|---|---|
| §1.1 缺陷描述（Postgres `reflect()` 全返回 None） | Task 1 开头 |
| §1.2 修法 + `regtype` vs `format_type` 那张对照表 | Task 1 Step 4 |
| §1.3 契约测补一条、三 kind 都跑、skip 26 → 28、门禁 39 → 42 | Task 1 Step 1–2、Step 6 |
| §2 两张表的建表 SQL | Task 2 Step 3 |
| §2.1 `schema_name` 偏离及其理由 | Task 2 Step 3 的列注释 + Step 1 的第二条测试 |
| §2.2 两个外键的删除行为 | Task 2 Step 3 + Step 1 的第一条测试 |
| §2.3 `payload` 存什么 / 不存什么 | Task 2 Step 3 的列注释（序列化本身在 p2c2 Task 3） |
| §5.3 反向验证要两个方向跑 | Task 1 Step 7（四条）、Task 2 Step 7（三条） |

**本份不覆盖的设计小节**：§3（`col_id`）· §4（合并）· §5（端点）· §6.1–6.3 的三个新模块 · §7.1 任务 3–5 的测试 · §8.2 的三笔回填——全部在 p2c2。**§8.2 的回填由 p2c2 收尾时做**，本份不做，因为其中一笔要写「门禁目标改成 42」，而那个数字要等 Task 1 实测确认契约测真的是 14 条 × 3。

**占位符扫描**：无 TBD / TODO / 「类似 Task N」/ 无代码的「写测试」步骤。Task 1 Step 5 的「本机验不了」不是占位符——它列了三条具体的门禁核对项和一条失败时的诊断路径（先查注释有没有写进去，再决定是语法问题还是读取问题）。

**类型一致性核对**

`ColumnSchema` / `TableSchema` 的字段名在三个驱动的 `reflect()` 里逐一对齐（`name` / `data_type` / `is_nullable` / `is_numeric` / `comment`；表级 `name` / `schema_name` / `columns` / `comment`）。**协议本身没改**——`base.py` 的两个 dataclass 早就有 `comment` 字段，本份只是把它填上。

Postgres 的 `is_nullable` 从 `is_nullable == "YES"`（information_schema 的字符串）变成直接的 `bool`（SQL 里已 `not a.attnotnull`）。MySQL 那边**仍然是字符串比较**，因为它还在查 information_schema。两个驱动这一处不同是对的，别为了「看起来一致」把其中一个改成另一个的写法。

`Dialect` 新增两个字段后，`DIALECTS` 三份都必须填——漏一份会在那个 kind 上抛 `TypeError: missing required argument`，而不是安静地跳过。

**写作过程中的回改一处**

**Task 1 从「只改 Postgres」扩到「改三个驱动」**。写契约测时才意识到 `assert table.comment == "契约测表"` 对三个 kind 都会跑，而 MySQL 与 ClickHouse 的 `reflect()` 也都没取表注释——只改 Postgres 就是在门禁那天埋两条红。于是加了 Step 5，并把「本机验不了」连同门禁核对清单一起写明，而不是留一句「门禁时再看」。
