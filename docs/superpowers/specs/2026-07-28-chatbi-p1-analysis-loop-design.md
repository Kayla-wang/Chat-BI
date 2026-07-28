# Chat-BI P1 设计文档：分析闭环

- **日期**: 2026-07-28
- **状态**: 设计已批准,待写实现计划
- **前序文档**: [2026-07-27-chat-bi-design.md](./2026-07-27-chat-bi-design.md)（MVP 设计）

## 概述与范围

MVP 已经跑通「单轮提问 → NL2SQL → 一个图表」。P1 把它补成一个**分析闭环**：图表能表达多系列与时间序列，结果自带可信的自然语言解读，用户能在上一轮结果上继续追问细化。

### P1 交付内容

1. **图表 IR（ChartSpec）**——后端产出语义化的图表描述,`packages/shared` 提供唯一的 ECharts renderer,消除前后端重复的 `buildOption`。
2. **多系列 / 时间轴 / 堆叠**——多指标、按维度拆系列（pivot）、真时间轴（排序 + 缺口补齐 + 粒度格式化）、普通堆叠与百分比堆叠、数值格式化（千分位 / 万 / 亿 / 百分比）。
3. **结果洞察**——纯函数从结果集算出结构化事实,再交 LLM 改写成一段中文;LLM 不接触原始数据,数字不可能被算错。
4. **多轮下钻**——前端回传上一轮 SQL,LLM 在其基础上改写（追加筛选、换时间粒度、加拆分维度）;后端保持无状态。
5. **SQL 安全层重做**——只读连接为根本防线,AST 校验取代关键字黑名单。
6. **前端设计系统与 UI 重做**——CSS 变量 + CSS Modules,可访问的图表调色板,结果卡片重新分层。
7. **两个确定性 bug 修复**——截断误报、`ChatWindow` 消息索引错位。

### 不在 P1 范围

数据源适配层、语义层 / 指标层、元数据持久化、dashboard 编排、认证与多用户——全部留给 P2。P1 仍然是单用户本地工具,数据源仍是内置 SQLite 示例库。

### 成功标准

- 「按月看各区域销售额」能画出多条折线,而不是只取第二列。
- 「各类别销售额占比」的饼图下方有一段引用真实数字的中文解读,且能展开看到计算依据。
- 「按月统计订单金额」→「只看华东区」→「按周看」三轮追问能连续生效。
- 关掉 Ollama 的第二轮调用（洞察）时,图表仍然正常渲染,洞察降级为模板文本。
- `sqlGuard` 不再误杀 `SELECT '已delete' AS status`,且只读连接下任何写操作被引擎拒绝。

## 1. 架构总览与模块变更

### 单轮数据流（含下钻）

```
前端 POST /api/chat { question, history, context? }
   context = { lastSql, lastColumns }        ← 仅下钻时存在
        │
        ▼  chatService.handleChat
  ① db.getSchema()                           进程内缓存
  ② promptBuilder.buildPrompt({ question, schema, history, context })
  ③ llm.chatStream → 收全 → parseJson
        → { sql, explanation, hint: ChartHint }
          explanation 在下发时改名为 queryIntent（见第 4 节 ResultPayload）
  ④ sqlGuard.validate(sql)                   AST 校验,失败回灌重试 1 次
  ⑤ db.runQuery(sql, limit + 1)              执行报错回灌重试 1 次
  ⑥ inferChartSpec(rows, hint) → ChartSpec
        emit  result { spec, table, queryIntent, sql }   ◀── 图表立刻渲染
  ⑦ computeFacts(rows, spec) → InsightFact[]  纯函数,零延迟
        emit  insightFacts { facts }
  ⑧ insightWriter.write(facts, question)      真 token 流
        emit  insightDelta × N                          ◀── 洞察逐字写出
        LLM 报错 / 超时 8s → 一次性下发模板降级文本
        emit  done
```

**编排要点**:第一轮 LLM 输出必须完整才能解析 JSON,所以 `queryIntent` 一次性下发,不再假装流式（MVP 里 `emitExplanationDeltas` 把已收全的字符串按 2 字符切片,首字延迟等于全量延迟,是纯粹的视觉欺骗）。真正的流式留给第二轮——那一轮输出纯文本,可以逐 token 推送。

**图表优先于洞察**:`result` 事件在第二轮 LLM 开始前就发出,用户先看到图。第二轮失败不影响已渲染的图表。

**空结果短路**:`rows.length === 0` 时 `computeFacts` 只产 `empty` 事实,直接跳过第二轮 LLM,下发固定文案。

### 文件级变更清单

| 文件 | 动作 |
|---|---|
| `packages/shared/src/index.ts` | 扩展:`ChartSpec` / `ChartHint` / `InsightFact` / `DrillContext` / `ResultPayload` / `StreamEvent` |
| `packages/shared/src/renderer.ts` | **新增** `specToEchartsOption(spec)`,两端唯一的 ECharts 生成实现 |
| `packages/shared/src/format.ts` | **新增** 数值 / 日期格式化纯函数 |
| `apps/backend/src/columnTypes.ts` | **新增** 列角色嗅探 `temporal / categorical / numeric` |
| `apps/backend/src/chartSpec.ts` | **替换** `chartAssembler.ts`:`inferChartSpec(rows, hint)` |
| `apps/backend/src/facts.ts` | **新增** `computeFacts(rows, spec)` |
| `apps/backend/src/insightWriter.ts` | **新增** facts → LLM 流 / 模板降级 |
| `apps/backend/src/sqlGuard.ts` | **重写**为 AST 校验 + 加固回退 |
| `apps/backend/src/dbClient.ts` | 拆读写连接:查询用 `readonly: true`,迁移用可写连接;`limit + 1` 截断探测 |
| `apps/backend/src/promptBuilder.ts` | 扩展:hint 字段要求、下钻上下文注入;**新增** `buildInsightPrompt` |
| `apps/backend/src/chatService.ts` | 编排扩展:两轮 LLM、新事件序列 |
| `apps/backend/src/config.ts` | 新增 `insightTimeoutMs`（默认 8000） |
| `apps/frontend/src/api.ts` | 传 `context`,解析新事件 |
| `apps/frontend/src/components/*` | 拆分重做,见第 6 节 |
| `apps/frontend/src/theme/*` | **新增** 设计 tokens + 图表调色板 + 全局样式 |

`chartAssembler.ts` 及其测试删除。它的职责一分为二:**语义推导**进 `chartSpec.ts`（后端,依赖结果集）,**ECharts 生成**进 `shared/renderer.ts`（纯函数,两端共用,未来 P2 的服务端图片导出也调它）。

### 模块边界

- `columnTypes` / `chartSpec` / `facts` / `shared/renderer` / `shared/format` / `sqlGuard` —— 纯函数,无 I/O,可直接单测。
- `dbClient` / `llmClient` —— 纯 I/O,可 mock。
- `insightWriter` —— 依赖注入 `llm`,可测降级路径。
- `chatService` —— 唯一的编排者,依赖全部通过 `ChatDeps` 注入。

## 2. ChartSpec 契约

职责划分:**LLM 只出语义 hint,后端产出完整 spec**。hint 的每个字段都是不可信输入,必须校验后才使用;校验失败时后端有确定性兜底,不会因为模型幻觉出现空图。

### 类型定义

```ts
export type ChartType = "bar" | "line" | "pie" | "table";
export type ColumnRole = "temporal" | "categorical" | "numeric";
export type TimeGrain = "day" | "week" | "month" | "quarter" | "year";
export type StackMode = "none" | "normal" | "percent";

/** LLM 输出的一部分——不可信,全部字段校验后才用 */
export interface ChartHint {
  chartType: ChartType;
  dimensions: string[];        // 首个作 x 轴
  measures: string[];
  seriesBy?: string;           // 按该维度拆系列
  stack?: StackMode;
}

export interface ValueFormat {
  kind: "number" | "currency" | "percent";
  decimals: number;
  unit?: string;               // "元"
  scale?: 1 | 10000 | 100000000;   // 原值 / 万 / 亿
}

export interface ChartSeries {
  name: string;                // 图例名:单指标时为列名,拆系列时为维度值
  field: string;               // 来源指标列名
  data: (number | null)[];     // 与 x.labels 等长
  format: ValueFormat;
}

export interface ChartSpec {
  chartType: ChartType;
  stack: StackMode;            // 仅 bar 生效
  x: {
    field: string;
    role: "temporal" | "categorical";
    labels: string[];          // 已格式化的轴标签
    grain?: TimeGrain;         // role === "temporal" 时存在
  };
  series: ChartSeries[];       // table 时为空数组
  notes: string[];             // 降级 / 补齐 / 截断的说明,前端展示在图表下方
}
```

### inferChartSpec 推导顺序

每一步都是确定性的,可独立单测:

1. **列角色嗅探**（`columnTypes`）
   - 全部非空值都能 `Number()` 且非 NaN → `numeric`
   - 匹配 `YYYY`、`YYYY-MM`、`YYYY-MM-DD`、ISO 8601 之一 → `temporal`
   - 其余 → `categorical`
   - 全空列视为 `categorical`;混合类型列按上面顺序首次命中即定

2. **hint 校验**——`dimensions` / `measures` / `seriesBy` 里的列名逐个比对结果集实际列名,不存在的字段直接丢弃。模型幻觉出的列名不会传播到 spec。

3. **x 轴选取**——`hint.dimensions[0]` 有效则用;否则取第一个非 numeric 列;都没有则取第一列。

4. **measures 选取**——`hint.measures ∩ numeric 列`;结果为空则取全部 numeric 列。

5. **拆系列（pivot）**——`seriesBy` 有效且其去重基数 ≤ **12** 时,按该列的取值展开成多条系列;基数 > 12 时忽略 `seriesBy` 并写 note,例如「region 取值过多（37 个）,已改为单系列」。上限取 12 是因为超过这个数量的折线 / 柱组已无可读性。

6. **时间轴处理**——`x.role === "temporal"` 时:
   - 按解析后的真实时间排序（不是字符串排序）
   - 从相邻刻度间隔推断 `grain`
   - **补齐缺失刻度**:默认按 **0** 补,并写 note「已补齐 2 个无数据的时间点（按 0 计）」。理由是主流场景是 `SUM` / `COUNT` 聚合,某月无订单在语义上就是 0;补 `null` 会让折线断开,看起来像数据缺失。
   - **例外**:`format.kind === "percent"` 的系列补 `null`。比率类指标没有数据不等于 0%,补 0 会严重失真。
   - 按 `grain` 格式化轴标签（`2026-01` → `1月`,跨年时 → `2026年1月`）

7. **格式推断**
   - 列名启发式:匹配 `amount|price|revenue|金额|销售额|收入` → `currency`,单位「元」;匹配 `rate|ratio|percent|率|占比` → `percent`;其余 `number`
   - 量级:该系列绝对值最大者 ≥ 1e8 → `scale: 1e8`（亿）,≥ 1e4 → `scale: 1e4`（万）,否则 `1`
   - `decimals`:`percent` 为 1,`currency` 缩放后为 2、未缩放为 0,`number` 为 0

8. **pie 约束**——`series` 必须恰好 1 条。多 measure 时取第一条并写 note「饼图仅展示第一个指标（amount）」。

9. **table**——`series` 为空数组,`x` 仍填充第一列信息以保持类型完整;前端只渲染表格。

10. **stack**——仅当 `chartType === "bar"` 且 `series.length > 1` 时生效,否则强制为 `"none"`。

11. **截断说明**——结果被截断时写 note「结果已截断至 1000 行」。同一事实也会进入 `InsightFact` 的 `truncated`,因为图表下方的 note 和洞察文本是两个独立的展示位,都需要提到它。MVP 里把这句话拼进 `explanation` 的做法被移除。

### renderer 的职责

`specToEchartsOption(spec)` 是纯函数,不做任何语义决策,只做机械翻译:

- `stack: "normal"` → 各 series 加 `stack: "total"`
- `stack: "percent"` → renderer **内部归一化**每个 x 位置上各系列的占比（ECharts 不提供原生百分比堆叠）,`yAxis` 用百分比 formatter;`table` 里保留的仍是原值
- `format` → `yAxis.axisLabel.formatter` 与 `tooltip.valueFormatter`,复用 `shared/format`
- 颜色由调用方通过参数传入调色板,renderer 本身不含颜色字面量
- `chartType === "table"` → 返回 `{}`

## 3. fact 层与洞察生成

核心原则:**事实由纯函数算,LLM 只负责措辞**。LLM 从不看到原始数据行,因此不可能算错百分比或编造峰值。

### 事实类型

```ts
export type InsightFact =
  | { kind: "trend"; series: string; dir: "up" | "down" | "flat"; pct: number; from: string; to: string }
  | { kind: "trendAbs"; series: string; delta: number; from: string; to: string }
  | { kind: "peak"; series: string; label: string; value: number }
  | { kind: "trough"; series: string; label: string; value: number }
  | { kind: "topShare"; series: string; label: string; pct: number }
  | { kind: "concentration"; series: string; topN: number; pct: number }
  | { kind: "total"; series: string; value: number }
  | { kind: "seriesGap"; high: string; low: string; ratio: number }
  | { kind: "truncated"; limit: number }
  | { kind: "empty" };
```

### computeFacts 规则

| 条件 | 产出的事实 |
|---|---|
| `x.role === "temporal"` | `trend`（首末对比）、`peak`、`trough` |
| `x.role === "categorical"` | `topShare`（最大项占比）、`concentration`（头部 3 项合计占比）、`total` |
| `series.length > 1` | 追加 `seriesGap`（总量最高与最低系列的倍数） |
| 结果被截断 | 追加 `truncated` |
| `rows.length === 0` | 只产 `empty`,其余全部跳过 |

**多系列降噪**:`trend` / `peak` / `trough` 只对**总量最大的那条系列**计算。否则 8 条系列会产出 24 条事实,洞察文本变成事实罗列。

**事实上限 6 条**,超出时按上表从上到下的顺序截断。

**`trend` 的零值边界**:`pct = (last - first) / |first| × 100`。当 `first === 0`,或 `first` 与 `last` 符号相反时,百分比无意义（`Infinity` 或误导性的负增长率）——此时改产 `trendAbs`,措辞变成「从 0 增长到 12.8 万」。

**`flat` 判定**:`|pct| < 3` 时 `dir = "flat"`。

### insightWriter

```
buildInsightPrompt(facts, question) →

以下是系统已经算好的事实,请用 2-3 句中文串成一段连贯的分析。
严格约束:
- 不得引入任何未在下方列出的数字
- 不得逐条罗列,要串成自然的句子
- 不得给出业务建议或结论性判断

用户问题: 按月统计订单金额
事实:
- 趋势: 系列「订单金额」向上 23.4%（1月 → 6月）
- 峰值: 3月 128,400 元
- 头部占比: 华东 41.2%
```

- **真流式**:`llm.chatStream(prompt)` 的 token 直接 `yield` 成 `insightDelta` 事件,不缓冲。
- **独立超时**:`config.insightTimeoutMs`（默认 8000ms）。超时或 LLM 抛错 → 丢弃已收到的部分,一次性下发 `renderFactsTemplate(facts)` 的模板文本。图表已在页面上,用户体验是「洞察那一栏换成了朴素版本」,不是报错。
- **模板降级示例**:`趋势:上涨 23.4%（1月 → 6月）。峰值:3月,128,400 元。头部占比:华东 41.2%。`
- **空结果**:不调 LLM,直接下发「没有符合条件的记录」。

### 数字可信度的处理

不做 LLM 输出后校验。用正则从中文段落里抽数字再比对 facts 数字集合,会因为格式化形态（`128,400` / `12.84万` / `128400`）产生大量假警报,维护成本高于收益。

改为**在 UI 上把 facts 以「计算依据」折叠区列出**——用户展开就能逐条对照模型有没有胡说。这是 `insightFacts` 事件存在的理由,也是把可信度问题交给人而不是交给更多代码的诚实做法。

## 4. 多轮下钻

### 上下文载体

```ts
export interface DrillContext {
  lastSql: string;
  lastColumns: string[];
}
```

**前端持有,请求时回传,后端保持无状态。** 前端在会话里记住最近一轮的 `sql` 和结果列名,追问时随 `POST /api/chat` 一起发回。后端不引入任何 session store——P2 会做真正的持久化,现在加一层进程内 Map 只会在 P2 被推翻,而且带来「重启丢上下文」「多实例不一致」两个新问题。

### prompt 注入

`buildPrompt` 在有 `context` 时追加:

```
上一轮查询（用户可能要在此基础上细化）:
SQL: SELECT strftime('%Y-%m', order_date) AS month, SUM(total_amount) AS amount
     FROM orders GROUP BY month ORDER BY month
结果列: month, amount

若用户的问题是对上一轮的细化（追加筛选、更换时间粒度、增加拆分维度）,
请在上面的 SQL 基础上改写;若是全新问题,忽略上一轮。
```

无 `context` 时不注入这一段。

**是否下钻由 LLM 隐式判断**,不做显式意图分类器。分类器意味着第三次 LLM 调用和一整类新的错误模式（把新问题误判成下钻,导致莫名其妙的 WHERE 条件),而 prompt 里一句说明已经能覆盖绝大多数情况。

**只带最近一轮的 SQL**,不带整条下钻链。对话历史仍是最近 2 轮的纯文本问答（`HISTORY_MESSAGE_LIMIT = 4`,沿用现状）。三轮以上的下钻靠「上一轮 SQL 本身已经累积了前面所有的筛选条件」自然传递。

### SQL 回传给前端

`result` 事件新增 `sql` 字段。它已经通过 `sqlGuard` 校验,回传只读展示没有风险,而且顺带解锁了 BI 产品应有的**「查看 SQL」折叠区**——用户能验证模型到底查了什么,这对建立信任比洞察文本更重要。

### 事件契约变更

```ts
export interface ResultPayload {
  spec: ChartSpec;
  table: { columns: string[]; rows: Row[] };
  queryIntent: string;         // 原 explanation,一次性下发
  sql: string;
}

export type StreamEvent =
  | { type: "result"; payload: ResultPayload }
  | { type: "insightFacts"; facts: InsightFact[] }
  | { type: "insightDelta"; text: string }
  | { type: "done" }
  | { type: "error"; message: string; raw?: string };
```

`explanationDelta` 移除,`ChartPayload` 被 `ResultPayload` 取代。这是 breaking change,但前后端同仓库同时改,不需要兼容期。

## 5. SQL 安全层重做

### 现状的问题

MVP 的防线只有一层关键字黑名单正则。它同时存在误杀和漏网:

- `SELECT '已delete' AS status` 被拦——字符串字面量里的关键字参与了判定
- `PRAGMA` 在 `sqlGuard` 里被禁,而 `dbClient` 自己在用 `db.pragma()`——说明黑名单这个思路本身站不住
- SQL 注释可能成为绕过手段

### 四道防线

**防线 1（根本）:只读连接。** `dbClient` 拆成两个连接:

- 查询连接:`new Database(path, { readonly: true })`
- 迁移 / 建表连接:独立的可写连接,仅 `migrate.ts` 使用,用完即关

SQLite 引擎层面拒绝一切写入。这是最重要的一条,它把「正则或 parser 有没有漏洞」从安全前提降级为体验问题。

**防线 2:AST 校验（`node-sql-parser`,sqlite 方言）。**

```
validate(sql):
  1. 含 SQL 注释（-- 或 /* */）→ 直接拒绝
     LLM 没有理由生成注释,允许它只是白送攻击面
  2. parse(sql, { database: "sqlite" })
     ├─ 成功 → 必须是单条语句,且 ast.type === "select"
     │          CTE / WITH 允许;遍历子节点,任何非 select 语句节点 → 拒绝
     └─ 失败 → 回退到防线 3
  3. enforceLimit：AST 可用时读 ast.limit,无则注入;回退路径用正则
```

**防线 3:加固后的正则回退。** parser 对 SQLite 特有语法（`strftime`、部分窗口函数）可能解析失败,直接拒绝会误杀合法查询、拖累可用性。所以 parse 失败时回退到白名单正则,但**先剥离字符串字面量和注释再匹配关键字**——这修掉了 `'已delete'` 被误杀的问题。

**防线 4:引擎级双保险。** `better-sqlite3` 的 `stmt.reader === true` 才允许 `.all()`,由引擎判断语句是否返回数据集。

### 行数上限与截断探测

`runQuery(sql, limit)` 实际执行 `LIMIT limit + 1`,拿到 `limit + 1` 行才判定为截断,返回前截掉多出的一行。修掉 MVP 里 `rows.length >= config.rowLimit` 导致「恰好 1000 行的真实结果被误报为已截断」的 bug。

### 依赖新增

`node-sql-parser`。若实测其 sqlite 方言对示例查询（`strftime` 分组、`CASE WHEN`、子查询、CTE）解析失败率过高,防线 3 会承担主要流量——功能上仍然安全（防线 1 兜底）,但会退化成「AST 只是尽力而为」。实现时需要用手动验收清单里的查询实测一遍解析成功率,并把结果记录在 README。

## 6. 前端与视觉

### 结果卡片的信息层级

MVP 把图表、切换按钮、完整表格平铺在一起,1000 行表格会直接撑爆页面。P1 重新分层:

```
┌───────────────────────────────────────────────┐
│ Chat-BI                                       │  顶栏（P1 仅标题,右侧留数据源占位）
├───────────────────────────────────────────────┤
│ ▌你：按月统计订单金额                          │
│                                               │
│ 统计每月订单总额                               │  queryIntent,一次性下发,静态
│ ╭───────────────────────────────────────────╮ │
│ │ ⟨折线│柱状│饼图│表格⟩            ⌄ SQL   │ │  segmented control + SQL 折叠
│ │                                           │ │
│ │            ╭─╮        ECharts             │ │
│ │       ╭────╯ ╰──╮                         │ │
│ │  ⓘ 已补齐 2 个无数据的时间点（按 0 计）    │ │  spec.notes
│ ├───────────────────────────────────────────┤ │
│ │ 洞察  上半年订单金额整体上涨 23.4%,3 月▍ │ │  insightDelta 真流式
│ │ ⌄ 计算依据（3 项）                        │ │  facts 折叠,默认收起
│ ├───────────────────────────────────────────┤ │
│ │ ⌄ 数据表格（6 行 × 2 列）                 │ │  默认收起
│ ╰───────────────────────────────────────────╯ │
├───────────────────────────────────────────────┤
│ [ 继续追问,例如「只看华东区」        ] [发送] │  有下钻上下文时 placeholder 换成示例
└───────────────────────────────────────────────┘
```

### 样式实现方式

**CSS 变量 + CSS Modules,不引入 Tailwind。** Vite 原生支持 CSS Modules,零额外依赖和配置;深浅色靠 `:root` 与 `@media (prefers-color-scheme: dark)` 两套变量值切换,组件里不写任何颜色字面量。

### theme/tokens.css

- **中性色阶**:`--bg` / `--surface` / `--surface-raised` / `--border` / `--text` / `--text-muted`
- **语义色**:`--accent` / `--positive` / `--negative` / `--warning`
- **字体**:一个 sans 字族;**数字统一 `font-variant-numeric: tabular-nums`**——表格列和坐标轴数字必须等宽对齐,这是 BI 界面最容易被忽略却最影响观感的细节
- **间距**:4px 基准的 6 档（4 / 8 / 12 / 16 / 24 / 32）
- **圆角**:2 档;**阴影**:2 档

### theme/chartPalette.ts

8 色分类色板,约束:

- 相邻色在常见色觉障碍模拟（deuteranopia / protanopia）下可区分
- 深浅色各一套
- 不与语义色（正 / 负 / 警告）撞色,避免用户把某条系列误读为「警告」

顺序色板 P1 不做,留给 P2 的热力图。

**明确决策:涨跌不上色。** 中国金融惯例涨红跌绿,国际 BI 惯例涨绿跌红,两套完全相反。P1 的洞察文本和图表统一用中性 `--accent`,涨跌只靠文字表达（「上涨 23.4%」),避免用颜色传递会被误读的信息。

### 组件拆分

MVP 的 `ResultCard`（55 行）同时负责 option 构建、ECharts 生命周期、类型切换、表格渲染四件事。拆开:

| 组件 | 职责 | 预估 |
|---|---|---|
| `AppShell` | 顶栏 + 整体布局 | ~40 行 |
| `ChatWindow` | 消息列表 + 输入框 + 持有 `lastSql` 下钻上下文 | ~70 行 |
| `MessageBubble` | 用户 / 助手气泡样式区分 | ~30 行 |
| `ResultCard` | 结果卡片容器,编排下面四个 | ~50 行 |
| `ChartView` | 调 `shared/renderer` + ECharts 挂载 / dispose / resize + notes | ~60 行 |
| `SqlDisclosure` | SQL 折叠展示 | ~25 行 |
| `InsightPanel` | 流式文本 + `FactList` 折叠 | ~55 行 |
| `DataTable` | 折叠表格,超过 100 行只渲染前 100 行并提示 | ~45 行 |

### ChatWindow 状态改造

同时修掉索引 bug。MVP 用 `const assistantIdx = messages.length + 1` 从闭包里的旧值算下标,快速连发两条消息时会写错气泡。改为:

- 每条消息带 `id`
- 全部用 `setMessages(prev => ...)` 函数式更新,按 `id` 定位而不是下标
- `lastSql` 从最近一条带 `payload` 的助手消息取,而不是单独维护一份可能不同步的状态

## 7. 测试策略

沿用 Vitest。优先覆盖纯函数和易错边界,编排层用 mock 断言事件序列。

| 模块 | 覆盖点 |
|---|---|
| `columnTypes` | `2026-01` / `2026-01-15` / ISO / 数字字符串 / 全空列 / 混合类型列的角色判定 |
| `chartSpec` | hint 有效路径;**幻觉列名被丢弃**;`seriesBy` 基数 37 → 降级单系列 + note;时间缺口补 0;percent 指标补 null;pie 多 measure 降级 + note;format 与量级推断（元 / 万 / 亿 / %）;`stack` 在单系列或非 bar 时被强制归零 |
| `shared/renderer` | spec → option 快照:单系列、多系列、普通堆叠、**百分比堆叠的归一化**、pie、table 返回 `{}`。纯函数,不需要 jsdom / canvas |
| `shared/format` | 千分位、万 / 亿缩放、百分比、小数位 |
| `facts` | trend / **首值为 0 → trendAbs** / 符号相反 → trendAbs / `flat` 阈值 3% / peak / trough / topShare / concentration / seriesGap / 多系列只算最大系列 / 上限 6 条的截断顺序 / empty |
| `insightWriter` | 正常流逐 token;LLM 抛错 → 模板降级;超时 8s → 模板降级;空结果不调 LLM |
| `sqlGuard` | AST 拦 INSERT / UPDATE / DROP / 多语句 / 含注释;**`SELECT '已delete'` 不被误杀**;parse 失败走回退且回退仍拦写操作;LIMIT 注入与已有 LIMIT 不重复 |
| `dbClient` | **只读连接下 INSERT 抛错**（引擎级验证,不是 mock）;`limit + 1` 探测真截断,恰好 limit 行不误报;schema 提取 |
| `promptBuilder` | 有 context 时注入上轮 SQL、无 context 时不注入;history 截断到 4 条;`buildInsightPrompt` 渲染 facts |
| `chatService` | 事件序列断言 `result → insightFacts → insightDelta* → done`;下钻 context 透传;空结果**跳过第二轮 LLM**;JSON 解析失败重试 1 次;SQL 执行失败回灌重试 1 次;两次都失败发 `error` |
| 前端 | `ResultCard` 切图型调 shared renderer;「查看 SQL」折叠;`InsightPanel` 流式追加 + 计算依据折叠;`DataTable` 超 100 行截断提示;**`ChatWindow` 快速连发两条不串位**（针对索引 bug 的回归测试）;`api` 解析新事件 |

### 不测什么

- 不发真实 Ollama 调用（慢、不稳、依赖外部）
- 不测洞察文案的「好不好」——模型措辞不可定测,靠手动验收
- 不测 ECharts 实际绘制像素——只测传给它的 option

### 手动验收清单（更新 README）

沿用 MVP 的 4 条,新增:

5. 「按月看各区域销售额」→ 多条折线,图例为区域名
6. 「各类别在各区域的销售额占比」→ 百分比堆叠柱状图
7. 三轮下钻链:「按月统计订单金额」→「只看华东区」→「按周看」,每轮图表都正确变化
8. 关掉 Ollama 后重新提问 → 图表仍渲染,洞察降级为模板文本（验证第二轮失败不影响第一轮）
9. 切到深色模式 → 图表配色与界面一致,数字仍等宽对齐

## 8. 实施分期

P1 有 7 条工作流,一个实施计划装不下也不好执行。拆成两期,**各出一份实现计划**:

### P1a — 契约与后端

1. `packages/shared`:类型扩展 + `format.ts` + `renderer.ts`
2. `columnTypes.ts` + `chartSpec.ts`（替换 `chartAssembler.ts`）
3. `facts.ts` + `insightWriter.ts`
4. `sqlGuard.ts` 重写 + `dbClient.ts` 读写连接拆分与截断探测
5. `promptBuilder.ts` 扩展 + `chatService.ts` 编排改造
6. 前端最小适配:`api.ts` 传 `context` 与解析新事件,`ResultCard` 改调 shared renderer,`ChatWindow` 修索引 bug 并持有上下文——**保持现有裸样式**,只保证功能可跑通、测试全绿

P1a 结束时,分析闭环功能完整,界面还是朴素的。

### P1b — 前端与视觉

1. `theme/`:tokens + 图表调色板 + 全局样式
2. 组件拆分:`AppShell` / `ChartView` / `SqlDisclosure` / `InsightPanel` / `DataTable`
3. `ResultCard` / `MessageBubble` / `ChatWindow` 套用设计系统
4. 深浅色适配与图表配色联动

这样切的理由:P1b 依赖 P1a 定下的 `ChartSpec` 与 `InsightFact` 契约（调色板要按 measure 语义上色,`FactList` 要按 fact 类型渲染),反过来不依赖。P1a 独立可验收,P1b 是纯粹的表现层增量,风险和体量都可控。

## 9. 明确不做（YAGNI）

以下都被讨论过并明确排除,不要在实现时「顺手加上」:

| 排除项 | 理由 |
|---|---|
| 数据源适配层（MySQL / PG / ClickHouse） | P2 的核心工作,P1 动它会让每个模块都要处理方言分支 |
| 语义层 / 指标层 | P2。现在做等于把 Text2SQL 换成 QuerySpec 编译器,P1 体量翻倍 |
| 结构化 `QuerySpec` 取代 SQL 文本 | 同上;且窗口函数、复杂子查询表达不了,会退化回 SQL 模式 |
| 元数据持久化 / 会话入库 | P2。P1 后端保持无状态 |
| dashboard 编排与布局 | P2 |
| 图表点击下钻 | 需要接 ECharts 事件、坐标反查维度值、面包屑导航;P1 先把上下文链路跑通 |
| LLM 推荐下钻问题 | 每轮多一次本地模型调用,收益不确定 |
| 双轴 / 散点 / KPI 卡片 | 图表类型从 4 种扩到 7 种会显著抬高 prompt 选型难度 |
| 洞察输出的数字后校验 | 格式化形态多样导致假警报;改用「计算依据」折叠让人对照 |
| 下钻意图分类器 | 第三次 LLM 调用 + 一整类新错误模式,prompt 一句说明已够 |
| 顺序色板 / 热力图配色 | P1 没有用到它的图表类型 |
| 认证与多用户 | 仍是单用户本地工具 |
| Docker | 沿用 MVP 决策,首版不引入 |

## 10. 已决策清单

| # | 决策 | 备选与理由 |
|---|---|---|
| 1 | **LLM 出语义 hint,后端推 encoding** | 备选「LLM 出完整 IR」不稳且无法单测;「纯后端推断」拿不到用户意图（「占比」应该给饼图） |
| 2 | **规则算事实 + LLM 改写措辞** | 备选「纯 LLM 解读」会算错数字;「纯模板」读感生硬 |
| 3 | **前端回传上轮 SQL,后端无状态** | 备选「后端会话 store」会在 P2 被推翻,且带来重启丢上下文问题 |
| 4 | **下钻靠自然语言追问** | 图表点击下钻留待后续,先跑通上下文链路 |
| 5 | **图表覆盖多系列 + 时间轴 + 堆叠 / 百分比堆叠** | 不扩新图型,避免抬高 prompt 选型难度 |
| 6 | **renderer 放 `packages/shared`** | 消除前后端重复的 `buildOption`,且 P2 服务端导出可复用 |
| 7 | **两次 LLM 串行,图表先落地** | 备选「洞察独立端点」多一次往返;「合并成一次」模型没看到数据 |
| 8 | **时间缺口按 0 补,percent 指标按 null 补** | SUM/COUNT 场景无数据即 0;比率类补 0 会失真 |
| 9 | **`seriesBy` 基数上限 12** | 超过则退化单系列 + note,30 条线无可读性 |
| 10 | **`trend` 首值为 0 或符号相反时改产 `trendAbs`** | 避免 `Infinity` 和误导性增长率 |
| 11 | **事实上限 6 条,多系列只算最大系列** | 防止洞察文本退化成事实罗列 |
| 12 | **只读连接为根本防线,AST 为体验层** | 把安全性从「正则对不对」转移到引擎强制 |
| 13 | **AST parse 失败回退加固正则,而非直接拒绝** | 避免误杀 SQLite 特有语法,可用性优先（安全由防线 1 兜底） |
| 14 | **拒绝含 SQL 注释的语句** | LLM 无理由生成注释,允许它只是白送攻击面 |
| 15 | **`result` 事件回传 SQL** | 下钻需要,且解锁「查看 SQL」,对建立信任比洞察更重要 |
| 16 | **移除 `explanationDelta` 假流式** | 首字延迟等于全量延迟,是视觉欺骗;真流式给第二轮 |
| 17 | **CSS 变量 + CSS Modules,不用 Tailwind** | Vite 原生支持,零配置成本 |
| 18 | **涨跌不上色** | 中式涨红跌绿与国际涨绿跌红相反,用颜色传递会被误读 |
| 19 | **不做洞察数字后校验,改用「计算依据」折叠** | 格式化形态多样导致假警报;把可信度交给人 |
| 20 | **拆成 P1a / P1b 两份实现计划** | P1b 依赖 P1a 的契约,反之不依赖;各自独立可验收 |

## 待定项

无。所有关键决策已在上表明确。实现阶段唯一需要实测确认的是 `node-sql-parser` 对 SQLite 方言的解析成功率（见第 5 节末),结果影响的是 AST 与正则回退的流量分配,不影响任何接口设计。
