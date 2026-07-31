import { randomUUID } from "node:crypto";
import type { TableSchema } from "@chatbi/shared";
import type { AppDb } from "./index";
import { encryptJson, decryptJson, DecryptError } from "./secrets";
import type { DataSourceKind, DataSourceRecord, DsConfig, WritePrivilege } from "../datasources/types";

export class DuplicateNameError extends Error {
  constructor(name: string) { super(`已有同名数据源:${name}`); this.name = "DuplicateNameError"; }
}

interface RawRow {
  id: string; name: string; kind: string; owner: string;
  config_cipher: Buffer; config_iv: Buffer; config_tag: Buffer;
  write_probe: string | null;
  created_at: string; updated_at: string;
  last_check_at: string | null; last_check_ok: number | null; last_check_error: string | null;
}

const COLUMNS = `id, name, kind, owner, config_cipher, config_iv, config_tag, write_probe,
  created_at, updated_at, last_check_at, last_check_ok, last_check_error`;

function toRecord(row: RawRow, key: Buffer): DataSourceRecord {
  let config: DsConfig | null = null;
  let configError = false;
  try {
    config = decryptJson<DsConfig>(
      { cipher: row.config_cipher, iv: row.config_iv, tag: row.config_tag }, key,
    );
  } catch (e) {
    if (!(e instanceof DecryptError)) throw e;
    configError = true;   // 不抛:名字与 id 仍然有用,界面要能显示「需重新配置」
  }
  return {
    id: row.id, name: row.name, kind: row.kind as DataSourceKind, owner: row.owner,
    config, configError,
    writePrivilege: (row.write_probe as WritePrivilege | null) ?? null,
    createdAt: row.created_at, updatedAt: row.updated_at,
    lastCheckAt: row.last_check_at,
    lastCheckOk: row.last_check_ok === null ? null : row.last_check_ok === 1,
    lastCheckError: row.last_check_error,
  };
}

export function createDataSource(
  db: AppDb, key: Buffer,
  input: { name: string; config: DsConfig; writePrivilege?: WritePrivilege },
): DataSourceRecord {
  const sealed = encryptJson(input.config, key);
  const now = new Date().toISOString();
  const id = randomUUID();
  try {
    db.raw.prepare(
      `INSERT INTO data_sources
         (id, name, kind, config_cipher, config_iv, config_tag, write_probe, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).run(id, input.name, input.config.kind, sealed.cipher, sealed.iv, sealed.tag,
      input.writePrivilege ?? null, now, now);
  } catch (e) {
    if (/UNIQUE constraint failed: data_sources\.name/i.test((e as Error).message)) {
      throw new DuplicateNameError(input.name);
    }
    throw e;
  }
  return getDataSource(db, key, id)!;
}

export function getDataSource(db: AppDb, key: Buffer, id: string): DataSourceRecord | null {
  const row = db.raw.prepare(`SELECT ${COLUMNS} FROM data_sources WHERE id = ?`).get(id) as RawRow | undefined;
  return row ? toRecord(row, key) : null;
}

export function listDataSources(db: AppDb, key: Buffer): DataSourceRecord[] {
  const rows = db.raw.prepare(`SELECT ${COLUMNS} FROM data_sources ORDER BY created_at`).all() as RawRow[];
  return rows.map(r => toRecord(r, key));
}

export function updateDataSource(
  db: AppDb, key: Buffer, id: string, patch: { name?: string; config?: DsConfig },
): DataSourceRecord | null {
  const current = getDataSource(db, key, id);
  if (!current) return null;
  const now = new Date().toISOString();
  try {
    if (patch.config) {
      const sealed = encryptJson(patch.config, key);
      db.raw.prepare(
        `UPDATE data_sources SET name = ?, kind = ?, config_cipher = ?, config_iv = ?,
           config_tag = ?, updated_at = ? WHERE id = ?`,
      ).run(patch.name ?? current.name, patch.config.kind,
        sealed.cipher, sealed.iv, sealed.tag, now, id);
    } else {
      db.raw.prepare("UPDATE data_sources SET name = ?, updated_at = ? WHERE id = ?")
        .run(patch.name ?? current.name, now, id);
    }
  } catch (e) {
    if (/UNIQUE constraint failed: data_sources\.name/i.test((e as Error).message)) {
      throw new DuplicateNameError(patch.name!);
    }
    throw e;
  }
  return getDataSource(db, key, id);
}

export function deleteDataSource(db: AppDb, id: string): boolean {
  // schema_cache 靠 ON DELETE CASCADE 跟着走(openAppDb 已开 foreign_keys)。
  return db.raw.prepare("DELETE FROM data_sources WHERE id = ?").run(id).changes > 0;
}

export function recordCheck(
  db: AppDb, id: string, r: { ok: boolean; error?: string; writePrivilege?: WritePrivilege },
): void {
  db.raw.prepare(
    `UPDATE data_sources
        SET last_check_at = ?, last_check_ok = ?, last_check_error = ?,
            write_probe = COALESCE(?, write_probe)
      WHERE id = ?`,
  ).run(new Date().toISOString(), r.ok ? 1 : 0, r.error ?? null, r.writePrivilege ?? null, id);
}

export function putSchemaCache(db: AppDb, id: string, schema: TableSchema[]): void {
  db.raw.prepare(
    `INSERT INTO schema_cache (data_source_id, schema_json, fetched_at) VALUES (?, ?, ?)
     ON CONFLICT(data_source_id) DO UPDATE SET schema_json = excluded.schema_json,
       fetched_at = excluded.fetched_at`,
  ).run(id, JSON.stringify(schema), new Date().toISOString());
}

export function getSchemaCache(
  db: AppDb, id: string,
): { schema: TableSchema[]; fetchedAt: string } | null {
  const row = db.raw.prepare(
    "SELECT schema_json, fetched_at FROM schema_cache WHERE data_source_id = ?",
  ).get(id) as { schema_json: string; fetched_at: string } | undefined;
  return row ? { schema: JSON.parse(row.schema_json) as TableSchema[], fetchedAt: row.fetched_at } : null;
}
