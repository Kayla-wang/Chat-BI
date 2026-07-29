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
