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
