import styles from "./SqlDisclosure.module.css";

export function SqlDisclosure({ sql }: { sql: string }) {
  if (!sql) return null;
  return (
    <details className={styles.wrap} data-testid="sql-disclosure">
      <summary className={styles.summary}>查看 SQL</summary>
      <pre className={styles.code}>{sql}</pre>
    </details>
  );
}
