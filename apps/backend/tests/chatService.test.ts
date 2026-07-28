import { describe, it, expect, vi } from "vitest";
import { handleChat } from "../src/chatService";
import type { TableSchema, StreamEvent } from "@chatbi/shared";

const schema: TableSchema[] = [{
  tableName: "orders",
  columns: [
    { name: "region", type: "TEXT", notNull: false, pk: false },
    { name: "total", type: "REAL", notNull: false, pk: false },
  ],
  foreignKeys: [],
}];

function mockDeps(llmChunks: string[], rows: any[]) {
  return {
    db: {
      getSchema: () => schema,
      runQuery: vi.fn(() => rows),
    },
    llm: { chatStream: async function* () { for (const c of llmChunks) yield c; } },
  };
}

async function collect(it: AsyncIterable<StreamEvent>): Promise<StreamEvent[]> {
  const out: StreamEvent[] = [];
  for await (const e of it) out.push(e);
  return out;
}

describe("handleChat happy path", () => {
  it("streams explanation deltas then a result", async () => {
    const json = JSON.stringify({ sql: "SELECT region, SUM(total) total FROM orders GROUP BY region", chartType: "bar", explanation: "按地区汇总" });
    const deps = mockDeps([json], [{ region: "east", total: 100 }]);
    const events = await collect(handleChat({ question: "各地区销售额", history: [], deps }));
    const deltas = events.filter(e => e.type === "explanationDelta");
    const result = events.find(e => e.type === "result")!;
    expect(deltas.length).toBeGreaterThan(0);
    expect(deltas.map(d => (d as any).text).join("")).toBe("按地区汇总");
    expect(result).toBeTruthy();
    expect((result as any).payload.chartType).toBe("bar");
    expect((result as any).payload.table.rows).toEqual([{ region: "east", total: 100 }]);
  });
});

describe("handleChat JSON parse failure → retry once", () => {
  it("retries once then errors if still bad", async () => {
    const deps = mockDeps(["not json at all"], []);
    const events = await collect(handleChat({ question: "q", history: [], deps }));
    const err = events.find(e => e.type === "error") as any;
    expect(err).toBeTruthy();
    expect(err.message).toMatch(/json|parse/i);
  });
  it("recovers on second attempt", async () => {
    // 第一次坏,第二次好
    let first = true;
    const deps = {
      db: { getSchema: () => schema, runQuery: vi.fn(() => [{ region: "east", total: 1 }]) },
      llm: { chatStream: async function* () { yield first ? "garbage" : JSON.stringify({ sql: "SELECT region,total FROM orders", chartType: "bar", explanation: "ok" }); first = false; } },
    };
    const events = await collect(handleChat({ question: "q", history: [], deps }));
    expect(events.some(e => e.type === "result")).toBe(true);
  });
});

describe("handleChat SQL validation failure", () => {
  it("errors on non-readonly sql", async () => {
    const json = JSON.stringify({ sql: "DELETE FROM orders", chartType: "table", explanation: "x" });
    const deps = mockDeps([json], []);
    const events = await collect(handleChat({ question: "q", history: [], deps }));
    const err = events.find(e => e.type === "error") as any;
    expect(err.message).toMatch(/read-only|readonly|拦截|not allowed/i);
  });
});

describe("handleChat SQL execution failure → retry once", () => {
  it("errors when runQuery throws", async () => {
    const json = JSON.stringify({ sql: "SELECT bad FROM orders", chartType: "table", explanation: "x" });
    const deps = {
      db: { getSchema: () => schema, runQuery: vi.fn(() => { throw new Error("no such column: bad"); }) },
      llm: { chatStream: async function* () { yield json; } },
    };
    const events = await collect(handleChat({ question: "q", history: [], deps }));
    expect(events.some(e => e.type === "error")).toBe(true);
  });
});

describe("handleChat empty result", () => {
  it("returns table result with explanation", async () => {
    const json = JSON.stringify({ sql: "SELECT region,total FROM orders WHERE 1=0", chartType: "table", explanation: "无记录" });
    const deps = mockDeps([json], []);
    const events = await collect(handleChat({ question: "q", history: [], deps }));
    const result = events.find(e => e.type === "result") as any;
    expect(result.payload.table.rows).toEqual([]);
    expect(result.payload.explanation).toBe("无记录");
  });
});
