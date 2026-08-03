import type { ReactNode } from "react";
import styles from "./AppShell.module.css";

export function AppShell({ children, toolbar }: { children: ReactNode; toolbar?: ReactNode }) {
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <h1 className={styles.brand}>Chat-BI</h1>
        {/* 槽位由 App 填 DataSourcePicker:AppShell 不读 Context,保持纯展示好测。 */}
        <div className={styles.slot} data-testid="datasource-slot">{toolbar}</div>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
