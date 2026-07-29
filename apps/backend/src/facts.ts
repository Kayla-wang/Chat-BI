import type { ChartSpec, ChartSeries, InsightFact } from "@chatbi/shared";

export { renderFactsLines, renderFactsTemplate } from "@chatbi/shared";

export const FACT_LIMIT = 6;
export const FLAT_THRESHOLD_PCT = 3;

const total = (d: (number | null)[]) => d.reduce<number>((a, v) => a + (v ?? 0), 0);
const hasValue = (s: ChartSeries) => s.data.some(v => v !== null);

export function computeFacts(
  spec: ChartSpec, opts: { truncated: boolean; rowLimit: number },
): InsightFact[] {
  const usable = spec.series.filter(hasValue);
  if (!usable.length) return [{ kind: "empty" }];

  const primary = usable.reduce((a, b) =>
    Math.abs(total(b.data)) > Math.abs(total(a.data)) ? b : a);
  const points = primary.data
    .map((v, i) => ({ i, v }))
    .filter((x): x is { i: number; v: number } => x.v !== null);
  const label = (i: number) => spec.x.labels[i] ?? "";
  const facts: InsightFact[] = [];

  if (spec.x.role === "temporal") {
    const first = points[0];
    const last = points[points.length - 1];
    if (first && last && first.i !== last.i) {
      if (first.v === 0 || Math.sign(first.v) !== Math.sign(last.v)) {
        facts.push({
          kind: "trendAbs", series: primary.name,
          delta: last.v - first.v, from: label(first.i), to: label(last.i),
        });
      } else {
        const pct = ((last.v - first.v) / Math.abs(first.v)) * 100;
        const dir = Math.abs(pct) < FLAT_THRESHOLD_PCT ? "flat" : pct > 0 ? "up" : "down";
        facts.push({ kind: "trend", series: primary.name, dir, pct, from: label(first.i), to: label(last.i) });
      }
    }
    const max = points.reduce((a, b) => (b.v > a.v ? b : a));
    const min = points.reduce((a, b) => (b.v < a.v ? b : a));
    facts.push({ kind: "peak", series: primary.name, label: label(max.i), value: max.v });
    facts.push({ kind: "trough", series: primary.name, label: label(min.i), value: min.v });
  } else {
    const sum = total(primary.data);
    const sorted = [...points].sort((a, b) => b.v - a.v);
    if (sum !== 0 && sorted.length) {
      facts.push({
        kind: "topShare", series: primary.name,
        label: label(sorted[0].i), pct: (sorted[0].v / sum) * 100,
      });
      const topN = Math.min(3, sorted.length);
      const topSum = sorted.slice(0, topN).reduce((a, b) => a + b.v, 0);
      facts.push({ kind: "concentration", series: primary.name, topN, pct: (topSum / sum) * 100 });
    }
    facts.push({ kind: "total", series: primary.name, value: sum });
  }

  if (usable.length > 1) {
    const sums = usable.map(s => ({ name: s.name, value: total(s.data) }));
    const high = sums.reduce((a, b) => (b.value > a.value ? b : a));
    const low = sums.reduce((a, b) => (b.value < a.value ? b : a));
    if (low.value !== 0 && high.name !== low.name) {
      facts.push({ kind: "seriesGap", high: high.name, low: low.name, ratio: high.value / low.value });
    }
  }
  if (opts.truncated) facts.push({ kind: "truncated", limit: opts.rowLimit });

  return facts.slice(0, FACT_LIMIT);
}
