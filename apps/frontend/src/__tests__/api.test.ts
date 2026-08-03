import { describe, it, expect, vi, beforeEach } from "vitest";
import { streamChat } from "../api";
import type { StreamEvent } from "@chatbi/shared";

function mockFetch(sseBody: string) {
  const stream = new ReadableStream({
    start(ctl) { ctl.enqueue(new TextEncoder().encode(sseBody)); ctl.close(); },
  });
  return vi.fn().mockResolvedValue({ ok: true, body: stream } as any);
}

const collect = (body: string, extra: Record<string, unknown> = {}) => {
  (global as any).fetch = mockFetch(body);
  const events: StreamEvent[] = [];
  return streamChat({
    question: "q", dataSourceId: "ds1", history: [],
    onEvent: e => events.push(e), ...extra,
  }).then(() => events);
};

beforeEach(() => { (global as any).fetch = undefined; });

describe("streamChat 事件解析", () => {
  it("解析 result / insightFacts / insightDelta / done", async () => {
    const body = [
      'data: {"type":"result","payload":{"spec":{"chartType":"bar","stack":"none","x":{"field":"region","role":"categorical","labels":["华东"]},"series":[],"notes":[]},"table":{"columns":["region"],"rows":[{"region":"华东"}]},"queryIntent":"按地区","sql":"SELECT 1"}}',
      'data: {"type":"insightFacts","facts":[{"kind":"empty"}]}',
      'data: {"type":"insightDelta","text":"华东领先"}',
      'data: {"type":"done"}',
    ].join("\n\n") + "\n\n";
    const events = await collect(body);
    expect(events.map(e => e.type)).toEqual(["result", "insightFacts", "insightDelta", "done"]);
    expect((events[0] as any).payload.queryIntent).toBe("按地区");
  });

  it("跨 chunk 的不完整事件不会被误解析", async () => {
    const events = await collect('data: {"type":"insightDelta","text":"a"}\n\ndata: {"type":"don');
    expect(events.map(e => e.type)).toEqual(["insightDelta"]);
  });
});

describe("streamChat 请求体", () => {
  it("带 context 时放进 body", async () => {
    await collect('data: {"type":"done"}\n\n', {
      context: { lastSql: "SELECT region FROM orders", lastColumns: ["region"] },
    });
    const body = JSON.parse((global as any).fetch.mock.calls[0][1].body);
    expect(body.context).toEqual({ lastSql: "SELECT region FROM orders", lastColumns: ["region"] });
  });

  it("无 context 时 body 里不出现该字段", async () => {
    await collect('data: {"type":"done"}\n\n');
    const body = JSON.parse((global as any).fetch.mock.calls[0][1].body);
    expect("context" in body).toBe(false);
  });

  it("带上 dataSourceId,后端按它取 driver", async () => {
    await collect('data: {"type":"done"}\n\n');
    const body = JSON.parse((global as any).fetch.mock.calls[0][1].body);
    expect(body.dataSourceId).toBe("ds1");
    expect(body.question).toBe("q");
  });
});

describe("streamChat 错误路径", () => {
  it("非 2xx 时发 error 事件", async () => {
    (global as any).fetch = vi.fn().mockResolvedValue({ ok: false, status: 500, body: null } as any);
    const events: StreamEvent[] = [];
    await streamChat({ question: "q", dataSourceId: "ds1", history: [], onEvent: e => events.push(e) });
    expect(events[0].type).toBe("error");
  });
  it("fetch 抛错时发 error 事件", async () => {
    (global as any).fetch = vi.fn().mockRejectedValue(new Error("offline"));
    const events: StreamEvent[] = [];
    await streamChat({ question: "q", dataSourceId: "ds1", history: [], onEvent: e => events.push(e) });
    expect((events[0] as any).message).toMatch(/offline|网络/);
  });
});
