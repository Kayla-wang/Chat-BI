import { describe, it, expect, beforeAll, afterAll } from "vitest";
import type { Driver } from "../driver";
import { DsError } from "../errors";

export interface ContractHooks {
  /** 建夹具表并灌数据,返回可用的 driver 与清理函数。 */
  setup(): Promise<{ driver: Driver; cleanup: () => Promise<void> }>;
  sql: {
    /** 按月汇总,应得 [["2024-01",300],["2024-02",700],["2024-03",1100]] */
    monthlyTotals: string;
    /** 返回全部 6 行订单 */
    manyRows: string;
    /** 一条写语句 */
    insert: string;
    /** 一条必然超过 200ms 的查询 */
    slow: string;
    /** 查一张不存在的表 */
    badTable: string;
  };
  /** engine = 引擎硬拒;expected-weak = 引擎拒不住(MySQL),改为断言能探出写权限 */
  writeRejection: "engine" | "expected-weak";
  /** server = 服务端能掐;none = 进程内无法强制(SQLite 同步执行) */
  timeoutEnforcement: "server" | "none";
}

export function runDriverContract(name: string, hooks: ContractHooks): void {
  describe(`${name} 驱动契约`, () => {
    let driver: Driver;
    let cleanup: () => Promise<void>;

    beforeAll(async () => { ({ driver, cleanup } = await hooks.setup()); }, 30_000);
    afterAll(async () => { await cleanup?.(); });

    it("testConnection 成功并给出写权限判断", async () => {
      const r = await driver.testConnection();
      expect(r.ok).toBe(true);
      if (r.ok) expect(["readonly", "writable", "unknown"]).toContain(r.writePrivilege);
    });

    it("introspect 找到两张夹具表", async () => {
      const names = (await driver.introspect()).map(t => t.tableName);
      expect(names).toEqual(expect.arrayContaining(["contract_customers", "contract_orders"]));
    });

    it("introspect 给出列名、主键与非空标记", async () => {
      const orders = (await driver.introspect()).find(t => t.tableName === "contract_orders")!;
      expect(orders.columns.map(c => c.name).sort())
        .toEqual(["amount", "customer_id", "order_date", "order_id"]);
      expect(orders.columns.find(c => c.name === "order_id")!.pk).toBe(true);
      const customers = (await driver.introspect()).find(t => t.tableName === "contract_customers")!;
      expect(customers.columns.find(c => c.name === "region")!.notNull).toBe(true);
    });

    it("introspect 给出外键指向", async () => {
      const orders = (await driver.introspect()).find(t => t.tableName === "contract_orders")!;
      expect(orders.foreignKeys).toEqual(expect.arrayContaining([
        { column: "customer_id", refTable: "contract_customers", refColumn: "customer_id" },
      ]));
    });

    it("按月汇总的结果三种源一致", async () => {
      const { rows } = await driver.runQuery(hooks.sql.monthlyTotals, 100, 5000);
      const pairs = rows.map(r => [String(Object.values(r)[0]), Number(Object.values(r)[1])]);
      expect(pairs).toEqual([["2024-01", 300], ["2024-02", 700], ["2024-03", 1100]]);
    });

    it("超过上限时切到上限并标记 truncated", async () => {
      const r = await driver.runQuery(hooks.sql.manyRows, 3, 5000);
      expect(r.rows).toHaveLength(3);
      expect(r.truncated).toBe(true);
    });

    it("行数不足上限时不误报截断", async () => {
      const r = await driver.runQuery(hooks.sql.manyRows, 100, 5000);
      expect(r.rows).toHaveLength(6);
      expect(r.truncated).toBe(false);
    });

    it("查不存在的表报 SCHEMA_STALE", async () => {
      await expect(driver.runQuery(hooks.sql.badTable, 10, 5000)).rejects.toMatchObject({
        code: "SCHEMA_STALE",
      });
    });

    it("抛出的一律是 DsError 而不是原生错误", async () => {
      await expect(driver.runQuery(hooks.sql.badTable, 10, 5000)).rejects.toBeInstanceOf(DsError);
    });

    if (hooks.writeRejection === "engine") {
      it("写操作被引擎拒绝", async () => {
        await expect(driver.runQuery(hooks.sql.insert, 10, 5000)).rejects.toBeInstanceOf(DsError);
      });
    } else {
      it("引擎拦不住写(已知弱点),但能探出账号有写权限", async () => {
        expect(await driver.probeWritePrivilege()).toBe("writable");
      });
    }

    if (hooks.timeoutEnforcement === "server") {
      it("超时由服务端掐断", async () => {
        await expect(driver.runQuery(hooks.sql.slow, 10, 200)).rejects.toMatchObject({
          code: "TIMEOUT",
        });
      }, 20_000);
    } else {
      it.skip(`超时无法在进程内强制(${name} 同步执行),已知限制`, () => {
        // 占位:保留一个可见的 skip,让「跳过」出现在测试报告里而不是消失。
      });
    }
  });
}
