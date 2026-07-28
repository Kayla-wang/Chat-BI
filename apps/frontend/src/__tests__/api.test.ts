import { describe, it, expect, vi, beforeEach } from "vitest";
import { streamChat } from "../api";
import type { StreamEvent } from "@chatbi/shared";

function mockFetch(sseBody: string) {
  const stream = new ReadableStream({
    start(ctl) {
      ctl.enqueue(new TextEncoder().encode(sseBody));
      ctl.close();
    },
  });
  return vi.fn().mockResolvedValue({ ok: true, body: stream } as any);
}

beforeEach(() => { (global as any).fetch = undefined; });

describe("streamChat", () => {
  it("parses SSE data lines into StreamEvents", async () => {
    const body = 'data: {"type":"explanationDelta","text":"hi"}\n\ndata: {"type":"result","payload":{"chartType":"table","echartsOption":{},"table":{"columns":[],"rows":[]},"explanation":"hi"}}\n\n';
    (global as any).fetch = mockFetch(body);
    const events: StreamEvent[] = [];
    await new Promise<void>(r => streamChat({ question: "q", history: [], onEvent: e => { events.push(e); if (e.type === "result") r(); } }));
    expect(events[0]).toEqual({ type: "explanationDelta", text: "hi" });
    expect(events[1].type).toBe("result");
  });
  it("calls onEvent with error on non-2xx", async () => {
    (global as any).fetch = vi.fn().mockResolvedValue({ ok: false, status: 500, body: null } as any);
    const events: StreamEvent[] = [];
    await new Promise<void>(r => streamChat({ question: "q", history: [], onEvent: e => { events.push(e); r(); } }));
    expect(events[0].type).toBe("error");
  });
});
