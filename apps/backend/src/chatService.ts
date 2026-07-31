import type {
  ChartHint, ChatTurn, DrillContext, Row, StreamEvent, TableSchema, ValueFormat,
} from "@chatbi/shared";
import { buildPrompt, buildRetryPrompt, buildInsightPrompt } from "./promptBuilder";
import { validate, enforceLimit } from "./sqlGuard";   // wrapTimeout 不再需要
import { inferChartSpec } from "./chartSpec";
import { computeFacts } from "./facts";
import { writeInsight } from "./insightWriter";
import { config } from "./config";
import type { Dialect } from "./datasources/dialect";
import { DsError, isRetryable } from "./datasources/errors";

export interface ChatDeps {
  db: {
    getSchema(): Promise<TableSchema[]>;
    /** 超时由 driver 下推到服务端,这里不再包 wrapTimeout。 */
    runQuery(sql: string, limit: number): Promise<{ rows: Row[]; truncated: boolean }>;
  };
  dialect: Dialect;
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
  let schema: TableSchema[];
  try {
    schema = await opts.deps.db.getSchema();
  } catch (e) {
    // 连不上库就别去问模型了,省一次无用的推理。
    yield { type: "error", message: toDsError(e).message };
    return;
  }
  let prompt = buildPrompt({
    question: opts.question, schema, history: opts.history,
    dialect: opts.deps.dialect, context: opts.context,
  });

  for (let attempt = 0; attempt < 2; attempt++) {
    const raw = await collectStream(opts.deps.llm.chatStream(prompt));
    const parsed = parseJson(raw);
    if (!parsed) {
      if (attempt === 0) { prompt = buildRetryPrompt(prompt, "输出不是合法 JSON,请只输出 JSON"); continue; }
      yield { type: "error", message: "LLM 输出无法解析为 JSON", raw };
      return;
    }

    const v = validate(parsed.sql, opts.deps.dialect);
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
      out = await opts.deps.db.runQuery(probeSql, config.rowLimit);
    } catch (e) {
      const err = toDsError(e);
      // 只有与 SQL 内容相关的错误值得把原因喂回模型;连不上、认证失败、超时重试都是白等。
      if (attempt === 0 && isRetryable(err.code)) {
        prompt = buildRetryPrompt(prompt, `SQL 执行报错:${err.details ?? err.message},请修正 SQL`);
        continue;
      }
      yield { type: "error", message: err.message };
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

/** 驱动层的契约是一律抛 DsError;裸 Error 说明有 bug,按 UNKNOWN 处理且不重试。 */
function toDsError(e: unknown): DsError {
  return e instanceof DsError
    ? e
    : new DsError("UNKNOWN", `SQL 执行失败:${(e as Error).message}`, (e as Error).message);
}
