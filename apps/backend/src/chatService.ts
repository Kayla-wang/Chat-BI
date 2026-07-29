import type {
  ChartHint, ChatTurn, DrillContext, Row, StreamEvent, TableSchema, ValueFormat,
} from "@chatbi/shared";
import { buildPrompt, buildRetryPrompt, buildInsightPrompt } from "./promptBuilder";
import { validate, enforceLimit, wrapTimeout } from "./sqlGuard";
import { inferChartSpec } from "./chartSpec";
import { computeFacts } from "./facts";
import { writeInsight } from "./insightWriter";
import { config } from "./config";

export interface ChatDeps {
  db: {
    getSchema(): TableSchema[];
    runQuery(sql: string, limit: number): { rows: Row[]; truncated: boolean };
  };
  llm: { chatStream(prompt: string): AsyncIterable<string> };
}

const DEFAULT_FORMAT: ValueFormat = { kind: "number", decimals: 0, scale: 1 };

interface ParsedLLM { sql: string; explanation: string; hint: ChartHint | null }

async function collectStream(stream: AsyncIterable<string>): Promise<string> {
  let out = "";
  for await (const t of stream) out += t;
  return out;
}

function parseJson(raw: string): ParsedLLM | null {
  const cleaned = raw.replace(/```json|```/g, "").trim();
  let obj: any;
  try { obj = JSON.parse(cleaned); } catch { return null; }
  if (typeof obj?.sql !== "string" || typeof obj?.explanation !== "string") return null;

  const strings = (v: unknown) =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  const hint: ChartHint | null = typeof obj.chartType === "string" ? {
    chartType: obj.chartType,
    dimensions: strings(obj.dimensions),
    measures: strings(obj.measures),
    ...(typeof obj.seriesBy === "string" && obj.seriesBy ? { seriesBy: obj.seriesBy } : {}),
    ...(typeof obj.stack === "string" ? { stack: obj.stack } : {}),
  } as ChartHint : null;

  return { sql: obj.sql, explanation: obj.explanation, hint };
}

export async function* handleChat(opts: {
  question: string; history: ChatTurn[]; context?: DrillContext; deps: ChatDeps;
}): AsyncIterable<StreamEvent> {
  const schema = opts.deps.db.getSchema();
  let prompt = buildPrompt({
    question: opts.question, schema, history: opts.history, context: opts.context,
  });

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
      if (attempt === 0) {
        prompt = buildRetryPrompt(prompt, `SQL 校验失败:${v.reason},请重新生成只读 SELECT`);
        continue;
      }
      yield { type: "error", message: `查询非只读,已拦截:${v.reason}` };
      return;
    }

    const probeSql = enforceLimit(v.sql, config.rowLimit + 1);
    let out: { rows: Row[]; truncated: boolean };
    try {
      out = await wrapTimeout(
        config.queryTimeoutMs,
        Promise.resolve().then(() => opts.deps.db.runQuery(probeSql, config.rowLimit)),
      );
    } catch (e) {
      if (attempt === 0) {
        prompt = buildRetryPrompt(prompt, `SQL 执行报错:${(e as Error).message},请修正 SQL`);
        continue;
      }
      yield { type: "error", message: `SQL 执行失败:${(e as Error).message}` };
      return;
    }

    const columns = out.rows.length ? Object.keys(out.rows[0]) : [];
    const spec = inferChartSpec({
      rows: out.rows, columns, hint: parsed.hint,
      truncated: out.truncated, rowLimit: config.rowLimit,
    });

    yield {
      type: "result",
      payload: {
        spec,
        table: { columns, rows: out.rows },
        queryIntent: parsed.explanation,
        sql: v.sql,
      },
    };

    const facts = computeFacts(spec, { truncated: out.truncated, rowLimit: config.rowLimit });
    yield { type: "insightFacts", facts };

    const format = spec.series[0]?.format ?? DEFAULT_FORMAT;
    const insightPrompt = buildInsightPrompt(facts, opts.question, format);
    for await (const text of writeInsight({
      facts, prompt: insightPrompt, llm: opts.deps.llm,
      timeoutMs: config.insightTimeoutMs, format,
    })) {
      yield { type: "insightDelta", text };
    }

    yield { type: "done" };
    return;
  }
}
