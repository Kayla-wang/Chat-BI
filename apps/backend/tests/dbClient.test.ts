import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { DbClient } from "../src/dbClient";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";

const tmpDir = join(process.cwd(), ".tmp-test");
const dbPath = join(tmpDir, "t.db");
let writable: DbClient;

beforeEach(() => {
  mkdirSync(tmpDir, { recursive: true });
  writable = new DbClient(dbPath);
  writable.execRaw(`
    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, region TEXT);
    CREATE TABLE orders (id INTEGER PRIMARY KEY, cust_id INTEGER, amount REAL,
      FOREIGN KEY(cust_id) REFERENCES customers(id));
    INSERT INTO customers VALUES (1,'Alice','east'),(2,'Bob','west');
    INSERT INTO orders VALUES (1,1,10.5),(2,2,20),(3,1,30),(4,2,40),(5,1,50);
  `);
});
afterEach(() => {
  writable.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("getSchema", () => {
  it("给出表、列与外键", () => {
    const orders = writable.getSchema().find(t => t.tableName === "orders")!;
    expect(orders.columns.map(c => c.name)).toContain("amount");
    expect(orders.foreignKeys[0]).toMatchObject({
      column: "cust_id", refTable: "customers", refColumn: "id",
    });
  });
});

describe("runQuery 截断探测", () => {
  it("超过上限时切到上限并标记 truncated", () => {
    const r = writable.runQuery("SELECT id FROM orders LIMIT 4", 3);
    expect(r.rows).toHaveLength(3);
    expect(r.truncated).toBe(true);
  });
  it("恰好等于上限时不误报截断", () => {
    const r = writable.runQuery("SELECT id FROM orders LIMIT 3", 3);
    expect(r.rows).toHaveLength(3);
    expect(r.truncated).toBe(false);
  });
  it("少于上限时不截断", () => {
    const r = writable.runQuery("SELECT id FROM orders LIMIT 2", 3);
    expect(r.rows).toHaveLength(2);
    expect(r.truncated).toBe(false);
  });
  it("空结果集", () => {
    const r = writable.runQuery("SELECT id FROM orders WHERE 1=0", 3);
    expect(r).toEqual({ rows: [], truncated: false });
  });
});

describe("runQuery 拒绝不返回数据的语句", () => {
  it("INSERT 抛错", () => {
    expect(() => writable.runQuery("INSERT INTO customers VALUES (9,'Eve','north')", 10))
      .toThrow(/does not return rows/i);
  });
  it("DROP 抛错", () => {
    expect(() => writable.runQuery("DROP TABLE customers", 10)).toThrow(/does not return rows/i);
  });
});

describe("只读连接", () => {
  it("SELECT 正常", () => {
    const ro = new DbClient(dbPath, { readonly: true });
    try {
      expect(ro.runQuery("SELECT COUNT(*) AS n FROM customers", 10).rows[0].n).toBe(2);
    } finally { ro.close(); }
  });
  it("引擎层面拒绝写入", () => {
    const ro = new DbClient(dbPath, { readonly: true });
    try {
      expect(() => ro.execRaw("INSERT INTO customers VALUES (9,'Eve','north')"))
        .toThrow(/readonly|read-only/i);
    } finally { ro.close(); }
  });
  it("即使绕过 execRaw,prepare 阶段也拒绝", () => {
    const ro = new DbClient(dbPath, { readonly: true });
    try {
      expect(() => ro.runQuery("INSERT INTO customers VALUES (9,'Eve','north')", 10)).toThrow();
    } finally { ro.close(); }
  });
});
