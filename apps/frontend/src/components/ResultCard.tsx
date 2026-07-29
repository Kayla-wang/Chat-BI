import { useMemo, useState } from "react";
import type { ChartType, InsightFact, ResultPayload } from "@chatbi/shared";
import { ChartView } from "./ChartView";
import { SqlDisclosure } from "./SqlDisclosure";
import { InsightPanel } from "./InsightPanel";
import { DataTable } from "./DataTable";
import styles from "./ResultCard.module.css";

const TYPES: { type: ChartType; label: string }[] = [
  { type: "line", label: "折线" },
  { type: "bar", label: "柱状" },
  { type: "pie", label: "饼图" },
  { type: "table", label: "表格" },
];

export function ResultCard({ payload, insight, facts }: {
  payload: ResultPayload; insight: string; facts: InsightFact[];
}) {
  const [type, setType] = useState<ChartType>(payload.spec.chartType);

  // 切类型不重算数据,只覆盖 chartType;stack 只对 bar 有意义。
  const spec = useMemo(() => ({
    ...payload.spec,
    chartType: type,
    stack: type === "bar" ? payload.spec.stack : ("none" as const),
  }), [payload.spec, type]);

  return (
    <div className={styles.card}>
      <div className={styles.toolbar}>
        <div className={styles.segmented} role="group" aria-label="图表类型">
          {TYPES.map(t => (
            <button
              key={t.type}
              type="button"
              className={styles.segment}
              aria-pressed={type === t.type}
              onClick={() => setType(t.type)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {type !== "table" && <ChartView spec={spec} />}

      {payload.spec.notes.length > 0 && (
        <ul className={styles.notes}>
          {payload.spec.notes.map(n => (
            <li key={n} className={styles.note} data-testid="note">ⓘ {n}</li>
          ))}
        </ul>
      )}

      <SqlDisclosure sql={payload.sql} />
      <InsightPanel text={insight} facts={facts} format={payload.spec.series[0]?.format} />
      <DataTable columns={payload.table.columns} rows={payload.table.rows} />
    </div>
  );
}
