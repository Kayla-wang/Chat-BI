# Chat-BI P2 设计文档：总体架构地图 + P2a 数据源接入与持久化

- **日期**: 2026-07-31
- **状态**: 设计已批准,待写实现计划
- **前序文档**: [2026-07-28-chatbi-p1-analysis-loop-design.md](./2026-07-28-chatbi-p1-analysis-loop-design.md)（P1 分析闭环）,[2026-07-27-chat-bi-design.md](./2026-07-27-chat-bi-design.md)（MVP）

## 概述与范围

P1 已经跑通「单轮提问 → 多系列图表 → 可信洞察 → 多轮下钻」的分析闭环,但它仍然是一个绑死在内置 SQLite 示例库上的单文件工具。目标产品要走完的链路是:

> 连接数据源 → 语义建模 → 对话产出图表 → 勾选图表组成布局 → 形成图片和链接

这条链路跨四个互相独立的子系统(数据源适配、语义层、元数据持久化、dashboard 编排),一份 spec 装不下。本文档因此分成两部分:**第一部分**是覆盖整条链路的总体架构地图(薄,只定边界与贯穿性约束),**第二部分**是 P2a 的可实施详细设计。P2b、P2c 各自再走一轮 spec → plan。

### 三段拆分

| 段 | 交付 | 依赖 | 可独立验收 |
|---|---|---|---|
| **P2a** 持久化 + 数据源 | `app.db` 与迁移框架、数据源 CRUD / 测连 / introspect 缓存、SQLite+MySQL+PostgreSQL 三个 driver + 方言层、`sqlGuard` 参数化、chat 请求带 `dataSourceId`、前端数据源管理页与选择器 | 无 | 连上自己的 MySQL 问出图 |
| **P2b** 语义层 | 语义模型表 + 建模 UI(选表、定 join、定维度/度量)、`QuerySpec` 契约、编译器(QuerySpec + 方言 → SQL)、LLM 改出 QuerySpec;**未建模的源继续走现有 Text2SQL** | P2a 的方言层与 schema 缓存 | 建模后问「销售额」得到模型定义的口径 |
| **P2c** 钉图 + 布局 + 分享 | 会话里「钉到看板」、Dashboard 网格布局编辑、`publicToken` 只读页(活链接)、前端 canvas 拼版导出 PNG | P2a 的持久化(**不依赖 P2b**,钉裸 SQL 也能钉) | 发一个链接给别人打开看到实时数据,导出一张 PNG |

### P2a 的成功标准

- 能在界面上新建一个 MySQL 或 PostgreSQL 数据源,测连通过后选中它提问,图表正常出。
- P1 手动验收清单那 9 条在「示例订单库」上全部仍然通过(回归基线;该基线已于 P1 结束时人工跑通)。
- 连接参数在 `app.db` 里是密文:`strings app.db | grep <密码>` 无命中。
- 对方言的差异有真实处理:同一个「按月汇总」问题在三种源上都能出正确的折线图。
- 拿一个有写权限的账号连库,界面上出现警告;拿只读账号连库,任何写操作被引擎拒绝。
- 切换数据源后下钻上下文被清空,不会拿上一个源的 SQL 去改写。

## 第一部分：总体架构地图

### 模块地图

```
                     ┌────────────── app.db(我们的元数据,P2a 新建)──────────────┐
                     │ data_sources │ schema_cache │ semantic_models │ saved_charts │
                     │    (P2a)     │    (P2a)     │     (P2b)       │  dashboards  │
                     └──────┬───────┴──────┬───────┴───────┬─────────┴──────┬(P2c)──┘
                            ▲              ▲               ▲                ▲
 ┌──────────┐  ①选源 ┌──────┴──────┐ ②建模 ┌──────┴─────┐ ③提问 ┌─────┴────┐ ④钉图 ⑤分享/导出
 │ 前端     │ ──────▶│ datasources/│◀─────│ semantic/  │◀─────│ chat 链路│──────▶ dashboards/
 │ React    │        │ registry    │      │ model      │      │(P1 已有) │        export
 │ Router   │        │ drivers/×3  │      │ compiler   │      └──────────┘
 └──────────┘        │ dialect     │      └────────────┘
                     └──────┬──────┘
                            ▼ 只读连接
              业务库:SQLite / MySQL / PostgreSQL
```

### 走完三段之后的单轮数据流

```
用户选定数据源 → 提问
  │
  ├─ 该源有语义模型? ──是──▶ LLM 输出 QuerySpec ──▶ 编译器(QuerySpec + Dialect)──▶ SQL
  │                  └─否──▶ LLM 输出 SQL(现有 Text2SQL)──▶ sqlGuard(SQL + Dialect)
  │
  ▼
driver.runQuery(只读连接 / 只读事务 + 服务端超时)
  │
  ▼
inferChartSpec(rows, columns, hint|querySpec)  →  ChartSpec
  │
  ├─▶ SSE result  →  insightFacts  →  insightDelta × N  →  done   【这一整段是 P1 原样,不动】
  │
  └─▶ 用户点「钉到看板」→ 存 { dataSourceId, source, chartConfig } → Dashboard 拖布局
                                                                      ├─▶ 分享链接(打开时重跑)
                                                                      └─▶ 导出 PNG(前端 canvas 拼版)
```

### 两条贯穿三段的约束

这两条现在就定下来,因为定错会导致后一段被迫回头改前一段的表结构。

**约束 1:钉图存「查询定义」,不存结果数据。**

链接是活的(打开时重新查库),所以 `saved_charts` 存的是:

```ts
{
  dataSourceId: string,
  source: { kind: "querySpec"; spec: QuerySpec } | { kind: "sql"; sql: string },
  chartConfig: ChartConfig,   // inferChartSpec 的推导参数,不是 ChartSpec
}
```

`chartConfig` 是 `chartType` / `stack` / x 轴字段 / series 字段 / `ValueFormat` 这些**推导参数**,而不是 `ChartSpec` 本身——后者含 `series[].data`,是某一时刻的数据快照。重跑查询后用同一份 `chartConfig` 推出同一形状的图,数据是新的。

`ChartConfig` 与 `QuerySpec` 这两个类型分别由 **P2c** 和 **P2b** 定义,**P2a 不要提前写它们**。上面的代码块是架构地图里的前向说明,不是 P2a 的交付物。

代价要说清楚:删掉一个数据源会让引用它的 Dashboard 卡片失效。处理方式是 `saved_charts.data_source_id` 用 `ON DELETE SET NULL`,卡片单独渲染成「数据源已移除」占位,**不级联删除 Dashboard**。

**约束 2:`ChartSpec` 与 `packages/shared/src/renderer.ts` 一个字不改。**

`ChartSpec` 已经是图表的单一来源。会话里的图、Dashboard 卡片里的图、导出 PNG 里的图,走的都是同一个 `renderer.ts`。三段都只在它**前面**接东西(换数据源、换 SQL 来源、换承载容器),不动它,也不再引入第二处 `buildOption`。

### 活链接的语义与已知代价

分享链接指向一个 Dashboard,打开时按每张卡片存的查询定义重跑,数据总是最新。代价:

- 打开有查询延迟(N 张卡片 = N 次查询),P2c 要做逐卡片加载而不是整页等待。
- 数据源不可达时,该卡片显示错误占位,其余卡片照常渲染。
- 分享页是**未认证**的只读入口,凭 `publicToken` 访问。这意味着 token 泄露等于数据泄露——P2c 必须用 `crypto.randomBytes` 生成不可猜的 token,并提供「停止分享」(吊销 token)。


## 第二部分：P2a 详细设计

### 1. app.db 与迁移框架

#### 两个库分开

| 文件 | 是什么 | 谁写 |
|---|---|---|
| `apps/backend/data/app.db` | **我们的元数据**:数据源、schema 缓存,以后加语义模型、看板 | 后端可写连接 |
| `apps/backend/data/chatbi.db` | 一个**恰好内置的业务示例源**,和用户自己的 MySQL 地位相同 | 现有 `migrate.ts` 灌示例订单数据,职责不变 |

现有 [`migrate.ts`](../../../apps/backend/src/migrate.ts) 只负责示例业务数据(无条件跑 `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE`),不动它。app.db 需要一个**记版本的**迁移框架,新文件 `appDb/migrations.ts`:

```ts
export const MIGRATIONS: { id: number; name: string; sql: string }[] = [
  { id: 1, name: "data_sources", sql: `...` },
  { id: 2, name: "schema_cache", sql: `...` },
  { id: 3, name: "seed_builtin_source", sql: `...` },
];
```

启动时:建 `schema_migrations(id INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)`,查出已应用的 id,按序在**单个事务**里补跑缺的。P2b / P2c 只往数组末尾追加,不改前面的条目。迁移失败沿用现有做法 `process.exit(1)`,但错误信息必须打印是哪一号迁移失败(现有 `startServer` 只打印 `migration failed:`,信息不足)。

#### 表结构

```sql
CREATE TABLE data_sources (
  id             TEXT PRIMARY KEY,          -- crypto.randomUUID(),零新依赖
  name           TEXT NOT NULL UNIQUE,
  kind           TEXT NOT NULL,             -- 'sqlite' | 'mysql' | 'postgres'
  config_cipher  BLOB NOT NULL,             -- 连接参数 JSON 的密文
  config_iv      BLOB NOT NULL,             -- AES-256-GCM 的 12 字节 IV
  config_tag     BLOB NOT NULL,             -- 16 字节认证标签
  owner          TEXT NOT NULL DEFAULT 'local',   -- 多用户留的接口,现在恒为 'local'
  write_probe    TEXT,                      -- 'readonly' | 'writable' | 'unknown'
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  last_check_at  TEXT,
  last_check_ok  INTEGER,                   -- 0 / 1
  last_check_error TEXT
);

CREATE TABLE schema_cache (
  data_source_id TEXT PRIMARY KEY REFERENCES data_sources(id) ON DELETE CASCADE,
  schema_json    TEXT NOT NULL,             -- TableSchema[] 原样序列化,契约不变
  fetched_at     TEXT NOT NULL
);
```

`owner` 现在恒为 `'local'`,存在的意义是将来加登录时不用改表结构、不用回填数据。这是唯一为多用户留的余地,不再多留。

外键要生效必须 `PRAGMA foreign_keys = ON`——better-sqlite3 默认是关的,`ON DELETE CASCADE` 会静默失效。这行 pragma 在打开 app.db 连接时立刻执行,并且要有一个测试断言删数据源后 `schema_cache` 确实空了。

#### schema 缓存的刷新策略

远程库 introspect 要查 `information_schema`,是好几个往返;而每一轮对话都要拿它拼 prompt。所以必须缓存:首次连接成功时自动抓一次,之后**只有显式刷新**才重抓。

**不做 TTL。** 隐式过期解释不清(「为什么我刚加的列问不到」/「为什么这次变慢了」),也不能真正解决问题——DDL 变更和 TTL 到期没有相关性。取而代之:

- 数据源管理页有「刷新结构」按钮,显示上次抓取时间。
- 查询报「列/表不存在」类错误时(见第 9 节的错误分类),错误提示里直接带一句「表结构可能已变更,试试刷新结构」。

#### 内置示例源

迁移 3 号插入一条记录:`kind='sqlite'`、`name='示例订单库'`、config 指向 `config.dbPath`。「开箱即跑」不退化,首次启动就有一个可问的源被默认选中。它的 config 同样走加密路径(不给内置源开后门,否则加解密路径就有两条)。

因为这条记录引用 `config.dbPath`,**启动顺序有依赖**,`startServer` 必须按这个次序:

1. 现有的示例业务库迁移(可写连接跑 `migrate.ts`,建表灌数据,然后关闭)——保证 `chatbi.db` 存在,否则内置源的只读连接打不开。
2. `loadKey()`(缺失时生成 `data/app.key`)。
3. 打开 app.db、`PRAGMA foreign_keys = ON`、`runMigrations()`——迁移 3 号此时才加密写入内置源的 config。
4. 建 registry(不建任何连接,懒建)。
5. 挂路由并监听。

第 3 步依赖第 2 步(要加密),第 1 步与第 3 步的顺序不能颠倒。**不做启动时全量测连**——那会把启动时间拖成 N 个连接超时之和。

### 2. 凭据加密与威胁模型

用 `node:crypto` 的 AES-256-GCM,零新依赖。新文件 `appDb/secrets.ts`,只有两个纯函数 + 一个密钥加载:

```ts
export function encryptJson(value: unknown, key: Buffer): { cipher: Buffer; iv: Buffer; tag: Buffer };
export function decryptJson<T>(parts: { cipher: Buffer; iv: Buffer; tag: Buffer }, key: Buffer): T;
export function loadKey(): Buffer;   // 见下
```

**密钥来源**,按优先级:

1. `APP_KEY` 环境变量,32 字节的 base64。
2. 没设置时读 `data/app.key`;文件不存在则 `crypto.randomBytes(32)` 生成并写入,权限 `0o600`。

零配置就能跑,又不是明文。GCM 的认证标签顺带提供完整性校验——手改过的密文会解密失败而不是产出垃圾。

**威胁模型,写明白不夸大**:

- **防住**:`app.db` 被误提交进 git、被随手拷走、被日志/备份带出去。
- **防不住**:能读本机文件系统的攻击者——钥匙就在 `data/app.key`,隔壁而已。
- 这是本机单用户工具的合理档位。将来做多用户时换成用户口令派生(scrypt/argon2)或外部 KMS,`secrets.ts` 的两个函数签名不用变,只换 `loadKey`。

**跨平台诚实说明**:`fs.chmod(0o600)` 在 Windows 上基本无效果(NTFS ACL 不由 mode 位控制)。README 必须直说:Windows 下 `data/app.key` 的保护等于该目录的 ACL,别把 `data/` 放在共享目录里。

**`.gitignore` 核对过**:现有规则里的 `data/` 与 `*.db` 已经覆盖 `data/app.db` 和 `data/app.key`,不需要新增。但要补一条 `*.key` 作为第二道保险——万一有人把密钥挪到别的目录,`data/` 就不管了;密钥和密文一起进 git 等于没加密。

**解密失败不能让服务起不来**(换过 `APP_KEY`、`app.key` 丢了、文件损坏)。行为:

- 启动时不解密任何 config(懒解密,用到才解)。
- 列表接口对解密失败的源返回 `status: 'needs_reconfig'`,前端渲染成红色「凭据无法解密,请重新填写连接信息」并允许直接进编辑表单。
- 用它提问时走 SSE `error`,消息同上。
- 不自动删除记录——名字和 id 还有用,Dashboard 卡片还引用着它。

### 3. 驱动接口与方言层

#### 接口

窄口:所有实现只暴露五件事,多一件都不行。

```ts
// datasources/driver.ts
export type DataSourceKind = "sqlite" | "mysql" | "postgres";

export interface QueryResult { rows: Row[]; truncated: boolean }

export type TestResult =
  | { ok: true; writePrivilege: WritePrivilege }
  | { ok: false; code: DsErrorCode; message: string; details?: string };

export type WritePrivilege = "readonly" | "writable" | "unknown";

export interface Driver {
  readonly kind: DataSourceKind;
  readonly dialect: Dialect;
  testConnection(): Promise<TestResult>;
  introspect(): Promise<TableSchema[]>;
  runQuery(sql: string, limit: number, timeoutMs: number): Promise<QueryResult>;
  probeWritePrivilege(): Promise<WritePrivilege>;
  close(): Promise<void>;
}
```

`testConnection()` 内部**就是**「连一次 + 调 `probeWritePrivilege()`」,把结果一并返回;`probeWritePrivilege()` 单独暴露只是为了能单测和以后重探。调用方(路由)拿 `TestResult.writePrivilege` 就够,**不要再单独调一次探测**——那会多打一次库,且两次结果可能不一致。

`TableSchema` 沿用 `packages/shared` 里现有的定义,不改一个字段——三种源都能填满 `columns` 与 `foreignKeys`。类型名(MySQL 的 `varchar(64)`、PG 的 `character varying`)原样透传,`columnTypes.ts` 的角色分类(temporal / categorical / numeric)据此判断,所以它的关键字表要相应扩充(见第 6 节)。

`runQuery` 的 `truncated` 语义与现在完全一致:调用方注入 `LIMIT limit + 1`,driver 取回后切片并报告是否多出来过。三种源的 `LIMIT n` 语法相同,`enforceLimit` 不需要方言分支。

#### 每种源的连接参数

```ts
type DsConfig =
  | { kind: "sqlite";   path: string }
  | { kind: "mysql";    host: string; port: number; database: string; user: string; password: string; ssl: boolean }
  | { kind: "postgres"; host: string; port: number; database: string; user: string; password: string; ssl: boolean; schema?: string };
```

`ssl: boolean` 而不是完整 TLS 配置:`true` 时 `rejectUnauthorized` 保持默认的 `true`。自定义 CA、客户端证书、SSH 隧道都不做(见「明确不做」)。PG 的 `schema` 可选,缺省 `public`——PG 的多 schema 是常态,introspect 时必须按它过滤,否则会把 `pg_catalog` 里几百张系统表全抓进 prompt。

新增两个后端依赖:`mysql2`(用其 promise 接口)与 `pg`。

#### 方言层

```ts
// datasources/dialect.ts
export interface Dialect {
  kind: DataSourceKind;
  quoteIdent(name: string): string;                     // `x` / "x"
  sqlParserDialect: "sqlite" | "mysql" | "postgresql";  // 喂 node-sql-parser
  promptNotes: string;                                  // 注入 prompt 的方言提示
}
```

只有三个成员,因为 P2a 里只有这三样真的被调用:

- `quoteIdent` —— 给 introspect 拼 `information_schema` 查询和 schema 渲染用。
- `sqlParserDialect` —— `sqlGuard` 的 AST 解析要按方言走,否则 MySQL 的反引号、PG 的 `::` 转换会被判成解析失败而退回正则兜底。
- `promptNotes` —— P2a 的 SQL 仍由 LLM 写,方言差异靠 prompt 告知。每种源一段短文本,举时间截断与字符串拼接的例子:

  | 源 | 按月截断 | 引号 |
  |---|---|---|
  | SQLite | `strftime('%Y-%m', order_date)` | `"col"` |
  | MySQL | `DATE_FORMAT(order_date, '%Y-%m')` | `` `col` `` |
  | PostgreSQL | `to_char(date_trunc('month', order_date), 'YYYY-MM')` | `"col"` |

**`truncateTime(expr, grain)` 留给 P2b**。P2a 没有调用者——SQL 是 LLM 写的,`promptNotes` 里的示例是硬编码文本。现在实现一个没人调的方法是坏味道;P2b 的编译器需要它时再加,那时它立刻有测试和调用方。

`promptNotes` 由 `promptBuilder` 插入现有 SYSTEM 提示词之后。SYSTEM 里第 1 条「只生成 SELECT」等规则与方言无关,不动。

### 4. 只读保证

接远程库是 P2a 引入的**真实新增攻击面**:P1 的根本防线是「只读打开 SQLite 文件」,这个手段在 MySQL / PG 上不存在。三道防线,从弱到强:

| 防线 | SQLite | MySQL | PostgreSQL |
|---|---|---|---|
| ① `sqlGuard` | 现状 AST 校验 + 方言禁用词 | 同 | 同 |
| ② 会话/事务级只读 | `new Database(path, { readonly: true })`,**引擎硬拒** | `SET SESSION TRANSACTION READ ONLY`,可被显式 `START TRANSACTION` 绕过 | 每次查询包进 `BEGIN READ ONLY` … `COMMIT`,**服务端硬拒写** |
| ③ 账号权限 | 文件系统权限 | 文档要求配只读账号 + 写权限探测警告 | 同 |

结论要诚实:**MySQL 的只读性质上弱于 PG**。PG 的只读事务由服务端强制,写语句直接报 `read-only transaction`;MySQL 的会话级设置理论上可被 SQL 里显式开启的新事务覆盖。所以 MySQL 更依赖 ③,README 与新建表单里都要显著提示配只读账号。

#### `sqlGuard` 参数化

`validate(sql)` → `validate(sql, dialect)`。改动两处:

1. AST 解析的方言参数从硬编码 `"sqlite"` 换成 `dialect.sqlParserDialect`。
2. 禁用词表 = 现有通用表 + 按方言的逃逸口:

| 方言 | 追加禁用 | 为什么 |
|---|---|---|
| MySQL | `INTO OUTFILE`、`INTO DUMPFILE`、`LOAD_FILE`、`LOAD DATA` | 读写服务器文件系统 |
| PostgreSQL | `COPY`、`pg_read_file`、`pg_read_binary_file`、`pg_ls_dir`、`dblink`、`pg_sleep`、`lo_import`、`lo_export` | 读文件、发起外连、拖死连接 |
| 通用(已有) | `INSERT`/`UPDATE`/`DELETE`/`DDL`/堆叠查询/注释 | 现状,不变 |

这些是 `SELECT` 语句内部就能触发的能力,AST 校验「是不是 SELECT」拦不住,必须显式列。现有那条「不误杀 `SELECT '已delete' AS status`」的测试原则继续保持:禁用词匹配只看 AST 里的函数名与语句结构,不是对原文做子串搜索。AST 解析失败退回加固正则时,正则同样按方言选表(与现状一致地保守)。

#### 写权限探测

`probeWritePrivilege()` 在测连时调用一次,结果存 `data_sources.write_probe`,只用来在界面上挂警告,**永不拦截连接**——用户可能就是只有一个可写账号,拦了他就没法用。

| 源 | 探测方式 |
|---|---|
| SQLite | 只读连接恒返回 `readonly` |
| MySQL | `SHOW GRANTS FOR CURRENT_USER()`,出现 `INSERT`/`UPDATE`/`DELETE`/`ALL PRIVILEGES`/`SUPER` 即 `writable` |
| PostgreSQL | `information_schema.table_privileges` 里当前用户有 `INSERT`/`UPDATE`/`DELETE`,或 `has_schema_privilege(current_user, <schema>, 'CREATE')`,或 `current_setting('is_superuser') = 'on'` 即 `writable` |

三种探测都是只读查询、零副作用。任何一种解析不出结果就返回 `unknown`(不撒谎说安全),界面上显示灰色「权限未知」。

探到 `writable`:数据源卡片挂黄色提示「此账号有写权限,建议改用只读账号」。这条恰好补上 MySQL 会话只读可被绕过的那个洞——把「我们拦不住」变成「我们至少告诉你」。

### 5. 超时与连接管理

#### 超时必须真取消

现有 `wrapTimeout` 是 `Promise.race`。对本机 SQLite 无害(同步执行,要么已经返回要么还在阻塞);对远程库则意味着「我们不等了,但对方还在跑」——用户连问三次慢查询,库上就攒了三个还在扫全表的连接。

所以超时下推到服务端:

| 源 | 手段 |
|---|---|
| SQLite | 现状不变(同步执行 + `wrapTimeout` 兜底) |
| MySQL | 连接建立时 `SET SESSION max_execution_time = <ms>`;`mysql2` 的 `timeout` 选项作为客户端兜底 |
| PostgreSQL | 只读事务里 `SET LOCAL statement_timeout = <ms>` |

`wrapTimeout` 保留,作为「服务端超时没生效」的最后兜底,但它的超时值要比服务端的**稍大**(例如 `timeoutMs + 500`),否则客户端先跳、服务端的取消永远不会被触发,等于白设。

`QUERY_TIMEOUT_MS` 的语义从「SQLite 执行超时」扩展为「任何数据源的单次查询超时」,默认值 5000 不变。README 的说明要改。

#### 连接管理

单用户,**不做连接池**。`datasources/registry.ts` 按 `dataSourceId` 缓存活的 `Driver` 实例,懒建:

- 第一次用到某个数据源时解密 config、建连、探一次连通性。
- 之后复用同一个实例。
- 数据源被编辑或删除时,立刻 `close()` 并从缓存移除(否则会拿旧凭据继续查)。
- 进程退出(`SIGINT` / `SIGTERM`)时遍历关闭。

不做空闲超时关闭:单用户场景下常驻一两个连接的成本远低于「每次查询都重连」的延迟,也远低于空闲检测的复杂度。如果以后发现云库主动切空闲连接,再在 `runQuery` 外面加一层「连接已断则重连一次」——那时它才有明确的触发场景。

`mysql2` / `pg` 的单连接对象都不是并发安全的多路复用器,但 SSE 一轮问答里同一时刻只有一个查询在跑,单用户下不会并发。这个假设写进注释,将来做多用户时它是必须回头看的地方。

### 6. 契约变更清单

P2a 会破坏几个现有契约。全列在这里,方便实施时逐条改、逐条改测试。

| # | 契约 | 现状 | 改成 | 影响 |
|---|---|---|---|---|
| 1 | `ChatDeps.db.runQuery` | 同步返回 `{rows, truncated}` | 返回 `Promise<QueryResult>` | `chatService.ts` 里已经用 `Promise.resolve().then(...)` 包着,改成 `await` 即可,其余逻辑不动 |
| 2 | `ChatDeps.db.getSchema` | 同步返回 `TableSchema[]` | 返回 `Promise<TableSchema[]>`(读缓存,缓存缺失时 introspect) | `handleChat` 第一行加 `await` |
| 3 | `sqlGuard.validate` | `validate(sql)`,内部硬编码 sqlite | `validate(sql, dialect)` | 所有 `sqlGuard` 测试要传 dialect;新增每方言的禁用词测试 |
| 4 | `POST /api/chat` body | `{question, history, context?}` | 增 `dataSourceId: string`(必填) | 前端 `api.ts` 与后端路由;缺失时走 SSE `error` |
| 5 | `ChatDeps` 组装位置 | `server.ts` 里建一个全局只读 `DbClient` | 每轮请求按 `dataSourceId` 从 registry 取 driver | `server.ts` 的 deps 从「一个 db」变成「一个 registry」 |
| 6 | `columnTypes.ts` 的类型关键字表 | 只覆盖 SQLite 类型名 | 追加 MySQL / PG 的类型名 | `datetime`/`timestamptz`/`character varying`/`numeric`/`double precision`/`bigint` 等;判定仍是「类型名包含关键字」的现有策略 |
| 7 | `DbClient` 的角色 | 通用 SQLite 客户端 | 拆成两个用途:`appDb/`(可写,元数据)与 `drivers/sqlite.ts`(只读,数据源) | 现有 `DbClient` 保留给 app.db,`execRaw` 的「只读连接禁用」保护继续有效 |

第 4 条是破坏性的 API 变更。前后端同仓、单用户、无外部调用方,**直接改,不做兼容层**——留一个「`dataSourceId` 缺失时回落到内置源」的兼容分支,只会让「为什么问的是另一个库」变成难查的 bug。

`StreamEvent` 契约不变:`result` / `insightFacts` / `insightDelta` / `done` / `error` 五种事件一个不加不减。数据源相关的错误全部走 `error` 事件,前端不需要新的事件处理分支。

### 7. HTTP API

新路由 `routes/datasources.ts`,普通 JSON REST(不用 SSE——这些都是短请求)。

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/datasources` | 列表 |
| `POST` | `/api/datasources` | 新建(先测连) |
| `PUT` | `/api/datasources/:id` | 修改 |
| `DELETE` | `/api/datasources/:id` | 删除 |
| `POST` | `/api/datasources/test` | 测连未保存的表单内容 |
| `POST` | `/api/datasources/:id/test` | 重测已存源 |
| `POST` | `/api/datasources/:id/refresh-schema` | 重抓结构写缓存 |
| `GET` | `/api/datasources/:id/schema` | 取缓存的 `TableSchema[]` |

#### 列表返回什么

**密码永不出后端。** 列表项:

```ts
interface DataSourceSummary {
  id: string;
  name: string;
  kind: DataSourceKind;
  target: string;              // 脱敏摘要:"mysql://bi_ro@10.0.0.5:3306/sales" 或 "./data/chatbi.db"
  status: "ok" | "error" | "needs_reconfig" | "unchecked";
  writePrivilege: WritePrivilege;
  lastCheckAt: string | null;
  lastCheckError: string | null;
  schemaFetchedAt: string | null;
  tableCount: number | null;
}
```

`target` 由 config 拼装,**不含密码**。`GET /api/datasources/:id` 返回同样的东西加上非敏感的 config 字段(host / port / database / user / ssl),密码位置返回 `hasPassword: boolean`。

#### 新建与修改的语义

- `POST` 先跑一次 `testConnection()`。失败返回 `400 { code, message, details?, canForce: true }`,**不落库**——避免攒一堆连不上的僵尸源。
- 但「库临时不可达而配置正确」是真实场景,所以前端在失败提示里给一个「仍然保存」,二次提交带 `force: true` 时跳过测连直接存,`status` 记为 `error`。
- 测连成功时同一次请求里顺带 `introspect()`,把 schema 写进缓存,写权限用 `TestResult.writePrivilege`。新建一次到位,用户不用再点刷新。
- `PUT` 的 `password` 字段留空 = 不改密码(读出旧 config 只替换其余字段);显式传空字符串 = 真的把密码设为空。这两种要在 API 层区分:字段缺失 vs 字段为 `""`。
- `PUT` 与 `DELETE` 之后必须让 registry 关闭并丢弃该源的缓存连接。
- `name` 唯一约束冲突返回 `409`,消息是「已有同名数据源」,不是 SQLite 的原生报错。

#### 错误响应统一形状

```ts
{ code: DsErrorCode; message: string; details?: string; canForce?: boolean }
```

`message` 是给人看的中文,`details` 是原生错误原文(前端折叠在「查看详情」里)。所有数据源相关的 HTTP 错误都用这个形状,前端一处渲染。

### 8. 前端改动

#### 引入路由

现在 `App = AppShell > ChatWindow`,没有路由。P2a 引入 `react-router-dom`(**唯一的新前端依赖**),只挂两条:

```
/              → ChatPage(现有 ChatWindow)
/datasources   → DataSourcesPage
```

为什么 P2a 就加:P2c 的分享页需要真实路径 `/s/:token`(发给别人的链接带 `#` 很难看,也不利于以后加服务端渲染),Dashboard 需要 `/d/:id`。P2a 把路由基建做掉,P2c 加两条 route 就是零成本。Vite dev server 与将来的静态托管都需要 history fallback,这一条写进 README(现有 README 的「已知限制」里已经提过后端不托管静态文件)。

#### 数据源选择器

放在 `AppShell` 顶栏,右边跟一个「管理」链接进 `/datasources`。

- 选中项记进 `localStorage`(键 `chatbi.selectedDataSourceId`),刷新页面不丢。
- 启动时校验:localStorage 里的 id 不在列表中(被删了)则回落到第一个可用源。
- 列表为空时(理论上不会,内置源总在)选择器显示「无可用数据源」,输入框禁用并提示去添加。
- 选中源的 `status` 是 `error` / `needs_reconfig` 时,选择器上挂状态点,提问前就能看出来。

#### 切源必须清空下钻上下文

`DrillContext.lastSql` 是**上一个源的方言和表名**。带着它去另一个源提问,LLM 会在错误的 SQL 上改写,产出必然报错的查询,而且报错原因看起来像模型能力问题,极难查。

所以:数据源选择变化时,`ChatWindow` 清空 `DrillContext`;历史消息保留在界面上(用户还想看之前的图),但**不再作为 LLM 的 history 传回**,并在会话流里插一条分隔提示「已切换到数据源 X,后续提问基于新数据源」。这条分隔提示是必要的:否则用户会以为上下文还连着。

#### 数据源管理页

一页搞定,不做多级导航:

- 列表:每行 name / kind 图标 / `target` / 状态点 / 上次检查时间 / 表数量;`writable` 时挂黄色警告徽标,`unknown` 时灰色。
- 行内操作:测连、刷新结构、编辑、删除(删除要二次确认,并提示「引用它的看板卡片会失效」)。
- 新建 / 编辑表单:kind 选择 → 按 kind 显示不同字段 → 「测试连接」按钮就地反馈(成功显示表数量,失败显示可读消息 + 可折叠详情 + 「仍然保存」)。
- 表结构预览:展开一个源看到 `TableSchema[]`——表名、列名与类型、外键。P2b 的建模 UI 会复用这个组件,所以现在就把它拆成独立组件 `SchemaTree`,不要写在页面里。

#### 视觉一致性

严格沿用 P1b 建立的设计系统:颜色只从 `theme/tokens.css` 的 CSS 变量取,不写颜色字面量;不用内联 `style={{}}`;每个组件配 `.module.css`。状态色(成功 / 警告 / 错误)如果 tokens 里还没有,就**加进 tokens.css 并按 WCAG 验算对比度**,不在组件里硬编码——P1b 的三条 grep 检查(`style={{`、组件内颜色字面量、旧模块名)在 P2a 之后必须仍然零命中。

### 9. 错误分类与降级

#### 错误分类

```ts
export type DsErrorCode =
  | "CONNECTION_ERROR"   // 连不上:ECONNREFUSED / ENOTFOUND / ETIMEDOUT / 端口不通
  | "AUTH_ERROR"         // 认证失败:ER_ACCESS_DENIED_ERROR / 28P01
  | "DB_NOT_FOUND"       // 库/文件不存在:ER_BAD_DB_ERROR / 3D000 / SQLITE_CANTOPEN
  | "TIMEOUT"            // 查询超时(服务端掐或客户端兜底)
  | "SQL_ERROR"          // 语法错、表/列不存在、类型不匹配
  | "SCHEMA_STALE"       // SQL_ERROR 的子类:表/列不存在
  | "PERMISSION_ERROR"   // 有连接但无权读该表
  | "DECRYPT_ERROR"      // 凭据无法解密
  | "UNKNOWN";
```

每种 driver 负责把原生错误映射到这张表:MySQL 看 `err.code` / `errno`,PG 看 `err.code`(SQLSTATE),SQLite 看 `err.code`。映射逻辑是纯函数(`drivers/errors.ts`),单测直接喂假错误对象,不需要真数据库。

`message` 一律是可读中文,例如「无法连接到 10.0.0.5:3306,请检查地址、端口与网络」;原生英文原文进 `details`。**不把 `ECONNREFUSED` 直接甩给用户**。

#### 重试策略必须按错误分类

现有 [`chatService.ts`](../../../apps/backend/src/chatService.ts) 的 `attempt` 循环对**任何**执行异常都重试一轮——那是给「LLM 写错 SQL」设计的,把错误原因喂回模型让它改。接了远程库以后这个行为会有害:

| 错误类型 | 重试? | 为什么 |
|---|---|---|
| `SQL_ERROR` | **是**(现状) | 喂回错误原因,模型能改对 |
| `SCHEMA_STALE` | **是**,但错误消息里追加「表结构可能已变更,试试刷新结构」 | 模型可能用了缓存里没有的列;若确是库变了,重试也会失败,提示引导用户刷新 |
| `CONNECTION_ERROR` / `AUTH_ERROR` / `DB_NOT_FOUND` / `TIMEOUT` / `PERMISSION_ERROR` / `DECRYPT_ERROR` | **否** | 重试只是让用户多等一个超时;错误与 SQL 内容无关,模型改不了 |

不可重试的错误直接 `yield { type: "error", message }` 结束。这是 P2a 里最容易被漏掉的正确性改动——现有代码的 `catch` 是不分类的。

#### 洞察降级不受影响

第二轮 LLM(洞察)的降级逻辑是 P1 建立的、与数据源无关,不动:洞察超时或失败仍然只降级为模板文本,图表照常。

#### 启动期的健壮性

| 情况 | 行为 |
|---|---|
| app.db 迁移失败 | `process.exit(1)`,打印失败的迁移号与原生错误 |
| `app.key` 生成失败(目录不可写) | `process.exit(1)`,提示检查 `data/` 目录权限 |
| 某个数据源连不上 / 解密失败 | **服务正常启动**,该源在列表里显示对应状态;不做启动时全量测连(会把启动时间拖成 N 个超时之和) |
| 内置示例源的 sqlite 文件缺失 | 现有 `migrate` 会重建,行为不变 |

### 10. 文件与模块布局

```
apps/backend/src/
  appDb/
    index.ts          打开 app.db(可写 + PRAGMA foreign_keys = ON)
    migrations.ts     MIGRATIONS 数组 + runMigrations()
    secrets.ts        encryptJson / decryptJson / loadKey
    dataSourceRepo.ts 数据源与 schema_cache 的 CRUD(唯一碰 SQL 的地方)
  datasources/
    driver.ts         Driver / QueryResult / TestResult / WritePrivilege 接口
    dialect.ts        三个 Dialect 常量对象
    errors.ts         原生错误 → DsErrorCode 的纯函数映射
    registry.ts       按 id 缓存 Driver、懒建、失效关闭、退出时全关
    drivers/
      sqlite.ts       包现有 DbClient 的只读模式
      mysql.ts        mysql2/promise
      postgres.ts     pg
  routes/
    chat.ts           改:取 dataSourceId → registry.get → 组装 deps
    datasources.ts    新:8 个端点
  sqlGuard.ts         改:validate(sql, dialect)
  columnTypes.ts      改:类型关键字表扩充 MySQL / PG
  promptBuilder.ts    改:插入 dialect.promptNotes
  chatService.ts      改:await runQuery / getSchema;错误按 DsErrorCode 分类重试
  dbClient.ts         保留,现在只服务 app.db 与 sqlite driver

apps/frontend/src/
  routes.tsx          两条路由
  pages/
    ChatPage.tsx        壳,内含现有 ChatWindow
    DataSourcesPage.tsx 列表 + 表单 + 结构预览
  components/
    DataSourcePicker.tsx  顶栏选择器
    DataSourceForm.tsx    按 kind 变化的表单 + 测连反馈
    SchemaTree.tsx        表结构预览(P2b 建模 UI 复用)
    StatusBadge.tsx       状态点 / 写权限警告徽标
  api.ts                改:chat 带 dataSourceId;新增 datasources 的 8 个调用
```

三条边界原则:

1. **只有 `dataSourceRepo.ts` 写 app.db 的 SQL。** 路由和 registry 都通过它,不散落 SQL 字符串。
2. **只有 `drivers/*.ts` 知道 `mysql2` / `pg` / `better-sqlite3` 的存在。** 上层只见 `Driver` 接口。测试可以塞假 driver。
3. **只有 `errors.ts` 知道原生错误码长什么样。** driver 捕获后立刻映射,不把原生错误往上抛。

按这个划分,单个文件都不大:最大的是 `datasources.ts` 路由(8 个端点)与 `DataSourcesPage.tsx`,都在两三百行量级。`postgres.ts` 因为要处理 schema 过滤和只读事务,是三个 driver 里最长的。

### 11. 测试策略

沿用现有做法:vitest,依赖注入桩,不碰网络。新增的重点是**一套契约测试跑三个 driver**。

#### 驱动契约测试

`datasources/drivers/contract.ts` 导出一个 `runDriverContract(name, setup)`,里面是与实现无关的断言:

| 断言 | 内容 |
|---|---|
| introspect 一致 | 建一张同构小表(含主键、非空列、外键、一个时间列、一个数值列),三种源 `introspect()` 出的 `TableSchema` 在表名/列名/notNull/pk/外键上一致(类型名允许各自不同) |
| 查询结果一致 | 同一语义的查询(按月分组求和)各方言写一遍,行数、排序、数值相等 |
| truncated 探测 | 插 `limit + 2` 行,断言 `rows.length === limit` 且 `truncated === true`;插 `limit` 行时 `truncated === false` |
| 写操作被拒 | `INSERT` / `CREATE TABLE` 抛错(SQLite 靠只读连接,PG 靠只读事务,MySQL 允许此项标记为 `expected-weak` 并断言 `probeWritePrivilege()` 至少报出 `writable`) |
| 超时被掐 | 一个必然慢的查询(递归 CTE / `pg_sleep` 的替代:大笛卡尔积)在 `timeoutMs` 后抛 `TIMEOUT`,且**服务端侧也结束**(PG 可用 `pg_stat_activity` 断言,MySQL/SQLite 只断言客户端抛错) |
| 错误映射 | 连错端口 → `CONNECTION_ERROR`;错密码 → `AUTH_ERROR`;查不存在的表 → `SCHEMA_STALE` |

`sqlite` **无条件跑**。`mysql` / `postgres` 读环境变量 `TEST_MYSQL_URL` / `TEST_PG_URL`:

- 变量存在 → 跑全套。
- 变量不存在 → `describe.skip`,并且 **在控制台打印一行「跳过 MySQL 契约测试:未设置 TEST_MYSQL_URL」**。静默跳过会让「全绿」变成假的,这一点比测试本身重要。
- 测试用独立的库名或 schema 前缀(`chatbi_test_*`),用后清理。

#### 不需要真数据库的测试

这些占绝大多数,是 CI 的主体:

| 模块 | 测什么 |
|---|---|
| `secrets.ts` | 加密-解密往返;篡改密文 / IV / tag 任一都解密失败;不同 IV 产出不同密文 |
| `migrations.ts` | 空库跑到最新;重复跑是幂等的;中途失败整体回滚(事务);已应用的迁移不重跑 |
| `dataSourceRepo.ts` | CRUD;同名冲突;删源级联删 `schema_cache`(顺带验证 `PRAGMA foreign_keys`真的开了) |
| `dialect.ts` | 三个方言的 `quoteIdent` / `sqlParserDialect` / `promptNotes` 非空且互不相同 |
| `errors.ts` | 各原生错误码 → `DsErrorCode` 的映射表逐条断言;未知错误 → `UNKNOWN` |
| `sqlGuard.ts` | 每方言的禁用词各一条(`INTO OUTFILE` / `pg_read_file` / …);**现有「不误杀 `SELECT '已delete' AS status`」的测试继续通过**;AST 解析失败退回正则的路径 |
| `registry.ts` | 懒建只建一次;编辑/删除后连接被 close;假 driver 注入 |
| `chatService.ts` | 按 `DsErrorCode` 决定重试:`SQL_ERROR` 重试一轮,`CONNECTION_ERROR` 立刻 `error` 不重试(用假 driver 断言调用次数) |
| `routes/datasources.ts` | 8 个端点的响应形状;密码不出现在任何响应体里(对整个 JSON 做子串断言);`force: true` 跳过测连;`PUT` 时密码字段缺失 vs `""` 的区别 |
| 前端组件 | 选择器切换触发上下文清空;表单按 kind 切字段;测连失败渲染消息 + 详情折叠 + 「仍然保存」;`SchemaTree` 渲染;`StatusBadge` 三种状态 |

#### 回归基线

`npm test --workspaces` 在 P2a 完成后必须仍然全绿。P1 留下的 267 个测试里,受契约变更影响的(`sqlGuard`、`chatService`、`chat.route`、`api`)要改签名而不是删断言——**任何一条被删掉的断言都要在 spec review 或 code review 里说明理由**。

### 12. 手动验收清单

自动化测试用桩,验不了「LLM 在真实方言下写出的 SQL 是否合理」,也验不了界面。发版前人工跑。

#### A. P1 回归(在「示例订单库」上,9 条原样)

P1 的手动验收清单 9 条必须全部仍然通过。它们是回归基线——P2a 改了 `promptBuilder`、`sqlGuard`、`chatService`、`columnTypes` 四个链路上的模块,不跑这 9 条就分不清新旧问题。清单见 [README 的「手动验收清单」](../../../README.md)。

#### B. P2a 新增

1. 新建一个 MySQL 数据源(只读账号)→ 测连成功,显示表数量 → 选中它问「按月统计订单金额」→ 出正确折线图,SQL 里是 `DATE_FORMAT` 而不是 `strftime`。
2. 同上换 PostgreSQL → 出图,SQL 里是 `date_trunc` / `to_char`。
3. 故意填错端口 → 提示「无法连接到 …」,不是 `ECONNREFUSED`;展开详情能看到原文。
4. 故意填错密码 → 提示认证失败。
5. 连不上时点「仍然保存」→ 记录存下来,列表里状态是红点。
6. 用**有写权限**的账号连一个库 → 卡片上出现黄色「建议改用只读账号」警告。
7. 在库里 `ALTER TABLE` 加一列 → 直接问新列,报错提示带「试试刷新结构」→ 点刷新 → 再问,能问到。
8. 在 A 源上做完一轮下钻(「按月统计订单金额」→「只看华东区」),切换到 B 源 → 会话里出现「已切换到数据源 B」分隔提示 → 问「按周看」→ **不是**在 A 的 SQL 上改写(展开 SQL 确认)。
9. 对只读账号执行写操作:直接问「删除所有订单」→ 被 `sqlGuard` 拦(消息说明非只读);若模型绕过校验生成了写语句,PG 的只读事务应报 `read-only transaction`。
10. 一个必然慢的查询 → 在 `QUERY_TIMEOUT_MS` 后报超时;去库上看会话/进程,确认查询已结束而不是还在跑。
11. 删除一个数据源 → 二次确认提示提到「引用它的看板卡片会失效」→ 删除后 `schema_cache` 里对应行也没了(可用 sqlite CLI 确认)。
12. `strings apps/backend/data/app.db | grep <你的数据库密码>` → **无命中**。
13. 删掉 `data/app.key` 重启 → 服务能起来,数据源显示「凭据无法解密,请重新填写」,重填后恢复可用。
14. 关掉 Ollama 再问 → 与 P1 一致:第一轮失败整轮 `error`(数据源正常与否不影响这个行为)。
15. 只能在浏览器里做的三项:键盘 Tab 能走完数据源表单与列表操作、200% 缩放下管理页不错位、系统深浅色切换后状态色仍然可辨(P1b 建立的检查项,新页面同样适用)。

## 第三部分：范围与决策

### 明确不做

| 不做 | 为什么 |
|---|---|
| ClickHouse / Doris 一类 OLAP 源 | 方言、类型系统、只读权限模型差异都更大;三种源已足够把驱动抽象打磨成型,加第四种是加一个文件 + 一遍契约测试 |
| Excel / CSV 上传导入 | 用户价值高但是**另一条独立线**:引入文件存储、类型推断、导入进度三块新工作。P2a 之后单独评估 |
| 连接池 | 单用户,同一时刻只有一个查询。做池等于凭空引入并发正确性问题 |
| 登录 / 多用户 / 权限 | 只留 `owner` 字段。认证与这条五步链路交集很小,现在做只是拖长 P2a |
| schema TTL / 自动侦测 DDL 变更 | 隐式过期解释不清且不解决问题(见第 1 节),显式刷新 + 报错提示更诚实 |
| SSH 隧道 / 跳板机 | 真实需求但属于运维接入,用户可以自己在本机起隧道后填 `localhost:<本地端口>` |
| 自定义 CA / 客户端证书 | `ssl: boolean` 覆盖绝大多数云库;自定义证书链要引入证书管理 UI |
| 语义层、维度/度量定义 | P2b |
| 钉图、Dashboard、分享链接、导出 PNG | P2c |
| `Dialect.truncateTime()` | P2b 的编译器才有调用方;先实现无人调用的方法是坏味道 |
| 会话历史入库 | 现在不存,P2c 也不打算存。「保存下来的东西」是**图表和看板**,不是聊天记录。真要做会话历史,单独立项 |
| 服务端出图 / 定时报表 | 出图定为前端 canvas(见第 1 节),定时推送依赖服务端渲染,一起留到以后 |

### 决策记录

| # | 决策 | 备选与为什么不选 |
|---|---|---|
| 1 | **三段拆分:P2a 数据源 → P2b 语义层 → P2c 看板与分享** | 「一份 spec 打通全链路的薄纵切」单个 plan 体量过大、返工风险高;「两段合并」每份仍然偏大 |
| 2 | **SQLite + MySQL + PostgreSQL** | 只加 MySQL 则抽象是否通用要等接第三种才知道;加 OLAP 源会显著拉长 P2a |
| 3 | **本机单用户,只留 `owner` 字段** | 现在就做登录会让 P2a 体量翻倍,且与五步链路交集很小;完全不留余地则日后要改表、改路由、改分享语义 |
| 4 | **真语义层(QuerySpec + 编译器),未建模的源走现有 Text2SQL** | 「轻量标注仍 Text2SQL」拿不到可复用指标口径;「彻底废除 Text2SQL」让新连的库不建模就完全不能用,且现有链路作废 |
| 5 | **活链接(打开时重跑查询)** | 快照链接会过期且存储随分享次数增长;「两种都要」使 P2c 体量翻倍 |
| 6 | **前端 canvas 导出 PNG** | 服务端 SSR 要自己拼整版 SVG 且 Node 侧中文字体必须内嵌;puppeteer 引入 ~300MB Chromium,与「完全离线轻量本机工具」定位相冲 |
| 7 | **自写窄口驱动接口** | Knex 的 builder 用不上(我们执行的是现成 SQL 字符串),方言痛点它也不管;DuckDB `ATTACH` 最优雅但要联网装 extension、下推不完全会拖大表、只读语义需重新论证 |
| 8 | **app.db 与业务库彻底分开** | 混在一个 SQLite 里会让「我们的表」出现在用户提问的 schema 里,LLM 会去查它 |
| 9 | **AES-256-GCM + 自动生成 `data/app.key`** | 明文存储会随 app.db 泄露;要求用户必填 `APP_KEY` 破坏零配置启动 |
| 10 | **不做 schema TTL,只给显式刷新** | TTL 与 DDL 变更无相关性,却带来「为什么这次变慢/为什么问不到新列」两类难解释的现象 |
| 11 | **写权限探测只警告不拦截** | 拦截会让只有可写账号的用户完全无法使用;不探测则 MySQL 会话只读可被绕过这件事对用户完全不可见 |
| 12 | **超时下推到服务端(`statement_timeout` / `max_execution_time`)** | 只用 `Promise.race` 会在库上攒下还在跑的查询 |
| 13 | **重试按 `DsErrorCode` 分类** | 现有「任何异常都重试一轮」会让连不上库的场景白等两个超时 |
| 14 | **`POST /api/chat` 直接加必填 `dataSourceId`,不做兼容层** | 「缺失时回落内置源」会把「问的怎么是另一个库」变成难查的 bug |
| 15 | **P2a 就引入 `react-router-dom`** | P2c 的分享页需要真实路径;推迟只是把同样的改动挪到 P2c 并附带一次页面结构重构 |
| 16 | **钉图存查询定义而非结果** | 与活链接配套的必然结果;存结果则「活链接」名不副实 |
| 17 | **`Driver` 只有五个方法** | 每加一个方法就要在三个实现里各写一遍;宁可上层多写一点组合逻辑 |
| 18 | **契约测试跳过时必须打印原因** | 静默 skip 让「全绿」变成假信号 |

### 为 P2b / P2c 预留的接口

P2a 只实现自己需要的东西,但下面这几处是**故意**留成现在这个形状的,P2b / P2c 接上去时不应该需要回头改 P2a:

| P2a 里的东西 | 后面谁用 | 怎么用 |
|---|---|---|
| `schema_cache` 存原样的 `TableSchema[]` | P2b 建模 UI | 建模时从缓存读表与列,不再打库 |
| `SchemaTree` 独立组件 | P2b 建模 UI | 选表 / 选列的交互长在它上面 |
| `Dialect` 接口 | P2b 编译器 | 加 `truncateTime()`、可能再加 `castExpr()`;接口扩字段,现有三个实现各补一处 |
| `Driver.runQuery` 接受任意 SQL 字符串 | P2b 编译器 | 编译器产出的 SQL 与 LLM 产出的 SQL 走同一条执行路径 |
| `migrations.ts` 的数组 | P2b / P2c | 各自往末尾追加 `semantic_models`、`saved_charts`、`dashboards` 的建表迁移 |
| `owner` 字段 | 将来的多用户 | 新表照抄这个字段,不用回填 |
| `react-router-dom` 路由基建 | P2c | 加 `/d/:id`、`/s/:token` 两条 |
| `registry` 按 id 拿 driver | P2c 分享页 | 分享页重跑查询时同样从 registry 取,不需要另一条数据访问路径 |
| `packages/shared` 的 `renderer.ts` | P2c 看板与导出 | 会话、看板卡片、导出的 PNG 共用同一个渲染函数 |

P2b 会引入一个 P2a 没有的概念:**`QuerySpec`** —— 放在 `packages/shared/src/types.ts` 里,和 `ChartSpec` 并列,由 LLM 产出、编译器消费、`saved_charts` 存储。P2a 不要提前定义它。
