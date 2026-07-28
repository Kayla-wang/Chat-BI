import { describe, it, expect } from "vitest";
import { assemble } from "../src/chartAssembler";
import type { Row } from "@chatbi/shared";

const rows: Row[] = [
  { region: "east", total: 100 },
  { region: "west", total: 200 },
];
const columns = ["region", "total"];

describe("assemble bar", () => {
  const p = assemble({ rows, chartType: "bar", columns, explanation: "ex" });
  it("echoes chartType + table + explanation", () => {
    expect(p.chartType).toBe("bar");
    expect(p.explanation).toBe("ex");
    expect(p.table.columns).toEqual(columns);
    expect(p.table.rows).toEqual(rows);
  });
  it("sets xAxis category from column[0] and series from column[1]", () => {
    const opt = p.echartsOption as any;
    expect(opt.xAxis.data).toEqual(["east", "west"]);
    expect(opt.series[0].type).toBe("bar");
    expect(opt.series[0].data).toEqual([100, 200]);
  });
});

describe("assemble line", () => {
  const p = assemble({ rows, chartType: "line", columns, explanation: "" });
  it("uses line series type", () => {
    expect((p.echartsOption as any).series[0].type).toBe("line");
  });
});

describe("assemble pie", () => {
  const p = assemble({ rows, chartType: "pie", columns, explanation: "" });
  it("produces pie series with name/value pairs", () => {
    const opt = p.echartsOption as any;
    expect(opt.series[0].type).toBe("pie");
    expect(opt.series[0].data).toEqual([{ name: "east", value: 100 }, { name: "west", value: 200 }]);
  });
});

describe("assemble table", () => {
  const p = assemble({ rows, chartType: "table", columns, explanation: "" });
  it("has no series/xAxis (pure table)", () => {
    expect((p.echartsOption as any).series).toBeUndefined();
  });
});

describe("assemble empty rows", () => {
  it("still returns a table payload without throwing", () => {
    const p = assemble({ rows: [], chartType: "table", columns: ["a"], explanation: "无记录" });
    expect(p.table.rows).toEqual([]);
    expect(p.explanation).toBe("无记录");
  });
});
