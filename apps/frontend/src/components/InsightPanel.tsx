import type { InsightFact, ValueFormat } from "@chatbi/shared";
import { FactList } from "./FactList";
import styles from "./InsightPanel.module.css";

export function InsightPanel({ text, facts, format }: {
  text: string; facts: InsightFact[]; format?: ValueFormat;
}) {
  if (!text && facts.length === 0) return null;
  return (
    <section className={styles.panel} aria-label="洞察">
      <h3 className={styles.title}>洞察</h3>
      <p className={styles.text} data-testid="insight-text">{text}</p>
      <FactList facts={facts} format={format} />
    </section>
  );
}
