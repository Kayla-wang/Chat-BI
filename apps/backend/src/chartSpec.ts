import type {
  ChartHint, ChartSeries, ChartSpec, ChartType, Row, StackMode, ValueFormat,
} from "@chatbi/shared";
import { formatTimeLabel } from "@chatbi/shared";
import { detectColumnRoles, parseTemporal } from "./columnTypes";
import { inferGrain, toTickKey, enumerateTicks, fillGaps } from "./timeAxis";
import { pivotSeries, distinctValues, SERIES_BY_MAX } from "./pivot";

const CHART_TYPES: ChartType[] = ["bar", "line", "pie", "table"];
const STACKS: StackMode[] = ["none", "normal", "percent"];
const CURRENCY_NAME = /(amount|price|revenue|sales|cost|金额|销售额|收入|总额|成本)/i;
const PERCENT_NAME = /(rate|ratio|percent|share|率|占比|比例)/i;

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const num = (v: unknown) => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
};

export function inferFormat(field: string, values: (number | null)[]): ValueFormat {
  if (PERCENT_NAME.test(field)) return { kind: "percent", decimals: 1, scale: 1 };
  const kind = CURRENCY_NAME.test(field) ? "currency" : "number";
  const max = values.reduce((a, v) => Math.max(a, v === null ? 0 : Math.abs(v)), 0);
  const scale: 1 | 10000 | 100000000 = max >= 1e8 ? 100000000 : max >= 1e4 ? 10000 : 1;
  return {
    kind, scale, decimals: scale > 1 ? 2 : 0,
    ...(kind === "currency" ? { unit: "元" } : {}),
  };
}

function collapse(labels: string[], series: ChartSeries[]):
  { labels: string[]; series: ChartSeries[]; collapsed: number } {
  const groups = new Map<string, number[]>();
  labels.forEach((l, i) => {
    const g = groups.get(l);
    if (g) g.push(i); else groups.set(l, [i]);
  });
  if (groups.size === labels.length) return { labels, series, collapsed: 0 };
  const uniq = [...groups.keys()];
  const out = series.map(s => ({
    ...s,
    data: uniq.map(l => {
      const vals = groups.get(l)!.map(i => s.data[i]).filter((v): v is number => v !== null);
      if (!vals.length) return null;
      const sum = vals.reduce((a, b) => a + b, 0);
      return s.format.kind === "percent" ? sum / vals.length : sum;
    }),
  }));
  return { labels: uniq, series: out, collapsed: labels.length - uniq.length };
}

export function inferChartSpec(opts: {
  rows: Row[]; columns: string[]; hint: ChartHint | null;
  truncated: boolean; rowLimit: number;
}): ChartSpec {
  const { rows, columns, hint, truncated, rowLimit } = opts;
  const notes: string[] = [];
  if (truncated) notes.push(`结果已截断至 ${rowLimit} 行`);

  const tableSpec = (field: string, labels: string[], role: "temporal" | "categorical"): ChartSpec =>
    ({ chartType: "table", stack: "none", x: { field, role, labels }, series: [], notes });

  if (rows.length === 0 || columns.length === 0) return tableSpec(columns[0] ?? "", [], "categorical");

  const roles = detectColumnRoles(rows, columns);
  const hintDims = (hint?.dimensions ?? []).filter(c => columns.includes(c));
  const hintMeasures = (hint?.measures ?? []).filter(c => columns.includes(c));
  const seriesBy = hint?.seriesBy && columns.includes(hint.seriesBy) ? hint.seriesBy : undefined;
  const chartType: ChartType = CHART_TYPES.includes(hint?.chartType as ChartType)
    ? (hint!.chartType as ChartType) : "table";

  const xField = hintDims[0] ?? columns.find(c => roles[c] !== "numeric") ?? columns[0];
  const xRole = roles[xField] === "temporal" ? "temporal" : "categorical";

  // 注意:chartType === "table" 不在这里提前返回——series 照常算,前端才能切成图表。
  let measureFields = hintMeasures.filter(c => roles[c] === "numeric");
  if (!measureFields.length) measureFields = columns.filter(c => c !== xField && roles[c] === "numeric");
  if (!measureFields.length) return tableSpec(xField, rows.map(r => str(r[xField])), xRole);

  const buildFlat = () => ({
    labels: rows.map(r => str(r[xField])),
    series: measureFields.map(f => {
      const data = rows.map(r => num(r[f]));
      return { name: f, field: f, data, format: inferFormat(f, data) };
    }) as ChartSeries[],
  });

  let labels: string[];
  let series: ChartSeries[];
  if (seriesBy && seriesBy !== xField && roles[seriesBy] !== "numeric") {
    const card = distinctValues(rows, seriesBy).length;
    if (card <= SERIES_BY_MAX) {
      const measure = measureFields[0];
      const p = pivotSeries({ rows, xField, seriesByField: seriesBy, measureField: measure });
      const format = inferFormat(measure, p.groups.flatMap(g => g.data));
      labels = p.labels;
      series = p.groups.map(g => ({ name: g.name, field: measure, data: g.data, format }));
    } else {
      notes.push(`${seriesBy} 取值过多（${card} 个），已改为单系列`);
      ({ labels, series } = buildFlat());
    }
  } else {
    ({ labels, series } = buildFlat());
  }

  const merged = collapse(labels, series);
  labels = merged.labels;
  series = merged.series;
  if (merged.collapsed > 0) notes.push(`${xField} 有重复取值，已按同一刻度聚合`);

  if (chartType === "pie" && series.length > 1) {
    notes.push(`饼图仅展示第一个指标（${series[0].field}）`);
    series = [series[0]];
  }

  let grain: ChartSpec["x"]["grain"];
  if (xRole === "temporal") {
    const dated = labels
      .map((k, i) => ({ i, d: parseTemporal(k) }))
      .filter((x): x is { i: number; d: Date } => x.d !== null)
      .sort((a, b) => a.d.getTime() - b.d.getTime());
    if (dated.length) {
      grain = inferGrain(labels);
      const rowKeys = dated.map(x => toTickKey(x.d, grain!));
      const ordered = series.map(s => ({ ...s, data: dated.map(x => s.data[x.i]) }));
      const tickKeys = enumerateTicks(rowKeys[0], rowKeys[rowKeys.length - 1], grain);
      const filledRes = fillGaps({ tickKeys, rowKeys, series: ordered });
      series = filledRes.series;
      if (filledRes.filled > 0) {
        notes.push(`已补齐 ${filledRes.filled} 个无数据的时间点（按 0 计）`);
      }
      const crossYear = new Set(tickKeys.map(k => k.slice(0, 4))).size > 1;
      labels = tickKeys.map(k => formatTimeLabel(k, grain!, crossYear));
    }
  }

  const hintStack = STACKS.includes(hint?.stack as StackMode) ? (hint!.stack as StackMode) : "none";
  const stack: StackMode = chartType === "bar" && series.length > 1 ? hintStack : "none";

  return {
    chartType, stack,
    x: { field: xField, role: xRole, labels, ...(grain ? { grain } : {}) },
    series, notes,
  };
}
