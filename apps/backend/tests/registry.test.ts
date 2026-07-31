import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import type { TableSchema } from "@chatbi/shared";
import { openAppDb, type AppDb } from "../src/appDb/index";
import { runMigrations } from "../src/appDb/migrations";
import { createDataSource, getSchemaCache } from "../src/appDb/dataSourceRepo";
import { createRegistry } from "../src/datasources/registry";
import { SQLITE_DIALECT } from "../src/datasources/dialect";
import type { Driver } from "../src/datasources/driver";
import type { DsConfig } from "../src/datasources/types";

const tmpDir = join(process.cwd(), ".tmp-test-registry");
const key = randomBytes(32);
const cfg: DsConfig = { kind: "sqlite", path: "./whatever.db" };
const schema: TableSchema[] = [{
  tableName: "t", columns: [{ name: "a", type: "INTEGER", notNull: false, pk: false }], foreignKeys: [],
}];

let db: AppDb;

function fakeDriver(): Driver & { closed: number; introspects: number } {
  const d = {
    kind: "sqlite" as const, dialect: SQLITE_DIALECT,
    closed: 0, introspects: 0,
    testConnection: async () => ({ ok: true as const, writePrivilege: "readonly" as const }),
    introspect: async () => { d.introspects++; return schema; },
    runQuery: async () => ({ rows: [], truncated: false }),
    probeWritePrivilege: async () => "readonly" as const,
    close: async () => { d.closed++; },
  };
  return d;
}

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  db = openAppDb(join(tmpDir, "app.db"));
  runMigrations(db);
});
afterEach(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

describe("get", () => {
  it("懒建:第一次才造 driver,第二次复用同一个实例", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const create = vi.fn(() => fakeDriver());
    const reg = createRegistry({ db, key, createDriver: create });
    expect(create).not.toHaveBeenCalled();
    const a = await reg.get(rec.id);
    const b = await reg.get(rec.id);
    expect(a).toBe(b);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("id 不存在时报 NOT_FOUND", async () => {
    const reg = createRegistry({ db, key, createDriver: () => fakeDriver() });
    await expect(reg.get("nope")).rejects.toMatchObject({ code: "NOT_FOUND" });
  });

  it("解密失败时报 DECRYPT_ERROR,且不去建连接", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const create = vi.fn(() => fakeDriver());
    const reg = createRegistry({ db, key: randomBytes(32), createDriver: create });
    await expect(reg.get(rec.id)).rejects.toMatchObject({ code: "DECRYPT_ERROR" });
    expect(create).not.toHaveBeenCalled();
  });
});

describe("invalidate", () => {
  it("关掉旧连接,下次重建", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const made: ReturnType<typeof fakeDriver>[] = [];
    const reg = createRegistry({
      db, key,
      createDriver: () => { const d = fakeDriver(); made.push(d); return d; },
    });
    await reg.get(rec.id);
    await reg.invalidate(rec.id);
    expect(made[0].closed).toBe(1);
    await reg.get(rec.id);
    expect(made).toHaveLength(2);
  });

  it("对没建过连接的 id 是安全的空操作", async () => {
    const reg = createRegistry({ db, key, createDriver: () => fakeDriver() });
    await expect(reg.invalidate("nope")).resolves.toBeUndefined();
  });
});

describe("schemaFor", () => {
  it("缓存缺失时 introspect 一次并写回缓存", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const d = fakeDriver();
    const reg = createRegistry({ db, key, createDriver: () => d });
    expect(await reg.schemaFor(rec.id)).toEqual(schema);
    expect(d.introspects).toBe(1);
    expect(getSchemaCache(db, rec.id)!.schema).toEqual(schema);
  });

  it("缓存命中时不再打库", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const d = fakeDriver();
    const reg = createRegistry({ db, key, createDriver: () => d });
    await reg.schemaFor(rec.id);
    await reg.schemaFor(rec.id);
    expect(d.introspects).toBe(1);
  });
});

describe("refreshSchema", () => {
  it("无论有没有缓存都重新抓,并覆盖缓存", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const d = fakeDriver();
    const reg = createRegistry({ db, key, createDriver: () => d });
    await reg.schemaFor(rec.id);
    const r = await reg.refreshSchema(rec.id);
    expect(d.introspects).toBe(2);
    expect(r.schema).toEqual(schema);
    expect(r.fetchedAt).toBeTruthy();
  });
});

describe("closeAll", () => {
  it("关闭所有活连接", async () => {
    const a = createDataSource(db, key, { name: "a", config: cfg });
    const b = createDataSource(db, key, { name: "b", config: cfg });
    const made: ReturnType<typeof fakeDriver>[] = [];
    const reg = createRegistry({
      db, key, createDriver: () => { const d = fakeDriver(); made.push(d); return d; },
    });
    await reg.get(a.id);
    await reg.get(b.id);
    await reg.closeAll();
    expect(made.map(d => d.closed)).toEqual([1, 1]);
  });
});
