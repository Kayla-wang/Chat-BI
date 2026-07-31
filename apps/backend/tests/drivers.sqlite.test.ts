import { describe, it, expect, afterAll } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { DbClient } from "../src/dbClient";
import { createSqliteDriver } from "../src/datasources/drivers/sqlite";
import { runDriverContract } from "../src/datasources/drivers/contract";

const tmpDir = join(process.cwd(), ".tmp-test-sqlite");
const dbPath = join(tmpDir, "contract.db");

const FIXTURE = `
CREATE TABLE contract_customers (
  customer_id INTEGER PRIMARY KEY, region TEXT NOT NULL
);
CREATE TABLE contract_orders (
  order_id INTEGER PRIMARY KEY, customer_id INTEGER,
  order_date TEXT, amount REAL,
  FOREIGN KEY (customer_id) REFERENCES contract_customers(customer_id)
);
INSERT INTO contract_customers VALUES (1,'华东'),(2,'华南');
INSERT INTO contract_orders VALUES
 (1,1,'2024-01-05',100),(2,2,'2024-01-20',200),(3,1,'2024-02-03',300),
 (4,2,'2024-02-14',400),(5,1,'2024-03-08',500),(6,2,'2024-03-22',600);
`;

runDriverContract("SQLite", {
  async setup() {
    rmSync(tmpDir, { recursive: true, force: true });
    mkdirSync(tmpDir, { recursive: true });
    const writable = new DbClient(dbPath);
    writable.execRaw(FIXTURE);
    writable.close();
    const driver = createSqliteDriver({ kind: "sqlite", path: dbPath });
    return {
      driver,
      cleanup: async () => {
        await driver.close();
        rmSync(tmpDir, { recursive: true, force: true });
      },
    };
  },
  sql: {
    monthlyTotals: `SELECT strftime('%Y-%m', order_date) AS m, SUM(amount) AS total
                    FROM contract_orders GROUP BY m ORDER BY m`,
    manyRows: "SELECT order_id, amount FROM contract_orders ORDER BY order_id LIMIT 7",
    insert: "INSERT INTO contract_customers VALUES (9,'华北')",
    slow: `WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 20000000)
           SELECT COUNT(*) AS n FROM c`,
    badTable: "SELECT * FROM contract_no_such_table",
  },
  writeRejection: "engine",
  timeoutEnforcement: "none",
});

/**
 * 契约里那条「写操作被引擎拒绝」用的是裸 INSERT,它在 DbClient 里就被
 * 「不返回行的语句」这道检查挡下了,根本没走到引擎——所以只能证明抛了 DsError。
 * 这里用 INSERT ... RETURNING(返回行的写语句)真正走到引擎,验证只读连接的硬拒。
 */
describe("SQLite 只读连接的引擎级硬拒", () => {
  const dir = join(process.cwd(), ".tmp-test-sqlite-ro");
  const path = join(dir, "ro.db");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const w = new DbClient(path);
  w.execRaw("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)");
  w.close();
  const driver = createSqliteDriver({ kind: "sqlite", path });

  afterAll(async () => {
    await driver.close();
    rmSync(dir, { recursive: true, force: true });
  });

  it("INSERT ... RETURNING 被引擎判为 PERMISSION_ERROR", async () => {
    await expect(driver.runQuery("INSERT INTO t (v) VALUES ('x') RETURNING id", 10, 5000))
      .rejects.toMatchObject({ code: "PERMISSION_ERROR" });
  });
});
