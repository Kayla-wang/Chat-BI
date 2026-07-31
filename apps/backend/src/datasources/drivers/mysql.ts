import mysql from "mysql2/promise";
import type { TableSchema } from "@chatbi/shared";
import { wrapTimeout } from "../../sqlGuard";
import type { Driver, QueryResult, TestResult } from "../driver";
import { MYSQL_DIALECT } from "../dialect";
import { mapMysqlError } from "../errors";
import type { DsConfig, WritePrivilege } from "../types";

type MysqlConfig = Extract<DsConfig, { kind: "mysql" }>;

const WRITE_PRIVS = /\b(ALL PRIVILEGES|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|SUPER|FILE|INDEX|REFERENCES|TRIGGER|LOCK TABLES)\b/i;

/**
 * 只看 `GRANT <权限段> ON ...` 里的权限段,避免被 `insert_logs` 这种库名骗到。
 * 认不出格式返回 unknown——宁可显示「权限未知」也不谎称只读。
 */
export function parseMysqlGrants(lines: string[]): WritePrivilege {
  let sawAny = false;
  for (const line of lines) {
    const m = /^\s*GRANT\s+([\s\S]*?)\s+ON\s+/i.exec(line);
    if (!m) continue;
    sawAny = true;
    if (WRITE_PRIVS.test(m[1])) return "writable";
  }
  return sawAny ? "readonly" : "unknown";
}

export function createMysqlDriver(config: MysqlConfig): Driver {
  let conn: mysql.Connection | null = null;
  let appliedTimeout = -1;

  async function connect(): Promise<mysql.Connection> {
    if (conn) return conn;
    try {
      conn = await mysql.createConnection({
        host: config.host, port: config.port, database: config.database,
        user: config.user, password: config.password,
        ssl: config.ssl ? {} : undefined,
        // DECIMAL 默认给字符串、日期默认给 Date 对象,都会破坏图表推导。
        // BI 要的是可画的数与统一的日期文本,精度上的取舍是有意的。
        decimalNumbers: true,
        dateStrings: true,
        supportBigNumbers: true,
        multipleStatements: false,
      });
      // 会话级只读。拦不住显式 START TRANSACTION,真正的防线是只读账号 + sqlGuard。
      await conn.query("SET SESSION TRANSACTION READ ONLY");
      return conn;
    } catch (e) {
      conn = null;
      throw mapMysqlError(e);
    }
  }

  async function applyTimeout(c: mysql.Connection, timeoutMs: number): Promise<void> {
    if (appliedTimeout === timeoutMs) return;
    // max_execution_time 只作用于 SELECT,正合我们的用途。
    await c.query(`SET SESSION max_execution_time = ${Number(timeoutMs)}`);
    appliedTimeout = timeoutMs;
  }

  return {
    kind: "mysql",
    dialect: MYSQL_DIALECT,

    async testConnection(): Promise<TestResult> {
      try {
        const c = await connect();
        await c.query("SELECT 1");
        return { ok: true, writePrivilege: await this.probeWritePrivilege() };
      } catch (e) {
        const err = mapMysqlError(e);
        return { ok: false, code: err.code, message: err.message, details: err.details };
      }
    },

    async introspect(): Promise<TableSchema[]> {
      try {
        const c = await connect();
        const [cols] = await c.query(
          `SELECT TABLE_NAME AS t, COLUMN_NAME AS c, COLUMN_TYPE AS ty,
                  IS_NULLABLE AS nullable, COLUMN_KEY AS ck
             FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = ?
            ORDER BY TABLE_NAME, ORDINAL_POSITION`,
          [config.database],
        ) as [Record<string, string>[], unknown];
        const [fks] = await c.query(
          `SELECT TABLE_NAME AS t, COLUMN_NAME AS c,
                  REFERENCED_TABLE_NAME AS rt, REFERENCED_COLUMN_NAME AS rc
             FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = ? AND REFERENCED_TABLE_NAME IS NOT NULL`,
          [config.database],
        ) as [Record<string, string>[], unknown];

        const byTable = new Map<string, TableSchema>();
        for (const r of cols) {
          if (!byTable.has(r.t)) byTable.set(r.t, { tableName: r.t, columns: [], foreignKeys: [] });
          byTable.get(r.t)!.columns.push({
            name: r.c, type: r.ty,
            notNull: r.nullable === "NO",
            pk: r.ck === "PRI",
          });
        }
        for (const r of fks) {
          byTable.get(r.t)?.foreignKeys.push({ column: r.c, refTable: r.rt, refColumn: r.rc });
        }
        return [...byTable.values()];
      } catch (e) {
        throw mapMysqlError(e);
      }
    },

    async runQuery(sql: string, limit: number, timeoutMs: number): Promise<QueryResult> {
      try {
        const c = await connect();
        await applyTimeout(c, timeoutMs);
        // 客户端兜底必须比服务端宽,否则服务端的取消永远来不及触发。
        const [rows] = await wrapTimeout(
          timeoutMs + 500,
          c.query({ sql, timeout: timeoutMs + 400 }) as Promise<[Record<string, never>[], unknown]>,
        );
        const all = rows as unknown as QueryResult["rows"];
        return { rows: all.slice(0, limit), truncated: all.length > limit };
      } catch (e) {
        throw mapMysqlError(e);
      }
    },

    async probeWritePrivilege(): Promise<WritePrivilege> {
      try {
        const c = await connect();
        const [rows] = await c.query("SHOW GRANTS FOR CURRENT_USER()") as [Record<string, string>[], unknown];
        return parseMysqlGrants(rows.map(r => String(Object.values(r)[0] ?? "")));
      } catch {
        return "unknown";   // 探测失败不影响可用性
      }
    },

    async close(): Promise<void> {
      await conn?.end().catch(() => { /* 已断开 */ });
      conn = null;
      appliedTimeout = -1;
    },
  };
}
