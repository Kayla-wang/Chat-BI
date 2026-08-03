import { Link } from "react-router-dom";
import { useDataSources } from "../dataSourceStore";
import { KIND_LABEL } from "../dsLabels";
import { StatusBadge } from "./StatusBadge";
import styles from "./DataSourcePicker.module.css";

export function DataSourcePicker() {
  const { list, selectedId, selected, loading, error, select } = useDataSources();

  return (
    <div className={styles.wrap}>
      {error ? (
        <span className={styles.hint} role="alert">{error}</span>
      ) : list.length === 0 ? (
        <span className={styles.hint} data-testid="picker-empty">
          {loading ? "正在读取数据源…" : "无可用数据源,请先到「管理」添加"}
        </span>
      ) : (
        <>
          <label className={styles.label} htmlFor="ds-picker">数据源</label>
          <select
            id="ds-picker"
            className={styles.select}
            value={selectedId ?? ""}
            onChange={e => select(e.target.value)}
          >
            {list.map(d => (
              <option key={d.id} value={d.id}>{d.name} · {KIND_LABEL[d.kind]}</option>
            ))}
          </select>
          {selected && <StatusBadge status={selected.status} writePrivilege={selected.writePrivilege} />}
        </>
      )}
      <Link className={styles.manage} to="/datasources">管理</Link>
    </div>
  );
}
