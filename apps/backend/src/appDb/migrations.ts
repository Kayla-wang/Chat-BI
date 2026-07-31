import type { AppDb } from "./index";

export interface Migration {
  id: number;
  name: string;
  /** 在同一个事务内被调用;抛错则整批回滚。 */
  up(db: AppDb): void;
}

const M1 = `
CREATE TABLE data_sources (
  id               TEXT PRIMARY KEY,
  name             TEXT NOT NULL UNIQUE,
  kind             TEXT NOT NULL,
  config_cipher    BLOB NOT NULL,
  config_iv        BLOB NOT NULL,
  config_tag       BLOB NOT NULL,
  owner            TEXT NOT NULL DEFAULT 'local',
  write_probe      TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  last_check_at    TEXT,
  last_check_ok    INTEGER,
  last_check_error TEXT
);
`;

const M2 = `
CREATE TABLE schema_cache (
  data_source_id TEXT PRIMARY KEY REFERENCES data_sources(id) ON DELETE CASCADE,
  schema_json    TEXT NOT NULL,
  fetched_at     TEXT NOT NULL
);
`;

/** 只许往末尾追加。改动已发布的条目会让老库与新库结构不一致。 */
export const MIGRATIONS: Migration[] = [
  { id: 1, name: "data_sources", up: db => db.raw.exec(M1) },
  { id: 2, name: "schema_cache", up: db => db.raw.exec(M2) },
];

/** 返回本次实际应用的迁移 id。整批在一个事务里,任一条失败全部回滚。 */
export function runMigrations(db: AppDb, migrations: Migration[] = MIGRATIONS): number[] {
  db.raw.exec(`CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
  )`);
  const done = new Set(
    (db.raw.prepare("SELECT id FROM schema_migrations").all() as { id: number }[]).map(r => r.id),
  );
  const pending = migrations.filter(m => !done.has(m.id)).sort((a, b) => a.id - b.id);
  if (!pending.length) return [];

  const record = db.raw.prepare(
    "INSERT INTO schema_migrations (id, name, applied_at) VALUES (?, ?, ?)",
  );
  const applyAll = db.raw.transaction((list: Migration[]) => {
    for (const m of list) {
      try {
        m.up(db);
      } catch (e) {
        throw new Error(`迁移 ${m.id}(${m.name})失败: ${(e as Error).message}`);
      }
      record.run(m.id, m.name, new Date().toISOString());
    }
  });
  applyAll(pending);
  return pending.map(m => m.id);
}
