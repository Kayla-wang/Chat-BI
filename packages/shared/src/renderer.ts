import type { ChartSpec, ChartSeries, ValueFormat } from "./types";
import { formatValue } from "./format";

const PERCENT_FORMAT: ValueFormat = { kind: "percent", decimals: 1 };

/** 把每个 x 位置上各系列的值换算成占比,列和为 0 时整列产出 null。 */
function normalizeToPercent(series: ChartSeries[]): ChartSeries[] {
  const len = series[0]?.data.length ?? 0;
  const sums: number[] = [];
  for (let i = 0; i < len; i++) {
    sums[i] = series.reduce((acc, s) => acc + (s.data[i] ?? 0), 0);
  }
  return series.map(s => ({
    ...s,
    format: PERCENT_FORMAT,
    data: s.data.map((v, i) => (sums[i] === 0 || v === null ? null : (v / sums[i]) * 100)),
  }));
}

export function specToEchartsOption(spec: ChartSpec, palette: string[]): Record<string, unknown> {
  if (spec.chartType === "table" || spec.series.length === 0) return {};

  if (spec.chartType === "pie") {
    const first = spec.series[0];
    return {
      color: palette,
      tooltip: { trigger: "item", valueFormatter: (v: number) => formatValue(v, first.format) },
      legend: { data: spec.x.labels },
      series: [{
        type: "pie",
        name: first.name,
        data: spec.x.labels.map((name, i) => ({ name, value: first.data[i] })),
      }],
    };
  }

  const isPercent = spec.chartType === "bar" && spec.stack === "percent";
  const series = isPercent ? normalizeToPercent(spec.series) : spec.series;
  const axisFormat = series[0].format;

  const option: Record<string, unknown> = {
    color: palette,
    tooltip: { trigger: "axis", valueFormatter: (v: number) => formatValue(v, axisFormat) },
    xAxis: { type: "category", data: spec.x.labels },
    yAxis: {
      type: "value",
      axisLabel: { formatter: (v: number) => formatValue(v, axisFormat) },
      ...(isPercent ? { max: 100, min: 0 } : {}),
    },
    series: series.map(s => ({
      type: spec.chartType,
      name: s.name,
      data: s.data,
      ...(spec.stack === "none" ? {} : { stack: "total" }),
    })),
  };
  if (series.length > 1) option.legend = { data: series.map(s => s.name) };
  return option;
}
