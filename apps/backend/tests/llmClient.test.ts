import { describe, it, expect, vi, beforeEach } from "vitest";
import { LlmClient, OllamaConnectionError } from "../src/llmClient";

function mockFetch(body: string, status = 200) {
  const lines = body.split("\n").map(line => JSON.stringify({ message: { content: line } }));
  const stream = new ReadableStream({
    start(ctl) {
      const enc = new TextEncoder();
      lines.forEach(l => ctl.enqueue(enc.encode(l + "\n")));
      ctl.close();
    },
  });
  return vi.fn().mockResolvedValue({ ok: status < 400, status, body: stream } as any);
}

beforeEach(() => { (global as any).fetch = undefined; });

describe("LlmClient.chatStream", () => {
  it("yields content tokens from NDJSON stream", async () => {
    (global as any).fetch = mockFetch("hello\nworld");
    const c = new LlmClient("http://x", "m");
    const out: string[] = [];
    for await (const t of c.chatStream("p")) out.push(t);
    expect(out).toEqual(["hello", "world"]);
  });
  it("sends POST to /api/chat with model + prompt", async () => {
    const f = mockFetch("a");
    (global as any).fetch = f;
    const c = new LlmClient("http://host:11434", "llama3.1");
    for await (const _ of c.chatStream("p")) break;
    expect(f).toHaveBeenCalledWith("http://host:11434/api/chat", expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"model":"llama3.1"'),
    }));
  });
  it("throws OllamaConnectionError on network failure", async () => {
    (global as any).fetch = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    const c = new LlmClient("http://x", "m");
    await expect(async () => { for await (const _ of c.chatStream("p")) { /* drain */ } })
      .rejects.toBeInstanceOf(OllamaConnectionError);
  });
  it("throws OllamaConnectionError on non-2xx status", async () => {
    (global as any).fetch = vi.fn().mockResolvedValue({ ok: false, status: 404, body: null } as any);
    const c = new LlmClient("http://x", "m");
    await expect(async () => { for await (const _ of c.chatStream("p")) { /* drain */ } })
      .rejects.toBeInstanceOf(OllamaConnectionError);
  });
});
