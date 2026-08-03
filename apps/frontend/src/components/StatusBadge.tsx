import type { DataSourceStatus, WritePrivilege } from "@chatbi/shared";
import styles from "./StatusBadge.module.css";

const STATUS_TEXT: Record<DataSourceStatus, string> = {
  ok: "正常",
  error: "连接失败",
  needs_reconfig: "需重新填写凭据",
  unchecked: "未检查",
};

// readonly 是期望状态,不占视觉;另两种才提示。
const PRIVILEGE_TEXT: Partial<Record<WritePrivilege, string>> = {
  writable: "建议改用只读账号",
  unknown: "写权限未知",
};

export function StatusBadge({ status, writePrivilege }: {
  status: DataSourceStatus;
  writePrivilege?: WritePrivilege | null;
}) {
  const privilege = writePrivilege ? PRIVILEGE_TEXT[writePrivilege] : undefined;
  return (
    <span className={styles.wrap}>
      <span
        className={`${styles.dot} ${styles[status]}`}
        data-testid="status-dot"
        data-status={status}
        aria-hidden="true"
      />
      <span className={styles.label}>{STATUS_TEXT[status]}</span>
      {privilege && (
        <span
          className={`${styles.privilege} ${writePrivilege === "writable" ? styles.warn : styles.muted}`}
          data-testid="privilege-badge"
          data-privilege={writePrivilege}
        >
          {privilege}
        </span>
      )}
    </span>
  );
}
