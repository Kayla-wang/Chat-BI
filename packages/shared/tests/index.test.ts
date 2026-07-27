import { describe, it, expect } from "vitest";
import type {
  Row, TableSchema, ChartType, ChartPayload, StreamEvent, ChatTurn,
} from "../src/index";

describe("shared types", () => {
  it("Row is a string-keyed record of primitives", () => {
    const r: Row = { id: 1, name: "x" };
    expect(r.name).toBe("x");
  });

  it("ChartType union has 4 members", () => {
    const c: ChartType[] = ["bar", "line", "pie", "table"];
    expect(c).toHaveLength(4);
  });

  it("ChartPayload shape compiles", (): ChartPayload => ({
    chartType: "bar",
    echartsOption: { xAxis: { type: "category", data: ["a"] }, series: [{ type: "bar", data: [1] }] },
    table: { columns: ["a"], rows: [{ a: 1 }] },
    explanation: "ok",
  }));

  it("StreamEvent is a discriminated union", () => {
    const a: StreamEvent = { type: "explanationDelta", text: "x" };
    const b: StreamEvent = { type: "result", payload: {} as ChartPayload };
    const c: StreamEvent = { type: "error", message: "bad", raw: "raw" };
    expect(a.type).toBe("explanationDelta");
    expect(b.type).toBe("result");
    expect(c.type).toBe("error");
  });

  it("ChatTurn shape compiles", (): ChatTurn => ({ role: "user", text: "q" }));
});
