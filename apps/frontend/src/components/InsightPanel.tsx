import type { InsightFact, ValueFormat } from "@chatbi/shared";
import { renderFactsLines } from "@chatbi/shared";

const DEFAULT_FORMAT: ValueFormat = { kind: "number", decimals: 0, scale: 1 };

export function InsightPanel({ text, facts, format }: {
  text: string; facts: InsightFact[]; format?: ValueFormat;
}) {
  if (!text && facts.length === 0) return null;
  const lines = renderFactsLines(facts, format ?? DEFAULT_FORMAT).filter(Boolean);
  return (
    <section>
      <h3>洞察</h3>
      <p data-testid="insight-text" style={{ whiteSpace: "pre-wrap" }}>{text}</p>
      {lines.length > 0 && (
        <details>
          <summary>计算依据（{lines.length} 项）</summary>
          <ul>{lines.map(l => <li key={l}>{l}</li>)}</ul>
        </details>
      )}
    </section>
  );
}
