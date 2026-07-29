import type { ReactNode } from "react";
import styles from "./AppShell.module.css";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <h1 className={styles.brand}>Chat-BI</h1>
        {/* P2 的数据源切换入口先占位 */}
        <span className={styles.slot} data-testid="datasource-slot">示例库 · SQLite</span>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
