import { describe, it } from "vitest";
import pg from "pg";
const { Client } = pg;
import { createPgDriver } from "../src/datasources/drivers/postgres";
import { runDriverContract } from "../src/datasources/drivers/contract";
import type { DsConfig } from "../src/datasources/types";

const FIXTURE = [
  "DROP TABLE IF EXISTS contract_orders",
  "DROP TABLE IF EXISTS contract_customers",
  `CREATE TABLE contract_customers (
     customer_id INTEGER PRIMARY KEY, region VARCHAR(32) NOT NULL
   )`,
  `CREATE TABLE contract_orders (
     order_id INTEGER PRIMARY KEY,
     customer_id INTEGER REFERENCES contract_customers(customer_id),
     order_date DATE, amount NUMERIC(12,2)
   )`,
  "INSERT INTO contract_customers VALUES (1,'华东'),(2,'华南')",
  `INSERT INTO contract_orders VALUES
     (1,1,'2024-01-05',100),(2,2,'2024-01-20',200),(3,1,'2024-02-03',300),
     (4,2,'2024-02-14',400),(5,1,'2024-03-08',500),(6,2,'2024-03-22',600)`,
];

const raw = process.env.TEST_PG_URL;

if (!raw) {
  console.log("跳过 PostgreSQL 驱动契约测试:未设置 TEST_PG_URL(例:postgres://user:pw@127.0.0.1:5432/chatbi_test)");
  describe("PostgreSQL 驱动契约", () => {
    it.skip("未设置 TEST_PG_URL,跳过", () => { /* 见上面的控制台提示 */ });
  });
} else {
  const u = new URL(raw);
  const config: Extract<DsConfig, { kind: "postgres" }> = {
    kind: "postgres",
    host: u.hostname,
    port: Number(u.port || 5432),
    database: u.pathname.replace(/^\//, ""),
    user: decodeURIComponent(u.username),
    password: decodeURIComponent(u.password),
    ssl: u.searchParams.get("ssl") === "true",
  };

  const admin = async (): Promise<pg.Client> => {
    const c = new Client({
      host: config.host, port: config.port, database: config.database,
      user: config.user, password: config.password,
      ssl: config.ssl ? { rejectUnauthorized: true } : false,
    });
    await c.connect();
    return c;
  };

  runDriverContract("PostgreSQL", {
    async setup() {
      const c = await admin();
      for (const stmt of FIXTURE) await c.query(stmt);
      await c.end();
      const driver = createPgDriver(config);
      return {
        driver,
        cleanup: async () => {
          await driver.close();
          const d = await admin();
          await d.query("DROP TABLE IF EXISTS contract_orders");
          await d.query("DROP TABLE IF EXISTS contract_customers");
          await d.end();
        },
      };
    },
    sql: {
      monthlyTotals: `SELECT to_char(date_trunc('month', order_date), 'YYYY-MM') AS m,
                             SUM(amount) AS total
                        FROM contract_orders GROUP BY 1 ORDER BY 1`,
      manyRows: "SELECT order_id, amount FROM contract_orders ORDER BY order_id LIMIT 7",
      insert: "INSERT INTO contract_customers VALUES (9,'华北')",
      // 不用 pg_sleep:它在我们的方言禁用词表里,拿它做夹具会造成「测试用的正是被禁的东西」的错觉。
      slow: "SELECT COUNT(*) AS n FROM generate_series(1, 300000000)",
      badTable: "SELECT * FROM contract_no_such_table",
    },
    // 只读事务让引擎真的拒写。
    writeRejection: "engine",
    timeoutEnforcement: "server",
  });
}
