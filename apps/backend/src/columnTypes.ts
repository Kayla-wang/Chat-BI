import type { Row, ColumnRole } from "@chatbi/shared";

const BARE_YEAR = /^\d{4}$/;
const ISO_LIKE = /^(\d{4})-(\d{2})(?:-(\d{2}))?(?:[T ].*)?$/;
const TIME_NAME = /(year|date|time|month|week|day|quarter|年|月|日|季|周|期)/i;

export function parseTemporal(v: string | number | null): Date | null {
  if (v === null || v === "") return null;
  const s = String(v);
  if (BARE_YEAR.test(s)) return new Date(Date.UTC(Number(s), 0, 1));
  const m = ISO_LIKE.exec(s);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = m[3] ? Number(m[3]) : 1;
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const d = new Date(Date.UTC(year, month - 1, day));
  return Number.isNaN(d.getTime()) ? null : d;
}

export function detectRole(values: (string | number | null)[], columnName: string): ColumnRole {
  const nonNull = values.filter(v => v !== null && v !== "");
  if (nonNull.length === 0) return "categorical";

  const allIso = nonNull.every(v => typeof v === "string" && ISO_LIKE.test(v) && parseTemporal(v) !== null);
  if (allIso) return "temporal";

  const allBareYear = nonNull.every(v => BARE_YEAR.test(String(v)));
  if (allBareYear && TIME_NAME.test(columnName)) return "temporal";

  const allNumeric = nonNull.every(v => !Number.isNaN(Number(v)));
  if (allNumeric) return "numeric";

  return "categorical";
}

export function detectColumnRoles(rows: Row[], columns: string[]): Record<string, ColumnRole> {
  const out: Record<string, ColumnRole> = {};
  for (const c of columns) out[c] = detectRole(rows.map(r => r[c] ?? null), c);
  return out;
}
