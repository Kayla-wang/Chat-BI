import { describe, it, expect } from "vitest";
import { buildPrompt } from "../src/promptBuilder";
import type { TableSchema, ChatTurn } from "@chatbi/shared";

const schema: TableSchema[] = [{
  tableName: "orders",
  columns: [
    { name: "id", type: "INTEGER", notNull: true, pk: true },
    { name: "amount", type: "REAL", notNull: false, pk: false },
  ],
  foreignKeys: [{ column: "cust_id", refTable: "customers", refColumn: "id" }],
}];

describe("buildPrompt", () => {
  it("injects schema table/column names", () => {
    const p = buildPrompt({ question: "orders 总额", schema, history: [] });
    expect(p).toContain("orders");
    expect(p).toContain("amount");
    expect(p).toContain("cust_id");
  });
  it("includes the user question verbatim", () => {
    const p = buildPrompt({ question: "各地区上季度销售额", schema, history: [] });
    expect(p).toContain("各地区上季度销售额");
  });
  it("truncates history to the last 4 messages (2 full rounds)", () => {
    const history: ChatTurn[] = [
      { role: "user", text: "q1" }, { role: "assistant", text: "a1" },
      { role: "user", text: "q2" }, { role: "assistant", text: "a2" },
      { role: "user", text: "q3" }, { role: "assistant", text: "a3" },
      { role: "user", text: "q4" }, { role: "assistant", text: "a4" },
    ];
    const p = buildPrompt({ question: "q5", schema, history });
    expect(p).toContain("q3"); expect(p).toContain("q4");
    expect(p).not.toContain("q1"); expect(p).not.toContain("q2");
  });
  it("demands strict JSON output with sql/chartType/explanation", () => {
    const p = buildPrompt({ question: "x", schema, history: [] });
    expect(p).toMatch(/strict.*JSON|"sql"/i);
    expect(p).toMatch(/chartType/);
    expect(p).toMatch(/explanation/);
  });
  it("lists chartType allowed values", () => {
    const p = buildPrompt({ question: "x", schema, history: [] });
    expect(p).toMatch(/bar|line|pie|table/);
  });
});
