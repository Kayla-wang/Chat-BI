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
