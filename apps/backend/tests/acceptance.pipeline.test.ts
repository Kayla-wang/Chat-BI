/**
 * 用真实示例库 + stub LLM 跑验收清单的四个场景。
 * 覆盖 migrate 数据 → sqlGuard → dbClient → chartAssembler 的真实链路,
 * 但不代替 README 的人工验收(那一步要验 LLM 自己选的 SQL 与图表类型)。
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { DbClient } from "../src/dbClient";
import { migrate } from "../src/migrate";
import { handleChat } from "../src/chatService";
import type { ChartType, StreamEvent } from "@chatbi/shared";

const tmpDir = join(process.cwd(), ".tmp-acceptance");
let db: DbClient;

beforeAll(() => {
  mkdirSync(tmpDir, { recursive: true });
  db = new DbClient(join(tmpDir, "a.db"));
  migrate(db);
});
afterAll(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

async function ask(sql: string, chartType: ChartType, explanation: string) {
  const raw = JSON.stringify({ sql, chartType, explanation });
  const deps = {
    db: { getSchema: () => db.getSchema(), runQuery: (s: string) => db.runQuery(s) },
    llm: { chatStream: async function* () { yield raw; } },
  };
  const events: StreamEvent[] = [];
  for await (const e of handleChat({ question: explanation, history: [], deps })) events.push(e);
  return events;
}

describe("验收场景(真实示例库 + stub LLM)", () => {
  it("1. 按月统计订单金额 → line", async () => {
    const events = await ask(
      "SELECT substr(order_date,1,7) month, SUM(total_amount) amount FROM orders GROUP BY month ORDER BY month",
      "line", "按月统计订单金额",
    );
    const r = events.find(e => e.type === "result") as any;
    expect(r.payload.chartType).toBe("line");
    expect(r.payload.table.rows.length).toBeGreaterThan(1);
    expect(r.payload.echartsOption.series[0].type).toBe("line");
  });

  it("2. 各产品类别销售额占比 → pie", async () => {
    const events = await ask(
      "SELECT p.category category, SUM(oi.quantity * oi.unit_price) amount FROM order_items oi JOIN products p ON p.product_id = oi.product_id GROUP BY p.category",
      "pie", "各产品类别销售额占比",
    );
    const r = events.find(e => e.type === "result") as any;
    expect(r.payload.chartType).toBe("pie");
    const data = r.payload.echartsOption.series[0].data;
    expect(data.length).toBeGreaterThan(1);
    expect(data.every((d: any) => typeof d.name === "string" && Number.isFinite(d.value))).toBe(true);
  });

  it("3. 各地区订单总额对比 → bar", async () => {
    const events = await ask(
      "SELECT c.region region, SUM(o.total_amount) amount FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.region ORDER BY amount DESC",
      "bar", "各地区订单总额对比",
    );
    const r = events.find(e => e.type === "result") as any;
    expect(r.payload.chartType).toBe("bar");
    expect(r.payload.echartsOption.xAxis.data.length).toBe(r.payload.table.rows.length);
    expect(r.payload.table.rows.length).toBeGreaterThan(1);
  });

  it("4. 查询 1999 年的订单 → 空结果不报错", async () => {
    const events = await ask(
      "SELECT order_id, order_date, total_amount FROM orders WHERE order_date LIKE '1999%'",
      "table", "1999 年没有订单记录",
    );
    const r = events.find(e => e.type === "result") as any;
    expect(events.some(e => e.type === "error")).toBe(false);
    expect(r.payload.table.rows).toEqual([]);
    expect(r.payload.explanation).toBe("1999 年没有订单记录");
  });

  it("写操作被拦截,示例库不被改动", async () => {
    const before = db.runQuery("SELECT COUNT(*) n FROM orders")[0].n;
    const events = await ask("DELETE FROM orders", "table", "删掉订单");
    const err = events.find(e => e.type === "error") as any;
    expect(err.message).toMatch(/拦截/);
    expect(db.runQuery("SELECT COUNT(*) n FROM orders")[0].n).toBe(before);
  });
});
