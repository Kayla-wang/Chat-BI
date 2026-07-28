import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import type { ChartPayload, ChartType, Row } from "@chatbi/shared";

function buildOption(rows: Row[], columns: string[], chartType: ChartType): echarts.EChartsOption {
  if (chartType === "table") return {};
  if (chartType === "pie") {
    return { tooltip: { trigger: "item" }, series: [{ type: "pie", data: rows.map(r => ({ name: String(r[columns[0]]), value: Number(r[columns[1]]) })) }] };
  }
  return {
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: rows.map(r => String(r[columns[0]])) },
    yAxis: { type: "value" },
    series: [{ type: chartType, data: rows.map(r => r[columns[1]]) }],
  } as echarts.EChartsOption;
}

const TYPES: ChartType[] = ["bar", "line", "pie", "table"];

export function ResultCard({ payload }: { payload: ChartPayload }) {
  const [type, setType] = useState<ChartType>(payload.chartType);
  const ref = useRef<HTMLDivElement>(null);
  const option = type === payload.chartType ? payload.echartsOption : buildOption(payload.table.rows, payload.table.columns, type);

  useEffect(() => {
    if (type === "table" || !ref.current) return;
    let chart: echarts.ECharts | undefined;
    try {
      chart = echarts.init(ref.current);
      chart.setOption(option as echarts.EChartsOption);
    } catch { /* jsdom 无 canvas:忽略 */ }
    return () => {
      try { chart?.dispose(); } catch { /* jsdom 无 canvas:忽略 */ }
    };
  }, [type, option]);

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        {TYPES.map(t => (
          <button key={t} aria-pressed={type === t} onClick={() => setType(t)}>{t}</button>
        ))}
      </div>
      {type !== "table" && <div ref={ref} style={{ width: "100%", height: 320 }} data-testid="chart" />}
      <table>
        <thead><tr>{payload.table.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {payload.table.rows.map((r, i) => (
            <tr key={i}>{payload.table.columns.map(c => <td key={c}>{String(r[c])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
