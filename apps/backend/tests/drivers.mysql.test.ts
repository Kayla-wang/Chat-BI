import { describe, it } from "vitest";
import mysql from "mysql2/promise";
import { createMysqlDriver } from "../src/datasources/drivers/mysql";
import { runDriverContract } from "../src/datasources/drivers/contract";
import type { DsConfig } from "../src/datasources/types";

const FIXTURE = [
  "DROP TABLE IF EXISTS contract_orders",
  "DROP TABLE IF EXISTS contract_customers",
  `CREATE TABLE contract_customers (
     customer_id INT PRIMARY KEY, region VARCHAR(32) NOT NULL
   )`,
  `CREATE TABLE contract_orders (
     order_id INT PRIMARY KEY, customer_id INT,
     order_date DATE, amount DECIMAL(12,2),
     FOREIGN KEY (customer_id) REFERENCES contract_customers(customer_id)
   )`,
  "INSERT INTO contract_customers VALUES (1,'华东'),(2,'华南')",
  `INSERT INTO contract_orders VALUES
     (1,1,'2024-01-05',100),(2,2,'2024-01-20',200),(3,1,'2024-02-03',300),
     (4,2,'2024-02-14',400),(5,1,'2024-03-08',500),(6,2,'2024-03-22',600)`,
];

const raw = process.env.TEST_MYSQL_URL;

if (!raw) {
  // 必须有可见的跳过:静默 skip 会让「全绿」变成假信号。
  console.log("跳过 MySQL 驱动契约测试:未设置 TEST_MYSQL_URL(例:mysql://user:pw@127.0.0.1:3306/chatbi_test)");
  describe("MySQL 驱动契约", () => {
    it.skip("未设置 TEST_MYSQL_URL,跳过", () => { /* 见上面的控制台提示 */ });
  });
} else {
  const u = new URL(raw);
  const config: Extract<DsConfig, { kind: "mysql" }> = {
    kind: "mysql",
    host: u.hostname,
    port: Number(u.port || 3306),
    database: u.pathname.replace(/^\//, ""),
    user: decodeURIComponent(u.username),
    password: decodeURIComponent(u.password),
    ssl: u.searchParams.get("ssl") === "true",
  };

  runDriverContract("MySQL", {
    async setup() {
      const admin = await mysql.createConnection({
        host: config.host, port: config.port, database: config.database,
        user: config.user, password: config.password, multipleStatements: false,
      });
      for (const stmt of FIXTURE) await admin.query(stmt);
      await admin.end();
      const driver = createMysqlDriver(config);
      return {
        driver,
        cleanup: async () => {
          await driver.close();
          const c = await mysql.createConnection({
            host: config.host, port: config.port, database: config.database,
            user: config.user, password: config.password,
          });
          await c.query("DROP TABLE IF EXISTS contract_orders");
          await c.query("DROP TABLE IF EXISTS contract_customers");
          await c.end();
        },
      };
    },
    sql: {
      monthlyTotals: `SELECT DATE_FORMAT(order_date, '%Y-%m') AS m, SUM(amount) AS total
                      FROM contract_orders GROUP BY m ORDER BY m`,
      manyRows: "SELECT order_id, amount FROM contract_orders ORDER BY order_id LIMIT 7",
      insert: "INSERT INTO contract_customers VALUES (9,'华北')",
      slow: "SELECT COUNT(*) AS n FROM contract_orders a, contract_orders b, contract_orders c, contract_orders d, contract_orders e, contract_orders f, contract_orders g, contract_orders h",
      badTable: "SELECT * FROM contract_no_such_table",
    },
    // 建夹具需要写权限,所以这个账号必然是 writable —— 正好验证探测能报出来。
    writeRejection: "expected-weak",
    timeoutEnforcement: "server",
  });
}
