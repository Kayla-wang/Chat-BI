import { describe, it, expect } from "vitest";
import express from "express";
import request from "supertest";
import { createChatRouter } from "../src/routes/chat";
import type { StreamEvent } from "@chatbi/shared";

function readSse(text: string): StreamEvent[] {
  const events: StreamEvent[] = [];
  for (const line of text.split("\n")) {
    if (!line.startsWith("data: ")) continue;
    events.push(JSON.parse(line.slice(6)));
  }
  return events;
}

describe("POST /api/chat (SSE)", () => {
  it("streams result event then closes", async () => {
    const deps = {
      db: { getSchema: () => [], runQuery: () => [{ a: 1 }] },
      llm: { chatStream: async function* () { yield JSON.stringify({ sql: "SELECT a FROM t", chartType: "table", explanation: "ok" }); } },
    };
    const app = express().use(express.json()).use("/api/chat", createChatRouter(deps as any));
    const res = await request(app).post("/api/chat").send({ question: "q", history: [] });
    const events = readSse(res.text);
    expect(events.some(e => e.type === "result")).toBe(true);
  });

  it("rejects a request without a question", async () => {
    const deps = {
      db: { getSchema: () => [], runQuery: () => [] },
      llm: { chatStream: async function* () { /* never called */ } },
    };
    const app = express().use(express.json()).use("/api/chat", createChatRouter(deps as any));
    const res = await request(app).post("/api/chat").send({ history: [] });
    expect(res.status).toBe(400);
  });
});
