import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { DbClient } from "../src/dbClient";
import { migrate } from "../src/migrate";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";

const tmpDir = join(process.cwd(), ".tmp-migrate");
let db: DbClient;
beforeEach(() => { mkdirSync(tmpDir, { recursive: true }); db = new DbClient(join(tmpDir, "m.db")); });
afterEach(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

describe("migrate", () => {
  it("creates the 4 tables", () => {
    migrate(db);
    const schema = db.getSchema().map(t => t.tableName);
    expect(schema).toEqual(expect.arrayContaining(["customers", "products", "orders", "order_items"]));
  });
  it("seeds sample rows", () => {
    migrate(db);
    expect(db.runQuery("SELECT COUNT(*) n FROM customers", 10).rows[0].n).toBeGreaterThan(0);
    expect(db.runQuery("SELECT COUNT(*) n FROM orders", 10).rows[0].n).toBeGreaterThan(0);
  });
  it("is idempotent (safe to run twice)", () => {
    migrate(db); migrate(db);
    expect(db.runQuery("SELECT COUNT(*) n FROM products", 10).rows[0].n).toBeGreaterThan(0);
  });
});
