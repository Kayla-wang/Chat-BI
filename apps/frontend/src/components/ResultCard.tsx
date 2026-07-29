import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import type { ChartType, InsightFact, ResultPayload } from "@chatbi/shared";
import { specToEchartsOption } from "@chatbi/shared";
import { InsightPanel } from "./InsightPanel";

// P1a 临时色板:先用 ECharts 默认色序,P1b 换成 theme/chartPalette 的可访问色板。
const PALETTE = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272", "#fc8452", "#9a60b4"];
const TYPES: ChartType[] = ["bar", "line", "pie", "table"];
const MAX_TABLE_ROWS = 100;

export function ResultCard({ payload, insight, facts }: {
  payload: ResultPayload; insight: string; facts: InsightFact[];
}) {
  const [type, setType] = useState<ChartType>(payload.spec.chartType);
  const ref = useRef<HTMLDivElement>(null);

  // 切类型不重算数据,只覆盖 chartType;stack 只对 bar 有意义。
  const option = useMemo(() => specToEchartsOption({
    ...payload.spec,
    chartType: type,
    stack: type === "bar" ? payload.spec.stack : "none",
  }, PALETTE), [payload.spec, type]);

  useEffect(() => {
    if (type === "table" || !ref.current) return;
    let chart: echarts.ECharts | undefined;
    try {
      chart = echarts.init(ref.current);
      chart.setOption(option as echarts.EChartsOption, true);
    } catch { /* jsdom 无 canvas:忽略 */ }
    return () => {
      try { chart?.dispose(); } catch { /* jsdom 无 canvas:忽略 */ }
    };
  }, [type, option]);

  const shown = payload.table.rows.slice(0, MAX_TABLE_ROWS);
  const hidden = payload.table.rows.length - shown.length;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        {TYPES.map(t => (
          <button key={t} aria-pressed={type === t} onClick={() => setType(t)}>{t}</button>
        ))}
      </div>

      {type !== "table" && <div ref={ref} style={{ width: "100%", height: 320 }} data-testid="chart" />}

      {payload.spec.notes.map(n => (
        <p key={n} data-testid="note" style={{ fontSize: 12 }}>ⓘ {n}</p>
      ))}

      <details>
        <summary>查看 SQL</summary>
        <pre style={{ whiteSpace: "pre-wrap" }}>{payload.sql}</pre>
      </details>

      <InsightPanel text={insight} facts={facts} format={payload.spec.series[0]?.format} />

      <details open={payload.table.rows.length <= 20}>
        <summary>
          数据表格（{payload.table.rows.length} 行 × {payload.table.columns.length} 列）
        </summary>
        <table>
          <thead><tr>{payload.table.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i}>{payload.table.columns.map(c => <td key={c}>{String(r[c])}</td>)}</tr>
            ))}
          </tbody>
        </table>
        {hidden > 0 && (
          <p style={{ fontSize: 12 }}>仅显示前 {MAX_TABLE_ROWS} 行,另有 {hidden} 行未展示</p>
        )}
      </details>
    </div>
  );
}
