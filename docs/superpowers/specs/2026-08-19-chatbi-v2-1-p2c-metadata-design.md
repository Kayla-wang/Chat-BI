# Chat-BI V2-1 · P2c 元数据接入（F-201）设计

**上游 spec**：`2026-08-11-chatbi-v2-1-design.md`（§2.4 端点表、§2.5 数据模型、§4.5 LLM 边界、§8.1 验收项 11）。本份只展开 F-201，不改上游的任何其他结论。

**一句话**：把三个驱动的 `reflect()` 输出缓存进应用库，叠加人工补的列注释，通过两个端点交给前端与 P3——并且**刷新不丢人工注释**。

## 0. 范围与不做

**做**：Postgres `reflect()` 的注释修复 · `schema_cache` 与 `column_notes` 两张表 · 库原生注释与人工注释的合并 · `GET /schema` 与 `PATCH /schema/columns/{col_id}` 两个端点 · 给 §4.5 白名单用的 `known_identifiers()`。

**不做，且各有归属**：

| 推后的东西 | 去哪 | 理由 |
|---|---|---|
| 列示例值（spec §4.5「可选，默认关闭，开启需管理员显式打开」） | P3 | 它要跑一条真查询、要一个 datasource 级的 admin 开关，而唯一消费方是 prompt。跟 prompt 构建同批做才能一次定下采样策略（取几行、去重不去重、超时多少） |
| `SchemaContextProvider`（spec §6） | P3 | 它只是把本份的输出格式化成 prompt 文本。放这里等于让 P2c 猜 prompt 的形状 |
| 语义层的指标/同义词/join 关系 | V2-2 | spec §6 已定 |

**前置**：P2b 的 `Driver.reflect()`、`connection_info()`、`driver_for` 全部已实现并入库。本份不需要 Docker、不需要 `CREATEROLE`——这是它被排在 P2b 两个人工前置之前的唯一理由。



## 1. 先修 `reflect()` 的注释——否则本份其余部分是空壳

### 1.1 缺陷（2026-08-19 实测确认，不是推断）

`drivers/postgres.py` 的 `reflect()` 对**每一列、每一张表**都返回 `comment=None`，即使库里有注释。MySQL 与 ClickHouse 两个驱动都正确带出了注释。

实测对照（`chatbi_test` 库的 `demo_sales.customers`）：

```
库里（col_description）：  id → 客户 ID    name → 客户名称    city → 所在城市
reflect() 返回的：         id → None       name → None        city → None
```

根因：`_REFLECT_SQL` 查的是 `information_schema.columns`，那张视图**没有注释列**。注释在 Postgres 里存 `pg_description`，要用 `col_description(oid, attnum)` 与 `obj_description(oid, 'pg_class')` 取。

为什么一直没被发现：13 条驱动契约测**没有一条断言注释**。P2b 第二份的交接清单还写着「示例库的列注释已经在 `ColumnSchema.comment` 里（`reflect()` 会带出来）」——那句话是错的，本份连带纠正它。

这条缺陷直接架空 F-201 与 spec §4.5：注释是进 prompt 的唯一业务语义来源，`demo_sales` 全列中文注释的那次工作（migration 0003）在 Postgres 这条路上等于没生效。

### 1.2 修法

`_REFLECT_SQL` 整条换成走 `pg_catalog`，一次取到列注释与表注释：

```sql
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
```

**类型名必须用 `a.atttypid::regtype::text`，不能用 `format_type(a.atttypid, a.atttypmod)`。** 已对 `demo_sales` 实测四种类型：

| 列 | `information_schema.data_type`（现状） | `::regtype::text` | `format_type()` |
|---|---|---|---|
| id | `integer` | `integer` | `integer` |
| name | `text` | `text` | `text` |
| amount | `numeric` | `numeric` | **`numeric(12,2)`** |
| ordered_at | `timestamp with time zone` | `timestamp with time zone` | `timestamp with time zone` |

`regtype` 与现状逐一相同，所以这次修改**不改变** `data_type` 的既有语义。而 `format_type` 给的 `numeric(12,2)` 不在 `_NUMERIC_TYPES` 里，会把 `is_numeric` 静默变成 `False`——前端按 `is_numeric` 选图（spec §2.3），坏掉的方式是「图表默默变成了另一种」，不报错。

`a.attnum > 0 and not a.attisdropped` 两个条件都必要：前者排除系统列（`ctid` 等），后者排除已 DROP 但物理仍在的列。少任何一个都会让快照里出现库里看不到的列。

`TableSchema.comment` 同时填上。`base.py` 的两个 dataclass 已经有 `comment` 字段，不需要改协议。

### 1.3 契约测补一条，三个 kind 都跑

新增 `test_reflect_carries_comments`，加进**共用**的 `tests/drivers/test_driver_contract.py`。语法差异放 `conftest.py` 的 `DIALECTS`，契约文件里**不加 if 分支**（该文件头部的约定：需要 if 就说明协议没抽对）。

`Dialect` 加两个字段：

| 字段 | postgres | mysql | clickhouse |
|---|---|---|---|
| `comment_column_sql` | `comment on column {table}.label is '标签注释'` | `alter table {table} modify column label varchar(64) null comment '标签注释'` | `alter table {table} comment column label '标签注释'` |
| `comment_table_sql` | `comment on table {table} is '契约测表'` | `alter table {table} comment = '契约测表'` | `alter table {table} modify comment '契约测表'` |

MySQL 的那条要重写整个列定义（`modify column` 的语义如此），所以它必须与 `create_table_sql` 里 `label` 的类型保持一致——两处不同步会静默改掉列类型，让 `test_reflect_describes_the_seeded_columns` 转红。这个耦合写进 `Dialect` 的字段注释里。

**对计数的影响**：契约测从 13 条 × 3 kind 变 14 × 3。Postgres 有真库所以新增那条立即跑；MySQL/ClickHouse 仍 skip，**skip 基线从 26 变 28**。P2b Task 7 门禁的目标数从 `39 passed / 0 skipped` 变 `42 passed / 0 skipped`——这条要回填进 P2b 那份计划，否则门禁那天会以为少跑了。



## 2. 数据模型（migration 0004）

```sql
schema_cache(datasource_id uuid pk fk → datasources.id on delete cascade,
             fetched_at timestamptz not null,
             payload jsonb not null)
-- 一个数据源一行，refresh 是整行覆盖。没有历史版本——快照的价值在「现在的库长什么样」

column_notes(id uuid pk,
             datasource_id uuid fk → datasources.id on delete cascade,
             schema_name text not null,
             table_name text not null,
             column_name text not null,
             note text not null,
             updated_by uuid fk → users.id on delete restrict,
             updated_at timestamptz not null,
             unique (datasource_id, schema_name, table_name, column_name))
```

### 2.1 对 spec §2.5 的一处有意偏离：`column_notes` 加 `schema_name`

spec 写的唯一键是三列 `(datasource_id, table_name, column_name)`。**改成四列，加 `schema_name`。**

理由：Postgres 的 `reflect()` 返回**所有非系统 schema**，本机现成的反例就是应用库自己——`demo_sales.orders` 与将来 `public.orders` 在三列键下会撞成同一条注释。撞了不会报错，会静默把注释挂到另一个 schema 的同名列上，而这种错误在界面上完全看不出来（注释本来就是自由文本，看到一条不对的注释只会以为是别人写错了）。

MySQL 的 `reflect()` 只返回 `database()` 那一个 schema、ClickHouse 只返回一个库，所以这一列对那两类恒为同一个值。为它们付一列的代价，换 Postgres 上不会静默错配——Postgres 是三类里唯一多 schema 的，也是 `demo_sales` 所在的那一类。

### 2.2 两个外键的删除行为

`datasource_id` 用 `CASCADE`：删数据源就该带走它的缓存与注释，两者脱离数据源都没有意义。

`updated_by` 用 `RESTRICT`，与 `datasources.created_by` 的取舍一致（migration 0002 已有先例：数据源是审计对象，删管理员不该静默丢掉归属）。这条现在不挡任何功能——`/api/users` 只有 GET 与 POST 两个路由，**没有删除用户的路径**。将来真要加删除用户，那时再决定是改成 `SET NULL`（保住注释、丢掉作者）还是先迁移注释，不在本份预留。

### 2.3 `payload` 里存什么

存 `SchemaSnapshot` 的 JSON。它是 frozen dataclass，`dataclasses.asdict()` 可用。

**`payload` 里绝不存人工注释。** 这是 spec §2.5 末尾那条注释的全部理由：`refresh` 整行覆盖 `payload`，人工注释若在里面就会跟着丢，而 F-201 AC1 要求两者并存。注释的真相源恒为 `column_notes` 表，合并只发生在读路径上。

反序列化要显式重建 dataclass，不能直接把 dict 塞回去：`asdict()` 把 `tuple` 变成 `list`，而三个 dataclass 都是 `frozen` + tuple 字段，用 list 构造出来的对象不可哈希、且与驱动新鲜产出的快照不相等——「序列化往返后相等」这条性质要有测试钉住。



## 3. `col_id`：服务端发出，客户端回传，PATCH 反查而不解析

spec §2.4 的路径是 `PATCH /api/datasources/{id}/schema/columns/{col_id}`。缓存里的列没有数据库 id，所以 `col_id` 要自己定义。

**定义**：`col_id = f"{schema_name}.{table_name}.{column_name}"`，由 `GET /schema` 在每一列上发出，客户端原样回传。

**PATCH 不解析这个字符串，而是拿它去缓存快照里反查**：把快照里每一列按同样规则拼出字符串，比对：

| 命中数 | 行为 |
|---|---|
| 恰好 1 | 写注释 |
| 0 | `404 COLUMN_NOT_FOUND` |
| ≥2 | `409 COLUMN_ID_AMBIGUOUS` |

反查而不 `split(".")`，是因为**标识符本身可以含点**：Postgres 里 `create table "a.b"` 完全合法，解析会把它切错，而反查天然正确——两侧用同一个拼接规则，含点的标识符只会让某些 `col_id` 无法唯一定位，那正是 409 要说的话。

那条 409 现实中几乎不会触发（要两个不同列拼出**逐字节相同**的字符串）。仍然留着它 + 一条测试，因为它防的是与 §2.1 加 `schema_name` 同一个失败：**静默把注释挂到错的列上**。返回 409 让用户知道「这个列现在改不了」，比默默改了另一列好；YAGNI 在这里不适用，因为代价是一个分支而收益是不撒谎。

**反查依赖缓存存在**。所以 PATCH 在缓存为空时返回 `404 COLUMN_NOT_FOUND`——不为 PATCH 触发一次拉取。理由：PATCH 是写注释，不该顺带产生一次对外部库的连接（那会让一次注释编辑因为数据源临时不可达而失败）。正常流程里前端必然先 `GET /schema` 才拿得到 `col_id`，缓存那时已经建好。

**新增两个错误码**（`errors.py`）：

```python
COLUMN_NOT_FOUND = ("COLUMN_NOT_FOUND", "列不存在或元数据尚未拉取", 404)
COLUMN_ID_AMBIGUOUS = ("COLUMN_ID_AMBIGUOUS", "该列标识不唯一，无法定位", 409)
```

两条文案都不含 schema 名、表名、列名——spec §4.4「错误信息不泄露结构」。用户知道自己传的是什么，不需要回显。



## 4. 合并：两个字段并存，谁都不覆盖谁

响应里每一列同时带两个字段：

| 字段 | 来源 | 空值含义 |
|---|---|---|
| `comment` | 库原生注释（`schema_cache.payload`） | 库里没写注释 |
| `note` | 人工补的注释（`column_notes`） | 没人补过 |

**不做「note 非空就覆盖 comment」的单字段合并。** 三个理由：

1. 前端要能显示来源差异——「这是 DBA 在库里写的」与「这是张三补的」对分析师是不同的可信度。
2. P3 的 prompt 构建自己决定怎么拼（很可能两条都放进去），单字段合并会提前替它做掉这个决定，且不可逆。
3. `demo_sales` 天然是这个对照的演示场景：库里已有全列中文注释，人工再补一条就同时有了两种来源。这是 spec §2.5 那批注释除了喂 prompt 之外的第二个用处。

表级同样带 `comment`（库原生），但**不做表级人工注释**——F-201 AC1 只说列。要加是 V2-2 的事，`column_notes` 也不为它预留行（用空 `column_name` 表示表级是个会污染唯一键语义的技巧，别用）。



## 5. 两个端点

两条都吃 `require_datasource`，所以「数据源不存在 → 404 / 无 `can_query` 授权 → 403」与既有的 `/test`、`/grants` 自动一致。

### 5.1 `GET /api/datasources/{id}/schema`

| 情形 | 行为 |
|---|---|
| 缓存有 | 直接返回缓存，**不连外部库** |
| 缓存为空 | 拉一次、写缓存、返回 |
| `?refresh=1` | 强制重拉、覆盖缓存、返回 |
| 拉取时连不上 | `503 CONNECTION_ERROR`；地址端口进服务端日志，不进响应（spec §4.4） |

响应带 `fetched_at`。**不设 TTL**：新鲜度交给界面展示（「元数据拉取于 X」+ 一个刷新按钮），不由后端猜多久算过期。私有化部署里 schema 的变更节奏差异极大，任何默认 TTL 都会在一半环境里是错的；而显式刷新的成本只是一次点击。

「缓存为空时自动拉一次」是为了让首次调用可用——否则前端要先发一个必然失败的 GET 再发一个 `?refresh=1`，把一个实现细节暴露成协议。

### 5.2 `PATCH /api/datasources/{id}/schema/columns/{col_id}`

请求体 `{"note": "..."}`。upsert 到 `column_notes`，`updated_by = current_user.id`、`updated_at = now()`。

**analyst 也能改**（有 `can_query` 授权即可），不限 admin。F-201 是分析师的工作流——知道 `segment` 在业务上意味着什么的人是他，要 admin 代录这个功能基本不会被用。代价是一个 analyst 能影响所有人的 prompt，用 `updated_by` 记账接受这个代价；spec §4.2 的角色分层没有被破坏（analyst 仍然改不了数据源本身的任何字段）。

`note` 允许空字符串，语义是「清空这条注释」——保留行、`note = ''`，不删行。删行会让 `updated_by`/`updated_at` 的审计痕迹消失，而「谁把注释清掉了」和「谁写了注释」一样值得留。

### 5.3 F-201 AC1 / 验收项 11 的红线

**「refresh 后人工注释不丢」必须有一条端到端测试**：写注释 → `?refresh=1` → GET → 注释仍在。

**反向也要验**（P1 起就在用的那条做法：覆盖测试两个方向都要跑）：把合并改成从 `payload` 里读注释，这条必须转红。只跑正向的话，一个「注释恰好没被覆盖」的实现也能过，而那不是设计承诺。



## 6. 文件落点与模块边界

### 6.1 新建

| 文件 | 职责 |
|---|---|
| `migrations/versions/0004_schema_cache_column_notes.py` | 两张表。不 import 任何 `chatbi.*`（与 0003 一致，让 CI 只验 schema 时不需要主密钥） |
| `src/chatbi/datasources/metadata.py` | **持久化与序列化**：`SchemaSnapshot` ⇄ jsonb、缓存读写、注释 upsert 与列出、`known_identifiers()` |
| `src/chatbi/datasources/schema_view.py` | **API 形状**：`col_id` 的生成与反解、快照 × 注释 → 响应模型 |
| `src/chatbi/api/schema_router.py` | 两个端点 |
| `tests/test_schema_metadata.py` | `metadata.py` 的领域测试（不过 HTTP） |
| `tests/test_schema_view.py` | `col_id` 与合并的纯函数测试（不碰库） |
| `tests/test_schema_router.py` | 两个端点的鉴权、缓存行为、503、AC1 红线 |

### 6.2 修改

| 文件 | 改动 |
|---|---|
| `src/chatbi/datasources/drivers/postgres.py` | `_REFLECT_SQL` 换 `pg_catalog` + 填两处 `comment`（§1.2） |
| `src/chatbi/db/models.py` | 加 `SchemaCache`、`ColumnNote` 两个模型 |
| `src/chatbi/datasources/schemas.py` | 加 `SchemaResponse` / `TableSchemaResponse` / `ColumnSchemaResponse` / `ColumnNoteUpdate` |
| `src/chatbi/errors.py` | 加 `COLUMN_NOT_FOUND`、`COLUMN_ID_AMBIGUOUS` |
| `src/chatbi/api/routers.py` | `ALL_ROUTERS` 加 `schema_router` |
| `tests/drivers/conftest.py` | `Dialect` 加两个字段 + `DIALECTS` 三份填上（§1.3） |
| `tests/drivers/test_driver_contract.py` | 加 `test_reflect_carries_comments` |
| `tests/test_migrations.py` | `TABLES` 加 `schema_cache`、`column_notes` |

### 6.3 为什么是三个新文件而不是塞进现有的

`datasource_router.py` 已 160 行、`repository.py` 已 187 行。spec §1.4 的硬上限只点了 `guard/validator.py` 与 `execution/executor.py`，所以这里不是违规问题，是职责问题：

- `repository.py` 的职责是「数据源与授权的持久化」，它跟着 `datasources` / `datasource_grants` 的表结构变。schema 缓存跟着 `SchemaSnapshot` 这个**驱动协议的产物**变——两者的变更理由不同，与 P2b 把 `connection.py` 单独拆出来是同一条判断。
- `metadata.py` 与 `schema_view.py` 分开，是因为一个跟着表结构变、另一个跟着 API 形状变。`col_id` 的生成与反解必须在同一个文件里（两侧共用一条拼接规则，分开写必然漂移），而那个文件天然属于 API 形状那一侧。
- `schema_view.py` 是纯函数、不 import `sqlalchemy` 也不 import `fastapi`，所以合并与 `col_id` 反解可以脱离库与 HTTP 测——`tests/test_schema_view.py` 一个夹具都不需要。它 import `errors.ApiError`，那是错误契约不是框架依赖，与 `repository.py` 文件头写明的同一条约定（`errors.py` 自身 import `fastapi`，这一点在 P2a 就已接受）。

### 6.4 任务切分（五个）

| # | 交付 | 独立可验收的理由 |
|---|---|---|
| 1 | Postgres `reflect()` 注释修复 + 契约测那条 | 不碰应用库、不碰 HTTP。做完 `demo_sales` 的中文注释就真的能被读出来了 |
| 2 | migration 0004 + 两个模型 + 迁移双向断言 | 只动 schema。up/down 双向过了就算完 |
| 3 | `metadata.py` | 领域层，序列化往返与 upsert 幂等都能脱离 HTTP 验 |
| 4 | `schema_view.py` | 纯函数，`col_id` 三条分支与两字段并存不需要库 |
| 5 | 两个端点 + `routers.py` 接缝 + AC1 红线 | 前四个任务在这里第一次接成一条真路径 |

顺序不能换：4 依赖 3 定下的注释读取形状，5 依赖 1（没有注释可读的话 AC1 红线测不出东西）。



## 7. 测试策略与计数

沿用既有三层（spec §5.1）：契约测（`tests/drivers/`，允许 skip 但必须计数）· 领域测试（不过 HTTP）· 端点测试（`TestClient` + `dependency_overrides`）。

**端点测试不需要真外部库**：`driver_for` 在 P2b 已做成 FastAPI 依赖，可被 `dependency_overrides` 换成假驱动。假驱动只实现 `reflect`——缺其余方法是**故意**的，端点若调了它不该调的方法会以 `AttributeError` 暴露（与 P2b `/test` 的假驱动同形）。

### 7.1 每个任务必须存在的测试

| 任务 | 关键测试 | 它证伪什么 |
|---|---|---|
| 1 | `test_reflect_carries_comments`（契约，三 kind） | 一个不取注释的 `reflect()`——现在的 Postgres 实现 |
| 1 | 既有 `test_reflect_describes_the_seeded_columns` 必须继续绿 | 换 SQL 时把 `data_type` 或 `is_numeric` 改坏（`format_type` 那个坑） |
| 2 | 删数据源带走缓存与注释 | `CASCADE` 写成了 `RESTRICT`/无外键 |
| 2 | 四列唯一键：同表名不同 schema 的两条注释可以共存 | 照 spec 写成三列键（§2.1 的那个静默错配） |
| 3 | 序列化往返后快照与原对象相等 | `asdict()` 之后没重建 dataclass（tuple → list） |
| 3 | 注释 upsert 幂等：同一列写两次只有一行、`note` 是后写的 | 写成了 insert，第二次撞唯一键 500 |
| 4 | `col_id` 反解：命中 1 / 命中 0 / 命中 ≥2 三条 | `split(".")` 式解析；歧义被静默取第一个 |
| 4 | 有库注释也有人工注释时，两个字段都在 | 单字段覆盖式合并 |
| 5 | 缓存为空时 GET 自动拉一次并写缓存 | 首次调用返回空 |
| 5 | 缓存有时 GET **不连**外部库 | 缓存没被读，每次都重拉 |
| 5 | `?refresh=1` 确实重拉 | 参数被忽略 |
| 5 | 拉取失败 → 503 且响应体不含 host/port | 把驱动异常原文透给客户端 |
| 5 | **写注释 → refresh → 注释仍在** | F-201 AC1 / 验收项 11 |
| 5 | analyst 能 PATCH、viewer 不能（无 `can_query` → 403） | 权限判断挂在错的角色上 |

### 7.2 反向验证（每条都要两个方向跑）

1. 把 `col_description(...)` 换成 `null` → 契约那条注释测试转红，`test_reflect_describes_the_seeded_columns` 保持绿（证明两条测的是不同东西）。
2. `data_type` 换成 `format_type(...)` → `is_numeric` 相关断言转红（证明 §1.2 那张表不是纸上推理）。
3. 唯一键去掉 `schema_name` → 「同表名不同 schema 共存」转红。
4. 合并改成从 `payload` 读注释 → AC1 红线转红。
5. `col_id` 反解改成命中多个时取第一个 → 409 那条转红。
6. GET 去掉缓存分支永远重拉 → 「缓存有时不连外部库」转红，而其余 GET 测试**全绿**（这条最值得记：它说明只有那一条测试在守缓存，删了它缓存就没人看）。

### 7.3 计数

起点 **190 passed / 26 skipped**（`637090f`）。

| 任务后 | passed | skipped |
|---|---|---|
| 1 | 191 | 28 |
| 2 | 194 | 28 |
| 3 | 200 | 28 |
| 4 | 206 | 28 |
| 5 | 217 | 28 |

skip 从 26 变 28 是 §1.3 的新契约测在 MySQL/ClickHouse 上各 skip 一条，**是预期的**，不是回退。实测与上表不符就停下核对，别改断言凑数。



## 8. 与上游 spec 的偏离，以及要回填进上游的东西

### 8.1 有意偏离（两处）

| 上游原文 | 本份的做法 | 理由 |
|---|---|---|
| §2.5 `column_notes ... unique (datasource_id, table_name, column_name)` | 加 `schema_name`，唯一键四列 | §2.1：Postgres 多 schema 会静默错配 |
| §2.4 `PATCH .../schema/columns/{col_id}`（未定义 `col_id`） | 定义为 `schema.table.column`，服务端发出、PATCH 反查 | §3：spec 没定义，本份补上 |

第一条**要回填进上游 spec §2.5 的 SQL**（与 P2b 那次回填 §2.5 措辞同样的动作）。第二条是补充而非冲突，上游 §2.4 的表格里加一句 `col_id` 的定义即可。

### 8.2 要回填进 P2b 计划的东西（三处）

1. **`2026-08-18-...-p2b-drivers.md` 的 Task 2**：Postgres `reflect()` 不取注释是缺陷，在 P2c Task 1 修。当时的契约测没覆盖注释，这是漏检的原因。
2. **同一份的 Task 7 门禁目标**：从 `39 passed / 0 skipped` 改成 `42 passed / 0 skipped`（契约测 13 → 14 条 × 3 kind）。
3. **`...-p2b-test-endpoint-and-demo.md` 的交接清单**：那句「示例库的列注释已经在 `ColumnSchema.comment` 里（`reflect()` 会带出来）」当时对 Postgres 是错的，改成「P2c Task 1 修好后才成立」。

这三处不回填的后果具体且可预期：门禁那天会以为少跑了三条；下一个人读交接清单会以为注释已经能用，从而在 P3 的 prompt 里拿到一堆 `None`。

### 8.3 已知的松散端与取舍

- **`payload` 没有版本号或 schema 版本标记**。将来 `SchemaSnapshot` 加字段时，旧缓存反序列化会缺字段。取舍：缓存是可重建的派生数据，加版本号的正确做法是「读不动就当缓存为空、重拉一次」，而那需要一个 try/except 分支；本份不写它，因为现在只有一个版本，写了也无法测到真实的迁移场景。加字段那天在 `metadata.py` 里加，并同时加一条「旧格式 payload 触发重拉」的测试。
- **`known_identifiers()` 在 P2c 结束时没有生产调用方**，只有测试。消费方是 P3 的 prompt 构建（spec §4.5 白名单）。这与 P2a 的 `read_password`、P2b 的 `execute()` 同形，是有意的，别当成新发现的死代码。
- **不做表级人工注释**（§4 末）。
- **`GET /schema` 返回全部 schema 的全部表**，不分页、不过滤。一个有几百张表的库会返回一个很大的 JSON。取舍：分页会让「白名单」与「合并」都要处理部分视图，复杂度不值得；真遇到大库时正确的做法是在数据源上加 schema 白名单配置，那是 V2-2 语义层的范围。
- **PATCH 在缓存为空时 404 而不触发拉取**（§3 末）。
- **`refresh=1` 没有并发保护**。两个用户同时点刷新会各拉一次、各写一次缓存，最后一次赢。都是同一个库的快照，结果等价；加锁的收益只是省一次连接。



## 9. 交接清单（P3 与 P4 要消费的签名）

```python
# 持久化与序列化（metadata.py）
snapshot_to_payload(snapshot: SchemaSnapshot) -> dict
payload_to_snapshot(payload: dict) -> SchemaSnapshot
read_cache(db, datasource_id: uuid.UUID) -> SchemaCache | None
write_cache(db, datasource_id: uuid.UUID, snapshot: SchemaSnapshot) -> SchemaCache
upsert_note(db, *, datasource_id, schema_name, table_name, column_name,
            note: str, updated_by: uuid.UUID) -> ColumnNote
list_notes(db, datasource_id: uuid.UUID) -> list[ColumnNote]
known_identifiers(db, datasource_id: uuid.UUID) -> frozenset[str]
#   spec §4.5 的白名单。含 schema 名、表名、以及 "schema.table" 两段形式

# API 形状（schema_view.py，纯函数）
column_id(schema_name: str, table_name: str, column_name: str) -> str
resolve_column_id(snapshot: SchemaSnapshot, col_id: str) -> tuple[str, str, str]
#   命中 0 抛 ApiError(*COLUMN_NOT_FOUND)、≥2 抛 ApiError(*COLUMN_ID_AMBIGUOUS)
merge_schema(snapshot, notes, *, fetched_at) -> SchemaResponse

# 端点
GET   /api/datasources/{id}/schema[?refresh=1] -> 200 | 401 | 403 | 404 | 503
PATCH /api/datasources/{id}/schema/columns/{col_id} -> 200 | 401 | 403 | 404 | 409
```

**P3 prompt 构建**
- 用 `merge_schema()` 的输出，别自己读 `schema_cache`。每列有 `comment`（库原生）与 `note`（人工）两个字段，两条都放进 prompt 是预期用法。
- 表名/schema 名进 prompt 前过 `known_identifiers()`（spec §4.5）。
- **结果行永不进 prompt**（spec §4.5）。示例值那条路径由 P3 自己新增，见 §0 的推后表。

**P4 前端**
- `col_id` 从 `GET /schema` 的响应里拿，**不要在前端拼**——拼接规则一改两侧就漂移。
- `fetched_at` 要显示出来 + 一个刷新按钮，没有 TTL 兜底（§5.1）。
- 409 `COLUMN_ID_AMBIGUOUS` 要有文案分支，尽管它几乎不会出现。

---

## 10. 自查记录

**上游 spec 覆盖核对**

| 上游条目 | 落在哪 |
|---|---|
| §2.4 `GET /api/datasources/{id}/schema`「走缓存，`?refresh=1` 强制重拉」 | §5.1 |
| §2.4 `PATCH .../schema/columns/{col_id}`「人工补注释（F-201 AC1）」 | §3 + §5.2 |
| §2.5 `schema_cache` / `column_notes` 两张表 | §2（唯一键有一处有意偏离） |
| §2.5「注释单独存：`schema_cache` 会被 refresh 整体覆盖，人工补的注释不能跟着丢」 | §2.3 + §5.3 红线 |
| §4.5「prompt 里只放 schema 元数据（表名、列名、类型、注释）」 | §1（注释修复）+ §9 交接 |
| §4.5「表名/schema 名进 prompt 前过白名单」 | `known_identifiers()`，消费方在 P3 |
| §4.5 列示例值 | **推后到 P3**，见 §0 |
| §5.1 三层测试、契约测 skip 必须计数 | §7 |
| §5.3 Alembic up/down 双向 | 任务 2 |
| §8.1 验收项 11「自动拉取表结构，人工补的注释在 refresh 后不丢」 | §5.3 —— 本份的退出标准 |
| §6 `SchemaContextProvider` | **推后到 P3**，见 §0 |

**歧义检查**：`col_id` 是本份唯一一处上游没定义的东西，§3 把它定死了（含三条命中分支与两个错误码）。「refresh」只有一种触发方式（显式参数），没有 TTL 这条第二解释。「合并」明确为两字段并存，不是覆盖。

**写作过程中的回改两处**
1. **`updated_by` 一度想写 `SET NULL` + nullable**。查了 `user_router.py` 才确认现在**没有**删除用户的路径，于是用 `RESTRICT` 与 `datasources.created_by` 对齐，并在 §2.2 写明「将来加删除用户时再决定」。写 nullable 是为一个不存在的功能预留，而 nullable 的 `updated_by` 会让「注释一定有作者」这条性质失效。
2. **`col_id` 初稿是 `split(".")` 解析**。写 §3 时想到 Postgres 的 `create table "a.b"` 合法，改成反查。这一改顺带让 409 分支成为必要——解析式实现里歧义根本不可见。

**§1 的缺陷是实测的，不是读代码推断的**：跑了 `reflect()` 对 `chatbi_test` 的 `demo_sales`，拿到全列 `comment=None`，同时直接查 `col_description()` 拿到中文注释。§1.2 那张 `regtype` vs `format_type` 的对照表也是同一次实测的输出。

