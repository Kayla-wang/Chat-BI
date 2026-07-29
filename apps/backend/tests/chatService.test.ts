import { describe, it, expect, vi } from "vitest";
import { handleChat } from "../src/chatService";
import type { TableSchema, StreamEvent, Row } from "@chatbi/shared";

const schema: TableSchema[] = [{
  tableName: "orders",
  columns: [
    { name: "region", type: "TEXT", notNull: false, pk: false },
    { name: "total", type: "REAL", notNull: false, pk: false },
  ],
  foreignKeys: [],
}];

const llmJson = (over: Record<string, unknown> = {}) => JSON.stringify({
  sql: "SELECT region, SUM(total) AS total FROM orders GROUP BY region",
  explanation: "按地区汇总",
  chartType: "bar",
  dimensions: ["region"],
  measures: ["total"],
  ...over,
});

/** 按顺序返回预设回复;记录每次收到的 prompt。 */
function queuedLlm(replies: (string | Error)[]) {
  const prompts: string[] = [];
  let i = 0;
  return {
    prompts,
    calls: () => i,
    chatStream: async function* (prompt: string) {
      prompts.push(prompt);
      const r = replies[Math.min(i++, replies.length - 1)];
      if (r instanceof Error) throw r;
      yield r;
    },
  };
}

function deps(llm: any, rows: Row[], truncated = false) {
  return {
    db: { getSchema: () => schema, runQuery: vi.fn(() => ({ rows, truncated })) },
    llm,
  };
}

async function collect(it: AsyncIterable<StreamEvent>): Promise<StreamEvent[]> {
  const out: StreamEvent[] = [];
  for await (const e of it) out.push(e);
  return out;
}

describe("handleChat 正常路径", () => {
  it("事件序列为 result → insightFacts → insightDelta* → done", async () => {
    const llm = queuedLlm([llmJson(), "华东区领先。"]);
    const events = await collect(handleChat({
      question: "各地区销售额", history: [],
      deps: deps(llm, [{ region: "华东", total: 412 }, { region: "华北", total: 588 }]),
    }));
    expect(events.map(e => e.type)).toEqual([
      "result", "insightFacts", "insightDelta", "done",
    ]);
  });

  it("result 带 spec / table / queryIntent / sql", async () => {
    const llm = queuedLlm([llmJson(), "文本"]);
    const events = await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 412 }]),
    }));
    const r = events.find(e => e.type === "result") as any;
    expect(r.payload.spec.chartType).toBe("bar");
    expect(r.payload.spec.series[0].data).toEqual([412]);
    expect(r.payload.table.columns).toEqual(["region", "total"]);
    expect(r.payload.queryIntent).toBe("按地区汇总");
    expect(r.payload.sql).toContain("GROUP BY region");
    expect(r.payload.sql).not.toContain("LIMIT");
  });

  it("洞察文本逐 token 透传", async () => {
    const llm = queuedLlm([llmJson(), "华东区领先"]);
    const events = await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 412 }]),
    }));
    const text = events.filter(e => e.type === "insightDelta").map((e: any) => e.text).join("");
    expect(text).toBe("华东区领先");
  });

  it("查询执行时用的是 LIMIT+1 探测,回传的 sql 不带它", async () => {
    const llm = queuedLlm([llmJson(), "x"]);
    const d = deps(llm, [{ region: "华东", total: 1 }]);
    await collect(handleChat({ question: "q", history: [], deps: d }));
    const [sqlArg, limitArg] = (d.db.runQuery as any).mock.calls[0];
    expect(sqlArg).toContain("LIMIT 1001");
    expect(limitArg).toBe(1000);
  });
});

describe("handleChat 下钻上下文", () => {
  it("context 被注入第一轮 prompt", async () => {
    const llm = queuedLlm([llmJson(), "x"]);
    await collect(handleChat({
      question: "只看华东区", history: [],
      context: { lastSql: "SELECT region FROM orders", lastColumns: ["region"] },
      deps: deps(llm, [{ region: "华东", total: 1 }]),
    }));
    expect(llm.prompts[0]).toContain("上一轮查询");
    expect(llm.prompts[0]).toContain("SELECT region FROM orders");
  });
  it("无 context 时第一轮 prompt 不含上一轮段落", async () => {
    const llm = queuedLlm([llmJson(), "x"]);
    await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 1 }]),
    }));
    expect(llm.prompts[0]).not.toContain("上一轮查询");
  });
});

describe("handleChat 空结果", () => {
  it("跳过第二轮 LLM,洞察为固定文案", async () => {
    const llm = queuedLlm([llmJson(), "不应被调用"]);
    const events = await collect(handleChat({
      question: "q", history: [], deps: deps(llm, []),
    }));
    expect(llm.calls()).toBe(1);
    const text = events.filter(e => e.type === "insightDelta").map((e: any) => e.text).join("");
    expect(text).toBe("没有符合条件的记录。");
    const r = events.find(e => e.type === "result") as any;
    expect(r.payload.spec.chartType).toBe("table");
  });
});

describe("handleChat 截断", () => {
  it("spec.notes 与 facts 同时反映截断", async () => {
    const llm = queuedLlm([llmJson(), "x"]);
    const events = await collect(handleChat({
      question: "q", history: [],
      deps: deps(llm, [{ region: "华东", total: 1 }], true),
    }));
    const r = events.find(e => e.type === "result") as any;
    const f = events.find(e => e.type === "insightFacts") as any;
    expect(r.payload.spec.notes.join()).toContain("截断");
    expect(f.facts.map((x: any) => x.kind)).toContain("truncated");
  });
});

describe("handleChat 重试与失败", () => {
  it("JSON 解析失败重试一次,第二次成功", async () => {
    const llm = queuedLlm(["garbage", llmJson(), "x"]);
    const events = await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 1 }]),
    }));
    expect(events.some(e => e.type === "result")).toBe(true);
  });

  it("两次都解析失败则报错,并附原始输出", async () => {
    const llm = queuedLlm(["garbage", "still garbage"]);
    const events = await collect(handleChat({ question: "q", history: [], deps: deps(llm, []) }));
    const err = events.find(e => e.type === "error") as any;
    expect(err.message).toMatch(/json/i);
    expect(err.raw).toBe("still garbage");
  });

  it("SQL 非只读被拦截", async () => {
    const llm = queuedLlm([llmJson({ sql: "DELETE FROM orders" })]);
    const events = await collect(handleChat({ question: "q", history: [], deps: deps(llm, []) }));
    const err = events.find(e => e.type === "error") as any;
    expect(err.message).toMatch(/拦截/);
  });

  it("SQL 执行报错重试一次后报错", async () => {
    const llm = queuedLlm([llmJson(), llmJson()]);
    const d = {
      db: {
        getSchema: () => schema,
        runQuery: vi.fn(() => { throw new Error("no such column: bad"); }),
      },
      llm,
    };
    const events = await collect(handleChat({ question: "q", history: [], deps: d }));
    expect(d.db.runQuery).toHaveBeenCalledTimes(2);
    const err = events.find(e => e.type === "error") as any;
    expect(err.message).toMatch(/no such column/);
  });

  it("重试 prompt 里带上失败原因", async () => {
    const llm = queuedLlm(["garbage", llmJson(), "x"]);
    await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 1 }]),
    }));
    expect(llm.prompts[1]).toContain("上次输出有问题");
  });
});
