import { describe, it, expect, vi } from "vitest";
import express from "express";
import request from "supertest";
import { createChatRouter } from "../src/routes/chat";
import { SQLITE_DIALECT } from "../src/datasources/dialect";
import { DsError } from "../src/datasources/errors";
import type { Driver } from "../src/datasources/driver";
import type { StreamEvent } from "@chatbi/shared";

function readSse(text: string): StreamEvent[] {
  const events: StreamEvent[] = [];
  for (const line of text.split("\n")) {
    if (!line.startsWith("data: ")) continue;
    events.push(JSON.parse(line.slice(6)));
  }
  return events;
}

const llmJson = JSON.stringify({
  sql: "SELECT a FROM t", explanation: "ok", chartType: "table",
  dimensions: ["a"], measures: [],
});

/** 假 driver:只要能报 kind / dialect / runQuery 就够路由用。 */
function fakeDriver(): Driver {
  return {
    kind: "sqlite", dialect: SQLITE_DIALECT,
    testConnection: async () => ({ ok: true as const, writePrivilege: "readonly" as const }),
    introspect: async () => [],
    runQuery: vi.fn(async () => ({ rows: [{ a: 1 }], truncated: false })),
    probeWritePrivilege: async () => "readonly" as const,
    close: async () => { /* 假 driver 无需关闭 */ },
  };
}

function makeDeps(chatStream: (prompt: string) => AsyncIterable<string>, driver = fakeDriver()) {
  return {
    driver,
    registry: {
      get: vi.fn(async (id: string) => {
        if (id !== "ds1") throw new DsError("NOT_FOUND", "数据源不存在,可能已被删除");
        return driver;
      }),
      schemaFor: vi.fn(async () => []),
    },
    llm: { chatStream },
  };
}

const app = (deps: unknown) =>
  express().use(express.json()).use("/api/chat", createChatRouter(deps as any));

describe("POST /api/chat (SSE)", () => {
  it("streams result then done and closes", async () => {
    let i = 0;
    const deps = makeDeps(async function* () { yield i++ === 0 ? llmJson : "洞察文本"; });
    const res = await request(app(deps)).post("/api/chat")
      .send({ question: "q", dataSourceId: "ds1", history: [] });
    const types = readSse(res.text).map(e => e.type);
    expect(types).toContain("result");
    expect(types[types.length - 1]).toBe("done");
  });

  it("rejects a request without a question", async () => {
    const deps = makeDeps(async function* () { /* never called */ });
    const res = await request(app(deps)).post("/api/chat").send({ history: [] });
    expect(res.status).toBe(400);
  });

  it("accepts a body carrying a drill-down context and passes it to the prompt", async () => {
    const prompts: string[] = [];
    let i = 0;
    const deps = makeDeps(async function* (prompt: string) {
      prompts.push(prompt);
      yield i++ === 0 ? llmJson : "洞察文本";
    });
    const res = await request(app(deps)).post("/api/chat").send({
      question: "只看华东区", dataSourceId: "ds1", history: [],
      context: { lastSql: "SELECT region FROM orders", lastColumns: ["region"] },
    });
    expect(res.status).toBe(200);
    expect(prompts[0]).toContain("SELECT region FROM orders");
    expect(readSse(res.text).some(e => e.type === "result")).toBe(true);
  });

  it("ignores a malformed context instead of failing the request", async () => {
    const prompts: string[] = [];
    let i = 0;
    const deps = makeDeps(async function* (prompt: string) {
      prompts.push(prompt);
      yield i++ === 0 ? llmJson : "洞察文本";
    });
    const res = await request(app(deps)).post("/api/chat")
      .send({ question: "q", dataSourceId: "ds1", history: [], context: { nope: 1 } });
    expect(res.status).toBe(200);
    expect(prompts[0]).not.toContain("上一轮查询");
  });
});

describe("dataSourceId", () => {
  it("按 id 从 registry 取 driver", async () => {
    const deps = makeDeps(async function* () { yield llmJson; });
    await request(app(deps)).post("/api/chat").send({ question: "q", dataSourceId: "ds1", history: [] });
    expect(deps.registry.get).toHaveBeenCalledWith("ds1");
  });

  it("缺 dataSourceId 时走 SSE error,不是 400", async () => {
    const deps = makeDeps(async function* () { /* 不该被调用 */ });
    const res = await request(app(deps)).post("/api/chat").send({ question: "q", history: [] });
    expect(res.status).toBe(200);
    const events = readSse(res.text);
    expect(events).toEqual([{ type: "error", message: "缺少 dataSourceId,请先在顶栏选择数据源" }]);
    expect(deps.registry.get).not.toHaveBeenCalled();
  });

  it("id 不存在时把 DsError 的中文消息发成 error 事件", async () => {
    const deps = makeDeps(async function* () { /* 不该被调用 */ });
    const res = await request(app(deps)).post("/api/chat")
      .send({ question: "q", dataSourceId: "nope", history: [] });
    const events = readSse(res.text);
    expect(events).toEqual([{ type: "error", message: "数据源不存在,可能已被删除" }]);
  });

  it("schema 走 registry 的缓存,不直接调 driver.introspect", async () => {
    const driver = fakeDriver();
    const deps = makeDeps(async function* () { yield llmJson; }, driver);
    await request(app(deps)).post("/api/chat").send({ question: "q", dataSourceId: "ds1", history: [] });
    expect(deps.registry.schemaFor).toHaveBeenCalledWith("ds1");
  });

  it("查询带上 config 的超时值", async () => {
    const driver = fakeDriver();
    const deps = makeDeps(async function* () { yield llmJson; }, driver);
    await request(app(deps)).post("/api/chat").send({ question: "q", dataSourceId: "ds1", history: [] });
    const [, limit, timeout] = (driver.runQuery as any).mock.calls[0];
    expect(limit).toBe(1000);
    expect(timeout).toBe(5000);
  });
});
