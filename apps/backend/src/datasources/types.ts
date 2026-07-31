import type { DataSourceKind, DsConfig, WritePrivilege } from "@chatbi/shared";

// 让本目录下的导入路径统一,不必到处区分「这个类型在 shared 还是在这里」。
export type { DataSourceKind, DsConfig, WritePrivilege } from "@chatbi/shared";

export interface DataSourceRecord {
  id: string;
  name: string;
  kind: DataSourceKind;
  owner: string;
  /** null 表示解密失败,此时 configError 为 true。 */
  config: DsConfig | null;
  configError: boolean;
  writePrivilege: WritePrivilege | null;
  createdAt: string;
  updatedAt: string;
  lastCheckAt: string | null;
  lastCheckOk: boolean | null;
  lastCheckError: string | null;
}

/** 给人看的脱敏摘要。永远不含密码——这个函数是密码不外泄的关键一环。 */
export function targetLabel(config: DsConfig): string {
  if (config.kind === "sqlite") return config.path;
  return `${config.kind}://${config.user}@${config.host}:${config.port}/${config.database}`;
}
