import { describe, it, expect, vi } from "vitest";
import { handleChat } from "../src/chatService";
import type { TableSchema, StreamEvent, Row } from "@chatbi/shared";
import { DsError } from "../src/datasources/errors";
import { SQLITE_DIALECT } from "../src/datasources/dialect";

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
    db: {
      getSchema: async () => schema,
      runQuery: vi.fn(async () => ({ rows, truncated })),
    },
    dialect: SQLITE_DIALECT,
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
    // 分类重试只认 DsError:驱动层的契约是一律抛它。原生原文放在 details 里。
    const d = {
      db: {
        getSchema: async () => schema,
        runQuery: vi.fn(async (): Promise<never> => {
          throw new DsError("SCHEMA_STALE", "表或列不存在;表结构可能已变更,试试刷新结构", "no such column: bad");
        }),
      },
      dialect: SQLITE_DIALECT,
      llm,
    };
    const events = await collect(handleChat({ question: "q", history: [], deps: d }));
    expect(d.db.runQuery).toHaveBeenCalledTimes(2);
    const err = events.find(e => e.type === "error") as any;
    // 给用户看的是中文消息;原生原文改为喂回模型,所以在重试 prompt 里断言它。
    expect(err.message).toMatch(/表或列不存在/);
    expect(llm.prompts[1]).toContain("no such column: bad");
  });

  it("重试 prompt 里带上失败原因", async () => {
    const llm = queuedLlm(["garbage", llmJson(), "x"]);
    await collect(handleChat({
      question: "q", history: [], deps: deps(llm, [{ region: "华东", total: 1 }]),
    }));
    expect(llm.prompts[1]).toContain("上次输出有问题");
  });
});

const SCHEMA: TableSchema[] = [{
  tableName: "orders",
  columns: [
    { name: "order_date", type: "TEXT", notNull: false, pk: false },
    { name: "total_amount", type: "REAL", notNull: false, pk: false },
  ],
  foreignKeys: [],
}];

/** 每次调用都吐同一段合法 JSON 的假 LLM,并记下被调了几次。 */
function countingLlm(): { chatStream(p: string): AsyncIterable<string>; calls: number } {
  const obj = JSON.stringify({
    sql: "SELECT order_date, total_amount FROM orders",
    explanation: "查订单",
    chartType: "line", dimensions: ["order_date"], measures: ["total_amount"],
  });
  const llm = {
    calls: 0,
    chatStream(_p: string): AsyncIterable<string> {
      llm.calls++;
      return (async function* () { yield obj; })();
    },
  };
  return llm;
}

describe("按错误码决定是否重试", () => {
  const run = (runQuery: () => Promise<never>, llm = countingLlm()) => ({
    llm,
    events: collect(handleChat({
      question: "按月统计订单金额", history: [],
      deps: { db: { getSchema: async () => SCHEMA, runQuery }, dialect: SQLITE_DIALECT, llm },
    })),
  });

  it("SQL_ERROR 重试一轮(LLM 被调两次)", async () => {
    const { llm, events } = run(async () => { throw new DsError("SQL_ERROR", "SQL 执行失败", "syntax error"); });
    const evs = await events;
    expect(llm.calls).toBe(2);
    expect(evs.at(-1)).toMatchObject({ type: "error" });
  });

  it("CONNECTION_ERROR 不重试(LLM 只被调一次)", async () => {
    const { llm, events } = run(async () => {
      throw new DsError("CONNECTION_ERROR", "无法连接到数据库,请检查地址、端口与网络", "ECONNREFUSED");
    });
    const evs = await events;
    expect(llm.calls).toBe(1);
    expect(evs.at(-1)).toMatchObject({ type: "error", message: expect.stringContaining("无法连接") });
  });

  it("TIMEOUT 不重试", async () => {
    const { llm, events } = run(async () => { throw new DsError("TIMEOUT", "查询超时"); });
    await events;
    expect(llm.calls).toBe(1);
  });

  it("SCHEMA_STALE 会重试,最终错误提示带刷新结构", async () => {
    const { llm, events } = run(async () => {
      throw new DsError("SCHEMA_STALE", "表或列不存在;表结构可能已变更,试试刷新结构", "no such column");
    });
    const evs = await events;
    expect(llm.calls).toBe(2);
    expect(evs.at(-1)).toMatchObject({ type: "error", message: expect.stringContaining("刷新结构") });
  });

  it("错误消息给人看的是中文,原生原文只喂回模型", async () => {
    const { events } = run(async () => {
      throw new DsError("AUTH_ERROR", "认证失败,请检查用户名与密码", "ER_ACCESS_DENIED_ERROR");
    });
    const last = (await events).at(-1) as { type: string; message: string };
    expect(last.message).not.toContain("ER_ACCESS_DENIED");
  });

  it("裸 Error(驱动层的 bug)当作 UNKNOWN,不重试", async () => {
    const { llm, events } = run(async () => { throw new Error("某个没被映射的错误"); });
    await events;
    expect(llm.calls).toBe(1);
  });
});

describe("取 schema 失败", () => {
  it("直接报错,一次 LLM 都不调", async () => {
    const llm = countingLlm();
    const evs = await collect(handleChat({
      question: "任意问题", history: [],
      deps: {
        db: {
          getSchema: async (): Promise<never> => {
            throw new DsError("CONNECTION_ERROR", "无法连接到数据库");
          },
          runQuery: async () => ({ rows: [], truncated: false }),
        },
        dialect: SQLITE_DIALECT, llm,
      },
    }));
    expect(llm.calls).toBe(0);
    expect(evs).toEqual([{ type: "error", message: "无法连接到数据库" }]);
  });
});
