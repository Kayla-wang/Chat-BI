import { Parser } from "node-sql-parser";

const FORBIDDEN = /\b(insert|update|delete|drop|create|alter|attach|detach|pragma|vacuum|reindex|replace|truncate)\b/i;
const SELECT_HEAD = /^\s*(with\b[\s\S]*\bselect|select)\b/i;

const parser = new Parser();

/** 把 '...' 与 "..." 的内容清空,保留引号本身,便于后续做关键字与注释判定。 */
export function stripLiterals(sql: string): string {
  return sql.replace(/'(?:[^']|'')*'/g, "''").replace(/"(?:[^"]|"")*"/g, '""');
}

export function hasComment(sql: string): boolean {
  const bare = stripLiterals(sql);
  return bare.includes("--") || bare.includes("/*");
}

export function validateByRegex(sql: string):
  { ok: true; sql: string } | { ok: false; reason: string } {
  const trimmed = sql.trim().replace(/;\s*$/, "");
  const bare = stripLiterals(trimmed);
  if (bare.includes(";")) return { ok: false, reason: "stacked queries not allowed" };
  if (!SELECT_HEAD.test(bare)) return { ok: false, reason: "only SELECT / WITH...SELECT allowed" };
  if (FORBIDDEN.test(bare)) return { ok: false, reason: "write/DDL keyword detected" };
  return { ok: true, sql: trimmed };
}

export function validate(sql: string):
  { ok: true; sql: string; viaAst: boolean } | { ok: false; reason: string } {
  if (hasComment(sql)) return { ok: false, reason: "SQL 注释不被允许（comment not allowed）" };
  const trimmed = sql.trim().replace(/;\s*$/, "");

  let ast: unknown;
  try {
    ast = parser.astify(trimmed, { database: "sqlite" });
  } catch {
    const fallback = validateByRegex(trimmed);
    return fallback.ok ? { ...fallback, viaAst: false } : fallback;
  }

  if (Array.isArray(ast)) {
    if (ast.length !== 1) return { ok: false, reason: "stacked queries not allowed" };
    ast = ast[0];
  }
  const type = (ast as { type?: string })?.type;
  if (type !== "select") {
    return { ok: false, reason: `only SELECT allowed, got ${type ?? "unknown"}` };
  }
  return { ok: true, sql: trimmed, viaAst: true };
}

export function enforceLimit(sql: string, limit: number): string {
  const trimmed = sql.trim().replace(/;\s*$/, "");
  if (/\blimit\s+\d+/i.test(trimmed)) return trimmed;
  return `${trimmed} LIMIT ${limit}`;
}

export function wrapTimeout<T>(ms: number, p: Promise<T>): Promise<T> {
  let timer: NodeJS.Timeout;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("query timeout")), ms);
  });
  return Promise.race([p, timeout]).finally(() => clearTimeout(timer!));
}
