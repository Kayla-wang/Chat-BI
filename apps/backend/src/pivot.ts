import type { Row } from "@chatbi/shared";

export const SERIES_BY_MAX = 12;

export function distinctValues(rows: Row[], field: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const r of rows) {
    const key = r[field] === null || r[field] === undefined ? "" : String(r[field]);
    if (!seen.has(key)) { seen.add(key); out.push(key); }
  }
  return out;
}

function toNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

export function pivotSeries(opts: {
  rows: Row[]; xField: string; seriesByField: string; measureField: string;
}): { labels: string[]; groups: { name: string; data: (number | null)[] }[] } {
  const labels = distinctValues(opts.rows, opts.xField);
  const names = distinctValues(opts.rows, opts.seriesByField);
  const xIndex = new Map(labels.map((l, i) => [l, i]));

  const groups = names.map(name => ({
    name,
    data: new Array<number | null>(labels.length).fill(null),
  }));
  const byName = new Map(groups.map(g => [g.name, g]));

  for (const r of opts.rows) {
    const name = r[opts.seriesByField] === null || r[opts.seriesByField] === undefined
      ? "" : String(r[opts.seriesByField]);
    const xKey = r[opts.xField] === null || r[opts.xField] === undefined
      ? "" : String(r[opts.xField]);
    const g = byName.get(name);
    const i = xIndex.get(xKey);
    if (!g || i === undefined) continue;
    const v = toNumber(r[opts.measureField]);
    if (v === null) continue;
    g.data[i] = (g.data[i] ?? 0) + v;
  }
  return { labels, groups };
}
