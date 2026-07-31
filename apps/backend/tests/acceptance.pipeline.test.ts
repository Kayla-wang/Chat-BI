/**
 * 用真实示例库 + stub LLM 跑验收清单的场景。
 * 覆盖 migrate 数据 → sqlGuard → sqlite driver → chartSpec → facts → insightWriter 的真实链路,
 * 但不代替 README 的人工验收(那一步要验 LLM 自己选的 SQL、hint 与措辞)。
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { DbClient } from "../src/dbClient";
import { migrate } from "../src/migrate";
import { handleChat } from "../src/chatService";
import { createSqliteDriver } from "../src/datasources/drivers/sqlite";
import type { ChartHint, StreamEvent } from "@chatbi/shared";

const tmpDir = join(process.cwd(), ".tmp-acceptance");
const dbPath = join(tmpDir, "a.db");
let db: DbClient;                       // 保留:第 8、9 条断言要用可读连接数行数与试写
let driver: ReturnType<typeof createSqliteDriver>;

beforeAll(() => {
  mkdirSync(tmpDir, { recursive: true });
  const writable = new DbClient(dbPath);
  migrate(writable);
  writable.close();
  db = new DbClient(dbPath, { readonly: true });
  driver = createSqliteDriver({ kind: "sqlite", path: dbPath });
});
afterAll(async () => {
  await driver.close();
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

async function ask(sql: string, hint: Partial<ChartHint>, explanation: string) {
  const raw = JSON.stringify({
    sql, explanation, chartType: "table", dimensions: [], measures: [], ...hint,
  });
  const deps = {
    // 走真 driver:这条验收链路顺带覆盖 driver → chatService 这一段。
    db: {
      getSchema: () => driver.introspect(),
      runQuery: (s: string, limit: number) => driver.runQuery(s, limit, 5000),
    },
    dialect: driver.dialect,
    llm: {
      chatStream: async function* (prompt: string) {
        // 第一轮出 JSON,第二轮(洞察)出散文——用 prompt 里的标志区分。
        yield prompt.includes("请用 2-3 句中文") ? "整体表现如上。" : raw;
      },
    },
  };
  const events: StreamEvent[] = [];
  for await (const e of handleChat({ question: explanation, history: [], deps })) events.push(e);
  return events;
}

const resultOf = (events: StreamEvent[]) => events.find(e => e.type === "result") as any;
const factsOf = (events: StreamEvent[]) => (events.find(e => e.type === "insightFacts") as any)?.facts ?? [];
const insightOf = (events: StreamEvent[]) =>
  events.filter(e => e.type === "insightDelta").map((e: any) => e.text).join("");

describe("验收场景(真实示例库 + stub LLM)", () => {
  it("1. 按月统计订单金额 → line + 时间轴 + 趋势事实", async () => {
    const events = await ask(
      "SELECT substr(order_date,1,7) AS month, SUM(total_amount) AS amount FROM orders GROUP BY month ORDER BY month",
      { chartType: "line", dimensions: ["month"], measures: ["amount"] },
      "按月统计订单金额",
    );
    const spec = resultOf(events).payload.spec;
    expect(spec.chartType).toBe("line");
    expect(spec.x.role).toBe("temporal");
    expect(spec.x.grain).toBe("month");
    expect(spec.series).toHaveLength(1);
    expect(factsOf(events).map((f: any) => f.kind)).toContain("trend");
    expect(insightOf(events)).toBe("整体表现如上。");
  });

  it("2. 各产品类别销售额占比 → pie + 占比事实", async () => {
    const events = await ask(
      "SELECT p.category AS category, SUM(oi.quantity * oi.unit_price) AS amount FROM order_items oi "
      + "JOIN products p ON p.product_id = oi.product_id GROUP BY p.category",
      { chartType: "pie", dimensions: ["category"], measures: ["amount"] },
      "各产品类别销售额占比",
    );
    const spec = resultOf(events).payload.spec;
    expect(spec.chartType).toBe("pie");
    expect(spec.x.labels.length).toBeGreaterThan(1);
    expect(spec.series[0].data.every((v: number) => Number.isFinite(v))).toBe(true);
    expect(factsOf(events).map((f: any) => f.kind)).toContain("topShare");
  });

  it("3. 各地区订单总额对比 → bar,轴与表格行数一致", async () => {
    const events = await ask(
      "SELECT c.region AS region, SUM(o.total_amount) AS amount FROM orders o "
      + "JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.region ORDER BY amount DESC",
      { chartType: "bar", dimensions: ["region"], measures: ["amount"] },
      "各地区订单总额对比",
    );
    const r = resultOf(events);
    expect(r.payload.spec.chartType).toBe("bar");
    expect(r.payload.spec.x.labels).toHaveLength(r.payload.table.rows.length);
  });

  it("4. 按月看各区域销售额 → 多系列", async () => {
    const events = await ask(
      "SELECT substr(o.order_date,1,7) AS month, c.region AS region, SUM(o.total_amount) AS amount "
      + "FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY month, region ORDER BY month",
      { chartType: "line", dimensions: ["month"], measures: ["amount"], seriesBy: "region" },
      "按月看各区域销售额",
    );
    const spec = resultOf(events).payload.spec;
    expect(spec.series.length).toBeGreaterThan(1);
    expect(spec.series.every((s: any) => s.data.length === spec.x.labels.length)).toBe(true);
  });

  it("5. 百分比堆叠 → stack 生效", async () => {
    const events = await ask(
      "SELECT c.region AS region, p.category AS category, SUM(oi.quantity * oi.unit_price) AS amount "
      + "FROM order_items oi JOIN products p ON p.product_id = oi.product_id "
      + "JOIN orders o ON o.order_id = oi.order_id JOIN customers c ON c.customer_id = o.customer_id "
      + "GROUP BY region, category",
      { chartType: "bar", dimensions: ["region"], measures: ["amount"], seriesBy: "category", stack: "percent" },
      "各区域各类别销售额占比结构",
    );
    expect(resultOf(events).payload.spec.stack).toBe("percent");
  });

  it("6. 查询 1999 年的订单 → 空结果不报错,洞察为固定文案", async () => {
    const events = await ask(
      "SELECT order_id, order_date, total_amount FROM orders WHERE order_date LIKE '1999%'",
      { chartType: "table" },
      "1999 年没有订单记录",
    );
    const r = resultOf(events);
    expect(events.some(e => e.type === "error")).toBe(false);
    expect(r.payload.table.rows).toEqual([]);
    expect(r.payload.spec.chartType).toBe("table");
    expect(r.payload.queryIntent).toBe("1999 年没有订单记录");
    expect(insightOf(events)).toBe("没有符合条件的记录。");
  });

  it("7. 事件序列以 done 结尾", async () => {
    const events = await ask(
      "SELECT c.region AS region, SUM(o.total_amount) AS amount FROM orders o "
      + "JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.region",
      { chartType: "bar", dimensions: ["region"], measures: ["amount"] },
      "各地区订单总额",
    );
    expect(events[0].type).toBe("result");
    expect(events[1].type).toBe("insightFacts");
    expect(events[events.length - 1].type).toBe("done");
  });

  it("8. 写操作被拦截,示例库不被改动", async () => {
    const before = db.runQuery("SELECT COUNT(*) AS n FROM orders", 10).rows[0].n;
    const events = await ask("DELETE FROM orders", { chartType: "table" }, "删掉订单");
    expect((events.find(e => e.type === "error") as any).message).toMatch(/拦截/);
    expect(db.runQuery("SELECT COUNT(*) AS n FROM orders", 10).rows[0].n).toBe(before);
  });

  it("9. 只读连接下写操作在引擎层被拒", () => {
    expect(() => db.execRaw("DELETE FROM orders")).toThrow(/readonly|read-only/i);
  });
});
