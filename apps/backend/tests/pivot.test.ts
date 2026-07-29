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
