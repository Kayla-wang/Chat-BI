import Database from "better-sqlite3";
import type { Database as RawDb } from "better-sqlite3";
import { dirname } from "node:path";
import { mkdirSync } from "node:fs";

/**
 * 应用元数据库的可写连接。`raw` 只允许 src/appDb/ 目录内使用——
 * 目录外一律走 dataSourceRepo 的函数,不要让 SQL 字符串散出去。
 */
export interface AppDb {
  raw: RawDb;
  close(): void;
}

export function openAppDb(path: string): AppDb {
  mkdirSync(dirname(path), { recursive: true });
  const raw = new Database(path);
  raw.pragma("journal_mode = WAL");
  // better-sqlite3 默认不开外键,不开则 ON DELETE CASCADE 静默失效。
  raw.pragma("foreign_keys = ON");
  return { raw, close: () => raw.close() };
}
