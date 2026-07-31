import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { openAppDb, type AppDb } from "../src/appDb/index";
import { runMigrations, MIGRATIONS, type Migration } from "../src/appDb/migrations";

// 每个测试文件必须用**独立**的临时目录:vitest 并行跑文件,共用 ".tmp-test"
// 会让彼此的 rmSync 互删,现象是随机的 SQLITE_CANTOPEN。
const tmpDir = join(process.cwd(), ".tmp-test-appdb");
const dbPath = join(tmpDir, "app.db");
let db: AppDb;

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  db = openAppDb(dbPath);
});
afterEach(() => {
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

const tableNames = (d: AppDb): string[] =>
  (d.raw.prepare("SELECT name FROM sqlite_master WHERE type='table'").all() as { name: string }[])
    .map(r => r.name);

describe("openAppDb", () => {
  it("打开外键约束", () => {
    expect(db.raw.pragma("foreign_keys", { simple: true })).toBe(1);
  });
});

describe("runMigrations", () => {
  it("空库跑到最新,建出两张表与版本表", () => {
    const applied = runMigrations(db);
    expect(applied).toEqual([1, 2]);
    expect(tableNames(db)).toEqual(
      expect.arrayContaining(["schema_migrations", "data_sources", "schema_cache"]),
    );
  });

  it("重复跑是幂等的,第二次什么也不应用", () => {
    runMigrations(db);
    expect(runMigrations(db)).toEqual([]);
  });

  it("只补跑缺失的那几号", () => {
    const first: Migration = MIGRATIONS[0];
    runMigrations(db, [first]);
    expect(runMigrations(db)).toEqual(MIGRATIONS.slice(1).map(m => m.id));
  });

  it("中途失败时整批回滚,已成功的那条也不留痕", () => {
    const boom: Migration = {
      id: 999, name: "boom",
      up: () => { throw new Error("故意失败"); },
    };
    expect(() => runMigrations(db, [...MIGRATIONS, boom])).toThrow(/迁移 999.*boom/);
    expect(tableNames(db)).not.toContain("data_sources");
    // 版本表先于迁移存在(CREATE TABLE IF NOT EXISTS 在事务外),所以只断言它是空的。
    expect(db.raw.prepare("SELECT COUNT(*) AS n FROM schema_migrations").get()).toEqual({ n: 0 });
  });

  it("data_sources 的 name 唯一", () => {
    runMigrations(db);
    const ins = db.raw.prepare(
      `INSERT INTO data_sources
        (id, name, kind, config_cipher, config_iv, config_tag, created_at, updated_at)
       VALUES (?, 'dup', 'sqlite', x'00', x'00', x'00', '', '')`,
    );
    ins.run("a");
    expect(() => ins.run("b")).toThrow(/UNIQUE/i);
  });

  it("删数据源时级联删掉 schema_cache", () => {
    runMigrations(db);
    db.raw.prepare(
      `INSERT INTO data_sources
        (id, name, kind, config_cipher, config_iv, config_tag, created_at, updated_at)
       VALUES ('s1', 'n', 'sqlite', x'00', x'00', x'00', '', '')`,
    ).run();
    db.raw.prepare(
      "INSERT INTO schema_cache (data_source_id, schema_json, fetched_at) VALUES ('s1', '[]', '')",
    ).run();
    db.raw.prepare("DELETE FROM data_sources WHERE id = 's1'").run();
    expect(db.raw.prepare("SELECT COUNT(*) AS n FROM schema_cache").get()).toEqual({ n: 0 });
  });
});
