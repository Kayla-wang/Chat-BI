# Chat-BI P1a 契约与后端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 MVP 的「单轮问答 → 一个图表」补成完整分析闭环的**后端与契约部分**:语义化 ChartSpec + 共享 renderer、多系列/时间轴/堆叠、规则算事实 + LLM 改写的洞察、带上轮 SQL 的多轮下钻、只读连接为根本防线的 SQL 安全层。前端只做能跑通的最小适配,视觉留给 P1b。

**Architecture:** LLM 只输出语义 hint(`ChartHint`),后端 `inferChartSpec` 校验 hint 并从结果集推导出完整 `ChartSpec`;`packages/shared` 提供唯一的 `specToEchartsOption` renderer 供两端复用。洞察走「纯函数算事实 → 第二次 LLM 调用改写措辞」,LLM 从不接触原始数据行。下钻上下文由前端持有并回传,后端保持无状态。

**Tech Stack:** Node.js + TypeScript + Express + better-sqlite3 + node-sql-parser + Vitest(后端);React + TypeScript + Vite + ECharts + Vitest + React Testing Library(前端);Ollama REST API;npm workspaces。

## Global Constraints

- 设计文档:`docs/superpowers/specs/2026-07-28-chatbi-p1-analysis-loop-design.md`。本计划实现其第 1–5 节与第 7 节的后端部分,第 6 节(前端与视觉)由 P1b 实现。
- 图表类型枚举固定 `bar | line | pie | table`,**P1 不新增图型**。
- 堆叠模式枚举 `none | normal | percent`,**仅 `chartType === "bar"` 且 `series.length > 1` 时生效**,否则强制 `"none"`。
- `seriesBy` 去重基数上限 **12**,超过则退化单系列并写 note。
- 时间缺口默认按 **0** 补;`format.kind === "percent"` 的系列按 **null** 补。
- 事实上限 **6 条**;`flat` 判定阈值 `|pct| < 3`;`trend` 首值为 0 或首末符号相反时改产 `trendAbs`。
- 多系列时 `trend`/`peak`/`trough` **只对总量最大的那条系列**计算。
- LLM 重试上限 **1 次**(沿用 MVP);洞察第二轮独立超时 `INSIGHT_TIMEOUT_MS` 默认 **8000**。
- 行数上限沿用 `ROW_LIMIT` 默认 **1000**;查询实际执行 `LIMIT limit + 1` 以探测真截断。
- SQL 安全四道防线:只读连接(根本)→ AST 校验 → 加固正则回退 → `stmt.reader` 检查。含 SQL 注释的语句直接拒绝。
- 后端保持**无状态**:不引入任何 session store,下钻上下文由前端回传。
- `explanationDelta` 事件移除;`ChartPayload` 被 `ResultPayload` 取代。前后端同仓库同时改,不做兼容期。
- 测试框架 Vitest;不发真实 Ollama 调用;不测 ECharts 绘制像素,只测传给它的 option。
- 每个 Task 以 TDD 五步推进(写失败测试 → 跑红 → 实现 → 跑绿 → 提交)。
- 提交信息英文,前缀 `feat:` / `test:` / `refactor:` / `fix:` / `chore:`。
- 工作分支 `p1-analysis-loop`(已存在,spec 已提交在 `5dbcd22`)。

---

## 与 spec 的一处签名细化

spec 第 3 节写的是 `computeFacts(rows, spec)`。实现改为 **`computeFacts(spec, opts)`**——`ChartSpec` 里已经有归一化后的 `series[].data`、`x.labels` 和 `format`,再传一份原始 `rows` 只会让事实计算面对「用 rows 还是用 spec」的二义性(补齐过的时间点在 rows 里不存在)。行为不变,只是去掉冗余入参。

---

## File Structure

```
packages/shared/src/
├─ types.ts          # 新增:ChartSpec / ChartHint / InsightFact / DrillContext
│                    #       ResultPayload / StreamEvent / ValueFormat / ChartSeries
├─ format.ts         # 新增:formatValue / formatTimeLabel  纯函数
├─ renderer.ts       # 新增:specToEchartsOption  唯一的 ECharts 生成实现
├─ facts.ts          # 新增:renderFactsLines / renderFactsTemplate  前后端共用的事实措辞
└─ index.ts          # 修改:改成纯 barrel,re-export 上面四个

apps/backend/src/
├─ columnTypes.ts    # 新增:列角色嗅探 detectRole / detectColumnRoles / parseTemporal
├─ timeAxis.ts       # 新增:inferGrain / toTickKey / enumerateTicks / fillGaps
├─ pivot.ts          # 新增:pivotSeries  按维度拆系列
├─ chartSpec.ts      # 新增:inferChartSpec / inferFormat  编排上面三者(替换 chartAssembler)
├─ facts.ts          # 新增:computeFacts,并 re-export shared 的两个渲染函数
├─ insightWriter.ts  # 新增:writeInsight  第二轮 LLM + 超时降级
├─ sqlGuard.ts       # 重写:AST 校验 + 加固正则回退
├─ dbClient.ts       # 修改:读写连接拆分、runQuery 返回 truncated
├─ promptBuilder.ts  # 修改:hint 字段要求 + 下钻上下文;新增 buildInsightPrompt
├─ chatService.ts    # 修改:两轮 LLM 编排、新事件序列
├─ config.ts         # 修改:新增 insightTimeoutMs
├─ chartAssembler.ts # 删除
└─ routes/chat.ts    # 修改:接收并透传 context

apps/frontend/src/
├─ api.ts            # 修改:传 context,解析新事件
├─ components/
│  ├─ ResultCard.tsx    # 修改:改调 shared renderer,删除本地 buildOption
│  ├─ MessageBubble.tsx # 修改:适配 ResultPayload,挂 InsightPanel
│  ├─ InsightPanel.tsx  # 新增:洞察文本 + 计算依据折叠(P1a 为无样式版)
│  └─ ChatWindow.tsx    # 修改:消息带 id、函数式更新、持有 lastSql
```

**测试文件**与被测文件一一对应,后端在 `apps/backend/tests/`,shared 在 `packages/shared/tests/`,前端在 `apps/frontend/src/__tests__/`。

---

### Task 1: shared 类型契约 + 格式化纯函数

**Files:**
- Create: `packages/shared/src/types.ts`(所有共享类型)
- Create: `packages/shared/src/format.ts`
- Modify: `packages/shared/src/index.ts`(全量替换成 barrel,现有 26 行)
- Modify: `packages/shared/tests/index.test.ts`(全量替换,现有断言引用了将被删除的 `ChartPayload`)
- Test: `packages/shared/tests/format.test.ts`

**Interfaces:**
- Consumes: 无(本计划第一个任务)
- Produces:
  - 全部共享类型:`Row` `ChartType` `ColumnRole` `TimeGrain` `StackMode` `TableSchema` `ChatTurn` `ValueFormat` `ChartSeries` `ChartSpec` `ChartHint` `InsightFact` `DrillContext` `ResultPayload` `StreamEvent`
  - `formatValue(v: number | null, f: ValueFormat): string`
  - `formatTimeLabel(tickKey: string, grain: TimeGrain, crossYear: boolean): string`

**包结构改成 barrel。** `packages/shared/package.json` 的入口是 `./src/index.ts`,而后端和前端都要从 `@chatbi/shared` 同时拿类型和纯函数(`formatValue`、`formatTimeLabel`,以及 Task 7 会加的 `renderFactsLines`)。如果类型和 re-export 都写在 `index.ts` 里,`renderer.ts` 又从 `index.ts` import 类型,就形成了循环 import。所以拆开:

```
packages/shared/src/
├─ types.ts     # 只有类型,不 import 任何本包文件
├─ format.ts    # import type from "./types"
├─ renderer.ts  # import type from "./types" + formatValue from "./format"   (Task 2)
├─ facts.ts     # import type from "./types" + formatValue from "./format"   (Task 7)
└─ index.ts     # 纯 barrel: export * from 上面四个
```

`package.json` 不用改,入口仍是 `src/index.ts`。

**两条口径约定**(后续所有任务依赖):
- `ValueFormat.kind === "percent"` 的数值**已经是百分数**:`41.2` 表示 41.2%。SQL 侧通常写 `ROUND(100.0 * x / total, 1)`,`InsightFact.pct` 同口径。
- `tickKey` 是时间刻度的规范化字符串:year `"2026"`、quarter `"2026-Q1"`、month `"2026-01"`、week `"2026-01-12"`(该周周一的日期)、day `"2026-01-15"`。week 的标签直接按「周起始日」渲染,不做 ISO 周序号计算。

- [ ] **Step 1: 写失败测试**

创建 `packages/shared/tests/format.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { formatValue, formatTimeLabel } from "../src/format";
import type { ValueFormat } from "../src/index";

const f = (over: Partial<ValueFormat> = {}): ValueFormat =>
  ({ kind: "number", decimals: 0, scale: 1, ...over });

describe("formatValue", () => {
  it("千分位分组", () => {
    expect(formatValue(128400, f())).toBe("128,400");
  });
  it("货币带单位", () => {
    expect(formatValue(128400, f({ kind: "currency", unit: "元" }))).toBe("128,400 元");
  });
  it("万缩放保留两位", () => {
    expect(formatValue(128400, f({ kind: "currency", decimals: 2, unit: "元", scale: 10000 })))
      .toBe("12.84 万元");
  });
  it("亿缩放", () => {
    expect(formatValue(1234567890, f({ kind: "number", decimals: 2, scale: 100000000 })))
      .toBe("12.35 亿");
  });
  it("百分数按已是百分数处理", () => {
    expect(formatValue(41.2, f({ kind: "percent", decimals: 1 }))).toBe("41.2%");
  });
  it("null 渲染为破折号", () => {
    expect(formatValue(null, f())).toBe("—");
  });
  it("负数保留符号与分组", () => {
    expect(formatValue(-1234.5, f({ decimals: 1 }))).toBe("-1,234.5");
  });
});

describe("formatTimeLabel", () => {
  it("月份同年只显示月", () => {
    expect(formatTimeLabel("2026-01", "month", false)).toBe("1月");
  });
  it("月份跨年带年份", () => {
    expect(formatTimeLabel("2026-01", "month", true)).toBe("2026年1月");
  });
  it("日", () => {
    expect(formatTimeLabel("2026-01-15", "day", false)).toBe("1月15日");
  });
  it("日跨年", () => {
    expect(formatTimeLabel("2026-01-15", "day", true)).toBe("2026年1月15日");
  });
  it("周按周起始日渲染", () => {
    expect(formatTimeLabel("2026-01-12", "week", false)).toBe("1月12日");
  });
  it("季度", () => {
    expect(formatTimeLabel("2026-Q1", "quarter", false)).toBe("Q1");
    expect(formatTimeLabel("2026-Q1", "quarter", true)).toBe("2026Q1");
  });
  it("年", () => {
    expect(formatTimeLabel("2026", "year", false)).toBe("2026年");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root packages/shared run tests/format.test.ts`
Expected: FAIL，`Failed to resolve import "../src/format"`

- [ ] **Step 3: 创建 `packages/shared/src/types.ts`**

```ts
export type Row = Record<string, string | number | null>;

export type ChartType = "bar" | "line" | "pie" | "table";
export type ColumnRole = "temporal" | "categorical" | "numeric";
export type TimeGrain = "day" | "week" | "month" | "quarter" | "year";
export type StackMode = "none" | "normal" | "percent";

export interface TableSchema {
  tableName: string;
  columns: { name: string; type: string; notNull: boolean; pk: boolean }[];
  foreignKeys: { column: string; refTable: string; refColumn: string }[];
}

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

/** 数值展示口径。percent 的值已是百分数(41.2 表示 41.2%)。 */
export interface ValueFormat {
  kind: "number" | "currency" | "percent";
  decimals: number;
  unit?: string;
  scale?: 1 | 10000 | 100000000;
}

export interface ChartSeries {
  name: string;
  field: string;
  data: (number | null)[];
  format: ValueFormat;
}

export interface ChartSpec {
  chartType: ChartType;
  stack: StackMode;
  x: {
    field: string;
    role: "temporal" | "categorical";
    labels: string[];
    grain?: TimeGrain;
  };
  series: ChartSeries[];
  notes: string[];
}

/** LLM 输出的图表语义提示——不可信,inferChartSpec 会逐字段校验。 */
export interface ChartHint {
  chartType: ChartType;
  dimensions: string[];
  measures: string[];
  seriesBy?: string;
  stack?: StackMode;
}

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

export interface DrillContext {
  lastSql: string;
  lastColumns: string[];
}

export interface ResultPayload {
  spec: ChartSpec;
  table: { columns: string[]; rows: Row[] };
  queryIntent: string;
  sql: string;
}

export type StreamEvent =
  | { type: "result"; payload: ResultPayload }
  | { type: "insightFacts"; facts: InsightFact[] }
  | { type: "insightDelta"; text: string }
  | { type: "done" }
  | { type: "error"; message: string; raw?: string };
```

- [ ] **Step 4: 创建 `packages/shared/src/format.ts`**

```ts
import type { ValueFormat, TimeGrain } from "./types";

const SCALE_SUFFIX: Record<number, string> = { 1: "", 10000: "万", 100000000: "亿" };

function group(n: string): string {
  const [int, frac] = n.split(".");
  const sign = int.startsWith("-") ? "-" : "";
  const digits = sign ? int.slice(1) : int;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac ? `${sign}${grouped}.${frac}` : `${sign}${grouped}`;
}

export function formatValue(v: number | null, f: ValueFormat): string {
  if (v === null || Number.isNaN(v)) return "—";
  if (f.kind === "percent") return `${v.toFixed(f.decimals)}%`;
  const scale = f.scale ?? 1;
  const scaled = v / scale;
  const num = group(scaled.toFixed(f.decimals));
  const suffix = SCALE_SUFFIX[scale] ?? "";
  if (f.kind === "currency") return `${num} ${suffix}${f.unit ?? ""}`.replace(/\s+$/, "");
  return suffix ? `${num} ${suffix}` : num;
}

export function formatTimeLabel(tickKey: string, grain: TimeGrain, crossYear: boolean): string {
  if (grain === "year") return `${tickKey}年`;
  if (grain === "quarter") {
    const [y, q] = tickKey.split("-");
    return crossYear ? `${y}${q}` : q;
  }
  const [y, m, d] = tickKey.split("-");
  const month = Number(m);
  if (grain === "month") return crossYear ? `${y}年${month}月` : `${month}月`;
  const day = Number(d);
  return crossYear ? `${y}年${month}月${day}日` : `${month}月${day}日`;
}
```

- [ ] **Step 5: 全量替换 `packages/shared/src/index.ts` 成 barrel**

```ts
export * from "./types";
export * from "./format";
```

Task 2 会追加 `export * from "./renderer";`,Task 7 会追加 `export * from "./facts";`。

- [ ] **Step 6: 全量替换 `packages/shared/tests/index.test.ts`**

旧文件断言了 `ChartPayload` 和 `explanationDelta`,两者都已删除。

```ts
import { describe, it, expect } from "vitest";
import type {
  Row, TableSchema, ChartType, ChartSpec, ResultPayload, StreamEvent, ChatTurn,
  InsightFact, DrillContext,
} from "../src/index";

describe("shared types", () => {
  it("Row 是主键为字符串的原始值记录", () => {
    const r: Row = { id: 1, name: "x", missing: null };
    expect(r.name).toBe("x");
  });

  it("ChartType 有 4 个成员", () => {
    const c: ChartType[] = ["bar", "line", "pie", "table"];
    expect(c).toHaveLength(4);
  });

  it("ChartSpec 形状可编译", (): ChartSpec => ({
    chartType: "line",
    stack: "none",
    x: { field: "month", role: "temporal", labels: ["1月"], grain: "month" },
    series: [{
      name: "金额", field: "amount", data: [1, null],
      format: { kind: "currency", decimals: 0, unit: "元", scale: 1 },
    }],
    notes: [],
  }));

  it("ResultPayload 形状可编译", (): ResultPayload => ({
    spec: {
      chartType: "table", stack: "none",
      x: { field: "a", role: "categorical", labels: [] }, series: [], notes: [],
    },
    table: { columns: ["a"], rows: [{ a: 1 }] },
    queryIntent: "ok",
    sql: "SELECT a FROM t",
  }));

  it("InsightFact 是可判别联合", () => {
    const f: InsightFact[] = [
      { kind: "trend", series: "s", dir: "up", pct: 1, from: "a", to: "b" },
      { kind: "trendAbs", series: "s", delta: 1, from: "a", to: "b" },
      { kind: "peak", series: "s", label: "a", value: 1 },
      { kind: "trough", series: "s", label: "a", value: 1 },
      { kind: "topShare", series: "s", label: "a", pct: 1 },
      { kind: "concentration", series: "s", topN: 3, pct: 1 },
      { kind: "total", series: "s", value: 1 },
      { kind: "seriesGap", high: "a", low: "b", ratio: 2 },
      { kind: "truncated", limit: 1000 },
      { kind: "empty" },
    ];
    expect(f).toHaveLength(10);
  });

  it("StreamEvent 是可判别联合", () => {
    const events: StreamEvent[] = [
      { type: "result", payload: {} as ResultPayload },
      { type: "insightFacts", facts: [{ kind: "empty" }] },
      { type: "insightDelta", text: "x" },
      { type: "done" },
      { type: "error", message: "bad", raw: "raw" },
    ];
    expect(events.map(e => e.type)).toEqual([
      "result", "insightFacts", "insightDelta", "done", "error",
    ]);
  });

  it("DrillContext 与 ChatTurn 形状可编译", () => {
    const d: DrillContext = { lastSql: "SELECT 1", lastColumns: ["a"] };
    const t: ChatTurn = { role: "user", text: "q" };
    const s: TableSchema = { tableName: "t", columns: [], foreignKeys: [] };
    expect([d.lastSql, t.role, s.tableName]).toEqual(["SELECT 1", "user", "t"]);
  });
});
```

- [ ] **Step 7: 跑测试确认通过**

Run: `npx vitest --root packages/shared run`
Expected: PASS(format + index 两个测试文件全绿)

- [ ] **Step 8: 提交**

```bash
git add packages/shared/src/types.ts packages/shared/src/index.ts packages/shared/src/format.ts packages/shared/tests/
git commit -m "feat(shared): P1 chart spec contract and value/time formatters"
```

### Task 2: shared renderer —— 唯一的 ECharts option 生成实现

**Files:**
- Create: `packages/shared/src/renderer.ts`
- Modify: `packages/shared/src/index.ts`(barrel 追加一行)
- Test: `packages/shared/tests/renderer.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `ChartSpec` `ChartSeries` `ValueFormat`、`formatValue`
- Produces: `specToEchartsOption(spec: ChartSpec, palette: string[]): Record<string, unknown>`

**为什么 renderer 里可以放函数**:P1 起后端不再下发 `echartsOption`,只下发 `ChartSpec`。renderer 在前端进程内调用,`formatter` 闭包不需要经过 JSON 序列化。

- [ ] **Step 1: 写失败测试**

创建 `packages/shared/tests/renderer.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { specToEchartsOption } from "../src/renderer";
import type { ChartSpec, ChartSeries } from "../src/index";

const PALETTE = ["#1", "#2", "#3"];
const fmt = { kind: "currency" as const, decimals: 0, unit: "元", scale: 1 as const };

const s = (name: string, data: (number | null)[]): ChartSeries =>
  ({ name, field: "amount", data, format: fmt });

const base = (over: Partial<ChartSpec> = {}): ChartSpec => ({
  chartType: "line",
  stack: "none",
  x: { field: "month", role: "temporal", labels: ["1月", "2月"], grain: "month" },
  series: [s("订单金额", [100, 200])],
  notes: [],
  ...over,
});

describe("specToEchartsOption", () => {
  it("table 返回空 option", () => {
    expect(specToEchartsOption(base({ chartType: "table", series: [] }), PALETTE)).toEqual({});
  });

  it("单系列折线:类目轴 + 一条 line", () => {
    const o = specToEchartsOption(base(), PALETTE) as any;
    expect(o.xAxis.type).toBe("category");
    expect(o.xAxis.data).toEqual(["1月", "2月"]);
    expect(o.series).toHaveLength(1);
    expect(o.series[0].type).toBe("line");
    expect(o.series[0].data).toEqual([100, 200]);
    expect(o.color).toEqual(PALETTE);
  });

  it("多系列生成图例", () => {
    const o = specToEchartsOption(
      base({ series: [s("华东", [1, 2]), s("华北", [3, 4])] }), PALETTE) as any;
    expect(o.legend.data).toEqual(["华东", "华北"]);
    expect(o.series).toHaveLength(2);
  });

  it("普通堆叠:每条 series 带同一个 stack key", () => {
    const o = specToEchartsOption(base({
      chartType: "bar", stack: "normal", series: [s("华东", [1, 2]), s("华北", [3, 4])],
    }), PALETTE) as any;
    expect(o.series.map((x: any) => x.stack)).toEqual(["total", "total"]);
  });

  it("百分比堆叠:renderer 内部归一化,轴按百分比", () => {
    const o = specToEchartsOption(base({
      chartType: "bar", stack: "percent", series: [s("华东", [1, 3]), s("华北", [3, 1])],
    }), PALETTE) as any;
    expect(o.series[0].data).toEqual([25, 75]);
    expect(o.series[1].data).toEqual([75, 25]);
    expect(o.yAxis.max).toBe(100);
    expect(o.yAxis.axisLabel.formatter(25)).toBe("25.0%");
  });

  it("百分比堆叠某列全为 0 时该列产出 null", () => {
    const o = specToEchartsOption(base({
      chartType: "bar", stack: "percent", series: [s("华东", [0, 3]), s("华北", [0, 1])],
    }), PALETTE) as any;
    expect(o.series[0].data[0]).toBeNull();
    expect(o.series[1].data[0]).toBeNull();
  });

  it("pie 用 x.labels 与第一条系列组 name/value", () => {
    const o = specToEchartsOption(base({
      chartType: "pie",
      x: { field: "category", role: "categorical", labels: ["电子", "机械"] },
      series: [s("销售额", [70, 30])],
    }), PALETTE) as any;
    expect(o.series[0].type).toBe("pie");
    expect(o.series[0].data).toEqual([
      { name: "电子", value: 70 }, { name: "机械", value: 30 },
    ]);
    expect(o.xAxis).toBeUndefined();
  });

  it("y 轴与 tooltip 复用 formatValue", () => {
    const o = specToEchartsOption(base(), PALETTE) as any;
    expect(o.yAxis.axisLabel.formatter(128400)).toBe("128,400 元");
    expect(o.tooltip.valueFormatter(128400)).toBe("128,400 元");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root packages/shared run tests/renderer.test.ts`
Expected: FAIL，`Failed to resolve import "../src/renderer"`

- [ ] **Step 3: 实现 `packages/shared/src/renderer.ts`**

```ts
import type { ChartSpec, ChartSeries, ValueFormat } from "./types";
import { formatValue } from "./format";

const PERCENT_FORMAT: ValueFormat = { kind: "percent", decimals: 1 };

/** 把每个 x 位置上各系列的值换算成占比,列和为 0 时整列产出 null。 */
function normalizeToPercent(series: ChartSeries[]): ChartSeries[] {
  const len = series[0]?.data.length ?? 0;
  const sums: number[] = [];
  for (let i = 0; i < len; i++) {
    sums[i] = series.reduce((acc, s) => acc + (s.data[i] ?? 0), 0);
  }
  return series.map(s => ({
    ...s,
    format: PERCENT_FORMAT,
    data: s.data.map((v, i) => (sums[i] === 0 || v === null ? null : (v / sums[i]) * 100)),
  }));
}

export function specToEchartsOption(spec: ChartSpec, palette: string[]): Record<string, unknown> {
  if (spec.chartType === "table" || spec.series.length === 0) return {};

  if (spec.chartType === "pie") {
    const first = spec.series[0];
    return {
      color: palette,
      tooltip: { trigger: "item", valueFormatter: (v: number) => formatValue(v, first.format) },
      legend: { data: spec.x.labels },
      series: [{
        type: "pie",
        name: first.name,
        data: spec.x.labels.map((name, i) => ({ name, value: first.data[i] })),
      }],
    };
  }

  const isPercent = spec.chartType === "bar" && spec.stack === "percent";
  const series = isPercent ? normalizeToPercent(spec.series) : spec.series;
  const axisFormat = series[0].format;

  const option: Record<string, unknown> = {
    color: palette,
    tooltip: { trigger: "axis", valueFormatter: (v: number) => formatValue(v, axisFormat) },
    xAxis: { type: "category", data: spec.x.labels },
    yAxis: {
      type: "value",
      axisLabel: { formatter: (v: number) => formatValue(v, axisFormat) },
      ...(isPercent ? { max: 100, min: 0 } : {}),
    },
    series: series.map(s => ({
      type: spec.chartType,
      name: s.name,
      data: s.data,
      ...(spec.stack === "none" ? {} : { stack: "total" }),
    })),
  };
  if (series.length > 1) option.legend = { data: series.map(s => s.name) };
  return option;
}
```

- [ ] **Step 4: barrel 追加导出**

`packages/shared/src/index.ts` 末尾加一行:

```ts
export * from "./renderer";
```

- [ ] **Step 5: 跑测试确认通过**

Run: `npx vitest --root packages/shared run`
Expected: PASS(format + renderer + index 三个测试文件全绿)

- [ ] **Step 6: 提交**

```bash
git add packages/shared/src/renderer.ts packages/shared/src/index.ts packages/shared/tests/renderer.test.ts
git commit -m "feat(shared): single ECharts renderer from ChartSpec"
```

### Task 3: 列角色嗅探

**Files:**
- Create: `apps/backend/src/columnTypes.ts`
- Test: `apps/backend/tests/columnTypes.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `Row` `ColumnRole`
- Produces:
  - `parseTemporal(v: string | number | null): Date | null`
  - `detectRole(values: (string | number | null)[], columnName: string): ColumnRole`
  - `detectColumnRoles(rows: Row[], columns: string[]): Record<string, ColumnRole>`

**一处对 spec 的必要收紧**:spec 第 2 节把 numeric 判定写在 temporal 之前。照字面实现会把年份列 `2024, 2025, 2026` 判成 numeric,进而被当成指标画进图里。所以判定顺序细化为:**带分隔符的 ISO 形态(`YYYY-MM`、`YYYY-MM-DD`、ISO 8601)优先判 temporal;裸四位年份只在列名含时间语义时(`year|date|time|month|年|月|日期|季|周`)才判 temporal,否则判 numeric**。

**日期一律按 UTC 构造**,避免本机时区(win32)让测试在跨时区环境下漂移。

- [ ] **Step 1: 写失败测试**

创建 `apps/backend/tests/columnTypes.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { detectRole, detectColumnRoles, parseTemporal } from "../src/columnTypes";

describe("detectRole", () => {
  it("YYYY-MM 判 temporal", () => {
    expect(detectRole(["2026-01", "2026-02"], "month")).toBe("temporal");
  });
  it("YYYY-MM-DD 判 temporal", () => {
    expect(detectRole(["2026-01-15", "2026-02-03"], "d")).toBe("temporal");
  });
  it("ISO 8601 判 temporal", () => {
    expect(detectRole(["2026-01-15T08:00:00Z"], "ts")).toBe("temporal");
  });
  it("裸年份 + 时间语义列名判 temporal", () => {
    expect(detectRole([2024, 2025, 2026], "order_year")).toBe("temporal");
  });
  it("裸年份 + 非时间语义列名判 numeric", () => {
    expect(detectRole([2024, 2025, 2026], "amount")).toBe("numeric");
  });
  it("数字字符串判 numeric", () => {
    expect(detectRole(["100", "200.5"], "total")).toBe("numeric");
  });
  it("含 null 的数值列仍判 numeric", () => {
    expect(detectRole([100.5, null, 200], "total")).toBe("numeric");
  });
  it("文本判 categorical", () => {
    expect(detectRole(["华东", "华北"], "region")).toBe("categorical");
  });
  it("全空列判 categorical", () => {
    expect(detectRole([null, null], "x")).toBe("categorical");
  });
  it("混合类型判 categorical", () => {
    expect(detectRole(["2026-01", "华东"], "month")).toBe("categorical");
    expect(detectRole(["1200", "abc"], "total")).toBe("categorical");
  });
  it("非法月份不算 temporal", () => {
    expect(detectRole(["2026-13"], "month")).toBe("categorical");
  });
});

describe("parseTemporal", () => {
  it("按 UTC 解析各形态", () => {
    expect(parseTemporal("2026-01")!.toISOString()).toBe("2026-01-01T00:00:00.000Z");
    expect(parseTemporal("2026-01-15")!.toISOString()).toBe("2026-01-15T00:00:00.000Z");
    expect(parseTemporal(2026)!.toISOString()).toBe("2026-01-01T00:00:00.000Z");
  });
  it("无法解析返回 null", () => {
    expect(parseTemporal("华东")).toBeNull();
    expect(parseTemporal(null)).toBeNull();
    expect(parseTemporal("2026-13")).toBeNull();
  });
});

describe("detectColumnRoles", () => {
  it("逐列给出角色", () => {
    const rows = [
      { month: "2026-01", region: "华东", amount: 100 },
      { month: "2026-02", region: "华北", amount: 200 },
    ];
    expect(detectColumnRoles(rows, ["month", "region", "amount"])).toEqual({
      month: "temporal", region: "categorical", amount: "numeric",
    });
  });
  it("空结果集所有列判 categorical", () => {
    expect(detectColumnRoles([], ["a", "b"])).toEqual({ a: "categorical", b: "categorical" });
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/backend run tests/columnTypes.test.ts`
Expected: FAIL，`Failed to resolve import "../src/columnTypes"`

- [ ] **Step 3: 实现 `apps/backend/src/columnTypes.ts`**

```ts
import type { Row, ColumnRole } from "@chatbi/shared";

const BARE_YEAR = /^\d{4}$/;
const ISO_LIKE = /^(\d{4})-(\d{2})(?:-(\d{2}))?(?:[T ].*)?$/;
const TIME_NAME = /(year|date|time|month|week|day|quarter|年|月|日|季|周|期)/i;

export function parseTemporal(v: string | number | null): Date | null {
  if (v === null || v === "") return null;
  const s = String(v);
  if (BARE_YEAR.test(s)) return new Date(Date.UTC(Number(s), 0, 1));
  const m = ISO_LIKE.exec(s);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = m[3] ? Number(m[3]) : 1;
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const d = new Date(Date.UTC(year, month - 1, day));
  return Number.isNaN(d.getTime()) ? null : d;
}

export function detectRole(values: (string | number | null)[], columnName: string): ColumnRole {
  const nonNull = values.filter(v => v !== null && v !== "");
  if (nonNull.length === 0) return "categorical";

  const allIso = nonNull.every(v => typeof v === "string" && ISO_LIKE.test(v) && parseTemporal(v) !== null);
  if (allIso) return "temporal";

  const allBareYear = nonNull.every(v => BARE_YEAR.test(String(v)));
  if (allBareYear && TIME_NAME.test(columnName)) return "temporal";

  const allNumeric = nonNull.every(v => !Number.isNaN(Number(v)));
  if (allNumeric) return "numeric";

  return "categorical";
}

export function detectColumnRoles(rows: Row[], columns: string[]): Record<string, ColumnRole> {
  const out: Record<string, ColumnRole> = {};
  for (const c of columns) out[c] = detectRole(rows.map(r => r[c] ?? null), c);
  return out;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest --root apps/backend run tests/columnTypes.test.ts`
Expected: PASS(24 个断言全绿)

- [ ] **Step 5: 提交**

```bash
git add apps/backend/src/columnTypes.ts apps/backend/tests/columnTypes.test.ts
git commit -m "feat(backend): column role detection for chart spec inference"
```

### Task 4: 时间轴 —— 粒度推断、刻度枚举、缺口补齐

**Files:**
- Create: `apps/backend/src/timeAxis.ts`
- Test: `apps/backend/tests/timeAxis.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `ChartSeries` `TimeGrain`、Task 3 的 `parseTemporal`
- Produces:
  - `inferGrain(keys: string[]): TimeGrain`
  - `toTickKey(d: Date, grain: TimeGrain): string`
  - `enumerateTicks(from: string, to: string, grain: TimeGrain): string[]`
  - `fillGaps(opts: { tickKeys: string[]; rowKeys: string[]; series: ChartSeries[] }): { series: ChartSeries[]; filled: number }`

**粒度从字符串形态推断,而不是从时间间隔推断**。SQL 侧写 `strftime('%Y-%m', ...)` 时每个键都是 `"2026-01"`,形态本身就是无歧义的答案;只有键是完整日期时才需要看间隔来区分「按日」和「按周」。这比纯间隔分析稳得多,单个数据点也不会退化。

**补齐口径**:缺失刻度按 `0` 补,`format.kind === "percent"` 的系列按 `null` 补(比率类没有数据不等于 0%)。

- [ ] **Step 1: 写失败测试**

创建 `apps/backend/tests/timeAxis.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { inferGrain, toTickKey, enumerateTicks, fillGaps } from "../src/timeAxis";
import type { ChartSeries, ValueFormat } from "@chatbi/shared";

const CURRENCY: ValueFormat = { kind: "currency", decimals: 0, unit: "元", scale: 1 };
const PERCENT: ValueFormat = { kind: "percent", decimals: 1 };
const series = (data: (number | null)[], format = CURRENCY): ChartSeries =>
  ({ name: "金额", field: "amount", data, format });

describe("inferGrain", () => {
  it("YYYY → year", () => expect(inferGrain(["2024", "2025"])).toBe("year"));
  it("YYYY-Qn → quarter", () => expect(inferGrain(["2025-Q4", "2026-Q1"])).toBe("quarter"));
  it("YYYY-MM → month", () => expect(inferGrain(["2026-01", "2026-02"])).toBe("month"));
  it("单个 YYYY-MM 仍为 month", () => expect(inferGrain(["2026-01"])).toBe("month"));
  it("连续日期 → day", () => expect(inferGrain(["2026-01-01", "2026-01-02"])).toBe("day"));
  it("七天间隔 → week", () => {
    expect(inferGrain(["2026-01-05", "2026-01-12", "2026-01-19"])).toBe("week");
  });
});

describe("toTickKey", () => {
  const d = new Date(Date.UTC(2026, 0, 15)); // 2026-01-15 是周四
  it("year", () => expect(toTickKey(d, "year")).toBe("2026"));
  it("quarter", () => expect(toTickKey(d, "quarter")).toBe("2026-Q1"));
  it("month", () => expect(toTickKey(d, "month")).toBe("2026-01"));
  it("day", () => expect(toTickKey(d, "day")).toBe("2026-01-15"));
  it("week 归到该周周一", () => expect(toTickKey(d, "week")).toBe("2026-01-12"));
});

describe("enumerateTicks", () => {
  it("月", () => {
    expect(enumerateTicks("2026-01", "2026-04", "month"))
      .toEqual(["2026-01", "2026-02", "2026-03", "2026-04"]);
  });
  it("跨年季度", () => {
    expect(enumerateTicks("2025-Q4", "2026-Q2", "quarter"))
      .toEqual(["2025-Q4", "2026-Q1", "2026-Q2"]);
  });
  it("日", () => {
    expect(enumerateTicks("2026-01-01", "2026-01-03", "day"))
      .toEqual(["2026-01-01", "2026-01-02", "2026-01-03"]);
  });
  it("周", () => {
    expect(enumerateTicks("2026-01-05", "2026-01-19", "week"))
      .toEqual(["2026-01-05", "2026-01-12", "2026-01-19"]);
  });
  it("年", () => expect(enumerateTicks("2024", "2026", "year")).toEqual(["2024", "2025", "2026"]));
  it("首末相同时只有一个刻度", () => {
    expect(enumerateTicks("2026-01", "2026-01", "month")).toEqual(["2026-01"]);
  });
});

describe("fillGaps", () => {
  it("缺失月份按 0 补并报告补齐数量", () => {
    const r = fillGaps({
      tickKeys: ["2026-01", "2026-02", "2026-03"],
      rowKeys: ["2026-01", "2026-03"],
      series: [series([100, 300])],
    });
    expect(r.series[0].data).toEqual([100, 0, 300]);
    expect(r.filled).toBe(1);
  });
  it("percent 系列按 null 补", () => {
    const r = fillGaps({
      tickKeys: ["2026-01", "2026-02", "2026-03"],
      rowKeys: ["2026-01", "2026-03"],
      series: [series([10, 30], PERCENT)],
    });
    expect(r.series[0].data).toEqual([10, null, 30]);
    expect(r.filled).toBe(1);
  });
  it("多系列同时补齐", () => {
    const r = fillGaps({
      tickKeys: ["2026-01", "2026-02"],
      rowKeys: ["2026-02"],
      series: [series([5]), series([7], PERCENT)],
    });
    expect(r.series[0].data).toEqual([0, 5]);
    expect(r.series[1].data).toEqual([null, 7]);
  });
  it("无缺口时原样返回,filled 为 0", () => {
    const r = fillGaps({
      tickKeys: ["2026-01", "2026-02"],
      rowKeys: ["2026-01", "2026-02"],
      series: [series([1, 2])],
    });
    expect(r.series[0].data).toEqual([1, 2]);
    expect(r.filled).toBe(0);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/backend run tests/timeAxis.test.ts`
Expected: FAIL，`Failed to resolve import "../src/timeAxis"`

- [ ] **Step 3: 实现 `apps/backend/src/timeAxis.ts`**

```ts
import type { ChartSeries, TimeGrain } from "@chatbi/shared";
import { parseTemporal } from "./columnTypes";

const YEAR_ONLY = /^\d{4}$/;
const QUARTER_KEY = /^(\d{4})-Q([1-4])$/;
const MONTH_ONLY = /^\d{4}-\d{2}$/;
const DAY_MS = 86400000;

const pad = (n: number) => String(n).padStart(2, "0");

/** 键的字符串形态优先;只有完整日期才用间隔区分 day / week。 */
export function inferGrain(keys: string[]): TimeGrain {
  if (keys.every(k => YEAR_ONLY.test(k))) return "year";
  if (keys.every(k => QUARTER_KEY.test(k))) return "quarter";
  if (keys.every(k => MONTH_ONLY.test(k))) return "month";
  const ts = keys.map(k => parseTemporal(k)).filter((d): d is Date => d !== null)
    .map(d => d.getTime()).sort((a, b) => a - b);
  if (ts.length < 2) return "day";
  const gaps: number[] = [];
  for (let i = 1; i < ts.length; i++) gaps.push((ts[i] - ts[i - 1]) / DAY_MS);
  gaps.sort((a, b) => a - b);
  const median = gaps[Math.floor(gaps.length / 2)];
  return median >= 5 ? "week" : "day";
}

export function toTickKey(d: Date, grain: TimeGrain): string {
  const y = d.getUTCFullYear();
  if (grain === "year") return String(y);
  if (grain === "quarter") return `${y}-Q${Math.floor(d.getUTCMonth() / 3) + 1}`;
  if (grain === "month") return `${y}-${pad(d.getUTCMonth() + 1)}`;
  if (grain === "week") {
    const monday = new Date(d.getTime() - ((d.getUTCDay() + 6) % 7) * DAY_MS);
    return `${monday.getUTCFullYear()}-${pad(monday.getUTCMonth() + 1)}-${pad(monday.getUTCDate())}`;
  }
  return `${y}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

function keyToDate(key: string, grain: TimeGrain): Date {
  const q = QUARTER_KEY.exec(key);
  if (q) return new Date(Date.UTC(Number(q[1]), (Number(q[2]) - 1) * 3, 1));
  return parseTemporal(key) ?? new Date(Date.UTC(1970, 0, 1));
}

function step(d: Date, grain: TimeGrain): Date {
  const y = d.getUTCFullYear(), m = d.getUTCMonth(), day = d.getUTCDate();
  if (grain === "year") return new Date(Date.UTC(y + 1, m, day));
  if (grain === "quarter") return new Date(Date.UTC(y, m + 3, day));
  if (grain === "month") return new Date(Date.UTC(y, m + 1, day));
  return new Date(d.getTime() + (grain === "week" ? 7 : 1) * DAY_MS);
}

export function enumerateTicks(from: string, to: string, grain: TimeGrain): string[] {
  const end = keyToDate(to, grain).getTime();
  const out: string[] = [];
  let cur = keyToDate(from, grain);
  while (cur.getTime() <= end && out.length < 5000) {
    out.push(toTickKey(cur, grain));
    cur = step(cur, grain);
  }
  return out;
}

export function fillGaps(opts: {
  tickKeys: string[]; rowKeys: string[]; series: ChartSeries[];
}): { series: ChartSeries[]; filled: number } {
  const index = new Map(opts.rowKeys.map((k, i) => [k, i]));
  const series = opts.series.map(s => {
    const fill = s.format.kind === "percent" ? null : 0;
    return {
      ...s,
      data: opts.tickKeys.map(k => {
        const i = index.get(k);
        return i === undefined ? fill : s.data[i] ?? fill;
      }),
    };
  });
  return { series, filled: opts.tickKeys.length - opts.rowKeys.length };
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest --root apps/backend run tests/timeAxis.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/backend/src/timeAxis.ts apps/backend/tests/timeAxis.test.ts
git commit -m "feat(backend): temporal axis grain inference, tick enumeration and gap filling"
```

### Task 5: 按维度拆系列(pivot)

**Files:**
- Create: `apps/backend/src/pivot.ts`
- Test: `apps/backend/tests/pivot.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `Row`
- Produces:
  - `SERIES_BY_MAX = 12`
  - `distinctValues(rows: Row[], field: string): string[]`
  - `pivotSeries(opts: { rows: Row[]; xField: string; seriesByField: string; measureField: string }): { labels: string[]; groups: { name: string; data: (number | null)[] }[] }`

**基数上限判定不在 pivot 里做**——`pivot` 只负责机械展开,是否降级由 Task 6 的 `inferChartSpec` 用 `distinctValues(...).length > SERIES_BY_MAX` 决定,这样降级的 note 文案和判定逻辑留在同一处。

**同一 `(x, seriesBy)` 组合重复出现时相加**。正常的 `GROUP BY` 不会产生重复,但模型偶尔会漏掉一个分组列;相加比「后者覆盖前者」更符合聚合直觉,也不会静默丢数据。

- [ ] **Step 1: 写失败测试**

创建 `apps/backend/tests/pivot.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { pivotSeries, distinctValues, SERIES_BY_MAX } from "../src/pivot";

const rows = [
  { month: "2026-01", region: "华东", amount: 10 },
  { month: "2026-01", region: "华北", amount: 20 },
  { month: "2026-02", region: "华东", amount: 30 },
];

describe("distinctValues", () => {
  it("按首次出现顺序去重", () => {
    expect(distinctValues(rows, "region")).toEqual(["华东", "华北"]);
    expect(distinctValues(rows, "month")).toEqual(["2026-01", "2026-02"]);
  });
  it("null 渲染为空串并去重", () => {
    expect(distinctValues([{ r: null }, { r: null }, { r: "x" }], "r")).toEqual(["", "x"]);
  });
  it("上限常量为 12", () => expect(SERIES_BY_MAX).toBe(12));
});

describe("pivotSeries", () => {
  it("展开成多系列,缺失组合补 null", () => {
    const r = pivotSeries({ rows, xField: "month", seriesByField: "region", measureField: "amount" });
    expect(r.labels).toEqual(["2026-01", "2026-02"]);
    expect(r.groups).toEqual([
      { name: "华东", data: [10, 30] },
      { name: "华北", data: [20, null] },
    ]);
  });

  it("重复组合相加", () => {
    const dup = [
      { month: "2026-01", region: "华东", amount: 10 },
      { month: "2026-01", region: "华东", amount: 5 },
    ];
    const r = pivotSeries({ rows: dup, xField: "month", seriesByField: "region", measureField: "amount" });
    expect(r.groups[0].data).toEqual([15]);
  });

  it("非数值指标当作 null", () => {
    const bad = [{ month: "2026-01", region: "华东", amount: "n/a" }];
    const r = pivotSeries({ rows: bad, xField: "month", seriesByField: "region", measureField: "amount" });
    expect(r.groups[0].data).toEqual([null]);
  });

  it("空结果集返回空 labels 与空 groups", () => {
    const r = pivotSeries({ rows: [], xField: "month", seriesByField: "region", measureField: "amount" });
    expect(r.labels).toEqual([]);
    expect(r.groups).toEqual([]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/backend run tests/pivot.test.ts`
Expected: FAIL，`Failed to resolve import "../src/pivot"`

- [ ] **Step 3: 实现 `apps/backend/src/pivot.ts`**

```ts
import type { Row } from "@chatbi/shared";

export const SERIES_BY_MAX = 12;

export function distinctValues(rows: Row[], field: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const r of rows) {
    const key = r[field] === null || r[field] === undefined ? "" : String(r[field]);
    if (!seen.has(key)) { seen.add(key); out.push(key); }
  }
  return out;
}

function toNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

export function pivotSeries(opts: {
  rows: Row[]; xField: string; seriesByField: string; measureField: string;
}): { labels: string[]; groups: { name: string; data: (number | null)[] }[] } {
  const labels = distinctValues(opts.rows, opts.xField);
  const names = distinctValues(opts.rows, opts.seriesByField);
  const xIndex = new Map(labels.map((l, i) => [l, i]));

  const groups = names.map(name => ({
    name,
    data: new Array<number | null>(labels.length).fill(null),
  }));
  const byName = new Map(groups.map(g => [g.name, g]));

  for (const r of opts.rows) {
    const name = r[opts.seriesByField] === null || r[opts.seriesByField] === undefined
      ? "" : String(r[opts.seriesByField]);
    const xKey = r[opts.xField] === null || r[opts.xField] === undefined
      ? "" : String(r[opts.xField]);
    const g = byName.get(name);
    const i = xIndex.get(xKey);
    if (!g || i === undefined) continue;
    const v = toNumber(r[opts.measureField]);
    if (v === null) continue;
    g.data[i] = (g.data[i] ?? 0) + v;
  }
  return { labels, groups };
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest --root apps/backend run tests/pivot.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/backend/src/pivot.ts apps/backend/tests/pivot.test.ts
git commit -m "feat(backend): pivot query rows into multiple chart series"
```

### Task 6: inferChartSpec —— 整合成完整 ChartSpec

**Files:**
- Create: `apps/backend/src/chartSpec.ts`
- Test: `apps/backend/tests/chartSpec.test.ts`
- Delete: `apps/backend/src/chartAssembler.ts`、`apps/backend/tests/chartAssembler.test.ts`

**Interfaces:**
- Consumes: Task 1 类型 + `formatTimeLabel`、Task 3 `detectColumnRoles`/`parseTemporal`、Task 4 `inferGrain`/`toTickKey`/`enumerateTicks`/`fillGaps`、Task 5 `pivotSeries`/`distinctValues`/`SERIES_BY_MAX`
- Produces:
  - `inferFormat(field: string, values: (number | null)[]): ValueFormat`
  - `inferChartSpec(opts: { rows: Row[]; columns: string[]; hint: ChartHint | null; truncated: boolean; rowLimit: number }): ChartSpec`

**一处对 spec 的必要收紧**:spec 第 2 节第 7 步写「`decimals`……`number` 为 0」。但 `number` 一旦带上万/亿缩放,0 位小数会把 `1,234,567,890` 显示成 `12 亿`,丢掉两位有效数字。实现统一为 **`percent` → 1;其余缩放后 → 2、未缩放 → 0**。

**空结果集强制 `chartType = "table"`**,让前端展示空表格而不是一张空白图。「没有符合条件的记录」这句话由洞察层负责(Task 7),不进 `notes`。

**第二处对 spec 的必要修正**:spec 第 2 节第 9 步写「`table` 时 `series` 为空数组」。但 spec 第 6 节又要求前端能把图表类型切成别的——如果 `series` 是空的,用户从「表格」切到「柱状」就只能看到一张空白图,这个交互直接失效。所以 **`table` 只是「默认视图是表格」这一个标记**,`series`、时间轴处理、格式推断全部照常计算;`specToEchartsOption` 看到 `chartType === "table"` 返回 `{}`,前端切换时用 `{ ...spec, chartType: "bar" }` 覆盖就能立刻画出来。`series` 只在两种情况下为空:结果集为空,或者结果里没有任何数值列。

- [ ] **Step 1: 写失败测试**

创建 `apps/backend/tests/chartSpec.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { inferChartSpec, inferFormat } from "../src/chartSpec";
import type { ChartHint, Row } from "@chatbi/shared";

const call = (rows: Row[], hint: ChartHint | null, over: Partial<{ truncated: boolean; rowLimit: number }> = {}) =>
  inferChartSpec({
    rows, columns: rows.length ? Object.keys(rows[0]) : [], hint,
    truncated: false, rowLimit: 1000, ...over,
  });

const hint = (o: Partial<ChartHint> = {}): ChartHint =>
  ({ chartType: "bar", dimensions: [], measures: [], ...o });

describe("inferFormat", () => {
  it("金额类列判货币,单位元", () => {
    expect(inferFormat("total_amount", [100])).toMatchObject({ kind: "currency", unit: "元" });
  });
  it("占比类列判百分数,一位小数", () => {
    expect(inferFormat("share_rate", [41.2])).toMatchObject({ kind: "percent", decimals: 1 });
  });
  it("其余判普通数值", () => {
    expect(inferFormat("order_count", [12])).toMatchObject({ kind: "number", scale: 1, decimals: 0 });
  });
  it("量级到万则缩放并保留两位", () => {
    expect(inferFormat("amount", [128400])).toMatchObject({ scale: 10000, decimals: 2 });
  });
  it("量级到亿则缩放", () => {
    expect(inferFormat("amount", [1234567890])).toMatchObject({ scale: 100000000, decimals: 2 });
  });
  it("percent 不做量级缩放", () => {
    expect(inferFormat("rate", [99999999]).scale).toBe(1);
  });
});

describe("inferChartSpec 基础推导", () => {
  const rows = [{ region: "华东", amount: 100 }, { region: "华北", amount: 200 }];

  it("按 hint 取维度与指标", () => {
    const s = call(rows, hint({ dimensions: ["region"], measures: ["amount"] }));
    expect(s.x).toMatchObject({ field: "region", role: "categorical", labels: ["华东", "华北"] });
    expect(s.series).toHaveLength(1);
    expect(s.series[0].data).toEqual([100, 200]);
  });

  it("幻觉列名被丢弃后回退到嗅探结果", () => {
    const s = call(rows, hint({ dimensions: ["province"], measures: ["revenue"] }));
    expect(s.x.field).toBe("region");
    expect(s.series.map(x => x.field)).toEqual(["amount"]);
  });

  it("hint 为 null 时全靠嗅探", () => {
    const s = call(rows, null);
    expect(s.x.field).toBe("region");
    expect(s.series[0].field).toBe("amount");
  });

  it("多指标生成多系列", () => {
    const s = call([{ region: "华东", amount: 1, profit: 2 }], hint({ dimensions: ["region"] }));
    expect(s.series.map(x => x.name)).toEqual(["amount", "profit"]);
  });

  it("空结果集强制 table", () => {
    const s = inferChartSpec({ rows: [], columns: [], hint: hint({ chartType: "line" }), truncated: false, rowLimit: 1000 });
    expect(s.chartType).toBe("table");
    expect(s.series).toEqual([]);
  });

  it("截断写入 notes", () => {
    const s = call(rows, hint({ dimensions: ["region"] }), { truncated: true });
    expect(s.notes.join()).toContain("1000");
  });
});

describe("inferChartSpec pie 约束", () => {
  it("多指标时只保留第一条并写 note", () => {
    const s = call([{ category: "电子", amount: 70, profit: 10 }],
      hint({ chartType: "pie", dimensions: ["category"] }));
    expect(s.series).toHaveLength(1);
    expect(s.series[0].field).toBe("amount");
    expect(s.notes.join()).toContain("amount");
  });
});

describe("inferChartSpec stack 约束", () => {
  const rows = [
    { month: "2026-01", region: "华东", amount: 1 },
    { month: "2026-01", region: "华北", amount: 2 },
  ];
  it("bar 多系列时 hint.stack 生效", () => {
    const s = call(rows, hint({ chartType: "bar", dimensions: ["month"], measures: ["amount"], seriesBy: "region", stack: "percent" }));
    expect(s.stack).toBe("percent");
  });
  it("line 上 stack 被强制归零", () => {
    const s = call(rows, hint({ chartType: "line", dimensions: ["month"], measures: ["amount"], seriesBy: "region", stack: "normal" }));
    expect(s.stack).toBe("none");
  });
  it("单系列上 stack 被强制归零", () => {
    const s = call([{ region: "华东", amount: 1 }],
      hint({ chartType: "bar", dimensions: ["region"], measures: ["amount"], stack: "normal" }));
    expect(s.stack).toBe("none");
  });
});

describe("inferChartSpec 拆系列", () => {
  it("按 seriesBy 展开成多条系列", () => {
    const rows = [
      { month: "2026-01", region: "华东", amount: 10 },
      { month: "2026-01", region: "华北", amount: 20 },
      { month: "2026-02", region: "华东", amount: 30 },
      { month: "2026-02", region: "华北", amount: 40 },
    ];
    const s = call(rows, hint({ chartType: "line", dimensions: ["month"], measures: ["amount"], seriesBy: "region" }));
    expect(s.series.map(x => x.name)).toEqual(["华东", "华北"]);
    expect(s.series[0].data).toEqual([10, 30]);
  });

  it("基数超过 12 时降级单系列并写 note", () => {
    const rows = Array.from({ length: 13 }, (_, i) => ({ month: "2026-01", city: `c${i}`, amount: i + 1 }));
    const s = call(rows, hint({ chartType: "bar", dimensions: ["month"], measures: ["amount"], seriesBy: "city" }));
    expect(s.series).toHaveLength(1);
    expect(s.notes.join()).toMatch(/city.*13/);
  });
});

describe("inferChartSpec 时间轴", () => {
  it("乱序按真实时间排序,缺月按 0 补并写 note", () => {
    const rows = [
      { month: "2026-03", amount: 300 },
      { month: "2026-01", amount: 100 },
    ];
    const s = call(rows, hint({ chartType: "line", dimensions: ["month"], measures: ["amount"] }));
    expect(s.x.role).toBe("temporal");
    expect(s.x.grain).toBe("month");
    expect(s.x.labels).toEqual(["1月", "2月", "3月"]);
    expect(s.series[0].data).toEqual([100, 0, 300]);
    expect(s.notes.join()).toContain("补齐");
  });

  it("percent 指标的时间缺口按 null 补", () => {
    const rows = [{ month: "2026-01", conv_rate: 10 }, { month: "2026-03", conv_rate: 30 }];
    const s = call(rows, hint({ chartType: "line", dimensions: ["month"], measures: ["conv_rate"] }));
    expect(s.series[0].data).toEqual([10, null, 30]);
  });

  it("跨年时标签带年份", () => {
    const rows = [{ month: "2025-12", amount: 1 }, { month: "2026-01", amount: 2 }];
    const s = call(rows, hint({ chartType: "line", dimensions: ["month"], measures: ["amount"] }));
    expect(s.x.labels).toEqual(["2025年12月", "2026年1月"]);
  });

  it("table 类型仍产出完整 series 与时间轴,供前端切图", () => {
    const rows = [{ month: "2026-03", amount: 3 }, { month: "2026-01", amount: 1 }];
    const s = call(rows, hint({ chartType: "table", dimensions: ["month"], measures: ["amount"] }));
    expect(s.chartType).toBe("table");
    expect(s.x.labels).toEqual(["1月", "2月", "3月"]);
    expect(s.series[0].data).toEqual([1, 0, 3]);
  });

  it("没有任何数值列时退化为空 series 的 table", () => {
    const s = call([{ region: "华东", city: "上海" }], hint({ chartType: "bar", dimensions: ["region"] }));
    expect(s.chartType).toBe("table");
    expect(s.series).toEqual([]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/backend run tests/chartSpec.test.ts`
Expected: FAIL，`Failed to resolve import "../src/chartSpec"`

- [ ] **Step 3: 实现 `apps/backend/src/chartSpec.ts`**

`x` 轴标签必须唯一(ECharts 类目轴的硬要求),所以 `collapse` 把重复刻度合并:非 percent 系列求和,percent 系列取均值(比率求和没有意义)。

```ts
import type {
  ChartHint, ChartSeries, ChartSpec, ChartType, Row, StackMode, ValueFormat,
} from "@chatbi/shared";
import { formatTimeLabel } from "@chatbi/shared";
import { detectColumnRoles, parseTemporal } from "./columnTypes";
import { inferGrain, toTickKey, enumerateTicks, fillGaps } from "./timeAxis";
import { pivotSeries, distinctValues, SERIES_BY_MAX } from "./pivot";

const CHART_TYPES: ChartType[] = ["bar", "line", "pie", "table"];
const STACKS: StackMode[] = ["none", "normal", "percent"];
const CURRENCY_NAME = /(amount|price|revenue|sales|cost|金额|销售额|收入|总额|成本)/i;
const PERCENT_NAME = /(rate|ratio|percent|share|率|占比|比例)/i;

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const num = (v: unknown) => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
};

export function inferFormat(field: string, values: (number | null)[]): ValueFormat {
  if (PERCENT_NAME.test(field)) return { kind: "percent", decimals: 1, scale: 1 };
  const kind = CURRENCY_NAME.test(field) ? "currency" : "number";
  const max = values.reduce((a, v) => Math.max(a, v === null ? 0 : Math.abs(v)), 0);
  const scale: 1 | 10000 | 100000000 = max >= 1e8 ? 100000000 : max >= 1e4 ? 10000 : 1;
  return {
    kind, scale, decimals: scale > 1 ? 2 : 0,
    ...(kind === "currency" ? { unit: "元" } : {}),
  };
}

function collapse(labels: string[], series: ChartSeries[]):
  { labels: string[]; series: ChartSeries[]; collapsed: number } {
  const groups = new Map<string, number[]>();
  labels.forEach((l, i) => {
    const g = groups.get(l);
    if (g) g.push(i); else groups.set(l, [i]);
  });
  if (groups.size === labels.length) return { labels, series, collapsed: 0 };
  const uniq = [...groups.keys()];
  const out = series.map(s => ({
    ...s,
    data: uniq.map(l => {
      const vals = groups.get(l)!.map(i => s.data[i]).filter((v): v is number => v !== null);
      if (!vals.length) return null;
      const sum = vals.reduce((a, b) => a + b, 0);
      return s.format.kind === "percent" ? sum / vals.length : sum;
    }),
  }));
  return { labels: uniq, series: out, collapsed: labels.length - uniq.length };
}

export function inferChartSpec(opts: {
  rows: Row[]; columns: string[]; hint: ChartHint | null;
  truncated: boolean; rowLimit: number;
}): ChartSpec {
  const { rows, columns, hint, truncated, rowLimit } = opts;
  const notes: string[] = [];
  if (truncated) notes.push(`结果已截断至 ${rowLimit} 行`);

  const tableSpec = (field: string, labels: string[], role: "temporal" | "categorical"): ChartSpec =>
    ({ chartType: "table", stack: "none", x: { field, role, labels }, series: [], notes });

  if (rows.length === 0 || columns.length === 0) return tableSpec(columns[0] ?? "", [], "categorical");

  const roles = detectColumnRoles(rows, columns);
  const hintDims = (hint?.dimensions ?? []).filter(c => columns.includes(c));
  const hintMeasures = (hint?.measures ?? []).filter(c => columns.includes(c));
  const seriesBy = hint?.seriesBy && columns.includes(hint.seriesBy) ? hint.seriesBy : undefined;
  const chartType: ChartType = CHART_TYPES.includes(hint?.chartType as ChartType)
    ? (hint!.chartType as ChartType) : "table";

  const xField = hintDims[0] ?? columns.find(c => roles[c] !== "numeric") ?? columns[0];
  const xRole = roles[xField] === "temporal" ? "temporal" : "categorical";

  // 注意:chartType === "table" 不在这里提前返回——series 照常算,前端才能切成图表。
  let measureFields = hintMeasures.filter(c => roles[c] === "numeric");
  if (!measureFields.length) measureFields = columns.filter(c => c !== xField && roles[c] === "numeric");
  if (!measureFields.length) return tableSpec(xField, rows.map(r => str(r[xField])), xRole);

  const buildFlat = () => ({
    labels: rows.map(r => str(r[xField])),
    series: measureFields.map(f => {
      const data = rows.map(r => num(r[f]));
      return { name: f, field: f, data, format: inferFormat(f, data) };
    }) as ChartSeries[],
  });

  let labels: string[];
  let series: ChartSeries[];
  if (seriesBy && seriesBy !== xField && roles[seriesBy] !== "numeric") {
    const card = distinctValues(rows, seriesBy).length;
    if (card <= SERIES_BY_MAX) {
      const measure = measureFields[0];
      const p = pivotSeries({ rows, xField, seriesByField: seriesBy, measureField: measure });
      const format = inferFormat(measure, p.groups.flatMap(g => g.data));
      labels = p.labels;
      series = p.groups.map(g => ({ name: g.name, field: measure, data: g.data, format }));
    } else {
      notes.push(`${seriesBy} 取值过多（${card} 个），已改为单系列`);
      ({ labels, series } = buildFlat());
    }
  } else {
    ({ labels, series } = buildFlat());
  }

  const merged = collapse(labels, series);
  labels = merged.labels;
  series = merged.series;
  if (merged.collapsed > 0) notes.push(`${xField} 有重复取值，已按同一刻度聚合`);

  if (chartType === "pie" && series.length > 1) {
    notes.push(`饼图仅展示第一个指标（${series[0].field}）`);
    series = [series[0]];
  }

  let grain: ChartSpec["x"]["grain"];
  if (xRole === "temporal") {
    const dated = labels
      .map((k, i) => ({ i, d: parseTemporal(k) }))
      .filter((x): x is { i: number; d: Date } => x.d !== null)
      .sort((a, b) => a.d.getTime() - b.d.getTime());
    if (dated.length) {
      grain = inferGrain(labels);
      const rowKeys = dated.map(x => toTickKey(x.d, grain!));
      const ordered = series.map(s => ({ ...s, data: dated.map(x => s.data[x.i]) }));
      const tickKeys = enumerateTicks(rowKeys[0], rowKeys[rowKeys.length - 1], grain);
      const filledRes = fillGaps({ tickKeys, rowKeys, series: ordered });
      series = filledRes.series;
      if (filledRes.filled > 0) {
        notes.push(`已补齐 ${filledRes.filled} 个无数据的时间点（按 0 计）`);
      }
      const crossYear = new Set(tickKeys.map(k => k.slice(0, 4))).size > 1;
      labels = tickKeys.map(k => formatTimeLabel(k, grain!, crossYear));
    }
  }

  const hintStack = STACKS.includes(hint?.stack as StackMode) ? (hint!.stack as StackMode) : "none";
  const stack: StackMode = chartType === "bar" && series.length > 1 ? hintStack : "none";

  return {
    chartType, stack,
    x: { field: xField, role: xRole, labels, ...(grain ? { grain } : {}) },
    series, notes,
  };
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest --root apps/backend run tests/chartSpec.test.ts`
Expected: PASS

- [ ] **Step 5: 删除被取代的 chartAssembler**

```bash
git rm apps/backend/src/chartAssembler.ts apps/backend/tests/chartAssembler.test.ts
```

此时 `chatService.ts` 仍 import `assemble`,后端**编译会失败**——这是预期的,Task 12 会改掉编排层。为了让本任务可独立验收,只跑本任务的测试文件,不跑全量。

- [ ] **Step 6: 提交**

```bash
git add apps/backend/src/chartSpec.ts apps/backend/tests/chartSpec.test.ts
git commit -m "feat(backend): infer full ChartSpec from rows and LLM hint, drop chartAssembler"
```

### Task 7: fact 层 —— 从 ChartSpec 算出结构化事实

**Files:**
- Create: `packages/shared/src/facts.ts`(两个渲染函数,前后端共用)
- Modify: `packages/shared/src/index.ts`(barrel 追加一行)
- Create: `apps/backend/src/facts.ts`(`computeFacts` + re-export 渲染函数)
- Test: `apps/backend/tests/facts.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `ChartSpec` `InsightFact` `ValueFormat` `formatValue`
- Produces:
  - `packages/shared`:`renderFactsLines(facts: InsightFact[], format: ValueFormat): string[]`、`renderFactsTemplate(facts: InsightFact[], format: ValueFormat): string`
  - `apps/backend/src/facts.ts`:`FACT_LIMIT = 6`、`FLAT_THRESHOLD_PCT = 3`、`computeFacts(spec: ChartSpec, opts: { truncated: boolean; rowLimit: number }): InsightFact[]`,并 re-export 上面两个渲染函数

**渲染函数放 `packages/shared` 的理由**:前端的「计算依据」折叠区(Task 14)要把 `insightFacts` 事件里的事实渲染成中文行,和后端拼 prompt / 降级文本用的是同一套措辞。放 shared 是唯一实现;后端 `facts.ts` 顺手 re-export,这样 Task 8 和 Task 11 可以继续从 `"./facts"` 导入,不用关心它实际住在哪。

`renderFacts*` 需要 `ValueFormat` 才能把 `128400` 渲染成 `12.84 万元`。调用方传 `spec.series[0]?.format`,没有系列时传 `{ kind: "number", decimals: 0, scale: 1 }`。

`FACT_LIMIT` 是安全上限:P1 的事实集合最多产出 6 条(temporal 3 条 + `seriesGap` + `truncated`,或 categorical 3 条 + 同样两条),`slice` 只是防止后续新增事实类型时无声膨胀。

- [ ] **Step 1: 写失败测试**

创建 `apps/backend/tests/facts.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { computeFacts, renderFactsTemplate, renderFactsLines, FACT_LIMIT } from "../src/facts";
import type { ChartSpec, ChartSeries, ValueFormat } from "@chatbi/shared";

const CURRENCY: ValueFormat = { kind: "currency", decimals: 0, unit: "元", scale: 1 };
const s = (name: string, data: (number | null)[]): ChartSeries =>
  ({ name, field: "amount", data, format: CURRENCY });

const temporal = (series: ChartSeries[], labels: string[]): ChartSpec => ({
  chartType: "line", stack: "none",
  x: { field: "month", role: "temporal", labels, grain: "month" },
  series, notes: [],
});
const categorical = (series: ChartSeries[], labels: string[]): ChartSpec => ({
  chartType: "bar", stack: "none",
  x: { field: "region", role: "categorical", labels },
  series, notes: [],
});
const opts = { truncated: false, rowLimit: 1000 };
const kinds = (f: any[]) => f.map(x => x.kind);

describe("computeFacts 时序", () => {
  const spec = temporal([s("金额", [100, 80, 123.4])], ["1月", "2月", "3月"]);

  it("产出趋势/峰值/谷值", () => {
    expect(kinds(computeFacts(spec, opts))).toEqual(["trend", "peak", "trough"]);
  });
  it("趋势按首末计算百分比并带首末标签", () => {
    const t = computeFacts(spec, opts)[0] as any;
    expect(t.dir).toBe("up");
    expect(t.pct).toBeCloseTo(23.4, 1);
    expect(t.from).toBe("1月");
    expect(t.to).toBe("3月");
  });
  it("变化小于 3% 判 flat", () => {
    const t = computeFacts(temporal([s("金额", [100, 102])], ["1月", "2月"]), opts)[0] as any;
    expect(t.dir).toBe("flat");
  });
  it("首值为 0 时改产 trendAbs", () => {
    const f = computeFacts(temporal([s("金额", [0, 128400])], ["1月", "2月"]), opts);
    expect(kinds(f)[0]).toBe("trendAbs");
    expect((f[0] as any).delta).toBe(128400);
  });
  it("首末符号相反时改产 trendAbs", () => {
    const f = computeFacts(temporal([s("利润", [-50, 100])], ["1月", "2月"]), opts);
    expect(kinds(f)[0]).toBe("trendAbs");
  });
  it("峰值与谷值带标签", () => {
    const f = computeFacts(spec, opts) as any[];
    expect(f[1]).toMatchObject({ label: "3月", value: 123.4 });
    expect(f[2]).toMatchObject({ label: "2月", value: 80 });
  });
});

describe("computeFacts 类目", () => {
  const spec = categorical([s("金额", [412, 300, 288])], ["华东", "华北", "华南"]);
  it("产出头部占比/集中度/总量", () => {
    expect(kinds(computeFacts(spec, opts))).toEqual(["topShare", "concentration", "total"]);
  });
  it("头部占比与总量数值正确", () => {
    const f = computeFacts(spec, opts) as any[];
    expect(f[0]).toMatchObject({ label: "华东" });
    expect(f[0].pct).toBeCloseTo(41.2, 1);
    expect(f[2].value).toBe(1000);
  });
  it("集中度按头部 3 项,项数不足时取实际项数", () => {
    const f = computeFacts(categorical([s("金额", [70, 30])], ["电子", "机械"]), opts) as any[];
    expect(f[1]).toMatchObject({ kind: "concentration", topN: 2, pct: 100 });
  });
});

describe("computeFacts 多系列与边界", () => {
  it("只对总量最大的系列算趋势,并追加 seriesGap", () => {
    const f = computeFacts(
      temporal([s("华东", [10, 20]), s("华北", [100, 200])], ["1月", "2月"]), opts) as any[];
    expect(f.filter(x => x.kind === "trend")).toHaveLength(1);
    expect(f.find(x => x.kind === "trend").series).toBe("华北");
    expect(f.find(x => x.kind === "seriesGap")).toMatchObject({ high: "华北", low: "华东", ratio: 10 });
  });
  it("最小系列总量为 0 时不产 seriesGap", () => {
    const f = computeFacts(temporal([s("华东", [0, 0]), s("华北", [1, 2])], ["1月", "2月"]), opts);
    expect(kinds(f)).not.toContain("seriesGap");
  });
  it("截断时追加 truncated,且总数不超上限", () => {
    const f = computeFacts(
      temporal([s("华东", [10, 20]), s("华北", [100, 200])], ["1月", "2月"]),
      { truncated: true, rowLimit: 1000 });
    expect(kinds(f)).toContain("truncated");
    expect(f.length).toBeLessThanOrEqual(FACT_LIMIT);
  });
  it("空结果集只产 empty", () => {
    expect(computeFacts(categorical([], []), opts)).toEqual([{ kind: "empty" }]);
  });
  it("全为 null 的系列也只产 empty", () => {
    expect(computeFacts(temporal([s("金额", [null, null])], ["1月", "2月"]), opts))
      .toEqual([{ kind: "empty" }]);
  });
});

describe("renderFacts*", () => {
  const f = computeFacts(temporal([s("金额", [100, 80, 123.4])], ["1月", "2月", "3月"]), opts);
  it("逐条文本带格式化数值", () => {
    const lines = renderFactsLines(f, CURRENCY);
    expect(lines[0]).toMatch(/上涨 23\.4%/);
    expect(lines[1]).toContain("123 元");
  });
  it("降级模板成段且以句号结尾", () => {
    const text = renderFactsTemplate(f, CURRENCY);
    expect(text).toContain("上涨");
    expect(text.endsWith("。")).toBe(true);
  });
  it("empty 的模板是固定文案", () => {
    expect(renderFactsTemplate([{ kind: "empty" }], CURRENCY)).toBe("没有符合条件的记录。");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/backend run tests/facts.test.ts`
Expected: FAIL，`Failed to resolve import "../src/facts"`

- [ ] **Step 3: 创建 `packages/shared/src/facts.ts`(渲染函数)**

```ts
import type { InsightFact, ValueFormat } from "./types";
import { formatValue } from "./format";

const DIR_TEXT = { up: "上涨", down: "下降", flat: "基本持平" } as const;

export function renderFactsLines(facts: InsightFact[], format: ValueFormat): string[] {
  return facts.map(f => {
    switch (f.kind) {
      case "trend":
        return f.dir === "flat"
          ? `趋势：系列「${f.series}」基本持平（${f.from} → ${f.to}）`
          : `趋势：系列「${f.series}」${DIR_TEXT[f.dir]} ${Math.abs(f.pct).toFixed(1)}%（${f.from} → ${f.to}）`;
      case "trendAbs":
        return `趋势：系列「${f.series}」净变化 ${formatValue(f.delta, format)}（${f.from} → ${f.to}）`;
      case "peak": return `峰值：${f.label} ${formatValue(f.value, format)}`;
      case "trough": return `谷值：${f.label} ${formatValue(f.value, format)}`;
      case "topShare": return `头部占比：${f.label} ${f.pct.toFixed(1)}%`;
      case "concentration": return `集中度：头部 ${f.topN} 项合计 ${f.pct.toFixed(1)}%`;
      case "total": return `总量：${formatValue(f.value, format)}`;
      case "seriesGap": return `系列差距：${f.high} 是 ${f.low} 的 ${f.ratio.toFixed(1)} 倍`;
      case "truncated": return `结果已截断至 ${f.limit} 行`;
      case "empty": return "没有符合条件的记录";
      default: return "";
    }
  });
}

export function renderFactsTemplate(facts: InsightFact[], format: ValueFormat): string {
  const lines = renderFactsLines(facts, format).filter(Boolean);
  return lines.length ? `${lines.join("；")}。` : "没有可用的分析结果。";
}
```

barrel 追加一行到 `packages/shared/src/index.ts`:

```ts
export * from "./facts";
```

- [ ] **Step 4: 实现 `apps/backend/src/facts.ts`(事实计算 + re-export)**

```ts
import type { ChartSpec, ChartSeries, InsightFact } from "@chatbi/shared";

export { renderFactsLines, renderFactsTemplate } from "@chatbi/shared";

export const FACT_LIMIT = 6;
export const FLAT_THRESHOLD_PCT = 3;

const total = (d: (number | null)[]) => d.reduce<number>((a, v) => a + (v ?? 0), 0);
const hasValue = (s: ChartSeries) => s.data.some(v => v !== null);

export function computeFacts(
  spec: ChartSpec, opts: { truncated: boolean; rowLimit: number },
): InsightFact[] {
  const usable = spec.series.filter(hasValue);
  if (!usable.length) return [{ kind: "empty" }];

  const primary = usable.reduce((a, b) =>
    Math.abs(total(b.data)) > Math.abs(total(a.data)) ? b : a);
  const points = primary.data
    .map((v, i) => ({ i, v }))
    .filter((x): x is { i: number; v: number } => x.v !== null);
  const label = (i: number) => spec.x.labels[i] ?? "";
  const facts: InsightFact[] = [];

  if (spec.x.role === "temporal") {
    const first = points[0];
    const last = points[points.length - 1];
    if (first && last && first.i !== last.i) {
      if (first.v === 0 || Math.sign(first.v) !== Math.sign(last.v)) {
        facts.push({
          kind: "trendAbs", series: primary.name,
          delta: last.v - first.v, from: label(first.i), to: label(last.i),
        });
      } else {
        const pct = ((last.v - first.v) / Math.abs(first.v)) * 100;
        const dir = Math.abs(pct) < FLAT_THRESHOLD_PCT ? "flat" : pct > 0 ? "up" : "down";
        facts.push({ kind: "trend", series: primary.name, dir, pct, from: label(first.i), to: label(last.i) });
      }
    }
    const max = points.reduce((a, b) => (b.v > a.v ? b : a));
    const min = points.reduce((a, b) => (b.v < a.v ? b : a));
    facts.push({ kind: "peak", series: primary.name, label: label(max.i), value: max.v });
    facts.push({ kind: "trough", series: primary.name, label: label(min.i), value: min.v });
  } else {
    const sum = total(primary.data);
    const sorted = [...points].sort((a, b) => b.v - a.v);
    if (sum !== 0 && sorted.length) {
      facts.push({
        kind: "topShare", series: primary.name,
        label: label(sorted[0].i), pct: (sorted[0].v / sum) * 100,
      });
      const topN = Math.min(3, sorted.length);
      const topSum = sorted.slice(0, topN).reduce((a, b) => a + b.v, 0);
      facts.push({ kind: "concentration", series: primary.name, topN, pct: (topSum / sum) * 100 });
    }
    facts.push({ kind: "total", series: primary.name, value: sum });
  }

  if (usable.length > 1) {
    const sums = usable.map(s => ({ name: s.name, value: total(s.data) }));
    const high = sums.reduce((a, b) => (b.value > a.value ? b : a));
    const low = sums.reduce((a, b) => (b.value < a.value ? b : a));
    if (low.value !== 0 && high.name !== low.name) {
      facts.push({ kind: "seriesGap", high: high.name, low: low.name, ratio: high.value / low.value });
    }
  }
  if (opts.truncated) facts.push({ kind: "truncated", limit: opts.rowLimit });

  return facts.slice(0, FACT_LIMIT);
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `npx vitest --root packages/shared run && npx vitest --root apps/backend run tests/facts.test.ts`
Expected: 两边都 PASS。`facts.test.ts` 从 `../src/facts` 导入渲染函数,走的是 re-export。

- [ ] **Step 6: 提交**

```bash
git add packages/shared/src/facts.ts packages/shared/src/index.ts \
  apps/backend/src/facts.ts apps/backend/tests/facts.test.ts
git commit -m "feat(shared,backend): insight fact computation and shared fact renderers"
```

### Task 8: insightWriter —— 第二轮 LLM 真流式 + 降级

**Files:**
- Create: `apps/backend/src/insightWriter.ts`
- Test: `apps/backend/tests/insightWriter.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `InsightFact` `ValueFormat`、Task 7 的 `renderFactsTemplate`
- Produces:
  - `export interface InsightLlm { chatStream(prompt: string): AsyncIterable<string> }`
  - `writeInsight(opts: { facts: InsightFact[]; prompt: string; llm: InsightLlm; timeoutMs: number; format: ValueFormat }): AsyncIterable<string>`

**prompt 由调用方传入**(Task 11 的 `buildInsightPrompt` 生成),`insightWriter` 不依赖 `promptBuilder`,避免两个模块互相 import。

**一处对 spec 的必要细化**:spec 第 3 节说超时/报错时「丢弃已收到的部分,一次性下发模板」。但 token 一旦 `yield` 出去就已经通过 SSE 到了前端,后端无法撤回,除非新增一个「清空洞察」事件——那要动 `StreamEvent` 契约。实现改为按失败时机分两种:

- **首个 token 之前**失败/超时 → 下发完整模板文本(用户看到的就是朴素版洞察,与 spec 意图一致)
- **已经吐出部分文本之后**失败/超时 → 停止并追加 `…（洞察生成中断）`,让用户知道这段话没写完,而不是把半句话当成完整结论

**超时是整段的墙钟上限**(默认 8s),不是每 token 超时。

- [ ] **Step 1: 写失败测试**

创建 `apps/backend/tests/insightWriter.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { writeInsight } from "../src/insightWriter";
import type { InsightFact, ValueFormat } from "@chatbi/shared";

const FORMAT: ValueFormat = { kind: "currency", decimals: 0, unit: "元", scale: 1 };
const FACTS: InsightFact[] = [
  { kind: "trend", series: "金额", dir: "up", pct: 23.4, from: "1月", to: "3月" },
  { kind: "peak", series: "金额", label: "3月", value: 128400 },
];

async function collect(it: AsyncIterable<string>): Promise<string> {
  let out = "";
  for await (const t of it) out += t;
  return out;
}

const run = (llm: any, over: Partial<{ facts: InsightFact[]; timeoutMs: number }> = {}) =>
  collect(writeInsight({
    facts: FACTS, prompt: "P", llm, timeoutMs: 5000, format: FORMAT, ...over,
  }));

describe("writeInsight 正常路径", () => {
  it("逐 token 透传", async () => {
    const llm = { chatStream: async function* () { yield "上半年"; yield "订单金额上涨"; } };
    expect(await run(llm)).toBe("上半年订单金额上涨");
  });

  it("prompt 原样传给 llm", async () => {
    const chatStream = vi.fn(async function* () { yield "x"; });
    await collect(writeInsight({ facts: FACTS, prompt: "PROMPT-X", llm: { chatStream }, timeoutMs: 5000, format: FORMAT }));
    expect(chatStream).toHaveBeenCalledWith("PROMPT-X");
  });
});

describe("writeInsight 降级", () => {
  it("空结果不调 LLM,直接固定文案", async () => {
    const chatStream = vi.fn(async function* () { yield "不应该被调用"; });
    const text = await run({ chatStream }, { facts: [{ kind: "empty" }] });
    expect(chatStream).not.toHaveBeenCalled();
    expect(text).toBe("没有符合条件的记录。");
  });

  it("首 token 之前报错 → 完整模板", async () => {
    const llm = { chatStream: async function* () { throw new Error("ollama down"); } };
    const text = await run(llm);
    expect(text).toContain("上涨 23.4%");
    expect(text).toContain("128,400 元");
    expect(text).not.toContain("中断");
  });

  it("部分输出后报错 → 保留已有文本并标注中断", async () => {
    const llm = {
      chatStream: async function* () { yield "上半年"; throw new Error("connection reset"); },
    };
    const text = await run(llm);
    expect(text).toBe("上半年…（洞察生成中断）");
  });

  it("超时 → 完整模板", async () => {
    const llm = {
      chatStream: async function* () {
        await new Promise(r => setTimeout(r, 1000));
        yield "太慢了";
      },
    };
    const text = await run(llm, { timeoutMs: 20 });
    expect(text).toContain("上涨 23.4%");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/backend run tests/insightWriter.test.ts`
Expected: FAIL，`Failed to resolve import "../src/insightWriter"`

- [ ] **Step 3: 实现 `apps/backend/src/insightWriter.ts`**

```ts
import type { InsightFact, ValueFormat } from "@chatbi/shared";
import { renderFactsTemplate } from "./facts";

export interface InsightLlm {
  chatStream(prompt: string): AsyncIterable<string>;
}

class InsightTimeout extends Error {}

function raceDeadline<T>(p: Promise<T>, ms: number): Promise<T> {
  let timer: NodeJS.Timeout;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new InsightTimeout("insight timeout")), ms);
  });
  return Promise.race([p, timeout]).finally(() => clearTimeout(timer!));
}

export async function* writeInsight(opts: {
  facts: InsightFact[]; prompt: string; llm: InsightLlm;
  timeoutMs: number; format: ValueFormat;
}): AsyncIterable<string> {
  const { facts, prompt, llm, timeoutMs, format } = opts;

  if (facts.length === 1 && facts[0].kind === "empty") {
    yield renderFactsTemplate(facts, format);
    return;
  }

  const deadline = Date.now() + timeoutMs;
  let emitted = false;
  try {
    const it = llm.chatStream(prompt)[Symbol.asyncIterator]();
    for (;;) {
      const remaining = deadline - Date.now();
      if (remaining <= 0) throw new InsightTimeout("insight timeout");
      const next = await raceDeadline(it.next(), remaining);
      if (next.done) break;
      if (next.value) { emitted = true; yield next.value; }
    }
  } catch {
    yield emitted ? "…（洞察生成中断）" : renderFactsTemplate(facts, format);
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest --root apps/backend run tests/insightWriter.test.ts`
Expected: PASS(6 个用例全绿,不应出现挂起或未清理定时器的告警)

- [ ] **Step 5: 提交**

```bash
git add apps/backend/src/insightWriter.ts apps/backend/tests/insightWriter.test.ts
git commit -m "feat(backend): stream insight prose with template fallback on failure"
```

### Task 9: sqlGuard 重写 —— AST 校验 + 加固正则回退

**Files:**
- Modify: `apps/backend/package.json`(新增 `node-sql-parser` 依赖)
- Modify: `apps/backend/src/sqlGuard.ts`(全量替换,现有 26 行)
- Modify: `apps/backend/tests/sqlGuard.test.ts`(全量替换,现有 56 行)

**Interfaces:**
- Consumes: 无
- Produces:
  - `validate(sql: string): { ok: true; sql: string; viaAst: boolean } | { ok: false; reason: string }`
  - `stripLiterals(sql: string): string`
  - `hasComment(sql: string): boolean`
  - `validateByRegex(sql: string): { ok: true; sql: string } | { ok: false; reason: string }`
  - `enforceLimit(sql: string, limit: number): string`(签名不变)
  - `wrapTimeout<T>(ms: number, p: Promise<T>): Promise<T>`(不变)

**返回值新增 `viaAst`**,现有测试里 `toEqual({ ok: true, sql })` 的断言会失败,所以测试文件整体替换(新文件是旧用例的超集)。

**两处对 spec 的简化,都是去掉无收益的代码**:

1. spec 第 5 节写「遍历子节点,任何非 select 语句节点 → 拒绝」。实际上 `astify` 成功且顶层 `type === "select"` 时,AST 里不可能挂着 INSERT/UPDATE 节点——子查询也是 select。所以只做「单语句 + 顶层 type 为 select」两项断言,不写永远走不到的遍历。
2. spec 说 `enforceLimit` 在 AST 可用时读 `ast.limit`。我们只需要知道「有没有 LIMIT」,正则已经能回答,读 AST 不增加任何能力。保留现有正则实现。

**注释检测必须先剥离字符串字面量**,否则 `SELECT '--x' AS a` 会被误判成含注释。

- [ ] **Step 1: 装依赖**

```bash
npm install node-sql-parser --workspace=apps/backend
```

装完 `apps/backend/package.json` 的 `dependencies` 里应出现 `"node-sql-parser"`。

- [ ] **Step 2: 全量替换 `apps/backend/tests/sqlGuard.test.ts`**

```ts
import { describe, it, expect } from "vitest";
import {
  validate, validateByRegex, stripLiterals, hasComment, enforceLimit, wrapTimeout,
} from "../src/sqlGuard";

describe("validate 放行只读查询", () => {
  it("普通 SELECT", () => {
    const r = validate("SELECT * FROM customers");
    expect(r.ok).toBe(true);
    expect((r as any).sql).toBe("SELECT * FROM customers");
  });
  it("WITH ... SELECT (CTE)", () => {
    expect(validate("WITH t AS (SELECT 1 AS a) SELECT * FROM t").ok).toBe(true);
  });
  it("带聚合与分组的真实查询", () => {
    const sql = "SELECT region, SUM(total_amount) AS amount FROM orders o "
      + "JOIN customers c ON c.customer_id = o.customer_id GROUP BY region ORDER BY amount DESC";
    expect(validate(sql).ok).toBe(true);
  });
  it("末尾单个分号可接受", () => {
    const r = validate("SELECT 1;");
    expect(r.ok).toBe(true);
    expect((r as any).sql).toBe("SELECT 1");
  });
  it("字符串字面量里的关键字不误杀", () => {
    expect(validate("SELECT '已delete' AS status").ok).toBe(true);
    expect(validate("SELECT id FROM t WHERE note = 'drop table'").ok).toBe(true);
  });
  it("列名含关键字前缀不误杀", () => {
    expect(validate("SELECT update_time, create_at FROM orders").ok).toBe(true);
  });
});

describe("validate 拦截写操作与 DDL", () => {
  it.each([
    ["INSERT INTO customers VALUES (1,'x')"],
    ["UPDATE customers SET name='x'"],
    ["DELETE FROM customers"],
    ["DROP TABLE customers"],
    ["CREATE TABLE x (id int)"],
    ["ALTER TABLE customers ADD col int"],
  ])("拦截 %s", sql => {
    expect(validate(sql).ok).toBe(false);
  });
  it("拦截堆叠查询", () => {
    expect(validate("SELECT 1; DROP TABLE customers").ok).toBe(false);
    expect(validate("SELECT 1; PRAGMA database_list").ok).toBe(false);
  });
  it("拦截 ATTACH", () => {
    expect(validate("ATTACH 'x.db' AS other").ok).toBe(false);
  });
});

describe("validate 拦截注释", () => {
  it("行注释", () => {
    const r = validate("SELECT 1 -- drop table customers");
    expect(r.ok).toBe(false);
    expect((r as any).reason).toMatch(/注释|comment/i);
  });
  it("块注释", () => {
    expect(validate("SELECT /* x */ 1").ok).toBe(false);
  });
  it("字符串里的 -- 不算注释", () => {
    expect(hasComment("SELECT '--x' AS a")).toBe(false);
    expect(validate("SELECT '--x' AS a").ok).toBe(true);
  });
});

describe("AST 解析失败时回退正则", () => {
  it("解析不了但形似 SELECT → 放行且标记非 AST 路径", () => {
    const r = validate("SELECT * FROM");
    expect(r.ok).toBe(true);
    expect((r as any).viaAst).toBe(false);
  });
  it("解析不了且是写操作 → 仍然拦截", () => {
    expect(validate("INSERT INTO t VALUES").ok).toBe(false);
  });
  it("validateByRegex 单独可用", () => {
    expect(validateByRegex("SELECT 1").ok).toBe(true);
    expect(validateByRegex("VACUUM").ok).toBe(false);
  });
});

describe("stripLiterals", () => {
  it("单双引号字面量都被清空", () => {
    expect(stripLiterals("SELECT 'a', \"b\" FROM t")).toBe("SELECT '', \"\" FROM t");
  });
});

describe("enforceLimit", () => {
  it("缺 LIMIT 时注入", () => {
    expect(enforceLimit("SELECT * FROM customers", 1000)).toBe("SELECT * FROM customers LIMIT 1000");
  });
  it("已有 LIMIT 时不重复注入", () => {
    expect(enforceLimit("SELECT * FROM customers LIMIT 5", 1000)).toBe("SELECT * FROM customers LIMIT 5");
  });
  it("处理末尾分号", () => {
    expect(enforceLimit("SELECT * FROM customers;", 1000)).toBe("SELECT * FROM customers LIMIT 1000");
  });
});

describe("wrapTimeout", () => {
  it("足够快时正常 resolve", async () => {
    await expect(wrapTimeout(100, Promise.resolve(7))).resolves.toBe(7);
  });
  it("超时时抛 timeout", async () => {
    await expect(wrapTimeout(50, new Promise(r => setTimeout(r, 200)))).rejects.toThrow(/timeout/i);
  });
});
```

- [ ] **Step 3: 跑测试确认失败**

Run: `npx vitest --root apps/backend run tests/sqlGuard.test.ts`
Expected: FAIL，`stripLiterals is not a function` 之类的导出缺失错误

- [ ] **Step 4: 全量替换 `apps/backend/src/sqlGuard.ts`**

```ts
import { Parser } from "node-sql-parser";

const FORBIDDEN = /\b(insert|update|delete|drop|create|alter|attach|detach|pragma|vacuum|reindex|replace|truncate)\b/i;
const SELECT_HEAD = /^\s*(with\b[\s\S]*\bselect|select)\b/i;

const parser = new Parser();

/** 把 '...' 与 "..." 的内容清空,保留引号本身,便于后续做关键字与注释判定。 */
export function stripLiterals(sql: string): string {
  return sql.replace(/'(?:[^']|'')*'/g, "''").replace(/"(?:[^"]|"")*"/g, '""');
}

export function hasComment(sql: string): boolean {
  const bare = stripLiterals(sql);
  return bare.includes("--") || bare.includes("/*");
}

export function validateByRegex(sql: string):
  { ok: true; sql: string } | { ok: false; reason: string } {
  const trimmed = sql.trim().replace(/;\s*$/, "");
  const bare = stripLiterals(trimmed);
  if (bare.includes(";")) return { ok: false, reason: "stacked queries not allowed" };
  if (!SELECT_HEAD.test(bare)) return { ok: false, reason: "only SELECT / WITH...SELECT allowed" };
  if (FORBIDDEN.test(bare)) return { ok: false, reason: "write/DDL keyword detected" };
  return { ok: true, sql: trimmed };
}

export function validate(sql: string):
  { ok: true; sql: string; viaAst: boolean } | { ok: false; reason: string } {
  if (hasComment(sql)) return { ok: false, reason: "SQL 注释不被允许（comment not allowed）" };
  const trimmed = sql.trim().replace(/;\s*$/, "");

  let ast: unknown;
  try {
    ast = parser.astify(trimmed, { database: "sqlite" });
  } catch {
    const fallback = validateByRegex(trimmed);
    return fallback.ok ? { ...fallback, viaAst: false } : fallback;
  }

  if (Array.isArray(ast)) {
    if (ast.length !== 1) return { ok: false, reason: "stacked queries not allowed" };
    ast = ast[0];
  }
  const type = (ast as { type?: string })?.type;
  if (type !== "select") {
    return { ok: false, reason: `only SELECT allowed, got ${type ?? "unknown"}` };
  }
  return { ok: true, sql: trimmed, viaAst: true };
}

export function enforceLimit(sql: string, limit: number): string {
  const trimmed = sql.trim().replace(/;\s*$/, "");
  if (/\blimit\s+\d+/i.test(trimmed)) return trimmed;
  return `${trimmed} LIMIT ${limit}`;
}

export function wrapTimeout<T>(ms: number, p: Promise<T>): Promise<T> {
  let timer: NodeJS.Timeout;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("query timeout")), ms);
  });
  return Promise.race([p, timeout]).finally(() => clearTimeout(timer!));
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `npx vitest --root apps/backend run tests/sqlGuard.test.ts`
Expected: PASS

若「拦截堆叠查询」用例失败——某些版本的 `astify` 对 `SELECT 1; DROP TABLE x` 直接抛错而不是返回数组,那会走正则回退,回退里的分号检查同样会拦住它,结果仍为 `ok: false`。两条路径都覆盖到了,不需要改测试。

- [ ] **Step 6: 记录解析成功率(spec 第 5 节末的实测要求)**

把手动验收清单里的 4 条查询和 Task 9 测试里那条 JOIN + GROUP BY 查询喂给 `validate`,确认 `viaAst === true`。若其中任何一条走了回退,在 README 的「已知限制」里记一行,写明哪类语法 `node-sql-parser` 解析不了。

```bash
node --input-type=module -e "
import { validate } from './apps/backend/dist/sqlGuard.js';
const qs = [
  \"SELECT strftime('%Y-%m', order_date) AS month, SUM(total_amount) AS amount FROM orders GROUP BY month ORDER BY month\",
  'SELECT p.category, SUM(oi.quantity * oi.unit_price) AS amount FROM order_items oi JOIN products p ON p.product_id = oi.product_id GROUP BY p.category',
  'SELECT c.region, SUM(o.total_amount) AS amount FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.region',
  \"SELECT * FROM orders WHERE order_date LIKE '1999%'\"
];
for (const q of qs) console.log(JSON.stringify(validate(q)));
"
```

`dist` 需要先 `npm run build --workspace=apps/backend`。也可以直接写一个临时 vitest 用例断言 `viaAst`,跑完删掉——两种方式都行,目的只是拿到实测结论。

- [ ] **Step 7: 提交**

```bash
git add apps/backend/package.json apps/backend/src/sqlGuard.ts apps/backend/tests/sqlGuard.test.ts package-lock.json
git commit -m "feat(backend): AST-based SQL guard with hardened regex fallback"
```

### Task 10: dbClient 读写连接拆分 + 真截断探测

**Files:**
- Modify: `apps/backend/src/dbClient.ts`(全量替换,现有 46 行)
- Modify: `apps/backend/tests/dbClient.test.ts`(全量替换,现有 42 行)
- Modify: `apps/backend/src/server.ts:10-19`(连接生命周期 + deps 签名)

**Interfaces:**
- Consumes: Task 1 的 `Row` `TableSchema`
- Produces:
  - `new DbClient(path: string, opts?: { readonly?: boolean })`
  - `runQuery(sql: string, limit: number): { rows: Row[]; truncated: boolean }`
  - `getSchema(): TableSchema[]`(不变)、`execRaw(sql: string): void`(只读连接上抛错)、`close(): void`

**连接生命周期**:`server.ts` 先用**可写连接**建表灌数据,关掉它,再开**只读连接**给查询用。只读连接打不开不存在的文件,所以顺序不能颠倒。

**截断探测的职责划分**:`chatService` 负责 `enforceLimit(sql, rowLimit + 1)`,`dbClient` 只负责「切到 `limit` 行并告诉调用方有没有多出来」。这样 `dbClient` 不用 import `sqlGuard`,`limit + 1` 这个技巧也只出现在一处。

**`stmt.reader` 取代旧的正则前缀检查**。旧检查和 `sqlGuard` 重复,而 `reader` 是引擎给出的判断。

- [ ] **Step 1: 全量替换 `apps/backend/tests/dbClient.test.ts`**

```ts
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { DbClient } from "../src/dbClient";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";

const tmpDir = join(process.cwd(), ".tmp-test");
const dbPath = join(tmpDir, "t.db");
let writable: DbClient;

beforeEach(() => {
  mkdirSync(tmpDir, { recursive: true });
  writable = new DbClient(dbPath);
  writable.execRaw(`
    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, region TEXT);
    CREATE TABLE orders (id INTEGER PRIMARY KEY, cust_id INTEGER, amount REAL,
      FOREIGN KEY(cust_id) REFERENCES customers(id));
    INSERT INTO customers VALUES (1,'Alice','east'),(2,'Bob','west');
    INSERT INTO orders VALUES (1,1,10.5),(2,2,20),(3,1,30),(4,2,40),(5,1,50);
  `);
});
afterEach(() => {
  writable.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("getSchema", () => {
  it("给出表、列与外键", () => {
    const orders = writable.getSchema().find(t => t.tableName === "orders")!;
    expect(orders.columns.map(c => c.name)).toContain("amount");
    expect(orders.foreignKeys[0]).toMatchObject({
      column: "cust_id", refTable: "customers", refColumn: "id",
    });
  });
});

describe("runQuery 截断探测", () => {
  it("超过上限时切到上限并标记 truncated", () => {
    const r = writable.runQuery("SELECT id FROM orders LIMIT 4", 3);
    expect(r.rows).toHaveLength(3);
    expect(r.truncated).toBe(true);
  });
  it("恰好等于上限时不误报截断", () => {
    const r = writable.runQuery("SELECT id FROM orders LIMIT 3", 3);
    expect(r.rows).toHaveLength(3);
    expect(r.truncated).toBe(false);
  });
  it("少于上限时不截断", () => {
    const r = writable.runQuery("SELECT id FROM orders LIMIT 2", 3);
    expect(r.rows).toHaveLength(2);
    expect(r.truncated).toBe(false);
  });
  it("空结果集", () => {
    const r = writable.runQuery("SELECT id FROM orders WHERE 1=0", 3);
    expect(r).toEqual({ rows: [], truncated: false });
  });
});

describe("runQuery 拒绝不返回数据的语句", () => {
  it("INSERT 抛错", () => {
    expect(() => writable.runQuery("INSERT INTO customers VALUES (9,'Eve','north')", 10))
      .toThrow(/does not return rows/i);
  });
  it("DROP 抛错", () => {
    expect(() => writable.runQuery("DROP TABLE customers", 10)).toThrow(/does not return rows/i);
  });
});

describe("只读连接", () => {
  it("SELECT 正常", () => {
    const ro = new DbClient(dbPath, { readonly: true });
    try {
      expect(ro.runQuery("SELECT COUNT(*) AS n FROM customers", 10).rows[0].n).toBe(2);
    } finally { ro.close(); }
  });
  it("引擎层面拒绝写入", () => {
    const ro = new DbClient(dbPath, { readonly: true });
    try {
      expect(() => ro.execRaw("INSERT INTO customers VALUES (9,'Eve','north')"))
        .toThrow(/readonly|read-only/i);
    } finally { ro.close(); }
  });
  it("即使绕过 execRaw,prepare 阶段也拒绝", () => {
    const ro = new DbClient(dbPath, { readonly: true });
    try {
      expect(() => ro.runQuery("INSERT INTO customers VALUES (9,'Eve','north')", 10)).toThrow();
    } finally { ro.close(); }
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/backend run tests/dbClient.test.ts`
Expected: FAIL，`runQuery` 返回数组而不是 `{ rows, truncated }`,断言 `r.rows` 为 undefined

- [ ] **Step 3: 全量替换 `apps/backend/src/dbClient.ts`**

```ts
import Database from "better-sqlite3";
import type { Database as DB } from "better-sqlite3";
import { dirname } from "node:path";
import { mkdirSync } from "node:fs";
import type { TableSchema, Row } from "@chatbi/shared";

export class DbClient {
  private db: DB;
  private readonlyMode: boolean;

  constructor(path: string, opts: { readonly?: boolean } = {}) {
    this.readonlyMode = opts.readonly ?? false;
    if (!this.readonlyMode) mkdirSync(dirname(path), { recursive: true });
    this.db = new Database(path, { readonly: this.readonlyMode });
    if (!this.readonlyMode) this.db.pragma("journal_mode = WAL");
  }

  /** 仅可写连接可用:迁移与测试建表。只读连接上调用直接抛错。 */
  execRaw(sql: string): void {
    if (this.readonlyMode) throw new Error("connection is readonly: execRaw not allowed");
    this.db.exec(sql);
  }

  getSchema(): TableSchema[] {
    const tables = this.db.prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).all() as { name: string }[];
    return tables.map(t => {
      const cols = this.db.pragma(`table_info(${t.name})`) as any[];
      const fks = this.db.pragma(`foreign_key_list(${t.name})`) as any[];
      return {
        tableName: t.name,
        columns: cols.map(c => ({
          name: c.name, type: c.type,
          notNull: Boolean(c.notnull), pk: Boolean(c.pk),
        })),
        foreignKeys: fks.map(f => ({ column: f.from, refTable: f.table, refColumn: f.to })),
      };
    });
  }

  /**
   * 调用方应已用 enforceLimit(sql, limit + 1) 注入过上限。
   * 这里只负责切回 limit 行,并报告是否多出来过(= 真的被截断)。
   */
  runQuery(sql: string, limit: number): { rows: Row[]; truncated: boolean } {
    const stmt = this.db.prepare(sql);
    if (!stmt.reader) throw new Error("statement does not return rows");
    const all = stmt.all() as Row[];
    return { rows: all.slice(0, limit), truncated: all.length > limit };
  }

  close(): void { this.db.close(); }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest --root apps/backend run tests/dbClient.test.ts`
Expected: PASS

- [ ] **Step 5: 改 `apps/backend/src/server.ts`,把 10-19 行替换为**

```ts
export function startServer() {
  // 先用可写连接建表灌数据,关掉后再开只读连接——只读连接打不开不存在的文件。
  const writable = new DbClient(config.dbPath);
  try {
    migrate(writable);
  } catch (e) {
    console.error("migration failed:", e);
    process.exit(1);
  } finally {
    writable.close();
  }

  const db = new DbClient(config.dbPath, { readonly: true });
  try { db.getSchema(); } catch (e) { console.error("schema self-check failed:", e); process.exit(1); }

  const deps = {
    db: {
      getSchema: () => db.getSchema(),
      runQuery: (sql: string, limit: number) => db.runQuery(sql, limit),
    },
    llm: new LlmClient(),
  };
```

后面的 `const app = express()` 起保持不动。

- [ ] **Step 6: 跑 migrate 测试确认没被连接拆分弄坏**

Run: `npx vitest --root apps/backend run tests/migrate.test.ts tests/dbClient.test.ts`
Expected: PASS。`migrate.test.ts` 若自己 `new DbClient(path)` 建连接,默认就是可写,不需要改。

- [ ] **Step 7: 提交**

```bash
git add apps/backend/src/dbClient.ts apps/backend/src/server.ts apps/backend/tests/dbClient.test.ts
git commit -m "feat(backend): readonly query connection and true truncation probing"
```

### Task 11: promptBuilder —— hint 字段、下钻上下文、洞察 prompt

**Files:**
- Modify: `apps/backend/src/promptBuilder.ts`(全量替换,现有 41 行)
- Modify: `apps/backend/tests/promptBuilder.test.ts`(**追加**用例,现有 5 个用例全部保留且仍应通过)

**Interfaces:**
- Consumes: Task 1 的 `TableSchema` `ChatTurn` `DrillContext` `InsightFact` `ValueFormat`、Task 7 的 `renderFactsLines`
- Produces:
  - `buildPrompt(opts: { question: string; schema: TableSchema[]; history: ChatTurn[]; context?: DrillContext }): string`
  - `buildRetryPrompt(prevPrompt: string, feedback: string): string`(不变)
  - `buildInsightPrompt(facts: InsightFact[], question: string, format: ValueFormat): string`

**prompt 里必须写清一条**:`dimensions` / `measures` / `seriesBy` 填的是 **SQL 结果列的别名**,不是原表列名。`inferChartSpec` 拿实际结果列名校验 hint,模型若写原表列名会被整条丢弃,图就退化了。

- [ ] **Step 1: 追加失败测试到 `apps/backend/tests/promptBuilder.test.ts`**

在文件末尾追加(顶部 import 改成 `import { buildPrompt, buildInsightPrompt } from "../src/promptBuilder";`,并补 `import type { InsightFact, ValueFormat } from "@chatbi/shared";`):

```ts
describe("buildPrompt 图表 hint 字段", () => {
  it("要求输出 dimensions/measures/seriesBy/stack", () => {
    const p = buildPrompt({ question: "x", schema, history: [] });
    expect(p).toContain("dimensions");
    expect(p).toContain("measures");
    expect(p).toContain("seriesBy");
    expect(p).toContain("stack");
  });
  it("说明 hint 列名必须是结果列别名", () => {
    const p = buildPrompt({ question: "x", schema, history: [] });
    expect(p).toMatch(/别名/);
  });
  it("列出 stack 的取值", () => {
    const p = buildPrompt({ question: "x", schema, history: [] });
    expect(p).toMatch(/normal/);
    expect(p).toMatch(/percent/);
  });
});

describe("buildPrompt 下钻上下文", () => {
  const context = {
    lastSql: "SELECT strftime('%Y-%m', order_date) AS month, SUM(total_amount) AS amount FROM orders GROUP BY month",
    lastColumns: ["month", "amount"],
  };
  it("有 context 时注入上轮 SQL 与结果列", () => {
    const p = buildPrompt({ question: "只看华东区", schema, history: [], context });
    expect(p).toContain("上一轮查询");
    expect(p).toContain("SUM(total_amount) AS amount");
    expect(p).toContain("month, amount");
    expect(p).toMatch(/细化/);
  });
  it("无 context 时完全不出现上一轮段落", () => {
    const p = buildPrompt({ question: "只看华东区", schema, history: [] });
    expect(p).not.toContain("上一轮查询");
  });
});

describe("buildInsightPrompt", () => {
  const FORMAT: ValueFormat = { kind: "currency", decimals: 0, unit: "元", scale: 1 };
  const facts: InsightFact[] = [
    { kind: "trend", series: "金额", dir: "up", pct: 23.4, from: "1月", to: "3月" },
    { kind: "peak", series: "金额", label: "3月", value: 128400 },
  ];
  it("逐条列出事实且数值已格式化", () => {
    const p = buildInsightPrompt(facts, "按月统计订单金额", FORMAT);
    expect(p).toContain("上涨 23.4%");
    expect(p).toContain("128,400 元");
  });
  it("带上用户问题", () => {
    expect(buildInsightPrompt(facts, "按月统计订单金额", FORMAT)).toContain("按月统计订单金额");
  });
  it("写明不得引入未列出的数字", () => {
    const p = buildInsightPrompt(facts, "q", FORMAT);
    expect(p).toMatch(/不得引入/);
    expect(p).toMatch(/不得逐条罗列/);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/backend run tests/promptBuilder.test.ts`
Expected: FAIL，`buildInsightPrompt is not a function`,以及 `dimensions` 等断言不通过

- [ ] **Step 3: 全量替换 `apps/backend/src/promptBuilder.ts`**

```ts
import type { TableSchema, ChatTurn, DrillContext, InsightFact, ValueFormat } from "@chatbi/shared";
import { renderFactsLines } from "./facts";

/** 保留最近 2 轮完整问答(user + assistant = 4 条消息)。*/
const HISTORY_MESSAGE_LIMIT = 4;

const SYSTEM = `你是 SQL 分析助手。根据下方数据库 schema 用自然语言回答用户问题。

规则:
1. 只生成 SELECT 语句,只读,不要写 SQL 注释。
2. 输出严格 JSON,字段如下:
   {"sql":"...","explanation":"...","chartType":"bar|line|pie|table","dimensions":["列名"],"measures":["列名"],"seriesBy":"列名(可省略)","stack":"none|normal|percent"}
3. dimensions / measures / seriesBy 里填的必须是 sql 结果列的**别名**,不是原表列名。
4. dimensions 首个元素作为 x 轴;measures 是要画的数值列。
5. chartType 选择:时序→line,占比→pie,分组对比→bar,无明显可视化→table。
6. 需要按某个维度拆成多条系列时(例如各区域各一条折线),把该维度放进 seriesBy。
7. stack 仅在 chartType 为 bar 时有意义:需要堆叠对比用 normal,需要看占比结构用 percent,否则 none。
8. explanation 用一句中文说明你打算查什么。
9. 只输出 JSON,不要 markdown 代码块,不要多余文字。`;

function renderSchema(schema: TableSchema[]): string {
  return schema.map(t => {
    const cols = t.columns.map(c => `  ${c.name} ${c.type}${c.pk ? " PK" : ""}${c.notNull ? " NOT NULL" : ""}`).join("\n");
    const fks = t.foreignKeys.map(f => `  FK ${f.column} -> ${f.refTable}(${f.refColumn})`).join("\n");
    return `TABLE ${t.tableName} (\n${cols}\n${fks ? fks + "\n" : ""})`;
  }).join("\n\n");
}

function renderDrill(context?: DrillContext): string {
  if (!context) return "";
  return `
上一轮查询(用户可能要在此基础上细化):
SQL: ${context.lastSql}
结果列: ${context.lastColumns.join(", ")}

若用户的问题是对上一轮的细化(追加筛选、更换时间粒度、增加拆分维度),
请在上面的 SQL 基础上改写;若是全新问题,忽略上一轮。
`;
}

export function buildPrompt(opts: {
  question: string; schema: TableSchema[]; history: ChatTurn[]; context?: DrillContext;
}): string {
  const recent = opts.history.slice(-HISTORY_MESSAGE_LIMIT);
  const historyText = recent.length
    ? recent.map(t => `${t.role}: ${t.text}`).join("\n")
    : "(无)";
  return `${SYSTEM}

数据库 schema:
${renderSchema(opts.schema)}
${renderDrill(opts.context)}
对话历史(最近 2 轮):
${historyText}

用户问题: ${opts.question}`;
}

export function buildRetryPrompt(prevPrompt: string, feedback: string): string {
  return `${prevPrompt}\n\n上次输出有问题:${feedback}\n请严格按要求只输出 JSON。`;
}

export function buildInsightPrompt(
  facts: InsightFact[], question: string, format: ValueFormat,
): string {
  const lines = renderFactsLines(facts, format).filter(Boolean).map(l => `- ${l}`).join("\n");
  return `以下是系统已经算好的事实,请用 2-3 句中文串成一段连贯的分析。

严格约束:
- 不得引入任何未在下方列出的数字
- 不得逐条罗列,要串成自然的句子
- 不得给出业务建议或结论性判断
- 只输出这段分析文字,不要 JSON,不要标题

用户问题: ${question}
事实:
${lines}`;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest --root apps/backend run tests/promptBuilder.test.ts`
Expected: PASS(原有 5 个用例 + 新增 8 个用例全绿)

- [ ] **Step 5: 提交**

```bash
git add apps/backend/src/promptBuilder.ts apps/backend/tests/promptBuilder.test.ts
git commit -m "feat(backend): chart hint fields, drill-down context and insight prompt"
```

### Task 12: chatService 编排改造 + 路由透传 context

**Files:**
- Modify: `apps/backend/src/config.ts`(新增 `insightTimeoutMs`)
- Modify: `apps/backend/src/chatService.ts`(全量替换,现有 74 行)
- Modify: `apps/backend/src/routes/chat.ts:8-15`(接收并透传 `context`)
- Modify: `apps/backend/tests/chatService.test.ts`(全量替换,现有 96 行)

**Interfaces:**
- Consumes: Task 6 `inferChartSpec`、Task 7 `computeFacts`、Task 8 `writeInsight`、Task 9 `validate`/`enforceLimit`/`wrapTimeout`、Task 11 `buildPrompt`/`buildRetryPrompt`/`buildInsightPrompt`
- Produces:
  - `export interface ChatDeps { db: { getSchema(): TableSchema[]; runQuery(sql: string, limit: number): { rows: Row[]; truncated: boolean } }; llm: { chatStream(prompt: string): AsyncIterable<string> } }`
  - `handleChat(opts: { question: string; history: ChatTurn[]; context?: DrillContext; deps: ChatDeps }): AsyncIterable<StreamEvent>`

**事件序列固定为** `result → insightFacts → insightDelta × N → done`。`result` 在第二轮 LLM 开始前发出,所以图表先落地。

**回传给前端的 `sql` 是校验后、未注入 `LIMIT+1` 的那条**——它要作为下一轮的 `lastSql`,不该带上探测用的 `+1`。

**同一个 `llm` 实例被调用两次**:第一轮出 SQL,第二轮写洞察。空结果集时第二轮不会发生(`writeInsight` 自己短路)。

- [ ] **Step 1: 全量替换 `apps/backend/tests/chatService.test.ts`**

```ts
import { describe, it, expect, vi } from "vitest";
import { handleChat } from "../src/chatService";
import type { TableSchema, StreamEvent, Row } from "@chatbi/shared";

const schema: TableSchema[] = [{
  tableName: "orders",
  columns: [
    { name: "region", type: "TEXT", notNull: false, pk: false },
    { name: "total", type: "REAL", notNull: false, pk: false },
  ],
  foreignKeys: [],
}];

const llmJson = (over: Record<string, unknown> = {}) => JSON.stringify({
  sql: "SELECT region, SUM(total) AS total FROM orders GROUP BY region",
  explanation: "按地区汇总",
  chartType: "bar",
  dimensions: ["region"],
  measures: ["total"],
  ...over,
});

/** 按顺序返回预设回复;记录每次收到的 prompt。 */
function queuedLlm(replies: (string | Error)[]) {
  const prompts: string[] = [];
  let i = 0;
  return {
    prompts,
    calls: () => i,
    chatStream: async function* (prompt: string) {
      prompts.push(prompt);
      const r = replies[Math.min(i++, replies.length - 1)];
      if (r instanceof Error) throw r;
      yield r;
    },
  };
}

function deps(llm: any, rows: Row[], truncated = false) {
  return {
    db: { getSchema: () => schema, runQuery: vi.fn(() => ({ rows, truncated })) },
    llm,
  };
}

async function collect(it: AsyncIterable<StreamEvent>): Promise<StreamEvent[]> {
  const out: StreamEvent[] = [];
  for await (const e of it) out.push(e);
  return out;
}

describe("handleChat 正常路径", () => {
  it("事件序列为 result → insightFacts → insightDelta* → done", async () => {
    const llm = queuedLlm([llmJson(), "华东区领先。"]);
    const events = await collect(handleChat({
      question: "各地区销售额", history: [],
      deps: deps(llm, [{ region: "华东", total: 412 }, { region: "华北", total: 588 }]),
    }));
    expect(events.map(e => e.type)).toEqual([
      "result", "insightFacts", "insightDelta", "done",
    ]);
  });

  it("result 带 spec / table / queryIntent / sql", async () => {
    const llm = queuedLlm([llmJson(), "文本"]);
    const events = await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 412 }]),
    }));
    const r = events.find(e => e.type === "result") as any;
    expect(r.payload.spec.chartType).toBe("bar");
    expect(r.payload.spec.series[0].data).toEqual([412]);
    expect(r.payload.table.columns).toEqual(["region", "total"]);
    expect(r.payload.queryIntent).toBe("按地区汇总");
    expect(r.payload.sql).toContain("GROUP BY region");
    expect(r.payload.sql).not.toContain("LIMIT");
  });

  it("洞察文本逐 token 透传", async () => {
    const llm = queuedLlm([llmJson(), "华东区领先"]);
    const events = await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 412 }]),
    }));
    const text = events.filter(e => e.type === "insightDelta").map((e: any) => e.text).join("");
    expect(text).toBe("华东区领先");
  });

  it("查询执行时用的是 LIMIT+1 探测,回传的 sql 不带它", async () => {
    const llm = queuedLlm([llmJson(), "x"]);
    const d = deps(llm, [{ region: "华东", total: 1 }]);
    await collect(handleChat({ question: "q", history: [], deps: d }));
    const [sqlArg, limitArg] = (d.db.runQuery as any).mock.calls[0];
    expect(sqlArg).toContain("LIMIT 1001");
    expect(limitArg).toBe(1000);
  });
});

describe("handleChat 下钻上下文", () => {
  it("context 被注入第一轮 prompt", async () => {
    const llm = queuedLlm([llmJson(), "x"]);
    await collect(handleChat({
      question: "只看华东区", history: [],
      context: { lastSql: "SELECT region FROM orders", lastColumns: ["region"] },
      deps: deps(llm, [{ region: "华东", total: 1 }]),
    }));
    expect(llm.prompts[0]).toContain("上一轮查询");
    expect(llm.prompts[0]).toContain("SELECT region FROM orders");
  });
  it("无 context 时第一轮 prompt 不含上一轮段落", async () => {
    const llm = queuedLlm([llmJson(), "x"]);
    await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 1 }]),
    }));
    expect(llm.prompts[0]).not.toContain("上一轮查询");
  });
});

describe("handleChat 空结果", () => {
  it("跳过第二轮 LLM,洞察为固定文案", async () => {
    const llm = queuedLlm([llmJson(), "不应被调用"]);
    const events = await collect(handleChat({
      question: "q", history: [], deps: deps(llm, []),
    }));
    expect(llm.calls()).toBe(1);
    const text = events.filter(e => e.type === "insightDelta").map((e: any) => e.text).join("");
    expect(text).toBe("没有符合条件的记录。");
    const r = events.find(e => e.type === "result") as any;
    expect(r.payload.spec.chartType).toBe("table");
  });
});

describe("handleChat 截断", () => {
  it("spec.notes 与 facts 同时反映截断", async () => {
    const llm = queuedLlm([llmJson(), "x"]);
    const events = await collect(handleChat({
      question: "q", history: [],
      deps: deps(llm, [{ region: "华东", total: 1 }], true),
    }));
    const r = events.find(e => e.type === "result") as any;
    const f = events.find(e => e.type === "insightFacts") as any;
    expect(r.payload.spec.notes.join()).toContain("截断");
    expect(f.facts.map((x: any) => x.kind)).toContain("truncated");
  });
});

describe("handleChat 重试与失败", () => {
  it("JSON 解析失败重试一次,第二次成功", async () => {
    const llm = queuedLlm(["garbage", llmJson(), "x"]);
    const events = await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 1 }]),
    }));
    expect(events.some(e => e.type === "result")).toBe(true);
  });

  it("两次都解析失败则报错,并附原始输出", async () => {
    const llm = queuedLlm(["garbage", "still garbage"]);
    const events = await collect(handleChat({ question: "q", history: [], deps: deps(llm, []) }));
    const err = events.find(e => e.type === "error") as any;
    expect(err.message).toMatch(/json/i);
    expect(err.raw).toBe("still garbage");
  });

  it("SQL 非只读被拦截", async () => {
    const llm = queuedLlm([llmJson({ sql: "DELETE FROM orders" })]);
    const events = await collect(handleChat({ question: "q", history: [], deps: deps(llm, []) }));
    const err = events.find(e => e.type === "error") as any;
    expect(err.message).toMatch(/拦截/);
  });

  it("SQL 执行报错重试一次后报错", async () => {
    const llm = queuedLlm([llmJson(), llmJson()]);
    const d = {
      db: {
        getSchema: () => schema,
        runQuery: vi.fn(() => { throw new Error("no such column: bad"); }),
      },
      llm,
    };
    const events = await collect(handleChat({ question: "q", history: [], deps: d }));
    expect(d.db.runQuery).toHaveBeenCalledTimes(2);
    const err = events.find(e => e.type === "error") as any;
    expect(err.message).toMatch(/no such column/);
  });

  it("重试 prompt 里带上失败原因", async () => {
    const llm = queuedLlm(["garbage", llmJson(), "x"]);
    await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 1 }]),
    }));
    expect(llm.prompts[1]).toContain("上次输出有问题");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/backend run tests/chatService.test.ts`
Expected: FAIL，`chatService` 仍 import 已删除的 `./chartAssembler`,报模块找不到

- [ ] **Step 3: 改 `apps/backend/src/config.ts`,加一行**

```ts
export const config = {
  dbPath: process.env.DB_PATH ?? "./data/chatbi.db",
  ollamaUrl: process.env.OLLAMA_URL ?? "http://localhost:11434",
  ollamaModel: process.env.OLLAMA_MODEL ?? "llama3.1",
  queryTimeoutMs: Number(process.env.QUERY_TIMEOUT_MS ?? 5000),
  rowLimit: Number(process.env.ROW_LIMIT ?? 1000),
  insightTimeoutMs: Number(process.env.INSIGHT_TIMEOUT_MS ?? 8000),
};
```

- [ ] **Step 4: 全量替换 `apps/backend/src/chatService.ts`**

```ts
import type {
  ChartHint, ChatTurn, DrillContext, Row, StreamEvent, TableSchema, ValueFormat,
} from "@chatbi/shared";
import { buildPrompt, buildRetryPrompt, buildInsightPrompt } from "./promptBuilder";
import { validate, enforceLimit, wrapTimeout } from "./sqlGuard";
import { inferChartSpec } from "./chartSpec";
import { computeFacts } from "./facts";
import { writeInsight } from "./insightWriter";
import { config } from "./config";

export interface ChatDeps {
  db: {
    getSchema(): TableSchema[];
    runQuery(sql: string, limit: number): { rows: Row[]; truncated: boolean };
  };
  llm: { chatStream(prompt: string): AsyncIterable<string> };
}

const DEFAULT_FORMAT: ValueFormat = { kind: "number", decimals: 0, scale: 1 };

interface ParsedLLM { sql: string; explanation: string; hint: ChartHint | null }

async function collectStream(stream: AsyncIterable<string>): Promise<string> {
  let out = "";
  for await (const t of stream) out += t;
  return out;
}

function parseJson(raw: string): ParsedLLM | null {
  const cleaned = raw.replace(/```json|```/g, "").trim();
  let obj: any;
  try { obj = JSON.parse(cleaned); } catch { return null; }
  if (typeof obj?.sql !== "string" || typeof obj?.explanation !== "string") return null;

  const strings = (v: unknown) =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  const hint: ChartHint | null = typeof obj.chartType === "string" ? {
    chartType: obj.chartType,
    dimensions: strings(obj.dimensions),
    measures: strings(obj.measures),
    ...(typeof obj.seriesBy === "string" && obj.seriesBy ? { seriesBy: obj.seriesBy } : {}),
    ...(typeof obj.stack === "string" ? { stack: obj.stack } : {}),
  } as ChartHint : null;

  return { sql: obj.sql, explanation: obj.explanation, hint };
}

export async function* handleChat(opts: {
  question: string; history: ChatTurn[]; context?: DrillContext; deps: ChatDeps;
}): AsyncIterable<StreamEvent> {
  const schema = opts.deps.db.getSchema();
  let prompt = buildPrompt({
    question: opts.question, schema, history: opts.history, context: opts.context,
  });

  for (let attempt = 0; attempt < 2; attempt++) {
    const raw = await collectStream(opts.deps.llm.chatStream(prompt));
    const parsed = parseJson(raw);
    if (!parsed) {
      if (attempt === 0) { prompt = buildRetryPrompt(prompt, "输出不是合法 JSON,请只输出 JSON"); continue; }
      yield { type: "error", message: "LLM 输出无法解析为 JSON", raw };
      return;
    }

    const v = validate(parsed.sql);
    if (!v.ok) {
      if (attempt === 0) {
        prompt = buildRetryPrompt(prompt, `SQL 校验失败:${v.reason},请重新生成只读 SELECT`);
        continue;
      }
      yield { type: "error", message: `查询非只读,已拦截:${v.reason}` };
      return;
    }

    const probeSql = enforceLimit(v.sql, config.rowLimit + 1);
    let out: { rows: Row[]; truncated: boolean };
    try {
      out = await wrapTimeout(
        config.queryTimeoutMs,
        Promise.resolve().then(() => opts.deps.db.runQuery(probeSql, config.rowLimit)),
      );
    } catch (e) {
      if (attempt === 0) {
        prompt = buildRetryPrompt(prompt, `SQL 执行报错:${(e as Error).message},请修正 SQL`);
        continue;
      }
      yield { type: "error", message: `SQL 执行失败:${(e as Error).message}` };
      return;
    }

    const columns = out.rows.length ? Object.keys(out.rows[0]) : [];
    const spec = inferChartSpec({
      rows: out.rows, columns, hint: parsed.hint,
      truncated: out.truncated, rowLimit: config.rowLimit,
    });

    yield {
      type: "result",
      payload: {
        spec,
        table: { columns, rows: out.rows },
        queryIntent: parsed.explanation,
        sql: v.sql,
      },
    };

    const facts = computeFacts(spec, { truncated: out.truncated, rowLimit: config.rowLimit });
    yield { type: "insightFacts", facts };

    const format = spec.series[0]?.format ?? DEFAULT_FORMAT;
    const insightPrompt = buildInsightPrompt(facts, opts.question, format);
    for await (const text of writeInsight({
      facts, prompt: insightPrompt, llm: opts.deps.llm,
      timeoutMs: config.insightTimeoutMs, format,
    })) {
      yield { type: "insightDelta", text };
    }

    yield { type: "done" };
    return;
  }
}
```

- [ ] **Step 5: 改 `apps/backend/src/routes/chat.ts`,把 8-15 行替换为**

```ts
    const { question, history, context } = req.body as {
      question: string; history?: ChatTurn[]; context?: DrillContext;
    };
    if (typeof question !== "string") { res.status(400).json({ error: "question required" }); return; }
    const drill = context && typeof context.lastSql === "string"
      ? { lastSql: context.lastSql, lastColumns: Array.isArray(context.lastColumns) ? context.lastColumns : [] }
      : undefined;
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders?.();
    try {
      for await (const ev of handleChat({ question, history: history ?? [], context: drill, deps })) {
        res.write(`data: ${JSON.stringify(ev)}\n\n`);
      }
```

顶部 import 补上 `DrillContext`:

```ts
import type { ChatTurn, DrillContext, StreamEvent } from "@chatbi/shared";
```

- [ ] **Step 6: 跑测试确认通过**

Run: `npx vitest --root apps/backend run tests/chatService.test.ts tests/chat.route.test.ts`
Expected: `chatService.test.ts` PASS。`chat.route.test.ts` 若断言了 `explanationDelta` 事件会失败——把它改为断言 `result` 与 `done`,并补一个「body 带 context 时不报 400」的用例。

- [ ] **Step 7: 提交**

```bash
git add apps/backend/src/config.ts apps/backend/src/chatService.ts apps/backend/src/routes/chat.ts \
  apps/backend/tests/chatService.test.ts apps/backend/tests/chat.route.test.ts
git commit -m "feat(backend): two-phase chat orchestration with facts and insight streaming"
```

### Task 13: 前端 api —— 回传 context、解析新事件

**Files:**
- Modify: `apps/frontend/src/api.ts:3-14`(opts 新增 `context`,body 带上它)
- Modify: `apps/frontend/src/__tests__/api.test.ts`(全量替换,现有断言用的是已删除的 `explanationDelta` / `ChartPayload`)

**Interfaces:**
- Consumes: Task 1 的 `ChatTurn` `DrillContext` `StreamEvent`
- Produces: `streamChat(opts: { question: string; history: ChatTurn[]; context?: DrillContext; onEvent: (e: StreamEvent) => void; endpoint?: string }): Promise<void>`

SSE 解析逻辑本身不用改——它对事件类型是透明的,`JSON.parse` 出什么就交给 `onEvent`。要改的只有请求体。

- [ ] **Step 1: 全量替换 `apps/frontend/src/__tests__/api.test.ts`**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { streamChat } from "../api";
import type { StreamEvent } from "@chatbi/shared";

function mockFetch(sseBody: string) {
  const stream = new ReadableStream({
    start(ctl) { ctl.enqueue(new TextEncoder().encode(sseBody)); ctl.close(); },
  });
  return vi.fn().mockResolvedValue({ ok: true, body: stream } as any);
}

const collect = (body: string, extra: Record<string, unknown> = {}) => {
  (global as any).fetch = mockFetch(body);
  const events: StreamEvent[] = [];
  return streamChat({ question: "q", history: [], onEvent: e => events.push(e), ...extra })
    .then(() => events);
};

beforeEach(() => { (global as any).fetch = undefined; });

describe("streamChat 事件解析", () => {
  it("解析 result / insightFacts / insightDelta / done", async () => {
    const body = [
      'data: {"type":"result","payload":{"spec":{"chartType":"bar","stack":"none","x":{"field":"region","role":"categorical","labels":["华东"]},"series":[],"notes":[]},"table":{"columns":["region"],"rows":[{"region":"华东"}]},"queryIntent":"按地区","sql":"SELECT 1"}}',
      'data: {"type":"insightFacts","facts":[{"kind":"empty"}]}',
      'data: {"type":"insightDelta","text":"华东领先"}',
      'data: {"type":"done"}',
    ].join("\n\n") + "\n\n";
    const events = await collect(body);
    expect(events.map(e => e.type)).toEqual(["result", "insightFacts", "insightDelta", "done"]);
    expect((events[0] as any).payload.queryIntent).toBe("按地区");
  });

  it("跨 chunk 的不完整事件不会被误解析", async () => {
    const events = await collect('data: {"type":"insightDelta","text":"a"}\n\ndata: {"type":"don');
    expect(events.map(e => e.type)).toEqual(["insightDelta"]);
  });
});

describe("streamChat 请求体", () => {
  it("带 context 时放进 body", async () => {
    await collect('data: {"type":"done"}\n\n', {
      context: { lastSql: "SELECT region FROM orders", lastColumns: ["region"] },
    });
    const body = JSON.parse((global as any).fetch.mock.calls[0][1].body);
    expect(body.context).toEqual({ lastSql: "SELECT region FROM orders", lastColumns: ["region"] });
  });

  it("无 context 时 body 里不出现该字段", async () => {
    await collect('data: {"type":"done"}\n\n');
    const body = JSON.parse((global as any).fetch.mock.calls[0][1].body);
    expect("context" in body).toBe(false);
  });
});

describe("streamChat 错误路径", () => {
  it("非 2xx 时发 error 事件", async () => {
    (global as any).fetch = vi.fn().mockResolvedValue({ ok: false, status: 500, body: null } as any);
    const events: StreamEvent[] = [];
    await streamChat({ question: "q", history: [], onEvent: e => events.push(e) });
    expect(events[0].type).toBe("error");
  });
  it("fetch 抛错时发 error 事件", async () => {
    (global as any).fetch = vi.fn().mockRejectedValue(new Error("offline"));
    const events: StreamEvent[] = [];
    await streamChat({ question: "q", history: [], onEvent: e => events.push(e) });
    expect((events[0] as any).message).toMatch(/offline|网络/);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/frontend run src/__tests__/api.test.ts`
Expected: FAIL，「带 context 时放进 body」不通过(body 里没有 `context`)

- [ ] **Step 3: 改 `apps/frontend/src/api.ts`**

把 3-14 行替换为:

```ts
import type { ChatTurn, DrillContext, StreamEvent } from "@chatbi/shared";

export function streamChat(opts: {
  question: string; history: ChatTurn[]; context?: DrillContext;
  onEvent: (e: StreamEvent) => void;
  endpoint?: string;
}): Promise<void> {
  const url = opts.endpoint ?? "/api/chat";
  return (async () => {
    let res: Response;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: opts.question,
          history: opts.history,
          ...(opts.context ? { context: opts.context } : {}),
        }),
      });
    } catch (e) {
```

其余部分(SSE 解析循环)不动。

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest --root apps/frontend run src/__tests__/api.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/frontend/src/api.ts apps/frontend/src/__tests__/api.test.ts
git commit -m "feat(frontend): send drill-down context and parse P1 stream events"
```

### Task 14: ResultCard 改调 shared renderer + InsightPanel

**Files:**
- Modify: `apps/frontend/src/components/ResultCard.tsx`(全量替换,现有 55 行)
- Create: `apps/frontend/src/components/InsightPanel.tsx`
- Modify: `apps/frontend/src/components/MessageBubble.tsx`(全量替换,现有 13 行)
- Modify: `apps/frontend/src/__tests__/ResultCard.test.tsx`(全量替换)
- Create: `apps/frontend/src/__tests__/InsightPanel.test.tsx`

**Interfaces:**
- Consumes: Task 1/2/7 的 `ResultPayload` `InsightFact` `ValueFormat` `ChartType`、`specToEchartsOption`、`renderFactsLines`
- Produces:
  - `ResultCard({ payload, insight, facts }: { payload: ResultPayload; insight: string; facts: InsightFact[] })`
  - `InsightPanel({ text, facts, format }: { text: string; facts: InsightFact[]; format?: ValueFormat })`
  - `export interface Message { id: string; role: "user" | "assistant"; text: string; payload?: ResultPayload; facts?: InsightFact[]; insight?: string }`(Task 15 的 `ChatWindow` 依赖这个形状)

**本地 `buildOption` 彻底删除**,改调 `specToEchartsOption`。切换图表类型时不重算数据,只覆盖 `chartType`(以及非 bar 时把 `stack` 归零)。

**P1a 的调色板是临时的**:先用 ECharts 默认色序写死在 `ResultCard.tsx`,P1b 会换成 `theme/chartPalette` 的可访问色板。样式仍是裸 inline style,P1b 再处理。

- [ ] **Step 1: 全量替换 `apps/frontend/src/__tests__/ResultCard.test.tsx`**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ResultCard } from "../components/ResultCard";
import type { ResultPayload, InsightFact } from "@chatbi/shared";

const CURRENCY = { kind: "currency" as const, decimals: 0, unit: "元", scale: 1 as const };

const payload = (over: Partial<ResultPayload> = {}): ResultPayload => ({
  spec: {
    chartType: "bar", stack: "none",
    x: { field: "region", role: "categorical", labels: ["华东", "华北"] },
    series: [{ name: "total", field: "total", data: [100, 200], format: CURRENCY }],
    notes: [],
  },
  table: {
    columns: ["region", "total"],
    rows: [{ region: "华东", total: 100 }, { region: "华北", total: 200 }],
  },
  queryIntent: "按地区汇总",
  sql: "SELECT region, SUM(total) AS total FROM orders GROUP BY region",
  ...over,
});

const facts: InsightFact[] = [{ kind: "total", series: "total", value: 300 }];

describe("ResultCard 表格与切换", () => {
  it("渲染表头与数据行", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    expect(screen.getByText("region")).toBeTruthy();
    expect(screen.getByText("华东")).toBeTruthy();
    expect(screen.getByText("200")).toBeTruthy();
  });

  it("4 个图表类型按钮,后端建议的那个高亮", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    expect(screen.getByRole("button", { name: /bar/i }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /pie/i }).getAttribute("aria-pressed")).toBe("false");
  });

  it("切到 pie 后高亮转移,表格仍在", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    fireEvent.click(screen.getByRole("button", { name: /pie/i }));
    expect(screen.getByRole("button", { name: /pie/i }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("华东")).toBeTruthy();
  });

  it("切到 table 时图表容器消失", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    expect(screen.queryByTestId("chart")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /table/i }));
    expect(screen.queryByTestId("chart")).toBeNull();
  });

  it("后端建议 table 时也能切成图表(series 已备好)", () => {
    const p = payload();
    p.spec.chartType = "table";
    render(<ResultCard payload={p} insight="" facts={[]} />);
    expect(screen.queryByTestId("chart")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /bar/i }));
    expect(screen.queryByTestId("chart")).toBeTruthy();
  });
});

describe("ResultCard notes / SQL / 大表格", () => {
  it("notes 逐条展示", () => {
    const p = payload();
    p.spec.notes = ["已补齐 2 个无数据的时间点（按 0 计）", "结果已截断至 1000 行"];
    render(<ResultCard payload={p} insight="" facts={[]} />);
    expect(screen.getAllByTestId("note")).toHaveLength(2);
  });

  it("查看 SQL 折叠区里是校验后的 SQL", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    expect(screen.getByText(/查看 SQL/)).toBeTruthy();
    expect(screen.getByText(/GROUP BY region/)).toBeTruthy();
  });

  it("超过 100 行只渲染前 100 行并提示", () => {
    const rows = Array.from({ length: 120 }, (_, i) => ({ region: `r${i}`, total: i }));
    render(<ResultCard payload={payload({ table: { columns: ["region", "total"], rows } })}
      insight="" facts={[]} />);
    expect(screen.getByText(/另有 20 行未展示/)).toBeTruthy();
    expect(screen.queryByText("r119")).toBeNull();
  });

  it("洞察文本与计算依据一起挂在卡片里", () => {
    render(<ResultCard payload={payload()} insight="华东区领先。" facts={facts} />);
    expect(screen.getByTestId("insight-text").textContent).toBe("华东区领先。");
    expect(screen.getByText(/计算依据/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: 创建 `apps/frontend/src/__tests__/InsightPanel.test.tsx`**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { InsightPanel } from "../components/InsightPanel";
import type { InsightFact } from "@chatbi/shared";

const CURRENCY = { kind: "currency" as const, decimals: 0, unit: "元", scale: 1 as const };
const facts: InsightFact[] = [
  { kind: "trend", series: "金额", dir: "up", pct: 23.4, from: "1月", to: "3月" },
  { kind: "peak", series: "金额", label: "3月", value: 128400 },
];

describe("InsightPanel", () => {
  it("展示洞察文本", () => {
    render(<InsightPanel text="上半年上涨明显。" facts={[]} format={CURRENCY} />);
    expect(screen.getByTestId("insight-text").textContent).toBe("上半年上涨明显。");
  });

  it("计算依据逐条列出,数值已格式化", () => {
    render(<InsightPanel text="x" facts={facts} format={CURRENCY} />);
    expect(screen.getByText(/计算依据（2 项）/)).toBeTruthy();
    expect(screen.getByText(/上涨 23\.4%/)).toBeTruthy();
    expect(screen.getByText(/128,400 元/)).toBeTruthy();
  });

  it("没有事实时不渲染计算依据折叠", () => {
    render(<InsightPanel text="x" facts={[]} format={CURRENCY} />);
    expect(screen.queryByText(/计算依据/)).toBeNull();
  });

  it("既无文本又无事实时整块不渲染", () => {
    const { container } = render(<InsightPanel text="" facts={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("不传 format 时按普通数值渲染,不崩", () => {
    render(<InsightPanel text="x" facts={[{ kind: "total", series: "s", value: 1234 }]} />);
    expect(screen.getByText(/1,234/)).toBeTruthy();
  });
});
```

- [ ] **Step 3: 跑测试确认失败**

Run: `npx vitest --root apps/frontend run src/__tests__/ResultCard.test.tsx src/__tests__/InsightPanel.test.tsx`
Expected: FAIL，`Failed to resolve import "../components/InsightPanel"`,以及 `ResultCard` 收到的 props 与旧签名不符

- [ ] **Step 4: 创建 `apps/frontend/src/components/InsightPanel.tsx`**

```tsx
import type { InsightFact, ValueFormat } from "@chatbi/shared";
import { renderFactsLines } from "@chatbi/shared";

const DEFAULT_FORMAT: ValueFormat = { kind: "number", decimals: 0, scale: 1 };

export function InsightPanel({ text, facts, format }: {
  text: string; facts: InsightFact[]; format?: ValueFormat;
}) {
  if (!text && facts.length === 0) return null;
  const lines = renderFactsLines(facts, format ?? DEFAULT_FORMAT).filter(Boolean);
  return (
    <section>
      <h3>洞察</h3>
      <p data-testid="insight-text" style={{ whiteSpace: "pre-wrap" }}>{text}</p>
      {lines.length > 0 && (
        <details>
          <summary>计算依据（{lines.length} 项）</summary>
          <ul>{lines.map(l => <li key={l}>{l}</li>)}</ul>
        </details>
      )}
    </section>
  );
}
```

- [ ] **Step 5: 全量替换 `apps/frontend/src/components/ResultCard.tsx`**

```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import type { ChartType, InsightFact, ResultPayload } from "@chatbi/shared";
import { specToEchartsOption } from "@chatbi/shared";
import { InsightPanel } from "./InsightPanel";

// P1a 临时色板:先用 ECharts 默认色序,P1b 换成 theme/chartPalette 的可访问色板。
const PALETTE = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272", "#fc8452", "#9a60b4"];
const TYPES: ChartType[] = ["bar", "line", "pie", "table"];
const MAX_TABLE_ROWS = 100;

export function ResultCard({ payload, insight, facts }: {
  payload: ResultPayload; insight: string; facts: InsightFact[];
}) {
  const [type, setType] = useState<ChartType>(payload.spec.chartType);
  const ref = useRef<HTMLDivElement>(null);

  // 切类型不重算数据,只覆盖 chartType;stack 只对 bar 有意义。
  const option = useMemo(() => specToEchartsOption({
    ...payload.spec,
    chartType: type,
    stack: type === "bar" ? payload.spec.stack : "none",
  }, PALETTE), [payload.spec, type]);

  useEffect(() => {
    if (type === "table" || !ref.current) return;
    let chart: echarts.ECharts | undefined;
    try {
      chart = echarts.init(ref.current);
      chart.setOption(option as echarts.EChartsOption, true);
    } catch { /* jsdom 无 canvas:忽略 */ }
    return () => {
      try { chart?.dispose(); } catch { /* jsdom 无 canvas:忽略 */ }
    };
  }, [type, option]);

  const shown = payload.table.rows.slice(0, MAX_TABLE_ROWS);
  const hidden = payload.table.rows.length - shown.length;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        {TYPES.map(t => (
          <button key={t} aria-pressed={type === t} onClick={() => setType(t)}>{t}</button>
        ))}
      </div>

      {type !== "table" && <div ref={ref} style={{ width: "100%", height: 320 }} data-testid="chart" />}

      {payload.spec.notes.map(n => (
        <p key={n} data-testid="note" style={{ fontSize: 12 }}>ⓘ {n}</p>
      ))}

      <details>
        <summary>查看 SQL</summary>
        <pre style={{ whiteSpace: "pre-wrap" }}>{payload.sql}</pre>
      </details>

      <InsightPanel text={insight} facts={facts} format={payload.spec.series[0]?.format} />

      <details open={payload.table.rows.length <= 20}>
        <summary>
          数据表格（{payload.table.rows.length} 行 × {payload.table.columns.length} 列）
        </summary>
        <table>
          <thead><tr>{payload.table.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i}>{payload.table.columns.map(c => <td key={c}>{String(r[c])}</td>)}</tr>
            ))}
          </tbody>
        </table>
        {hidden > 0 && (
          <p style={{ fontSize: 12 }}>仅显示前 {MAX_TABLE_ROWS} 行,另有 {hidden} 行未展示</p>
        )}
      </details>
    </div>
  );
}
```

- [ ] **Step 6: 全量替换 `apps/frontend/src/components/MessageBubble.tsx`**

```tsx
import type { InsightFact, ResultPayload } from "@chatbi/shared";
import { ResultCard } from "./ResultCard";

export interface Message {
  id: string;
  role: "user" | "assistant";
  /** 用户提问,或助手侧的错误提示。查询意图走 payload.queryIntent。 */
  text: string;
  payload?: ResultPayload;
  facts?: InsightFact[];
  insight?: string;
}

export function MessageBubble({ message }: { message: Message }) {
  return (
    <div style={{
      margin: "8px 0",
      alignSelf: message.role === "user" ? "flex-end" : "flex-start",
      maxWidth: "80%",
    }}>
      {message.payload && (
        <div style={{ whiteSpace: "pre-wrap" }}>{message.payload.queryIntent}</div>
      )}
      {message.text && (
        <div style={{ fontWeight: message.role === "user" ? 600 : 400, whiteSpace: "pre-wrap" }}>
          {message.text}
        </div>
      )}
      {message.payload && (
        <ResultCard
          payload={message.payload}
          insight={message.insight ?? ""}
          facts={message.facts ?? []}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 7: 跑测试确认通过**

Run: `npx vitest --root apps/frontend run src/__tests__/ResultCard.test.tsx src/__tests__/InsightPanel.test.tsx`
Expected: PASS。`ChatWindow.test.tsx` 此时仍会失败(它推的还是旧事件),Task 15 处理。

- [ ] **Step 8: 提交**

```bash
git add apps/frontend/src/components/ResultCard.tsx apps/frontend/src/components/InsightPanel.tsx \
  apps/frontend/src/components/MessageBubble.tsx apps/frontend/src/__tests__/ResultCard.test.tsx \
  apps/frontend/src/__tests__/InsightPanel.test.tsx
git commit -m "feat(frontend): render charts via shared renderer, add insight panel"
```

### Task 15: ChatWindow —— id 定位、下钻上下文、修索引 bug

**Files:**
- Modify: `apps/frontend/src/components/ChatWindow.tsx`(全量替换,现有 46 行)
- Modify: `apps/frontend/src/__tests__/ChatWindow.test.tsx`(全量替换)

**Interfaces:**
- Consumes: Task 13 的 `streamChat`、Task 14 的 `Message` / `MessageBubble`
- Produces: `ChatWindow()` —— 无 props

**修掉的 bug**:MVP 用 `const assistantIdx = messages.length + 1` 从闭包里的旧 `messages` 算下标,再用 `n[assistantIdx] = ...` 写数组。只要 `messages` 在这次 `send` 之后被别的路径改动过(错误追加、多轮累积),下标就会指错气泡。改成**每条消息带 `id`,全部用 `setMessages(prev => prev.map(...))` 按 id 定位**。

**下钻上下文从消息列表里现取**:向后找最近一条带 `payload` 的助手消息,取它的 `sql` 与 `table.columns`。不单独维护一份 `lastSql` state,避免两处状态不同步。

**输入框 placeholder 随上下文变化**,所以测试统一用 `getByRole("textbox")` 定位,不再用 placeholder 文案。

- [ ] **Step 1: 全量替换 `apps/frontend/src/__tests__/ChatWindow.test.tsx`**

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ChatWindow } from "../components/ChatWindow";
import { streamChat } from "../api";
import type { ResultPayload, StreamEvent } from "@chatbi/shared";

vi.mock("../api", () => ({ streamChat: vi.fn() }));

/** 每次调用记录 opts,并把 onEvent 存下来由测试驱动。 */
let calls: any[] = [];
let resolvers: (() => void)[] = [];

beforeEach(() => {
  calls = [];
  resolvers = [];
  vi.mocked(streamChat).mockImplementation((opts: any) => {
    calls.push(opts);
    return new Promise<void>(res => resolvers.push(res));
  });
});

const CURRENCY = { kind: "currency" as const, decimals: 0, unit: "元", scale: 1 as const };

const payload = (queryIntent: string, sql: string): ResultPayload => ({
  spec: {
    chartType: "bar", stack: "none",
    x: { field: "region", role: "categorical", labels: ["华东"] },
    series: [{ name: "total", field: "total", data: [100], format: CURRENCY }],
    notes: [],
  },
  table: { columns: ["region", "total"], rows: [{ region: "华东", total: 100 }] },
  queryIntent, sql,
});

const ask = (text: string) => {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /发送/ }));
};

const drive = (i: number, events: StreamEvent[]) => act(() => {
  for (const e of events) calls[i].onEvent(e);
});

const finish = (i: number) => act(async () => { resolvers[i](); });

describe("ChatWindow 单轮", () => {
  it("提交后显示用户问题", async () => {
    render(<ChatWindow />);
    ask("各地区销售额");
    await waitFor(() => expect(screen.getByText("各地区销售额")).toBeTruthy());
  });

  it("result → 表格,insightDelta → 洞察文本", async () => {
    render(<ChatWindow />);
    ask("各地区销售额");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [
      { type: "result", payload: payload("按地区汇总", "SELECT region FROM orders") },
      { type: "insightFacts", facts: [{ kind: "total", series: "total", value: 100 }] },
      { type: "insightDelta", text: "华东" },
      { type: "insightDelta", text: "区领先。" },
      { type: "done" },
    ]);
    await waitFor(() => expect(screen.getByText("按地区汇总")).toBeTruthy());
    expect(screen.getByText("华东", { selector: "td" })).toBeTruthy();
    expect(screen.getByTestId("insight-text").textContent).toBe("华东区领先。");
  });

  it("error 事件渲染成文本,不吞掉整轮", async () => {
    render(<ChatWindow />);
    ask("q");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [{ type: "error", message: "Ollama 未运行" }]);
    await waitFor(() => expect(screen.getByText(/\[错误\] Ollama 未运行/)).toBeTruthy());
  });
});

describe("ChatWindow 多轮与下钻", () => {
  it("第二轮带上第一轮的 sql 作为 context", async () => {
    render(<ChatWindow />);
    ask("按月统计订单金额");
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].context).toBeUndefined();
    drive(0, [
      { type: "result", payload: payload("统计每月订单总额", "SELECT month, SUM(x) AS amount FROM orders GROUP BY month") },
      { type: "done" },
    ]);
    await finish(0);

    ask("只看华东区");
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].context).toEqual({
      lastSql: "SELECT month, SUM(x) AS amount FROM orders GROUP BY month",
      lastColumns: ["region", "total"],
    });
  });

  it("history 里助手侧用的是 queryIntent", async () => {
    render(<ChatWindow />);
    ask("q1");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [{ type: "result", payload: payload("意图一", "SELECT 1") }, { type: "done" }]);
    await finish(0);
    ask("q2");
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].history).toEqual([
      { role: "user", text: "q1" },
      { role: "assistant", text: "意图一" },
    ]);
  });

  it("两轮的事件各自只更新自己的气泡", async () => {
    render(<ChatWindow />);
    ask("q1");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [
      { type: "result", payload: payload("意图一", "SELECT 1") },
      { type: "insightDelta", text: "洞察一" },
      { type: "done" },
    ]);
    await finish(0);

    ask("q2");
    await waitFor(() => expect(calls).toHaveLength(2));
    drive(1, [
      { type: "result", payload: payload("意图二", "SELECT 2") },
      { type: "insightDelta", text: "洞察二" },
      { type: "done" },
    ]);
    await waitFor(() => expect(screen.getByText("意图二")).toBeTruthy());

    const texts = screen.getAllByTestId("insight-text").map(n => n.textContent);
    expect(texts).toEqual(["洞察一", "洞察二"]);
    expect(screen.getByText("意图一")).toBeTruthy();
  });

  it("上一轮未结束时发送被忽略", async () => {
    render(<ChatWindow />);
    ask("q1");
    await waitFor(() => expect(calls).toHaveLength(1));
    ask("q2");
    expect(calls).toHaveLength(1);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/frontend run src/__tests__/ChatWindow.test.tsx`
Expected: FAIL，`calls[0].context` 相关断言与 `insight-text` 断言都不通过

- [ ] **Step 3: 全量替换 `apps/frontend/src/components/ChatWindow.tsx`**

```tsx
import { useState } from "react";
import type { ChatTurn, DrillContext, StreamEvent } from "@chatbi/shared";
import { streamChat } from "../api";
import { MessageBubble, type Message } from "./MessageBubble";

let seq = 0;
const nextId = () => `m${++seq}`;

export function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  /** 向后找最近一条带结果的助手消息,作为下钻上下文。 */
  const drillContext = (): DrillContext | undefined => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const p = messages[i].payload;
      if (p) return { lastSql: p.sql, lastColumns: p.table.columns };
    }
    return undefined;
  };

  const send = () => {
    if (!input.trim() || busy) return;
    const question = input;
    const userId = nextId();
    const assistantId = nextId();
    const context = drillContext();
    const history: ChatTurn[] = messages.map(m => ({
      role: m.role,
      text: m.role === "assistant" ? (m.payload?.queryIntent ?? m.text) : m.text,
    }));

    setInput("");
    setBusy(true);
    setMessages(prev => [
      ...prev,
      { id: userId, role: "user", text: question },
      { id: assistantId, role: "assistant", text: "" },
    ]);

    const patch = (fn: (m: Message) => Message) =>
      setMessages(prev => prev.map(m => (m.id === assistantId ? fn(m) : m)));

    streamChat({
      question, history, context,
      onEvent: (e: StreamEvent) => {
        if (e.type === "result") patch(m => ({ ...m, payload: e.payload }));
        else if (e.type === "insightFacts") patch(m => ({ ...m, facts: e.facts }));
        else if (e.type === "insightDelta") patch(m => ({ ...m, insight: (m.insight ?? "") + e.text }));
        else if (e.type === "error") patch(m => ({ ...m, text: `${m.text}\n[错误] ${e.message}`.trim() }));
      },
    }).finally(() => setBusy(false));
  };

  const hasContext = messages.some(m => m.payload);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", maxWidth: 900, margin: "0 auto" }}>
      <h1>Chat-BI</h1>
      <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
        {messages.map(m => <MessageBubble key={m.id} message={m} />)}
      </div>
      <div style={{ display: "flex", gap: 8, padding: 8 }}>
        <input
          value={input}
          placeholder={hasContext ? "继续追问，例如「只看华东区」" : "输入问题，例如「按月统计订单金额」"}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
          style={{ flex: 1 }}
        />
        <button onClick={send} disabled={busy}>发送</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest --root apps/frontend run`
Expected: PASS(api / ResultCard / InsightPanel / ChatWindow 四个测试文件全绿)

- [ ] **Step 5: 提交**

```bash
git add apps/frontend/src/components/ChatWindow.tsx apps/frontend/src/__tests__/ChatWindow.test.tsx
git commit -m "fix(frontend): id-based message updates and drill-down context wiring"
```

### Task 16: 端到端验收 + README 收尾

**Files:**
- Modify: `apps/backend/tests/acceptance.pipeline.test.ts`(全量替换,现有 88 行断言的是 `echartsOption` / `explanation`)
- Modify: `README.md`(配置表新增 `INSIGHT_TIMEOUT_MS`;手动验收清单从 4 条扩到 9 条;新增「已知限制」)

**Interfaces:**
- Consumes: 前面全部任务
- Produces: 无新接口。这是 P1a 的收口任务,跑通全量测试 + 更新文档。

- [ ] **Step 1: 全量替换 `apps/backend/tests/acceptance.pipeline.test.ts`**

```ts
/**
 * 用真实示例库 + stub LLM 跑验收清单的场景。
 * 覆盖 migrate 数据 → sqlGuard → dbClient → chartSpec → facts → insightWriter 的真实链路,
 * 但不代替 README 的人工验收(那一步要验 LLM 自己选的 SQL、hint 与措辞)。
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { DbClient } from "../src/dbClient";
import { migrate } from "../src/migrate";
import { handleChat } from "../src/chatService";
import type { ChartHint, StreamEvent } from "@chatbi/shared";

const tmpDir = join(process.cwd(), ".tmp-acceptance");
const dbPath = join(tmpDir, "a.db");
let db: DbClient;

beforeAll(() => {
  mkdirSync(tmpDir, { recursive: true });
  const writable = new DbClient(dbPath);
  migrate(writable);
  writable.close();
  db = new DbClient(dbPath, { readonly: true });
});
afterAll(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

async function ask(sql: string, hint: Partial<ChartHint>, explanation: string) {
  const raw = JSON.stringify({
    sql, explanation, chartType: "table", dimensions: [], measures: [], ...hint,
  });
  const deps = {
    db: {
      getSchema: () => db.getSchema(),
      runQuery: (s: string, limit: number) => db.runQuery(s, limit),
    },
    llm: {
      chatStream: async function* (prompt: string) {
        // 第一轮出 JSON,第二轮(洞察)出散文——用 prompt 里的标志区分。
        yield prompt.includes("请用 2-3 句中文") ? "整体表现如上。" : raw;
      },
    },
  };
  const events: StreamEvent[] = [];
  for await (const e of handleChat({ question: explanation, history: [], deps })) events.push(e);
  return events;
}

const resultOf = (events: StreamEvent[]) => events.find(e => e.type === "result") as any;
const factsOf = (events: StreamEvent[]) => (events.find(e => e.type === "insightFacts") as any)?.facts ?? [];
const insightOf = (events: StreamEvent[]) =>
  events.filter(e => e.type === "insightDelta").map((e: any) => e.text).join("");

describe("验收场景(真实示例库 + stub LLM)", () => {
  it("1. 按月统计订单金额 → line + 时间轴 + 趋势事实", async () => {
    const events = await ask(
      "SELECT substr(order_date,1,7) AS month, SUM(total_amount) AS amount FROM orders GROUP BY month ORDER BY month",
      { chartType: "line", dimensions: ["month"], measures: ["amount"] },
      "按月统计订单金额",
    );
    const spec = resultOf(events).payload.spec;
    expect(spec.chartType).toBe("line");
    expect(spec.x.role).toBe("temporal");
    expect(spec.x.grain).toBe("month");
    expect(spec.series).toHaveLength(1);
    expect(factsOf(events).map((f: any) => f.kind)).toContain("trend");
    expect(insightOf(events)).toBe("整体表现如上。");
  });

  it("2. 各产品类别销售额占比 → pie + 占比事实", async () => {
    const events = await ask(
      "SELECT p.category AS category, SUM(oi.quantity * oi.unit_price) AS amount FROM order_items oi "
      + "JOIN products p ON p.product_id = oi.product_id GROUP BY p.category",
      { chartType: "pie", dimensions: ["category"], measures: ["amount"] },
      "各产品类别销售额占比",
    );
    const spec = resultOf(events).payload.spec;
    expect(spec.chartType).toBe("pie");
    expect(spec.x.labels.length).toBeGreaterThan(1);
    expect(spec.series[0].data.every((v: number) => Number.isFinite(v))).toBe(true);
    expect(factsOf(events).map((f: any) => f.kind)).toContain("topShare");
  });

  it("3. 各地区订单总额对比 → bar,轴与表格行数一致", async () => {
    const events = await ask(
      "SELECT c.region AS region, SUM(o.total_amount) AS amount FROM orders o "
      + "JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.region ORDER BY amount DESC",
      { chartType: "bar", dimensions: ["region"], measures: ["amount"] },
      "各地区订单总额对比",
    );
    const r = resultOf(events);
    expect(r.payload.spec.chartType).toBe("bar");
    expect(r.payload.spec.x.labels).toHaveLength(r.payload.table.rows.length);
  });

  it("4. 按月看各区域销售额 → 多系列", async () => {
    const events = await ask(
      "SELECT substr(o.order_date,1,7) AS month, c.region AS region, SUM(o.total_amount) AS amount "
      + "FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY month, region ORDER BY month",
      { chartType: "line", dimensions: ["month"], measures: ["amount"], seriesBy: "region" },
      "按月看各区域销售额",
    );
    const spec = resultOf(events).payload.spec;
    expect(spec.series.length).toBeGreaterThan(1);
    expect(spec.series.every((s: any) => s.data.length === spec.x.labels.length)).toBe(true);
  });

  it("5. 百分比堆叠 → stack 生效", async () => {
    const events = await ask(
      "SELECT c.region AS region, p.category AS category, SUM(oi.quantity * oi.unit_price) AS amount "
      + "FROM order_items oi JOIN products p ON p.product_id = oi.product_id "
      + "JOIN orders o ON o.order_id = oi.order_id JOIN customers c ON c.customer_id = o.customer_id "
      + "GROUP BY region, category",
      { chartType: "bar", dimensions: ["region"], measures: ["amount"], seriesBy: "category", stack: "percent" },
      "各区域各类别销售额占比结构",
    );
    expect(resultOf(events).payload.spec.stack).toBe("percent");
  });

  it("6. 查询 1999 年的订单 → 空结果不报错,洞察为固定文案", async () => {
    const events = await ask(
      "SELECT order_id, order_date, total_amount FROM orders WHERE order_date LIKE '1999%'",
      { chartType: "table" },
      "1999 年没有订单记录",
    );
    const r = resultOf(events);
    expect(events.some(e => e.type === "error")).toBe(false);
    expect(r.payload.table.rows).toEqual([]);
    expect(r.payload.spec.chartType).toBe("table");
    expect(r.payload.queryIntent).toBe("1999 年没有订单记录");
    expect(insightOf(events)).toBe("没有符合条件的记录。");
  });

  it("7. 事件序列以 done 结尾", async () => {
    const events = await ask(
      "SELECT c.region AS region, SUM(o.total_amount) AS amount FROM orders o "
      + "JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.region",
      { chartType: "bar", dimensions: ["region"], measures: ["amount"] },
      "各地区订单总额",
    );
    expect(events[0].type).toBe("result");
    expect(events[1].type).toBe("insightFacts");
    expect(events[events.length - 1].type).toBe("done");
  });

  it("8. 写操作被拦截,示例库不被改动", async () => {
    const before = db.runQuery("SELECT COUNT(*) AS n FROM orders", 10).rows[0].n;
    const events = await ask("DELETE FROM orders", { chartType: "table" }, "删掉订单");
    expect((events.find(e => e.type === "error") as any).message).toMatch(/拦截/);
    expect(db.runQuery("SELECT COUNT(*) AS n FROM orders", 10).rows[0].n).toBe(before);
  });

  it("9. 只读连接下写操作在引擎层被拒", async () => {
    expect(() => db.execRaw("DELETE FROM orders")).toThrow(/readonly|read-only/i);
  });
});
```

- [ ] **Step 2: 跑全量测试**

```bash
npx vitest --root packages/shared run
npx vitest --root apps/backend run
npx vitest --root apps/frontend run
```

Expected: 三处全绿。若 `chat.route.test.ts` 还没在 Task 12 改完,这里补上。

- [ ] **Step 3: 类型检查**

```bash
npm run build --workspaces --if-present
```

Expected: 无 TS 错误。若报 `chartAssembler` 找不到,说明 Task 6 删文件后有残留 import。

- [ ] **Step 4: 更新 README**

配置表加一行:

```
| `INSIGHT_TIMEOUT_MS` | `8000` | 洞察生成(第二轮 LLM)超时,超时降级为模板文本 |
```

手动验收清单替换为 9 条:

```markdown
## 手动验收清单

发版前依次问,人工确认图表类型、数据与洞察:

1. 「按月统计订单金额」→ 折线图,x 轴按月排序,洞察提到趋势百分比
2. 「各产品类别销售额占比」→ 饼图,洞察提到头部占比
3. 「各地区订单总额对比」→ 柱状图
4. 「按月看各区域销售额」→ 多条折线,图例是区域名
5. 「各区域各类别销售额占比结构」→ 百分比堆叠柱状图,y 轴 0–100%
6. 三轮下钻:「按月统计订单金额」→「只看华东区」→「按周看」,每轮图表都正确变化
7. 「查询 1999 年的订单」→ 空表格 + 洞察「没有符合条件的记录」
8. 关掉 Ollama 后再问一次 → 图表仍渲染,洞察降级为模板文本(验证第二轮失败不影响第一轮)
9. 任意一轮展开「查看 SQL」与「计算依据」,核对 SQL 与洞察里的数字一致
```

「特性」小节里把「流式返回」那条改成:

```markdown
- **图表先落地,洞察后写**:结果与图表一次性下发立刻渲染,洞察文本由第二轮 LLM 真流式逐字写出;第二轮失败只降级洞察,不影响图表。
```

新增「已知限制」小节,把 Task 9 Step 6 实测到的 `node-sql-parser` 解析情况写进去:

```markdown
## 已知限制

- SQL 校验以只读数据库连接为根本防线;AST 校验(`node-sql-parser`,sqlite 方言)解析失败时回退到加固正则。<在此填入 Task 9 Step 6 的实测结论:哪类语法走了回退,或「示例库的全部验收查询均走 AST 路径」>
- 洞察文本由 LLM 措辞,数字由后端纯函数计算。若怀疑措辞与数字不符,展开「计算依据」核对。
- `seriesBy` 取值超过 12 个时自动退化为单系列,并在图表下方标注。
```

- [ ] **Step 5: 提交**

```bash
git add apps/backend/tests/acceptance.pipeline.test.ts README.md
git commit -m "test(backend): P1 acceptance pipeline over real sample db; docs: update README"
```

- [ ] **Step 6: P1a 完成确认**

逐项确认后再交给 P1b:

- `npx vitest --root packages/shared run && npx vitest --root apps/backend run && npx vitest --root apps/frontend run` 全绿
- `npm run build --workspaces --if-present` 无错
- `git grep -n chartAssembler` 无结果
- `git grep -n explanationDelta` 无结果
- `git grep -n ChartPayload` 无结果
- `git grep -n echartsOption -- apps` 只在 `packages/shared/src/renderer.ts` 之外无命中(前端不再自己拼 option)
- 手动跑一次真实链路:`ollama serve` + 启后端前端,按验收清单第 1、4、6、8 条各问一遍
