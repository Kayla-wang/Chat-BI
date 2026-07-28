import Database from "better-sqlite3";
import type { Database as DB } from "better-sqlite3";
import { dirname } from "node:path";
import { mkdirSync } from "node:fs";
import type { TableSchema, Row } from "@chatbi/shared";

export class DbClient {
  private db: DB;
  constructor(private path: string) {
    mkdirSync(dirname(path), { recursive: true });
    this.db = new Database(path);
    this.db.pragma("journal_mode = WAL");
  }
  /** 仅用于测试/迁移:直接执行任意 SQL(不含只读保护)。*/
  execRaw(sql: string) { this.db.exec(sql); }

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
        foreignKeys: fks.map(f => ({
          column: f.from, refTable: f.table, refColumn: f.to,
        })),
      };
    });
  }

  runQuery(sql: string): Row[] {
    // better-sqlite3 无原生只读开关:此处加一道 SELECT / WITH...SELECT 前缀防御
    const isReadOnly = /^\s*(with\b[\s\S]*\bselect|select)\b/i.test(sql);
    if (!isReadOnly) throw new Error("read-only check failed: not a SELECT or WITH...SELECT statement");
    const stmt = this.db.prepare(sql);
    return stmt.all() as Row[];
  }

  close() { this.db.close(); }
}
