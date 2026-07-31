import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { openAppDb, type AppDb } from "../src/appDb/index";
import { runMigrations } from "../src/appDb/migrations";
import {
  createDataSource, updateDataSource, getDataSource, listDataSources, deleteDataSource,
  recordCheck, putSchemaCache, getSchemaCache, DuplicateNameError,
} from "../src/appDb/dataSourceRepo";
import { targetLabel, type DsConfig } from "../src/datasources/types";
import type { TableSchema } from "@chatbi/shared";

const tmpDir = join(process.cwd(), ".tmp-test-repo");
const key = randomBytes(32);
let db: AppDb;

const mysqlCfg: DsConfig = {
  kind: "mysql", host: "10.0.0.5", port: 3306, database: "sales",
  user: "bi_ro", password: "s3cret", ssl: false,
};

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  db = openAppDb(join(tmpDir, "app.db"));
  runMigrations(db);
});
afterEach(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

describe("targetLabel", () => {
  it("给出可读摘要且不含密码", () => {
    const label = targetLabel(mysqlCfg);
    expect(label).toBe("mysql://bi_ro@10.0.0.5:3306/sales");
    expect(label).not.toContain("s3cret");
  });
  it("sqlite 用路径", () => {
    expect(targetLabel({ kind: "sqlite", path: "./data/chatbi.db" })).toBe("./data/chatbi.db");
  });
});

describe("createDataSource", () => {
  it("存进去再读出来,config 已解密", () => {
    const created = createDataSource(db, key, { name: "销售库", config: mysqlCfg });
    expect(created.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(getDataSource(db, key, created.id)!.config).toEqual(mysqlCfg);
  });
  it("密码不以明文存在库里", () => {
    createDataSource(db, key, { name: "销售库", config: mysqlCfg });
    const row = db.raw.prepare("SELECT config_cipher FROM data_sources").get() as { config_cipher: Buffer };
    expect(row.config_cipher.toString("latin1")).not.toContain("s3cret");
  });
  it("同名冲突抛 DuplicateNameError", () => {
    createDataSource(db, key, { name: "重名", config: mysqlCfg });
    expect(() => createDataSource(db, key, { name: "重名", config: mysqlCfg }))
      .toThrow(DuplicateNameError);
  });
  it("owner 默认 local,writePrivilege 默认为 null", () => {
    const r = createDataSource(db, key, { name: "x", config: mysqlCfg });
    expect(r.owner).toBe("local");
    expect(r.writePrivilege).toBeNull();
  });
});

describe("updateDataSource", () => {
  it("只改名字时保留原 config", () => {
    const c = createDataSource(db, key, { name: "旧名", config: mysqlCfg });
    const u = updateDataSource(db, key, c.id, { name: "新名" })!;
    expect(u.name).toBe("新名");
    expect(u.config).toEqual(mysqlCfg);
  });
  it("换 config 时重新加密", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    const next: DsConfig = { ...mysqlCfg, password: "另一个密码" };
    expect(updateDataSource(db, key, c.id, { config: next })!.config).toEqual(next);
  });
  it("updatedAt 会变", async () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    await new Promise(r => setTimeout(r, 5));
    expect(updateDataSource(db, key, c.id, { name: "y" })!.updatedAt).not.toBe(c.updatedAt);
  });
  it("id 不存在返回 null", () => {
    expect(updateDataSource(db, key, "nope", { name: "y" })).toBeNull();
  });
});

describe("解密失败", () => {
  it("换了钥匙则 config 为 null 且 configError 为真,不抛错", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    const other = randomBytes(32);
    const r = getDataSource(db, other, c.id)!;
    expect(r.config).toBeNull();
    expect(r.configError).toBe(true);
    expect(r.name).toBe("x");   // 名字与 id 仍然可用
  });
  it("列表里坏的和好的共存", () => {
    createDataSource(db, key, { name: "好的", config: mysqlCfg });
    const list = listDataSources(db, randomBytes(32));
    expect(list).toHaveLength(1);
    expect(list[0].configError).toBe(true);
  });
});

describe("recordCheck", () => {
  it("写入检查结果与写权限", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    recordCheck(db, c.id, { ok: true, writePrivilege: "writable" });
    const r = getDataSource(db, key, c.id)!;
    expect(r.lastCheckOk).toBe(true);
    expect(r.writePrivilege).toBe("writable");
    expect(r.lastCheckAt).toBeTruthy();
    expect(r.lastCheckError).toBeNull();
  });
  it("失败时记下原因,并清掉上一次的成功标记", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    recordCheck(db, c.id, { ok: true, writePrivilege: "readonly" });
    recordCheck(db, c.id, { ok: false, error: "连不上" });
    const r = getDataSource(db, key, c.id)!;
    expect(r.lastCheckOk).toBe(false);
    expect(r.lastCheckError).toBe("连不上");
  });
});

describe("schema 缓存", () => {
  const schema: TableSchema[] = [{
    tableName: "orders",
    columns: [{ name: "id", type: "int", notNull: true, pk: true }],
    foreignKeys: [],
  }];

  it("写入后能读回,带时间戳", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    putSchemaCache(db, c.id, schema);
    const got = getSchemaCache(db, c.id)!;
    expect(got.schema).toEqual(schema);
    expect(got.fetchedAt).toBeTruthy();
  });
  it("再写一次是覆盖而不是报主键冲突", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    putSchemaCache(db, c.id, schema);
    putSchemaCache(db, c.id, []);
    expect(getSchemaCache(db, c.id)!.schema).toEqual([]);
  });
  it("没缓存返回 null", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    expect(getSchemaCache(db, c.id)).toBeNull();
  });
});

describe("deleteDataSource", () => {
  it("删掉后连缓存一起没了", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    putSchemaCache(db, c.id, []);
    expect(deleteDataSource(db, c.id)).toBe(true);
    expect(getDataSource(db, key, c.id)).toBeNull();
    expect(getSchemaCache(db, c.id)).toBeNull();
  });
  it("删不存在的返回 false", () => {
    expect(deleteDataSource(db, "nope")).toBe(false);
  });
});
