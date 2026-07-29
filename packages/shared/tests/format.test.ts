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
