# Chat-BI V2-1 设计方案：基座 + 可控链路 + 结果展示

> 文档类型：设计 spec（brainstorming 产物）
> 日期：2026-08-11
> 上游文档：`docs/` 下 6 份（市场与竞品分析 / 竞品功能点逐项拆解表 / 分析师用户访谈提纲 / PRD 功能清单 / 技术架构与语义层设计方案 / ChatBI_Figma标注说明）
> 本段范围：三段拆分中的第一段 V2-1

## 0. 背景与范围

### 0.1 为什么是全量重写

v1（`feature_v2.0` 分支上已提交的实现）定位是「业务人员自助问数出图」的本机单用户离线工具：TypeScript 全栈、SQLite、无登录、只留 `owner` 字段。6 份新文档把产品方向整体换掉——**面向数据分析师/工程师的 AI 副驾**，差异化押在「每一句 SQL 都看得见、改得了、存得下」这四个 ★ 功能上（F-301 可见 / F-302 可编辑 / F-303 人在回路批准 / F-304 全链路可审计可回放），并要求完整多用户与行列级权限（PRD P0）。

栈、数据模型、权限模型、UI 骨架全部换掉后，v1 没有可增量演进的部分，因此**前端 + 后端 + shared 全量重写**。v1 代码从工作树删除，需要时从 git 历史恢复。原 P2b（语义层建模 UI）/ P2c（钉图看板分享）路线图作废。

> 这是已经权衡过的产品级取舍：重写等于丢掉 v1 已验收的 P1/P2a 与 551 个测试。取舍已定，本 spec 不再讨论。

### 0.2 三段拆分

| 段 | 范围 | 退出标准 |
|---|---|---|
| **V2-1（本 spec）** | 基座（认证/多用户/数据源/应用库）+ 可控链路（生成→可见→可编辑→批准→执行→日志/回放）+ 结果展示（表格 ⇄ 图表 + 下钻） | ★ 四个功能端到端可用；三类数据源对真库跑通；粗粒度权限可用 |
| V2-2 | 语义层（物理/业务/指标/治理四层，DB 为真相源）+ 行列级权限策略与编辑 UI + pgvector 语义检索 | 指标口径统一；行列级隔离可验证 |
| V2-3 | 资产沉淀（F-306）、feedback 学习（F-204）、洞察文本、导出到 Notebook（F-305） | 资产可复用；纠正一次后同类提问命中修正 |

每段各走一轮 spec → plan → 实施。

### 0.3 V2-1 覆盖的 PRD 功能

**完整实现**：F-101（多轮，最近 5 轮上下文）· F-103（实时执行）· F-201（元数据接入：自动拉取表结构 + 人工补注释）· F-301 ★ · F-302 ★ · F-303 ★ · F-304 ★ · F-401（下钻，走 F-303 批准）· F-501（Postgres / MySQL / ClickHouse 三类）

**降级实现**（完整版在后续段）：F-102 术语理解——V2-1 只靠 schema 注释与列示例值，同义词表在 V2-2；F-104 澄清——V2-1 只做「没太懂 + 示例」的单向提示，不做多选项交互；F-402 自动选图——V2-1 是规则推断而非 LLM 选图；F-503 行列级权限——V2-1 做到粗粒度 RBAC + 数据源级授权，行列级只在执行器留注入点（见 §4.2、§6）。

### 0.4 已定的技术取舍

| 决策 | 取舍 |
|---|---|
| 后端 Python + FastAPI | 照技术文档第八节；NLP/数据生态成熟 |
| Pydantic 为 OpenAPI 唯一真相源 | `openapi-typescript` 生成前端 TS 类型，CI 校验漂移，不手写两份契约 |
| 应用库 Postgres | V2-1 **不装 pgvector**——V2-1 没有向量检索需求（语义检索在 V2-2），扩展与表结构随 V2-2 的 migration 一起进 |
| 语义层 DB 为真相源 | 否决技术文档主张的「YAML + Git 为主」：审批流、版本、权限策略需要事务与并发控制，Git 做不了；YAML 只做导入导出 |
| 三类驱动 Postgres / MySQL / ClickHouse | Hive 推后——需要 Hadoop 环境，无法自动化验收（F-501 AC1 要求 4 类中至少 3 类，已满足） |
| 示例库灌进应用库的 `demo_sales` schema | 保住「开箱即跑」，不要求用户先接数据源 |
| 写操作**禁用**而非二次确认 | F-303 AC2 给了「二次确认或禁用」两个分支，取禁用；这是永久决策，不是推后 |
| 只做 Dark 主题 | 照 Figma「Dark 优先」，反转 v1 的跟随系统深浅色 |
| LLM 可插拔，默认本地 Ollama | 私有化（F-502）要求推理不出域；每次调用必须带超时与重试上限（v1 缺这个） |

---

## 1. 架构与模块边界

### 1.1 仓库结构

```
chat-bi/
├─ apps/
│  ├─ api/                  Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic
│  └─ web/                  React 19 + Vite + TypeScript + Monaco
├─ docker/
│  ├─ compose.yml           app-postgres · ollama
│  └─ compose.test.yml      测试用 postgres / mysql / clickhouse
└─ docs/
```

前端不再需要 `shared/` 包：契约由 `apps/api` 的 Pydantic 模型导出 OpenAPI，`apps/web/src/shared/api/schema.d.ts` 由 `openapi-typescript` 生成并入库，CI 重新生成后 `git diff --exit-code` 校验漂移。

### 1.2 后端模块

```
apps/api/src/chatbi/
├─ main.py               FastAPI 装配（生命周期、中间件、路由挂载）
├─ config.py             pydantic-settings：DB URL、主密钥来源、LLM provider、超时与行上限
├─ db/                   SQLAlchemy 声明式模型 + Alembic migrations
├─ auth/                 IdentityProvider 抽象、LocalIdentityProvider、会话、密码哈希、current_user 依赖
├─ datasources/          数据源 CRUD、凭据加解密、schema 反射与缓存
│  ├─ registry.py        kind → 驱动 的注册表
│  └─ drivers/           postgres.py · mysql.py · clickhouse.py（共用 Driver 协议）
├─ semantics/            ContextProvider 协议 + V2-1 的 SchemaContextProvider
├─ llm/                  LLMProvider 协议 + ollama.py · openai_compatible.py · fake.py
├─ pipeline/             ask 管线：理解 → 上下文装配 → 生成草稿 → 注释
├─ guard/                sqlglot AST 校验、LIMIT 注入、PolicyResolver 协议、ApprovedStatement
├─ execution/            执行器：连接、语句超时、取消、行截断、错误码映射
├─ runs/                 run 与事件的持久化、日志装配、回放载荷
└─ api/                  routers：HTTP/SSE 编排层，只做请求校验与事件转发
```

### 1.3 依赖方向与边界规则

```
api  ──▶  pipeline · runs · datasources · auth
              │
              ▼
        guard · execution · llm · semantics
              │
              ▼
             db
```

四条边界规则，全部可用测试或静态检查守住：

1. **`guard` 是唯一能放行 SQL 的地方。** `execution.execute()` 的签名只接受 `ApprovedStatement` 值对象，该类型的构造函数是 `guard` 模块私有的。没走过 guard 的 SQL 在类型层面到不了执行器——这比"记得调用校验函数"可靠。
2. **`api/` 不含业务逻辑。** router 只做：解析请求 → 调 pipeline/runs → 把领域事件序列化成 SSE。判断逻辑放在 pipeline/guard/execution，这样 SSE 编排可以单独测，业务逻辑也能脱离 HTTP 测。
3. **`llm` 与 `semantics` 不知道彼此。** pipeline 负责把 `ContextProvider` 的输出装配成 prompt 再交给 `LLMProvider`。V2-2 换语义层实现时，`llm` 一行不改。
4. **`db` 是叶子。** 领域模块通过仓储函数访问，不在 router 里写查询。

### 1.4 单文件规模约束

`guard/validator.py`（AST 校验器）与 `execution/executor.py` 是安全红线代码，各自保持在 200 行以内、只做一件事。驱动实现按库分文件，共用协议里的默认实现，避免出现一个 600 行的 `drivers.py`。前端同理：每个 feature 目录自带 store slice，不设跨 feature 的大 store（见 §3.3）。

---

## 2. 数据流与数据模型

### 2.1 为什么是两条流而不是一条

HITL 的本质是链路中间有一段**不确定时长的人类思考**：草稿生成完到用户点「运行」之间，可能是 3 秒，也可能是 5 分钟，还可能永远不点。一条长连接跨过这段等待会带来两个问题：连接要么被代理超时切断，要么在用户改 SQL 期间白占资源；而且「批准」这个动作必须携带**编辑器里的最终 SQL**，它不是流的延续，是一次新的带载荷的提交。

所以拆成两条：**问答流**产出草稿后正常结束；**执行流**由用户的批准动作单独开启。这也让 F-303 的红线在协议层面成立——服务端没有任何路径能从问答流直接走到执行。

### 2.2 问答流 `POST /api/ask`（SSE）

请求体：`{conversation_id?: uuid, datasource_id: uuid, question: str}`。省略 `conversation_id` 时新建会话。

| 事件 | 载荷 | 说明 |
|---|---|---|
| `run.created` | `{run_id, conversation_id}` | 立即发出，前端据此建立工作区上下文 |
| `understand` | `{chips: [{kind, label, value, hit}], resolved_tables: [str]}` | 意图 chips（Figma §4.3）；`hit=true` 的用 `ok` 色 |
| `draft.delta` | `{text}` | LLM token 流，前端追加渲染 |
| `draft.done` | `{sql, annotations: [{line, note}], warnings: [str]}` | 格式化后的完整 SQL + 权威注释（F-301 AC2） |
| `need_clarification` | `{message, examples: [str]}` | 无法生成时的降级出口（F-104 的 V2-1 形态） |
| `error` | `{code, message}` | 见 §2.6 错误码 |
| `done` | `{}` | 流正常结束 |

管线内部顺序：`understand`（LLM 抽实体，带超时）→ `ContextProvider.build()` 装配 schema 上下文 → `generate`（LLM 出 SQL）→ sqlglot 解析 + 格式化 + 注释挂载。任一步失败发 `error` 并把 run 置为 `failed`（草稿成功生成才是 `drafted`），**不抛裸异常给前端**。

草稿生成完 run 的状态是 `drafted`，`generated_sql` 落库——这是 F-302 AC2「原始生成版 vs 最终版」diff 的左侧。

### 2.3 执行流 `POST /api/runs/{run_id}/execute`（SSE）

请求体：`{sql: str}`——**编辑器当前内容，不是草稿**。服务端把它记为 `final_sql`。

| 事件 | 载荷 | 说明 |
|---|---|---|
| `validate` | `{ok: bool, code?, reason?}` | guard 的判定；`ok=false` 时流即结束，run 置 `blocked` |
| `execute.started` | `{dialect, effective_sql}` | `effective_sql` 是注入 LIMIT/策略后真正下发的语句，必须回显（可审计的前提） |
| `ping` | `{}` | 每 15s 心跳保活；驱动普遍不提供进度，不假装有进度条 |
| `result` | `{columns: [{name, type, is_numeric}], rows: [[...]], row_count, truncated}` | `rows` 最多 100 行 |
| `chart_spec` | `{type, x, y: [str], reason}` | 规则推断结果，前端可覆盖 |
| `log` | `{step, status, duration_ms, detail?}` | 多次；`step ∈ understand \| generate \| validate \| execute \| render` |
| `error` | `{code, message}` | |
| `done` | `{status, duration_ms, row_count}` | |

**取消**：客户端断开或调 `DELETE /api/runs/{run_id}/execute` → 后端 cancel asyncio task **并调驱动的取消能力**（Postgres `pg_cancel_backend`、MySQL `KILL QUERY`、ClickHouse `KILL QUERY WHERE query_id=`）。只关流不取消后端查询是错的：私有化部署里一条跑飞的查询能拖垮用户的生产库。

### 2.4 REST 端点

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/auth/login` · `/api/auth/logout` | 会话建立/销毁 |
| GET | `/api/auth/me` | 当前用户与角色 |
| GET/POST/PATCH/DELETE | `/api/datasources[/{id}]` | 数据源 CRUD（含 `datasource_grants`） |
| POST | `/api/datasources/{id}/test` | 就地测连，并探测账号是否具备写权限（有则告警，见 §4.3） |
| GET | `/api/datasources/{id}/schema` | 表结构（走缓存，`?refresh=1` 强制重拉） |
| PATCH | `/api/datasources/{id}/schema/columns/{col_id}` | 人工补注释（F-201 AC1）。`col_id` = `schema.table.column`，由 `GET /schema` 发出、客户端原样回传；服务端**反查而不解析**（标识符本身可以含点），命中 0 → 404、≥2 → 409 |
| POST | `/api/sql/validate` | 编辑器停止输入 300ms 后调用，返回 guard 判定 |
| GET | `/api/conversations` · `/api/runs` | 历史列表（分页、按数据源/状态过滤） |
| GET | `/api/runs/{id}` | 回放载荷：问题、chips、两版 SQL、结果摘要、事件流 |
| GET | `/api/runs/{id}/export.csv` | 全量导出，重跑 SQL 并流式写出，不走 100 行预览 |

### 2.5 Postgres 数据模型

```sql
users(id uuid pk, email text unique, display_name text, password_hash text,   -- email 在应用层小写规范化

      role text check (role in ('admin','analyst','viewer')), is_active bool,
      created_at timestamptz)

sessions(id uuid pk, user_id uuid fk, expires_at timestamptz, created_at timestamptz)
-- DB 存会话而非无状态 JWT：登出与禁用账号要立即失效

datasources(id uuid pk, name text unique, kind text, host text, port int,
            database text, username text,
            secret_ciphertext bytea, secret_nonce bytea,   -- AES-GCM，见 §4.4
            options jsonb, is_readonly_verified bool,
            created_by uuid fk, created_at, updated_at)

datasource_grants(datasource_id uuid fk, user_id uuid fk, can_query bool,
                  primary key (datasource_id, user_id))

schema_cache(datasource_id uuid pk fk, fetched_at timestamptz, payload jsonb)
column_notes(id uuid pk, datasource_id uuid fk,
             schema_name text, table_name text, column_name text,
             note text, updated_by uuid fk, updated_at timestamptz,
             unique (datasource_id, schema_name, table_name, column_name))
-- 注释单独存：schema_cache 会被 refresh 整体覆盖，人工补的注释不能跟着丢
-- 唯一键含 schema_name（P2c 实施时加的，本节初稿只有三列）：Postgres 的 reflect()
-- 返回所有非系统 schema，三列键会让 demo_sales.orders 与 public.orders 撞成同一条
-- 注释——而失败方式是静默挂到错的列上，界面上完全看不出来

conversations(id uuid pk, user_id uuid fk, datasource_id uuid fk, title text, created_at)

runs(id uuid pk, conversation_id uuid fk, user_id uuid fk, datasource_id uuid fk,
     question text, chips jsonb,
     generated_sql text,        -- LLM 原始生成版（F-302 AC2 左侧）
     final_sql text,            -- 用户批准的版本（F-302 AC2 右侧）
     effective_sql text,        -- 注入 LIMIT/策略后实际下发
     status text check (status in ('drafted','blocked','running','succeeded','failed','cancelled')),
     error_code text, row_count int, duration_ms int,
     llm_provider text, llm_model text,
     parent_run_id uuid fk,     -- 下钻链路（F-401）
     created_at timestamptz, executed_at timestamptz)

run_events(id bigserial pk, run_id uuid fk, seq int, step text, status text,
           duration_ms int, detail jsonb, at timestamptz,
           unique (run_id, seq))
-- append-only：无 UPDATE/DELETE 路径，仓储层只暴露 append 与 list（F-304、技术文档 §六）

run_result_previews(run_id uuid pk fk, columns jsonb, rows jsonb, truncated bool)
-- 只存前 100 行摘要，不存全量快照；回放时重跑取全量
```

`demo_sales` schema 与应用表同库不同 schema，由一个独立 migration 建表灌数；注册成一个名为「示例销售库」的数据源由 CLI `seed-demo` 完成，**不由 migration 自动做**。

理由：注册数据源必须 seal 密码，而 seal 需要主密钥。让 `alembic upgrade` 依赖 `CHATBI_SECRET_KEY` 会把「跑迁移」和「持有主密钥」永久绑死——CI 只想验 schema 时也得先配好密钥。「开箱即跑」仍然成立，只是多一条命令。该数据源必须用只能读 `demo_sales` 的专用只读角色，不能复用应用库账号（应用库里有 `users.password_hash` 与 `datasources` 的密文）。

### 2.6 错误码

前端按码渲染文案，不透传后端消息原文（§4.4：错误消息不得含凭据或结构信息）。

| 码 | 触发 | 前端表现 |
|---|---|---|
| `WRITE_BLOCKED` | AST 命中写操作/DDL/多语句 | 编辑器下方内联说明，运行按钮 disabled |
| `SQL_PARSE_ERROR` | sqlglot 无法解析 | 内联说明 + 报错位置 |
| `PERMISSION_DENIED` | 无数据源授权，或越权字段 | 「无权限」，不列出哪些表/字段（F-503 AC2） |
| `CONNECTION_ERROR` | 连不上数据源 | 通用文案，不回显地址端口 |
| `QUERY_TIMEOUT` | 超过语句超时 | 提示当前超时值与「缩小时间范围」建议 |
| `QUERY_CANCELLED` | 用户取消 | 中性提示 |
| `LLM_TIMEOUT` / `LLM_UNAVAILABLE` | LLM 超时或不可达 | 提示可重试；不影响已有草稿 |
| `DATASOURCE_NOT_FOUND` / `RUN_NOT_FOUND` | 引用不存在 | 通用 404 文案 |

---

## 3. 前端与 UI

### 3.1 布局：工作区优先（对 Figma 的一处结构性偏离）

Figma §3.2 把弹性列给了中栏对话，右栏固定 380px。V2-1 **反转这个分配**：

```
┌ 1280 ────────────────────────────────────────────────────┐
│ Topbar 52    问数 · 数据源 · 历史问答                       │
├─ 210 ──┬── 对话 400（可折叠）──┬── 工作区 flex（min 560）──┤
│ 导航   │ 消息流               │ SQL 编辑器   [运行] ★     │
│        │ · 意图 chips         │ （Monaco，min-h 200，可拖）│
│ 问数   │ · SQL 草稿卡（只读） │ ─────────────────────────  │
│ 数据源 │   [载入到编辑器]     │ 结果 │ 图表 │ 日志         │
│ 历史   ├──────────────────────┤ （Tab 共用下半区）         │
│        │ 输入栏               │                            │
└────────┴──────────────────────┴────────────────────────────┘
```

理由：对话文字在 400px 宽下阅读体验最好，再宽只是把句子拉长；而 SQL 编辑器和结果表才是吃横向空间的。Figma 的分配会让 1920 屏上多出的 640px 全给对话，工作区永远 380px——弹性给错了对象。380px 去掉 padding 只剩 352px，Monaco 在这个宽度里基本不可用。

偏离仅限**哪一列弹性**；Design Tokens（§2.1）、组件库（§五 12 个组件）、区域内的组件构成全部照 Figma 还原。

**断点收敛为两档**（不做 Figma §九 的三档）：≥1200 三栏完整；<1200 对话栏折叠成图标条，工作区吃满。移动端明确不做。工作区上下分割比例与对话栏折叠状态存 localStorage。

### 3.2 路由与导航

只有三条真实路由，导航不放「暂未开放」的空壳：

| 路由 | 内容 |
|---|---|
| `/` | 问数（三栏主界面） |
| `/datasources` | 数据源列表 / 新建编辑表单 / schema 树与注释编辑 |
| `/history` | 历史问答列表 + 回放入口 |

Figma 顶栏的「资产库」随 V2-3 加，「语义层」随 V2-2 加。切换数据源时清空对话上下文并提示「上下文已变更」（F-101 AC3）。

### 3.3 前端模块

```
apps/web/src/
├─ app/                  路由、三栏骨架、主题 provider、错误边界
├─ features/
│  ├─ ask/               消息流、意图 chips、SQL 草稿卡（只读）、输入栏
│  ├─ workspace/         Monaco 编辑器、运行闸门、结果/图表/日志 Tab
│  ├─ datasources/       列表、表单（按 kind 变字段、就地测连）、schema 树
│  └─ history/           历史列表、回放入口
└─ shared/
   ├─ api/               schema.d.ts（生成）+ fetch 客户端 + SSE 客户端
   ├─ ui/                Figma §五 的 12 个组件
   └─ theme/tokens.css   与 Figma §2.1 token 一一对应
```

**状态管理用 zustand，不用 v1 的 Context + useReducer。** 理由：`draft.delta` 是 token 级高频更新，走 Context 会让整棵子树重渲染，而 Monaco 挂在同一棵树里，重挂载代价很高；zustand 的 selector 能把重渲染限制在消息气泡上。REST 数据用 TanStack Query。每个 feature 一个 store slice，无跨 feature 大 store。

两条 SSE 各自独立连接、独立重连（指数退避，上限 5 次）：问答流的输出落进 `ask` slice，执行流的输出落进 `workspace` slice。

### 3.4 HITL 交互（产品红线）

- **草稿卡只读留痕**，唯一动作是「载入到编辑器」。编辑器已有脏内容时二次确认「会覆盖你的改动」。
- **运行按钮全局只有一处**，在编辑器头部。`Ctrl/Cmd+Enter` 是同一个闸门的键盘入口，不是第二条路径。中栏草稿卡上没有运行按钮——F-303 不能有两个守门人。
- 提交给执行流的永远是**编辑器当前内容**。真相在编辑器，不在草稿。
- 运行按钮的 disabled 条件：SQL 为空 / 正在执行 / `/api/sql/validate` 判定为写操作。
- **写操作拦截用内联说明，不用 toast**——toast 会消失，而这是个需要用户改 SQL 才能解除的阻塞状态，必须留在屏上（Figma §6.1「写操作 → 禁用/拦截提示」）。
- 下钻（F-401）：点表格维度值或图表元素 → 生成下钻问题 → **回到问答流**产出新草稿（`parent_run_id` 指向来源 run）→ 仍需点运行。下钻不绕闸门（F-401 AC1）。

### 3.5 结果、图表、日志、回放

**结果 Tab**：`表格 ⇄ 图表` 分段控件，数值列右对齐并用 `ok` 色（Figma §4.4）。只渲染前 100 行，超出时显示「已显示前 100 行，共 N 行」+「导出 CSV」（走 §2.4 的全量导出端点）。

**图表 Tab**：规则推断图型——1 维度 + 1 度量 → 柱状；含时间维度 → 折线；2 度量 → 散点；单值 → 大数字卡。用户可手动改类型与字段（F-402 AC2）。调色板用 Okabe-Ito 派生 8 色（色盲安全）；**涨跌不用颜色表达**，用箭头与符号——红绿在色觉障碍下不可辨，且中西方涨跌色相反。

**日志 Tab**：按 `run_events` 的 step 逐行渲染（understand / generate / validate / execute / render），mono 11px，`ok` 行用成功色（Figma §4.4）。F-304 AC1 要求的时间、用户、SQL 各版本、数据源、耗时、结果摘要都在这里可见，含 `generated_sql` vs `final_sql` 的 diff 视图（F-302 AC2）。

**回放（F-304 AC2）**：`/history` 每条带「回放」→ 把当时的问题、chips、两版 SQL、结果摘要装回工作区，编辑器可编辑，运行按钮文案变「重跑」。**回放是恢复现场 + 可手动重跑，不是重放当时的结果快照**——底层数据已变，假装能复现当时的数字是不诚实的；界面上标注结果摘要的原始执行时间。

### 3.6 主题与可访问性

只做 Dark，`tokens.css` 与 Figma §2.1 逐条对应，不做深浅色切换。

三条 v1 踩过的坑写进验收（见 §8.2）：键盘 Tab 走位可完成「提问 → 载入 → 改写 → 运行」全程；200% 缩放不破版；错误原文的 `<details>` 默认收起——RTL 里断言 `details.open === false`，不能用 `textContent).not.toContain(...)`，因为折叠内容仍在 DOM 里。

分割线可用方向键调整（`role="separator"` + `aria-valuenow`）。SSE 流式内容用 `aria-live="polite"` 播报关键状态变化，不逐 token 播报。

---

## 4. 安全边界

### 4.1 认证与会话

本地账号，密码 argon2id。会话用 httpOnly + `SameSite=Lax` + `Secure`（生产）的 cookie，**不用 localStorage 存 JWT**——localStorage 里的令牌任何 XSS 都能读走，而这个产品的界面本身就在渲染用户可控的 SQL 与错误文本。会话记录落 `sessions` 表，登出与禁用账号立即失效。

`IdentityProvider` 抽象接口，V2-1 只有 `LocalIdentityProvider` 一个实现（见 §6）。首次启动用 CLI 创建 admin，不做注册页面——私有化部署里账号由管理员发。

### 4.2 授权分层（V2-1 与 V2-2 的分界）

| 层 | V2-1 | 后续 |
|---|---|---|
| 角色 | RBAC 粗粒度：`admin`（管数据源与用户）/ `analyst`（问数、改 SQL、执行）/ `viewer`（只看历史，不能执行） | — |
| 数据源级 | `datasource_grants` 授权，未授权数据源不出现在选择器里 | — |
| 行级 / 列级 | **只在执行器留注入点**，`PolicyResolver` 恒返回空策略 | V2-2 接语义层策略 |

这样 V2-2 落地行列级权限时，改动限于 `guard` 内的 `PolicyResolver` 实现与语义层新表，执行器与其余模块不动。

> 与 PRD 的张力已知并明确接受：F-503 行列级权限是 P0，V2-1 只交付到粗粒度。理由是行列级策略的真相源在语义层，而语义层整体在 V2-2；若强行提前，语义层的策略表要拆一半进 V2-1，两段边界会糊掉。

**权限真相源是语义层自建策略 + 执行器注入**，不走技术文档 §3.4 说的「权限继承底层数据源」。原因：数据源账号是共享的服务账号，底层库看不见应用层的用户身份，无法据此隔离；F-205 的「继承」在这个架构下只能靠应用层自己实现。

### 4.3 SQL 执行：四道闸

这是最需要守的一层。

1. **只读账号**。数据源表单明写要求只读账号；`/test` 端点顺带探测写权限，探到就在界面上告警并把 `is_readonly_verified` 置 false（不阻止保存——有些环境拿不到只读账号，但要让用户知道）。
2. **AST 校验**。sqlglot 解析后只放行 `SELECT` 与 `WITH`，禁多语句、禁 DDL/DML/`COPY`/`GRANT` 等一切非查询语句。**用 AST 而不是正则**——正则挡不住 `SELECT 1; DROP TABLE t`、注释夹带、大小写与空白变形。解析失败即拒绝，不做「看起来像 SELECT 就放过」的兜底。
3. **强制注入 LIMIT**（默认 1000，可配）。已有 LIMIT 且更小则保留原值。注入后的语句就是 `effective_sql`，必须回显给用户（§2.3）。
4. **语句超时 + 真取消**（默认 60s，可配）。超时与客户端断开都要调驱动的取消能力，见 §2.3。

写操作是**永久禁用**，不做二次确认：F-303 AC2 给了两个分支，取禁用分支。这个产品没有任何需要写库的功能，留一条能写的路径只是留一个攻击面。

### 4.4 凭据与日志脱敏

数据源密码用 AES-GCM 加密后存 `secret_ciphertext` + `secret_nonce`。主密钥从环境变量或密钥文件读取，**不入库、不入日志、不进任何错误消息**。API 响应里数据源对象永不含密码字段（Pydantic 响应模型不声明该字段，而不是靠序列化时记得排除）。

`CONNECTION_ERROR` 的用户可见文案是通用的「无法连接到数据库，请检查地址、端口与网络」，不回显地址端口——技术文档 §七「错误信息不泄露结构」。地址端口进服务端日志，不进 HTTP 响应。

### 4.5 LLM 边界

prompt 里只放 schema 元数据（表名、列名、类型、注释）与**可选**的列示例值（默认关闭，开启需管理员在数据源上显式打开）——**真实结果行永不进 prompt**。私有化（F-502 AC2）要求推理可走本地，默认 Ollama。

每次 LLM 调用带超时（默认 30s）与重试上限（2 次），超时发 `LLM_TIMEOUT` 而不是无限挂着（v1 缺这个）。

表名/schema 名在进 prompt 前过白名单校验（只允许来自 `schema_cache` 的已知标识符），防止被污染的元数据把指令注进 prompt。

### 4.6 审计

每次 run 记录 who / when / 数据源 / 问题原文 / 两版 SQL / `effective_sql` / 行数 / 耗时 / 状态 / 错误码 / LLM provider 与 model。`run_events` 是 append-only：仓储层只暴露 `append()` 与 `list()`，没有 UPDATE/DELETE 路径。

**不记录结果行内容到日志**，只记行数——结果摘要存在 `run_result_previews` 里受同样的权限控制，日志系统不该成为数据外泄的旁路。

---

## 5. 测试策略

### 5.1 后端三层（pytest）

**单元测**：`guard` 的 AST 校验器（含各类绕过尝试：多语句、注释夹带、大小写变形、CTE 里藏 DML、`SELECT ... INTO`）、LIMIT 注入、`PolicyResolver` 空策略路径、`ContextProvider` 的上下文装配、错误码映射。

**驱动契约测**：三类驱动跑同一套契约用例（连通性、schema 反射、类型映射、超时、取消、行截断），对 `docker/compose.test.yml` 起的真库执行。

> **没库时必须 skip 并计数上报，不能静默算通过。** v1 就是因为「无本地库 → skip」被当成绿灯，MySQL/PG 驱动到重写前一次真库都没跑过。V2-1 的 CI 输出里 skip 数必须显式打印，且真库契约测是 §8.2 人工验收的必过项。

**E2E**：FastAPI `TestClient` 走完两条 SSE，覆盖四条路径——正常链路、写操作被 `validate` 拦截、执行超时、客户端断开触发取消（断言驱动的 cancel 被调用）。

LLM 在所有自动化测试里一律用 `FakeLLMProvider`（确定性输出）。真 LLM 只进人工验收。

### 5.2 前端（Vitest + RTL）

每个 store slice 单测。一条集成回路测「提问 → 草稿 → 载入到编辑器 → 改写 → 运行 → 结果 + 日志」，SSE 用 MSW mock，含断线重连与写操作拦截两个分支。

三个 v1 踩过的测试坑写进 plan 的注意事项：① 测试临时目录每个文件一个，共用会互删；② 断言「错误原文没外露」要用 `details.open === false`；③ 前端不再有 better-sqlite3，v1 的 `pool: "forks"` 问题不复现，但后端 pytest 里数据库 fixture 要按测试模块隔离 schema。

### 5.3 硬要求与不设的门槛

**硬要求**：
- `guard/validator.py` 与 `execution/executor.py` **分支全覆盖**——这是安全红线代码，漏一条分支就是漏一个绕过路径。
- OpenAPI 漂移：CI 跑 `openapi-typescript` 重新生成后 `git diff --exit-code`。
- Alembic migration 的 up/down 双向测试（`upgrade head` → `downgrade base` → `upgrade head`）。

**不设**：整体覆盖率门槛。除上述两个模块外按测试价值写，不为凑数字写测试。

---

## 6. 给 V2-2 / V2-3 预留的接口

只留四个接口，形状都是「V2-1 有一个朴素实现，后续段换实现而不改调用方」。**不预留数据库字段**——加字段是一次 migration，比背着一堆空字段便宜。

| 接口 | 位置 | V2-1 实现 | 谁来换 |
|---|---|---|---|
| `ContextProvider` | `semantics/` | `SchemaContextProvider`：schema 元数据 + 人工注释 + 可选示例值 | V2-2 语义层（指标/同义词/join 关系） |
| `PolicyResolver` | `guard/` | 恒返回空策略（`rows=None, columns=None`） | V2-2 行列级权限 |
| `IdentityProvider` | `auth/` | `LocalIdentityProvider` | OIDC / LDAP |
| `LLMProvider` | `llm/` | `ollama` / `openai_compatible` / `fake` | 后续增加自托管 SQLCoder 等 |

`ChartSpec` 不设接口——V2-1 的规则推断是纯函数，V2-3 要换成 LLM 选图时直接替换该函数，加一层抽象是过早的。

资产沉淀（F-306）不预留：`runs` + `run_events` 已经记全了建资产需要的信息，V2-3 加新表引用 `run_id` 即可，不用改 `runs`。

---

## 7. 明确不做

### 7.1 推后到 V2-2 / V2-3

语义层建模 UI 与指标中心（F-202/203）· 行列级策略编辑 UI（F-503 完整版）· pgvector 与语义检索 · 同义词表 · 资产库与我的资产（F-306）· feedback 学习（F-204）· 洞察文本 · 导出到 Notebook（F-305）· 澄清的多选项交互（F-104 完整版）· LLM 选图（F-402 完整版）· 跨源 join（F-105）

### 7.2 本产品不做

| 不做 | 原因 |
|---|---|
| 写操作与多语句执行 | 永久禁用，不是推后。见 §4.3 |
| 看板 / 钉图 / 分享 | v1 的 P2c 路线图已作废；这是「业务人员自助」定位的产物，与副驾定位不符 |
| 浅色主题 | Figma 定 Dark 优先，浅色是「后续 Phase」；V2-1 不做切换开关 |
| 移动端 / <900px 单栏 | Figma §九 明确 MVP 只交付 Desktop ≥1200 |
| Hive 驱动 | 需 Hadoop 环境，无法自动化验收；F-501 AC1 已由三类满足 |
| OIDC / LDAP 实现 | 只留 `IdentityProvider` 接口 |
| 连接池 / 查询缓存 | 单机私有化部署下是过早优化 |
| 嵌入 SDK / iframe（F-505） | P1，不在 MVP 门槛内 |
| 预测建模 / 归因 / 预警 / 报告（F-403~405） | PRD 明确 P2 与 Out |

---

## 8. 验收标准

### 8.1 功能验收（自动化可覆盖）

| # | 验收项 | 对应 |
|---|---|---|
| 1 | 提问后默认展示完整格式化 SQL（非折叠摘要），关键过滤/聚合处有注释 | F-301 AC1/AC2 |
| 2 | 编辑器可改写 SQL，改后可重新校验；执行以用户最终版为准，日志里能看到两版 diff | F-302 AC1/AC2 |
| 3 | 草稿生成后**不自动执行**；界面上只有一处运行按钮 | F-303 AC1 |
| 4 | 写操作/DDL/多语句被 AST 拦截，运行按钮 disabled + 内联说明 | F-303 AC2 |
| 5 | 每条 run 记录含时间、用户、问题、两版 SQL、`effective_sql`、数据源、耗时、结果摘要 | F-304 AC1 |
| 6 | 历史问答可回放：恢复现场并可手动重跑 | F-304 AC2 |
| 7 | 第二问含指代（「它」「上个月」）能绑定上一轮实体 | F-101 AC1 |
| 8 | 上下文保留最近 5 轮，可手动清除；切数据源提示上下文已变更 | F-101 AC2/AC3 |
| 9 | 执行超时/报错给出可读错误与定位建议，不泄露地址与结构 | F-103 AC2、F-503 AC2 |
| 10 | 点表格维度值可下钻，生成下钻 SQL 并**仍需批准**；图表与表格数据一致 | F-401 AC1/AC2 |
| 11 | 从数据源自动拉取表结构，人工补的注释在 refresh 后不丢 | F-201 AC1 |
| 12 | 未授权数据源不出现在选择器；越权访问返回「无权限」且不列出结构 | F-503 AC2 |
| 13 | 客户端断开后后端查询被真取消（断言驱动 cancel 被调用） | §2.3 |
| 14 | `demo_sales` 示例库在全新部署上开箱可问 | §0.4 |

### 8.2 人工验收清单（自动化替代不了）

1. **三类驱动对真库跑通契约测**：起 `compose.test.yml` 的 Postgres / MySQL / ClickHouse，全套契约用例通过，skip 数为 0。这一项是 v1 的历史欠账，不能再靠 skip 蒙过去。
2. **浏览器可访问性三项**：键盘 Tab 走位可完成「提问 → 载入 → 改写 → 运行」全程；200% 缩放三栏不破版；深色下状态色（`ok` / `warn` / 错误红）可辨。
3. **真 LLM 下的 SQL 质量抽查**：接真 Ollama 模型，用一组覆盖常见问法的问题抽查一次可执率与采纳率，作为 PRD §1.3 门槛（一次可执率 ≥60%、采纳率 ≥80%）的基线读数——**V2-1 不承诺达标**，语义层（V2-2）才是达标的手段，这里只取基线。
4. **凭据不外泄核查**：抓一遍 API 响应与服务端日志，确认无明文密码、无主密钥、无回显地址端口。
5. **离线部署验证**：断网环境下 `docker compose up` 能起全栈并完成一次完整问数（F-502 AC1）。

---

## 9. 自查记录

写作过程中发现并已回改、或需要读者特别注意的点：

1. **§1 与 §2 是重建稿。** 这两节在上一个会话中已获批，但那段上下文已被清除，本文是照已定决策条目重新写的，措辞与当时不同。审阅时请重点复核这两节，特别是 §2.2/§2.3 的事件名与载荷。
2. **pgvector 从 V2-1 推到 V2-2。** 先前定的是「应用库 Postgres + pgvector」，写 §0.4 时发现 V2-1 没有任何向量检索需求（语义检索属于 V2-2），装了也只是空扩展，因此推后。
3. **`column_notes` 拆成独立表**是写 §2.5 时发现的问题：`schema_cache` 在 refresh 时整体覆盖 payload，人工补的注释若存在同一 jsonb 里会跟着丢，而 F-201 AC1 要求「自动拉取 + 人工补充」并存。
4. **与上游文档的三处有意偏离**，均已在正文说明理由：语义层真相源用 DB 而非 YAML+Git（§0.4）；权限真相源用自建策略而非继承底层数据源（§4.2）；Figma 的弹性列由中栏反转到工作区（§3.1）。
5. **与 PRD 优先级的一处已知张力**：F-503 行列级权限是 P0，V2-1 只交付粗粒度 + 执行器注入点（§4.2）。已明确接受。
6. **四个功能是降级实现**，plan 阶段不要按完整版拆任务：F-102、F-104、F-402、F-503（§0.3）。
7. **F-303 AC2 取「禁用」分支**且定为永久决策（§4.3、§7.2），plan 里不要留二次确认的实现路径。
8. **`users.email` 从 `citext` 改为 `text` + 应用层小写规范化**（写 P1 计划 Task 3 时回改）：citext 要额外建扩展、SQLAlchemy 的 CITEXT 类型有版本门槛，收益只是省一次 `.lower()`。规范化在 `LocalIdentityProvider` 与 admin CLI 两处入口做。
