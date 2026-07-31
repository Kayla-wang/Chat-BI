import { describe, it, expect, vi } from "vitest";
import express from "express";
import request from "supertest";
import { createChatRouter } from "../src/routes/chat";
import { SQLITE_DIALECT } from "../src/datasources/dialect";
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

function makeDeps(chatStream: (prompt: string) => AsyncIterable<string>) {
  return {
    // deps 已异步化(driver 契约),假 db 也要 async。
    db: {
      getSchema: async () => [],
      runQuery: async () => ({ rows: [{ a: 1 }], truncated: false }),
    },
    dialect: SQLITE_DIALECT,
    llm: { chatStream },
  };
}

const app = (deps: unknown) =>
  express().use(express.json()).use("/api/chat", createChatRouter(deps as any));

describe("POST /api/chat (SSE)", () => {
  it("streams result then done and closes", async () => {
    let i = 0;
    const deps = makeDeps(async function* () { yield i++ === 0 ? llmJson : "洞察文本"; });
    const res = await request(app(deps)).post("/api/chat").send({ question: "q", history: [] });
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
      question: "只看华东区", history: [],
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
      .send({ question: "q", history: [], context: { nope: 1 } });
    expect(res.status).toBe(200);
    expect(prompts[0]).not.toContain("上一轮查询");
  });
});
