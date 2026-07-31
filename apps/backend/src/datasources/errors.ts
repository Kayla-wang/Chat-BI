import type { DsErrorCode } from "@chatbi/shared";

// 与 DsConfig 同理:类型定义在 shared,本目录 re-export 一次,免得导入路径两套。
export type { DsErrorCode } from "@chatbi/shared";

export class DsError extends Error {
  constructor(readonly code: DsErrorCode, message: string, readonly details?: string) {
    super(message);
    this.name = "DsError";
  }
}

/** 只有与 SQL 内容相关的错误值得把原因喂回模型重试;连不上库重试只是多等一个超时。 */
export function isRetryable(code: DsErrorCode): boolean {
  return code === "SQL_ERROR" || code === "SCHEMA_STALE";
}

const NET_CODES = new Set([
  "ECONNREFUSED", "ENOTFOUND", "ETIMEDOUT", "EHOSTUNREACH", "ENETUNREACH", "ECONNRESET", "EPIPE",
]);

const MESSAGES: Record<DsErrorCode, string> = {
  CONNECTION_ERROR: "无法连接到数据库,请检查地址、端口与网络",
  AUTH_ERROR: "认证失败,请检查用户名与密码",
  DB_NOT_FOUND: "数据库或文件不存在,请检查库名/路径",
  NOT_FOUND: "数据源不存在,可能已被删除",
  DUPLICATE_NAME: "已有同名数据源,请换个名字",
  TIMEOUT: "查询超时,请缩小查询范围或调高 QUERY_TIMEOUT_MS",
  SQL_ERROR: "SQL 执行失败",
  SCHEMA_STALE: "表或列不存在;表结构可能已变更,试试刷新结构",
  PERMISSION_ERROR: "当前账号权限不足",
  DECRYPT_ERROR: "凭据无法解密,请重新填写连接信息",
  UNKNOWN: "数据库返回了未预期的错误",
};

function build(code: DsErrorCode, e: unknown): DsError {
  const raw = e instanceof Error ? e.message : String(e);
  return new DsError(code, MESSAGES[code], raw);
}

const codeOf = (e: unknown): string =>
  typeof (e as { code?: unknown })?.code === "string" ? (e as { code: string }).code : "";

const MYSQL_MAP: Record<string, DsErrorCode> = {
  ER_ACCESS_DENIED_ERROR: "AUTH_ERROR",
  ER_DBACCESS_DENIED_ERROR: "AUTH_ERROR",
  ER_BAD_DB_ERROR: "DB_NOT_FOUND",
  ER_QUERY_TIMEOUT: "TIMEOUT",
  PROTOCOL_SEQUENCE_TIMEOUT: "TIMEOUT",
  ER_NO_SUCH_TABLE: "SCHEMA_STALE",
  ER_BAD_FIELD_ERROR: "SCHEMA_STALE",
  ER_PARSE_ERROR: "SQL_ERROR",
  ER_TABLEACCESS_DENIED_ERROR: "PERMISSION_ERROR",
  ER_COLUMNACCESS_DENIED_ERROR: "PERMISSION_ERROR",
  ER_SPECIFIC_ACCESS_DENIED_ERROR: "PERMISSION_ERROR",
  ER_CANT_UPDATE_WITH_READLOCK: "PERMISSION_ERROR",
};

export function mapMysqlError(e: unknown): DsError {
  if (e instanceof DsError) return e;
  const code = codeOf(e);
  if (NET_CODES.has(code)) return build("CONNECTION_ERROR", e);
  const mapped = MYSQL_MAP[code];
  if (mapped) return build(mapped, e);
  if (/query timeout/i.test((e as Error)?.message ?? "")) return build("TIMEOUT", e);
  return build("UNKNOWN", e);
}

const PG_MAP: Record<string, DsErrorCode> = {
  "28P01": "AUTH_ERROR",
  "28000": "AUTH_ERROR",
  "3D000": "DB_NOT_FOUND",
  "57014": "TIMEOUT",       // query_canceled,statement_timeout 生效时就是这个
  "42P01": "SCHEMA_STALE",  // undefined_table
  "42703": "SCHEMA_STALE",  // undefined_column
  "42601": "SQL_ERROR",     // syntax_error
  "42883": "SQL_ERROR",     // undefined_function
  "42804": "SQL_ERROR",     // datatype_mismatch
  "42501": "PERMISSION_ERROR",
  "25006": "PERMISSION_ERROR",  // read_only_sql_transaction
};

export function mapPgError(e: unknown): DsError {
  if (e instanceof DsError) return e;
  const code = codeOf(e);
  if (NET_CODES.has(code)) return build("CONNECTION_ERROR", e);
  const mapped = PG_MAP[code];
  if (mapped) {
    if (mapped === "PERMISSION_ERROR" && code === "25006") {
      return new DsError("PERMISSION_ERROR", "该连接是只读事务,拒绝写入操作",
        e instanceof Error ? e.message : String(e));
    }
    return build(mapped, e);
  }
  if (/query timeout/i.test((e as Error)?.message ?? "")) return build("TIMEOUT", e);
  return build("UNKNOWN", e);
}

export function mapSqliteError(e: unknown): DsError {
  if (e instanceof DsError) return e;
  const code = codeOf(e);
  const msg = (e as Error)?.message ?? "";
  if (/query timeout/i.test(msg)) return build("TIMEOUT", e);
  if (code === "SQLITE_CANTOPEN") return build("DB_NOT_FOUND", e);
  if (code.startsWith("SQLITE_READONLY")) return build("PERMISSION_ERROR", e);
  if (/no such (table|column)/i.test(msg)) return build("SCHEMA_STALE", e);
  if (code.startsWith("SQLITE_")) return build("SQL_ERROR", e);
  return build("UNKNOWN", e);
}
