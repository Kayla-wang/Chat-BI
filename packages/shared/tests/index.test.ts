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
