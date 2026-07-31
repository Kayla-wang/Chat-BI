import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdirSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { openAppDb, type AppDb } from "../src/appDb/index";
import { runMigrations } from "../src/appDb/migrations";
import { createDataSource, listDataSources } from "../src/appDb/dataSourceRepo";
import { ensureBuiltinDataSource } from "../src/appDb/bootstrap";
import { bootstrapApp } from "../src/server";

const tmpDir = join(process.cwd(), ".tmp-test-boot");
const key = randomBytes(32);
let db: AppDb;

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  db = openAppDb(join(tmpDir, "app.db"));
  runMigrations(db);
});
afterEach(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

describe("ensureBuiltinDataSource", () => {
  it("空库时插入一条 sqlite 示例源,config 指向给定路径", () => {
    const r = ensureBuiltinDataSource(db, key, { path: "./data/chatbi.db" })!;
    expect(r.kind).toBe("sqlite");
    expect(r.name).toBe("示例订单库");
    expect(r.config).toEqual({ kind: "sqlite", path: "./data/chatbi.db" });
  });

  it("内置源的 config 也是加密的,不给它开后门", () => {
    ensureBuiltinDataSource(db, key, { path: "./data/chatbi.db" });
    const row = db.raw.prepare("SELECT config_cipher FROM data_sources").get() as { config_cipher: Buffer };
    expect(row.config_cipher.toString("latin1")).not.toContain("chatbi.db");
  });

  it("已经有数据源时什么也不做", () => {
    createDataSource(db, key, { name: "我的库", config: { kind: "sqlite", path: "./x.db" } });
    expect(ensureBuiltinDataSource(db, key, { path: "./data/chatbi.db" })).toBeNull();
    expect(listDataSources(db, key)).toHaveLength(1);
  });

  it("连续调用两次只插一条", () => {
    ensureBuiltinDataSource(db, key, { path: "./data/chatbi.db" });
    ensureBuiltinDataSource(db, key, { path: "./data/chatbi.db" });
    expect(listDataSources(db, key)).toHaveLength(1);
  });
});

describe("bootstrapApp", () => {
  const paths = {
    dbPath: join(tmpDir, "biz.db"),
    appDbPath: join(tmpDir, "app2.db"),
    appKeyPath: join(tmpDir, "app2.key"),
  };

  it("按顺序建出业务库、密钥、元数据库与内置源", () => {
    const app = bootstrapApp(paths);
    try {
      expect(existsSync(paths.dbPath)).toBe(true);      // 第 1 步:示例业务库
      expect(existsSync(paths.appKeyPath)).toBe(true);   // 第 2 步:密钥
      expect(existsSync(paths.appDbPath)).toBe(true);    // 第 3 步:元数据库
      const list = listDataSources(app.appDb, app.key);  // 第 4 步:内置源
      expect(list).toHaveLength(1);
      expect(list[0].config).toEqual({ kind: "sqlite", path: paths.dbPath });
    } finally {
      app.appDb.close();
    }
  });

  it("第二次启动不重复插入,也不重新生成密钥", () => {
    const first = bootstrapApp(paths);
    const firstKey = Buffer.from(first.key);
    first.appDb.close();
    const second = bootstrapApp(paths);
    try {
      expect(second.key.equals(firstKey)).toBe(true);
      expect(listDataSources(second.appDb, second.key)).toHaveLength(1);
    } finally {
      second.appDb.close();
    }
  });

  it("registry 建好但不预热任何连接", async () => {
    const app = bootstrapApp(paths);
    try {
      // 内置源指向刚建好的业务库,取一次应当成功。
      const id = listDataSources(app.appDb, app.key)[0].id;
      const driver = await app.registry.get(id);
      expect(driver.kind).toBe("sqlite");
      await app.registry.closeAll();
    } finally {
      app.appDb.close();
    }
  });
});
