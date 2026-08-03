import type { TableSchema } from "@chatbi/shared";
import styles from "./SchemaTree.module.css";

/**
 * UTC ISO 串 → 「2026-08-03 10:20」。故意不用 toLocaleString:
 * 它的输出随宿主 locale 与时区变,测试与截图都不可复现。
 */
export const fmtIsoMinute = (iso: string): string => iso.slice(0, 16).replace("T", " ");

export function SchemaTree({ schema, fetchedAt }: { schema: TableSchema[]; fetchedAt?: string | null }) {
  if (schema.length === 0) {
    return (
      <p className={styles.empty} data-testid="schema-empty">
        暂无表结构,点「刷新结构」抓取一次。
      </p>
    );
  }

  return (
    <div className={styles.wrap}>
      {fetchedAt && (
        <p className={styles.meta} data-testid="schema-fetched-at">
          结构抓取于 {fmtIsoMinute(fetchedAt)}(UTC)
        </p>
      )}
      {schema.map(t => (
        // 用原生 details:键盘可达、无需自己管展开状态,与 SqlDisclosure 一致。
        <details key={t.tableName} className={styles.table}>
          <summary className={styles.summary}>
            <span className={styles.tableName}>{t.tableName}</span>
            <span className={styles.count}>{t.columns.length} 列</span>
          </summary>
          <table className={styles.columns}>
            <tbody>
              {t.columns.map(c => (
                <tr key={c.name}>
                  <td className={styles.colName}>{c.name}</td>
                  <td className={styles.colType}>{c.type}</td>
                  <td className={styles.flags}>
                    {c.pk && <span className={styles.flag} data-testid={`pk-${c.name}`}>主键</span>}
                    {c.notNull && !c.pk && (
                      <span className={styles.flag} data-testid={`notnull-${c.name}`}>非空</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {t.foreignKeys.length > 0 && (
            <ul className={styles.fks} data-testid="fk-list">
              {t.foreignKeys.map(fk => (
                <li key={`${fk.column}-${fk.refTable}-${fk.refColumn}`}>
                  {fk.column} → {fk.refTable}.{fk.refColumn}
                </li>
              ))}
            </ul>
          )}
        </details>
      ))}
    </div>
  );
}
