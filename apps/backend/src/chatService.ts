import type { ChatTurn, StreamEvent, ChartType, Row, TableSchema } from "@chatbi/shared";
import { buildPrompt, buildRetryPrompt } from "./promptBuilder";
import { validate, enforceLimit, wrapTimeout } from "./sqlGuard";
import { assemble } from "./chartAssembler";
import { config } from "./config";

export interface ChatDeps {
  db: { getSchema(): TableSchema[]; runQuery(sql: string): Row[] };
  llm: { chatStream(prompt: string): AsyncIterable<string> };
}

interface ParsedLLM { sql: string; chartType: ChartType; explanation: string; }

async function collectStream(stream: AsyncIterable<string>): Promise<string> {
  let out = "";
  for await (const t of stream) out += t;
  return out;
}

function parseJson(raw: string): ParsedLLM | null {
  // 容错:剥离可能的 markdown 代码块包裹
  const cleaned = raw.replace(/```json|```/g, "").trim();
  try {
    const obj = JSON.parse(cleaned);
    if (typeof obj.sql === "string" && typeof obj.chartType === "string" && typeof obj.explanation === "string") {
      return obj;
    }
  } catch { /* fall through */ }
  return null;
}

async function* emitExplanationDeltas(text: string): AsyncIterable<StreamEvent> {
  const chunk = 2; // 每 2 字符一个 delta,模拟打字
  for (let i = 0; i < text.length; i += chunk) {
    yield { type: "explanationDelta", text: text.slice(i, i + chunk) };
  }
}

export async function* handleChat(opts: { question: string; history: ChatTurn[]; deps: ChatDeps }): AsyncIterable<StreamEvent> {
  const schema = opts.deps.db.getSchema();
  let prompt = buildPrompt({ question: opts.question, schema, history: opts.history });

  for (let attempt = 0; attempt < 2; attempt++) {
    const raw = await collectStream(opts.deps.llm.chatStream(prompt));
    const parsed = parseJson(raw);
    if (!parsed) {
      if (attempt === 0) { prompt = buildRetryPrompt(prompt, "输出不是合法 JSON,请只输出 JSON"); continue; }
      yield { type: "error", message: "LLM 输出无法解析为 JSON", raw };
      return;
    }
    const v = validate(parsed.sql);
    if (!v.ok) {
      if (attempt === 0) { prompt = buildRetryPrompt(prompt, `SQL 校验失败:${v.reason},请重新生成只读 SELECT`); continue; }
      yield { type: "error", message: `查询非只读,已拦截:${v.reason}` };
      return;
    }
    const limitedSql = enforceLimit(v.sql, config.rowLimit);
    let rows: Row[];
    try {
      rows = await wrapTimeout(config.queryTimeoutMs, Promise.resolve().then(() => opts.deps.db.runQuery(limitedSql)));
    } catch (e) {
      if (attempt === 0) { prompt = buildRetryPrompt(prompt, `SQL 执行报错:${(e as Error).message},请修正 SQL`); continue; }
      yield { type: "error", message: `SQL 执行失败:${(e as Error).message}` };
      return;
    }
    const columns = rows.length ? Object.keys(rows[0]) : [];
    const wasTruncated = rows.length >= config.rowLimit;
    const explanation = wasTruncated ? `${parsed.explanation}(结果已截断至 ${config.rowLimit} 行)` : parsed.explanation;
    for await (const e of emitExplanationDeltas(explanation)) yield e;
    const payload = assemble({ rows, chartType: parsed.chartType, columns, explanation });
    yield { type: "result", payload };
    return;
  }
}
