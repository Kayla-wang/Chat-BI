// pg 是 CJS:必须默认导入再取属性,具名导入在真实启动时抛 SyntaxError。
import pg from "pg";
const { Client } = pg;
import type { TableSchema } from "@chatbi/shared";
import { wrapTimeout } from "../../sqlGuard";
import type { Driver, QueryResult, TestResult } from "../driver";
import { POSTGRES_DIALECT } from "../dialect";
import { mapPgError } from "../errors";
import type { DsConfig, WritePrivilege } from "../types";

type PgConfig = Extract<DsConfig, { kind: "postgres" }>;

/**
 * 按连接覆盖类型解析:numeric/int8 默认给字符串、date/timestamp 默认给 Date 对象,
 * 都会破坏图表推导。不用 pg.types.setTypeParser——那是进程全局的。
 */
const OVERRIDES: Record<number, (v: string) => unknown> = {
  20: v => Number(v),     // int8
  1700: v => Number(v),   // numeric
  1082: v => v,           // date      → 原样文本
  1114: v => v,           // timestamp → 原样文本
  1184: v => v,           // timestamptz
};
const typeConfig = {
  getTypeParser: ((oid: number, format?: unknown) =>
    OVERRIDES[oid] ?? (pg.types.getTypeParser as (o: number, f?: unknown) => unknown)(oid, format)
  ) as never,
};

const COLUMNS_SQL = `
SELECT c.table_name AS t, c.column_name AS col, c.data_type AS ty,
       c.is_nullable AS nullable,
       (pk.column_name IS NOT NULL) AS is_pk
  FROM information_schema.columns c
  LEFT JOIN (
    SELECT kcu.table_name, kcu.column_name
      FROM information_schema.table_constraints tc
      JOIN information_schema.key_column_usage kcu
        ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
     WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = $1
  ) pk ON pk.table_name = c.table_name AND pk.column_name = c.column_name
 WHERE c.table_schema = $1
 ORDER BY c.table_name, c.ordinal_position`;

const FK_SQL = `
SELECT tc.table_name AS t, kcu.column_name AS col,
       ccu.table_name AS rt, ccu.column_name AS rc
  FROM information_schema.table_constraints tc
  JOIN information_schema.key_column_usage kcu
    ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
  JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
 WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = $1`;

const PRIV_SQL = `
SELECT current_setting('is_superuser') = 'on' AS is_super,
       has_schema_privilege(current_user, $1, 'CREATE') AS can_create,
       EXISTS (
         SELECT 1 FROM information_schema.table_privileges
          WHERE grantee = current_user AND table_schema = $1
            AND privilege_type IN ('INSERT','UPDATE','DELETE')
       ) AS can_write`;

export function createPgDriver(config: PgConfig): Driver {
  const schema = config.schema ?? "public";
  let client: pg.Client | null = null;

  async function connect(): Promise<pg.Client> {
    if (client) return client;
    const c = new Client({
      host: config.host, port: config.port, database: config.database,
      user: config.user, password: config.password,
      ssl: config.ssl ? { rejectUnauthorized: true } : false,
      types: typeConfig,
    });
    try {
      await c.connect();
      client = c;
      return c;
    } catch (e) {
      await c.end().catch(() => { /* 连都没连上 */ });
      throw mapPgError(e);
    }
  }

  return {
    kind: "postgres",
    dialect: POSTGRES_DIALECT,

    async testConnection(): Promise<TestResult> {
      try {
        const c = await connect();
        await c.query("SELECT 1");
        return { ok: true, writePrivilege: await this.probeWritePrivilege() };
      } catch (e) {
        const err = mapPgError(e);
        return { ok: false, code: err.code, message: err.message, details: err.details };
      }
    },

    async introspect(): Promise<TableSchema[]> {
      try {
        const c = await connect();
        const cols = await c.query(COLUMNS_SQL, [schema]);
        const fks = await c.query(FK_SQL, [schema]);
        const byTable = new Map<string, TableSchema>();
        for (const r of cols.rows as Record<string, string | boolean>[]) {
          const t = String(r.t);
          if (!byTable.has(t)) byTable.set(t, { tableName: t, columns: [], foreignKeys: [] });
          byTable.get(t)!.columns.push({
            name: String(r.col), type: String(r.ty),
            notNull: r.nullable === "NO",
            pk: r.is_pk === true,
          });
        }
        for (const r of fks.rows as Record<string, string>[]) {
          byTable.get(r.t)?.foreignKeys.push({ column: r.col, refTable: r.rt, refColumn: r.rc });
        }
        return [...byTable.values()];
      } catch (e) {
        throw mapPgError(e);
      }
    },

    async runQuery(sql: string, limit: number, timeoutMs: number): Promise<QueryResult> {
      const c = await connect();
      try {
        // 只读事务:PG 服务端硬拒写入,是这三种源里最强的一档。
        await c.query("BEGIN READ ONLY");
        await c.query(`SET LOCAL statement_timeout = ${Number(timeoutMs)}`);
        // 客户端兜底比服务端宽,否则服务端的取消来不及触发。
        const res = await wrapTimeout(timeoutMs + 500, c.query(sql));
        await c.query("COMMIT");
        const all = res.rows as unknown as QueryResult["rows"];
        return { rows: all.slice(0, limit), truncated: all.length > limit };
      } catch (e) {
        // 不 ROLLBACK 会让连接卡在失败事务里,之后每条查询都报 25P02。
        await c.query("ROLLBACK").catch(() => { /* 连接可能已断 */ });
        throw mapPgError(e);
      }
    },

    async probeWritePrivilege(): Promise<WritePrivilege> {
      try {
        const c = await connect();
        const r = await c.query(PRIV_SQL, [schema]);
        const row = r.rows[0] as { is_super: boolean; can_create: boolean; can_write: boolean };
        return row.is_super || row.can_create || row.can_write ? "writable" : "readonly";
      } catch {
        return "unknown";
      }
    },

    async close(): Promise<void> {
      await client?.end().catch(() => { /* 已断开 */ });
      client = null;
    },
  };
}
