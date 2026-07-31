import type { Row, TableSchema } from "@chatbi/shared";
import type { DataSourceKind, WritePrivilege } from "./types";
import type { Dialect } from "./dialect";
import type { DsErrorCode } from "./errors";

export interface QueryResult { rows: Row[]; truncated: boolean }

export type TestResult =
  | { ok: true; writePrivilege: WritePrivilege }
  | { ok: false; code: DsErrorCode; message: string; details?: string };

/**
 * 数据源驱动。只有这五个方法——每加一个都要在三个实现里各写一遍,
 * 宁可让上层多写一点组合逻辑。所有失败一律抛 DsError。
 */
export interface Driver {
  readonly kind: DataSourceKind;
  readonly dialect: Dialect;
  /** 连一次并顺带探写权限。调用方直接用返回的 writePrivilege,不要再单独探一次。 */
  testConnection(): Promise<TestResult>;
  introspect(): Promise<TableSchema[]>;
  /** 调用方应已用 enforceLimit(sql, limit + 1) 注入上限;实现负责切回 limit 行并报告是否多出来过。 */
  runQuery(sql: string, limit: number, timeoutMs: number): Promise<QueryResult>;
  probeWritePrivilege(): Promise<WritePrivilege>;
  close(): Promise<void>;
}
