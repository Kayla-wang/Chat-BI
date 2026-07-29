import Database from "better-sqlite3";
import type { Database as DB } from "better-sqlite3";
import { dirname } from "node:path";
import { mkdirSync } from "node:fs";
import type { TableSchema, Row } from "@chatbi/shared";

export class DbClient {
  private db: DB;
  private readonlyMode: boolean;

  constructor(path: string, opts: { readonly?: boolean } = {}) {
    this.readonlyMode = opts.readonly ?? false;
    if (!this.readonlyMode) mkdirSync(dirname(path), { recursive: true });
    this.db = new Database(path, { readonly: this.readonlyMode });
    if (!this.readonlyMode) this.db.pragma("journal_mode = WAL");
  }

  /** 仅可写连接可用:迁移与测试建表。只读连接上调用直接抛错。 */
  execRaw(sql: string): void {
    if (this.readonlyMode) throw new Error("connection is readonly: execRaw not allowed");
    this.db.exec(sql);
  }

  getSchema(): TableSchema[] {
    const tables = this.db.prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).all() as { name: string }[];
    return tables.map(t => {
      const cols = this.db.pragma(`table_info(${t.name})`) as any[];
      const fks = this.db.pragma(`foreign_key_list(${t.name})`) as any[];
      return {
        tableName: t.name,
        columns: cols.map(c => ({
          name: c.name, type: c.type,
          notNull: Boolean(c.notnull), pk: Boolean(c.pk),
        })),
        foreignKeys: fks.map(f => ({ column: f.from, refTable: f.table, refColumn: f.to })),
      };
    });
  }

  /**
   * 调用方应已用 enforceLimit(sql, limit + 1) 注入过上限。
   * 这里只负责切回 limit 行,并报告是否多出来过(= 真的被截断)。
   */
  runQuery(sql: string, limit: number): { rows: Row[]; truncated: boolean } {
    const stmt = this.db.prepare(sql);
    if (!stmt.reader) throw new Error("statement does not return rows");
    const all = stmt.all() as Row[];
    return { rows: all.slice(0, limit), truncated: all.length > limit };
  }

  close(): void { this.db.close(); }
}
