import { describe, it, expect, vi } from "vitest";
import { writeInsight } from "../src/insightWriter";
import type { InsightFact, ValueFormat } from "@chatbi/shared";

const FORMAT: ValueFormat = { kind: "currency", decimals: 0, unit: "元", scale: 1 };
const FACTS: InsightFact[] = [
  { kind: "trend", series: "金额", dir: "up", pct: 23.4, from: "1月", to: "3月" },
  { kind: "peak", series: "金额", label: "3月", value: 128400 },
];

async function collect(it: AsyncIterable<string>): Promise<string> {
  let out = "";
  for await (const t of it) out += t;
  return out;
}

const run = (llm: any, over: Partial<{ facts: InsightFact[]; timeoutMs: number }> = {}) =>
  collect(writeInsight({
    facts: FACTS, prompt: "P", llm, timeoutMs: 5000, format: FORMAT, ...over,
  }));

describe("writeInsight 正常路径", () => {
  it("逐 token 透传", async () => {
    const llm = { chatStream: async function* () { yield "上半年"; yield "订单金额上涨"; } };
    expect(await run(llm)).toBe("上半年订单金额上涨");
  });

  it("prompt 原样传给 llm", async () => {
    const chatStream = vi.fn(async function* () { yield "x"; });
    await collect(writeInsight({ facts: FACTS, prompt: "PROMPT-X", llm: { chatStream }, timeoutMs: 5000, format: FORMAT }));
    expect(chatStream).toHaveBeenCalledWith("PROMPT-X");
  });
});

describe("writeInsight 降级", () => {
  it("空结果不调 LLM,直接固定文案", async () => {
    const chatStream = vi.fn(async function* () { yield "不应该被调用"; });
    const text = await run({ chatStream }, { facts: [{ kind: "empty" }] });
    expect(chatStream).not.toHaveBeenCalled();
    expect(text).toBe("没有符合条件的记录。");
  });

  it("首 token 之前报错 → 完整模板", async () => {
    const llm = { chatStream: async function* () { throw new Error("ollama down"); } };
    const text = await run(llm);
    expect(text).toContain("上涨 23.4%");
    expect(text).toContain("128,400 元");
    expect(text).not.toContain("中断");
  });

  it("部分输出后报错 → 保留已有文本并标注中断", async () => {
    const llm = {
      chatStream: async function* () { yield "上半年"; throw new Error("connection reset"); },
    };
    const text = await run(llm);
    expect(text).toBe("上半年…（洞察生成中断）");
  });

  it("超时 → 完整模板", async () => {
    const llm = {
      chatStream: async function* () {
        await new Promise(r => setTimeout(r, 1000));
        yield "太慢了";
      },
    };
    const text = await run(llm, { timeoutMs: 20 });
    expect(text).toContain("上涨 23.4%");
  });
});
