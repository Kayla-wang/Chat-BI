import type { DataSourceKind, WritePrivilege } from "@chatbi/shared";

export const KIND_LABEL: Record<DataSourceKind, string> = {
  sqlite: "SQLite", mysql: "MySQL", postgres: "PostgreSQL",
};

export const PRIVILEGE_LABEL: Record<WritePrivilege, string> = {
  readonly: "只读", writable: "可写", unknown: "未知",
};
