// node-sql-parser 是纯 CJS(package.json 无 exports 字段),Node 的 ESM 静态分析
// 取不到具名导出,`import { Parser }` 在真实启动时抛 SyntaxError;测试里走 Vite
// 的 interop 反而能过。只能默认导入再取属性。
import sqlParser from "node-sql-parser";
const { Parser } = sqlParser;
import type { Dialect } from "./datasources/dialect";
import type { DataSourceKind } from "./datasources/types";

const FORBIDDEN = /\b(insert|update|delete|drop|create|alter|attach|detach|pragma|vacuum|reindex|replace|truncate)\b/i;
const SELECT_HEAD = /^\s*(with\b[\s\S]*\bselect|select)\b/i;

const parser = new Parser();

/**
 * 方言特有的逃逸口。这些都是「一条合法 SELECT 内部就能触发」的能力,
 * AST 只判断「是不是 SELECT」拦不住,必须显式列。
 *
 * 函数类一律要求后面紧跟 `(`,免得误杀名叫 dblink 的列;
 * 语句类只在行首匹配,因为 AST 已经保证了是 SELECT。
 */
const DIALECT_FORBIDDEN: Record<DataSourceKind, RegExp[]> = {
  sqlite: [],
  mysql: [
    /\binto\s+(outfile|dumpfile)\b/i,
    /\b(load_file)\s*\(/i,
    /^\s*load\s+data\b/i,
  ],
  postgres: [
    /\b(pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|dblink|dblink_exec|pg_sleep|lo_import|lo_export)\s*\(/i,
    /^\s*copy\b/i,
  ],
};

function dialectViolation(bareSql: string, dialect: Dialect): string | null {
  for (const re of DIALECT_FORBIDDEN[dialect.kind]) {
    if (re.test(bareSql)) return `${dialect.kind} forbidden construct detected`;
  }
  return null;
}

/** 把 '...' 与 "..." 的内容清空,保留引号本身,便于后续做关键字与注释判定。 */
export function stripLiterals(sql: string): string {
  return sql.replace(/'(?:[^']|'')*'/g, "''").replace(/"(?:[^"]|"")*"/g, '""');
}

export function hasComment(sql: string): boolean {
  const bare = stripLiterals(sql);
  return bare.includes("--") || bare.includes("/*");
}

export function validateByRegex(sql: string, dialect: Dialect):
  { ok: true; sql: string } | { ok: false; reason: string } {
  const trimmed = sql.trim().replace(/;\s*$/, "");
  const bare = stripLiterals(trimmed);
  if (bare.includes(";")) return { ok: false, reason: "stacked queries not allowed" };
  if (!SELECT_HEAD.test(bare)) return { ok: false, reason: "only SELECT / WITH...SELECT allowed" };
  if (FORBIDDEN.test(bare)) return { ok: false, reason: "write/DDL keyword detected" };
  const bad = dialectViolation(bare, dialect);
  if (bad) return { ok: false, reason: bad };
  return { ok: true, sql: trimmed };
}

export function validate(sql: string, dialect: Dialect):
  { ok: true; sql: string; viaAst: boolean } | { ok: false; reason: string } {
  if (hasComment(sql)) return { ok: false, reason: "SQL 注释不被允许（comment not allowed）" };
  const trimmed = sql.trim().replace(/;\s*$/, "");

  // 方言禁用词在 AST 路径上同样要查:pg_read_file(...) 是一条合法 SELECT。
  const bad = dialectViolation(stripLiterals(trimmed), dialect);
  if (bad) return { ok: false, reason: bad };

  let ast: unknown;
  try {
    ast = parser.astify(trimmed, { database: dialect.sqlParserDialect });
  } catch {
    const fallback = validateByRegex(trimmed, dialect);
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
