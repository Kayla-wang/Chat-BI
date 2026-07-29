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
