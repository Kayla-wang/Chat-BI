import type { InsightFact, ValueFormat } from "@chatbi/shared";
import { renderFactsTemplate } from "./facts";

export interface InsightLlm {
  chatStream(prompt: string): AsyncIterable<string>;
}

class InsightTimeout extends Error {}

function raceDeadline<T>(p: Promise<T>, ms: number): Promise<T> {
  let timer: NodeJS.Timeout;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new InsightTimeout("insight timeout")), ms);
  });
  return Promise.race([p, timeout]).finally(() => clearTimeout(timer!));
}

export async function* writeInsight(opts: {
  facts: InsightFact[]; prompt: string; llm: InsightLlm;
  timeoutMs: number; format: ValueFormat;
}): AsyncIterable<string> {
  const { facts, prompt, llm, timeoutMs, format } = opts;

  if (facts.length === 1 && facts[0].kind === "empty") {
    yield renderFactsTemplate(facts, format);
    return;
  }

  const deadline = Date.now() + timeoutMs;
  let emitted = false;
  try {
    const it = llm.chatStream(prompt)[Symbol.asyncIterator]();
    for (;;) {
      const remaining = deadline - Date.now();
      if (remaining <= 0) throw new InsightTimeout("insight timeout");
      const next = await raceDeadline(it.next(), remaining);
      if (next.done) break;
      if (next.value) { emitted = true; yield next.value; }
    }
  } catch {
    yield emitted ? "…（洞察生成中断）" : renderFactsTemplate(facts, format);
  }
}
