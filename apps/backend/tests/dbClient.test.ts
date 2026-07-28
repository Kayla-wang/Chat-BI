import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { DbClient } from "../src/dbClient";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";

const tmpDir = join(process.cwd(), ".tmp-test");
let db: DbClient;

beforeEach(() => {
  mkdirSync(tmpDir, { recursive: true });
  db = new DbClient(join(tmpDir, "t.db"));
  db.execRaw(`
    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, region TEXT);
    CREATE TABLE orders (id INTEGER PRIMARY KEY, cust_id INTEGER, amount REAL,
      FOREIGN KEY(cust_id) REFERENCES customers(id));
    INSERT INTO customers VALUES (1,'Alice','east'),(2,'Bob','west');
    INSERT INTO orders VALUES (1,1,10.5),(2,2,20);
  `);
});
afterEach(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

describe("DbClient.getSchema", () => {
  it("returns tables with columns and FKs", () => {
    const schema = db.getSchema();
    const orders = schema.find(t => t.tableName === "orders")!;
    expect(orders.columns.map(c => c.name)).toContain("amount");
    expect(orders.foreignKeys[0]).toMatchObject({ column: "cust_id", refTable: "customers", refColumn: "id" });
  });
});

describe("DbClient.runQuery", () => {
  it("returns rows for select", () => {
    const rows = db.runQuery("SELECT region, COUNT(*) n FROM customers GROUP BY region");
    expect(rows).toHaveLength(2);
  });
  it("aborts write statements", () => {
    expect(() => db.runQuery("INSERT INTO customers VALUES (3,'Eve','north')")).toThrow(/read-only|readonly/i);
  });
  it("aborts DDL", () => {
    expect(() => db.runQuery("DROP TABLE customers")).toThrow(/read-only|readonly/i);
  });
});
