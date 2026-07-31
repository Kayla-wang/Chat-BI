import type { TableSchema } from "@chatbi/shared";
import { DbClient } from "../../dbClient";
import { wrapTimeout } from "../../sqlGuard";
import type { Driver, QueryResult, TestResult } from "../driver";
import { SQLITE_DIALECT } from "../dialect";
import { mapSqliteError } from "../errors";
import type { DsConfig, WritePrivilege } from "../types";

type SqliteConfig = Extract<DsConfig, { kind: "sqlite" }>;

/**
 * SQLite 驱动:只读打开文件,写操作由引擎硬拒——这是三种源里最强的只读保证。
 * 超时只有 wrapTimeout 兜底:better-sqlite3 同步执行,长查询会堵住事件循环,
 * 进程内无法真正掐断(不暴露 sqlite3_interrupt)。契约测试里以 timeoutEnforcement: "none" 标注。
 */
export function createSqliteDriver(config: SqliteConfig): Driver {
  let client: DbClient | null = null;
  const open = (): DbClient => {
    if (!client) {
      try {
        client = new DbClient(config.path, { readonly: true });
      } catch (e) {
        throw mapSqliteError(e);
      }
    }
    return client;
  };

  return {
    kind: "sqlite",
    dialect: SQLITE_DIALECT,

    async testConnection(): Promise<TestResult> {
      try {
        open().getSchema();
        return { ok: true, writePrivilege: "readonly" };
      } catch (e) {
        const err = mapSqliteError(e);
        return { ok: false, code: err.code, message: err.message, details: err.details };
      }
    },

    async introspect(): Promise<TableSchema[]> {
      try {
        return open().getSchema().filter(t => !t.tableName.startsWith("sqlite_"));
      } catch (e) {
        throw mapSqliteError(e);
      }
    },

    async runQuery(sql: string, limit: number, timeoutMs: number): Promise<QueryResult> {
      try {
        return await wrapTimeout(
          timeoutMs,
          Promise.resolve().then(() => open().runQuery(sql, limit)),
        );
      } catch (e) {
        throw mapSqliteError(e);
      }
    },

    async probeWritePrivilege(): Promise<WritePrivilege> {
      // 只读连接,恒定只读。
      return "readonly";
    },

    async close(): Promise<void> {
      client?.close();
      client = null;
    },
  };
}
