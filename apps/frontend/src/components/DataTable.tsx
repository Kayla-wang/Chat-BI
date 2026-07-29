import type { Row } from "@chatbi/shared";
import styles from "./DataTable.module.css";

export const MAX_TABLE_ROWS = 100;
const DEFAULT_OPEN_THRESHOLD = 20;

const cell = (v: Row[string]) =>
  v === null || v === undefined ? "—" : String(v);

export function DataTable({ columns, rows, maxRows = MAX_TABLE_ROWS }: {
  columns: string[]; rows: Row[]; maxRows?: number;
}) {
  const shown = rows.slice(0, maxRows);
  const hidden = rows.length - shown.length;

  return (
    <details
      className={styles.wrap}
      data-testid="data-table"
      open={rows.length <= DEFAULT_OPEN_THRESHOLD}
    >
      <summary className={styles.summary}>
        数据表格（{rows.length} 行 × {columns.length} 列）
      </summary>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr>{columns.map(c => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i}>
                {columns.map(c => {
                  const v = r[c];
                  const numeric = typeof v === "number";
                  return (
                    <td key={c} className={numeric ? styles.numeric : undefined} data-numeric={numeric || undefined}>
                      {cell(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hidden > 0 && (
        <p className={styles.hint}>仅显示前 {maxRows} 行,另有 {hidden} 行未展示</p>
      )}
    </details>
  );
}
