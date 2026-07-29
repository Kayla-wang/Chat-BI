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
