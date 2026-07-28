const FORBIDDEN = /\b(insert|update|delete|drop|create|alter|attach|detach|pragma|vacuum|reindex)\b/i;

export function validate(sql: string): { ok: true; sql: string } | { ok: false; reason: string } {
  // 禁止分号(堆叠查询);允许末尾单个分号
  const trimmed = sql.trim().replace(/;\s*$/, "");
  if (/;/.test(trimmed)) return { ok: false, reason: "stacked queries not allowed" };
  // 允许 WITH ... SELECT;否则必须以 SELECT 开头
  const isSelect = /^\s*(with\b[\s\S]*\bselect|select)\b/i.test(trimmed);
  if (!isSelect) return { ok: false, reason: "only SELECT / WITH...SELECT allowed" };
  if (FORBIDDEN.test(trimmed)) return { ok: false, reason: "write/DDL keyword detected" };
  return { ok: true, sql: trimmed };
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
