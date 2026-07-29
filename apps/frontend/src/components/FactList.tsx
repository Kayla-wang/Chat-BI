import type { InsightFact, ValueFormat } from "@chatbi/shared";
import { renderFactsLines } from "@chatbi/shared";
import styles from "./InsightPanel.module.css";

const DEFAULT_FORMAT: ValueFormat = { kind: "number", decimals: 0, scale: 1 };

export function FactList({ facts, format }: {
  facts: InsightFact[]; format?: ValueFormat;
}) {
  const lines = renderFactsLines(facts, format ?? DEFAULT_FORMAT).filter(Boolean);
  if (lines.length === 0) return null;
  return (
    <details className={styles.facts} data-testid="fact-list">
      <summary className={styles.factsSummary}>计算依据（{lines.length} 项）</summary>
      <ul className={styles.factItems}>
        {lines.map(l => <li key={l} data-numeric>{l}</li>)}
      </ul>
    </details>
  );
}
