# Chat-BI 设计文档

- **日期**: 2026-07-27
- **状态**: 设计已批准,待写实现计划
- **方案**: A — 轻量手写 prompt + Ollama JSON 输出

## 概述

Chat-BI 是一个本地运行的对话式 BI 工具。用户用自然语言提问,后端用本地 Ollama 模型把问题转成只读 SQL,在 SQLite 示例库上执行,并把结果组装成 ECharts option 返回前端渲染。数据全程不出本机。

**核心约束**:
- 后端 Node.js + TypeScript(Express)
- 前端 React + TypeScript + Vite + ECharts
- 数据源:内置 SQLite 示例数据集
- LLM:本地 Ollama
- 返回 ECharts option 格式,前端渲染
- 图表类型:后端建议 + 前端可改
- 单用户本地工具,无认证

## 1. 架构总览

单仓库、前后端分离,本地一键启动。

### 仓库结构

```
Chat-BI/
├─ apps/
│  ├─ backend/        # Node.js + TypeScript (Express)
│  └─ frontend/       # React + TypeScript + Vite + ECharts
├─ packages/
│  └─ shared/         # 前后端共享类型 (QueryResult, ChartSuggestion, ChatMessage)
└─ data/
   └─ chatbi.db       # SQLite 示例数据库 (内置,首次启动初始化)
```

### 运行时拓扑

- 浏览器 → React 前端(Vite dev / 静态构建)
- 前端 → 后端 REST API(单端口,生产由后端托管前端静态文件)
- 后端 → Ollama(`http://localhost:11434`,可配置)
- 后端 → SQLite(`data/chatbi.db`)

### 核心请求链路(单轮对话)

1. 前端发 `POST /api/chat` `{ question, history }`
2. 后端:取 schema → 构造 prompt → 调 Ollama → 解析 JSON → 校验 SQL → 执行 → 组装 ECharts option + 表格数据 + 解释
3. 后端经 SSE 流式推回 `explanation` 文本,最后推一个 `result` 事件携带结构化数据
4. 前端流式渲染解释 + 最后挂载 ECharts 图表和表格

### 部署形态

单用户本地工具:无认证,默认监听 `localhost`。Docker 留作后续,首版不引入。

## 2. 组件与职责

后端按职责拆成独立小模块,每个单一职责、可独立测试。

### 后端模块

| 模块 | 职责 | 关键接口 |
|---|---|---|
| `dbClient` | SQLite 连接、schema 提取(PRAGMA table_info)、执行只读查询 | `getSchema(): TableSchema[]` `runQuery(sql): Row[]` |
| `promptBuilder` | 把 schema + 用户问题 + 历史 拼成 prompt,要求 JSON 输出 | `build(question, history, schema): string` |
| `llmClient` | 调 Ollama REST(`/api/chat` 流式),解析 token 流 | `chatStream(prompt): AsyncIterable<string>` |
| `sqlGuard` | 校验 SQL:只读(拒绝 INSERT/UPDATE/.../DDL)、行数上限(1000)、超时 | `validate(sql): {ok, reason?}` |
| `chartAssembler` | 把查询结果 + 模型建议的 `chartType` 组装成 ECharts option + 表格数据 | `assemble(rows, chartType, fields): ChartPayload` |
| `chatService` | 编排上面五者:取 schema → prompt → 流式调 LLM → 解析 → 校验 → 执行 → 组装 | `handleChat(question, history): AsyncIterable<StreamEvent>` |
| `route /api/chat` | SSE 端点,把 `chatService` 的事件流转成 SSE | — |

### 共享类型(`packages/shared`)

```ts
type StreamEvent =
  | { type: "explanationDelta"; text: string }
  | { type: "result"; payload: ChartPayload }
  | { type: "error"; message: string; raw?: string };

interface ChartPayload {
  chartType: "bar" | "line" | "pie" | "table";
  echartsOption: object;   // ECharts option,前端 setOption 直接用
  table: { columns: string[]; rows: Row[] };
  explanation: string;
}
```

### 前端组件

- `ChatWindow` — 消息列表 + 输入框,管理 history
- `MessageBubble` — 渲染解释文本(流式)+ 附带结果卡片
- `ResultCard` — ECharts 图表 + 表格 + 图表类型切换控件(读后端建议,用户可改 → 前端重算 option)
- `api` — SSE 客户端,解析事件流

### 边界原则

`dbClient`/`llmClient` 是纯 I/O 可 mock;`sqlGuard`/`chartAssembler` 是纯函数易测;`chatService` 是编排核心。

## 3. 数据流与 Prompt 设计

### SQLite 示例数据集

内置一个**销售订单**场景库 `data/chatbi.db`,首次启动若不存在则用迁移脚本初始化:

```
customers   (customer_id, name, region, signup_date)
products    (product_id, name, category, unit_price)
orders      (order_id, customer_id, order_date, total_amount)
order_items (order_id, product_id, quantity, unit_price)
```

覆盖典型分析维度:时序(订单按月)、占比(类别销售额占比)、分组对比(区域销售额)、Top-N(畅销产品)。示例问题如"各地区上季度销售额对比""按类别看销售额占比"都有合理图表可画。

### Prompt 结构(让 Ollama 输出 JSON)

```
你是 SQL 分析助手。根据下方数据库 schema 用自然语言回答用户问题。

数据库 schema:
<PRAGMA 提取的表/列/类型/外键>

规则:
1. 只生成 SELECT 语句,只读
2. 输出严格 JSON:{"sql": "...", "chartType": "bar|line|pie|table", "explanation": "..."}
3. chartType 选择:时序→line,占比→pie,分组对比→bar,无明显可视化→table
4. explanation 用一句中文说明你打算查什么

用户问题: <question>
对话历史: <history, 最近 3 轮>
```

`explanation` 用流式生成(自然语言),`sql`/`chartType` 在 JSON 解析阶段提取。

### 单轮数据流(时序)

```
前端 POST {question, history}
  │
  ▼
chatService
  ├─ dbClient.getSchema() ── 缓存(进程内,schema 不变)
  ├─ promptBuilder.build(...)
  ├─ llmClient.chatStream(prompt)
  │     └─ 流 token → 边收边解析 explanation(在 JSON 的 explanation 字段内)
  ├─ 解析完整 JSON → {sql, chartType}
  ├─ sqlGuard.validate(sql) ── 失败→error 事件
  ├─ dbClient.runQuery(sql) ── LIMIT 注入 / 超时
  ├─ chartAssembler.assemble(rows, chartType, fields)
  └─ 发 result 事件 {chartType, echartsOption, table, explanation}

前端: explanation 流式打字 → result 到达后挂载 ECharts + 表格
```

### 历史处理

后端只把最近 3 轮(问题 + 最终 explanation,不含 SQL/数据)塞回 prompt,避免 token 膨胀。完整对话历史由前端持有,后端无状态。

## 4. 错误处理与降级

本地 Ollama 模型的已知弱点:JSON 输出不稳、SQL 偶有语法错、能力上限导致答非所问。每类都要有兜底,且错误要能流式传到前端。

### 错误分类与处理

| 场景 | 检测 | 处理 |
|---|---|---|
| Ollama 未启动/连接失败 | `llmClient` 抓网络错 | `error` 事件,前端显示"Ollama 未运行,请确认 11434 端口",不崩溃 |
| 模型输出非 JSON / JSON 缺字段 | `JSON.parse` 失败或缺 `sql` | **重试一次**(prompt 追加"上次输出无法解析,请严格输出 JSON"),仍失败→`error` 事件附原始输出 |
| SQL 校验失败(含写操作/DDL) | `sqlGuard.validate` | `error` 事件"查询非只读,已拦截",不执行 |
| SQL 执行语法错 | `dbClient.runQuery` 抓 SQLite 错 | 把 SQLite 报错回灌进 prompt **重试一次**,仍失败→`error` 事件附报错 |
| 查询超时 / 行数超上限 | sqlGuard 超时 / LIMIT 截断 | 截断时在 `explanation` 追加"(结果已截断至 1000 行)" |
| 空结果集 | `rows.length === 0` | 正常返回 `table` 图表 + explanation"无符合条件的记录" |

### 重试上限

统一为 **1 次**,避免本地模型在坏输出上空转烧 token。两次都失败就把原始内容透传给用户,让用户自己判断或换问法。

### 前端错误展示

`error` 事件渲染为红色卡片,但仍保留当轮 explanation 流式文本(已收到的部分),用户能看到模型"想说什么",而不是一个干巴巴的报错。

### 不可恢复的启动错误

- `chatbi.db` 初始化失败(磁盘满/权限)→ 后端启动即退出,日志打明确原因
- schema 提取失败 → 启动时自检,失败拒绝启动

## 5. 测试策略

按模块可测性分层,优先覆盖纯函数和易错点(LLM 输出解析、SQL 校验、图表组装),编排层用 mock 跑端到端。

### 测试分层

| 层 | 工具 | 覆盖 |
|---|---|---|
| 纯函数单测 | Vitest | `sqlGuard.validate`(各类写操作/DDL 拦截、LIMIT 注入)、`chartAssembler.assemble`(bar/line/pie/table 各字段映射)、`promptBuilder.build`(schema 注入、history 截断到 3 轮) |
| 解析容错单测 | Vitest | 给定 LLM"脏输出"(非 JSON、缺字段、多余文本包裹 JSON),断言重试与降级路径 |
| `dbClient` | Vitest + 临时 SQLite 文件 | schema 提取正确、只读查询返回行、写 SQL 被拦截、超时/行数上限生效 |
| `llmClient` | Vitest + mock fetch | 断言 token 流解析、网络错抛出可识别错误类型;**不打真实 Ollama** |
| 编排层 `chatService` | Vitest + mock(`llmClient`/`dbClient`) | 端到端:正常路径、JSON 解析失败重试、SQL 执行失败重试、超时截断、空结果。断言事件序列 |
| 前端 | Vitest + React Testing Library | `ResultCard` 图表类型切换重算 option;`api` SSE 解析事件流 |

### 不测什么

- 不发真实 Ollama 调用(慢、不稳、依赖外部);`llmClient` 只测 mock 路径
- 不写"模型回答正确性"测试(模型行为不可定测),靠手动验收

### 手动验收清单(README 记录)

固定问四类示例问题,人工确认:① 时序折线 ② 占比饼图 ③ 分组柱状 ④ 空结果。作为发版前自测。

## 待定项

无。所有关键决策(技术栈、数据源、LLM、返回格式、图表决策权、错误兜底、测试范围)已在设计中明确。
