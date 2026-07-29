import { describe, it, expect } from "vitest";
import {
  validate, validateByRegex, stripLiterals, hasComment, enforceLimit, wrapTimeout,
} from "../src/sqlGuard";

describe("validate 放行只读查询", () => {
  it("普通 SELECT", () => {
    const r = validate("SELECT * FROM customers");
    expect(r.ok).toBe(true);
    expect((r as any).sql).toBe("SELECT * FROM customers");
  });
  it("WITH ... SELECT (CTE)", () => {
    expect(validate("WITH t AS (SELECT 1 AS a) SELECT * FROM t").ok).toBe(true);
  });
  it("带聚合与分组的真实查询", () => {
    const sql = "SELECT region, SUM(total_amount) AS amount FROM orders o "
      + "JOIN customers c ON c.customer_id = o.customer_id GROUP BY region ORDER BY amount DESC";
    expect(validate(sql).ok).toBe(true);
  });
  it("末尾单个分号可接受", () => {
    const r = validate("SELECT 1;");
    expect(r.ok).toBe(true);
    expect((r as any).sql).toBe("SELECT 1");
  });
  it("字符串字面量里的关键字不误杀", () => {
    expect(validate("SELECT '已delete' AS status").ok).toBe(true);
    expect(validate("SELECT id FROM t WHERE note = 'drop table'").ok).toBe(true);
  });
  it("列名含关键字前缀不误杀", () => {
    expect(validate("SELECT update_time, create_at FROM orders").ok).toBe(true);
  });
});

describe("validate 拦截写操作与 DDL", () => {
  it.each([
    ["INSERT INTO customers VALUES (1,'x')"],
    ["UPDATE customers SET name='x'"],
    ["DELETE FROM customers"],
    ["DROP TABLE customers"],
    ["CREATE TABLE x (id int)"],
    ["ALTER TABLE customers ADD col int"],
  ])("拦截 %s", sql => {
    expect(validate(sql).ok).toBe(false);
  });
  it("拦截堆叠查询", () => {
    expect(validate("SELECT 1; DROP TABLE customers").ok).toBe(false);
    expect(validate("SELECT 1; PRAGMA database_list").ok).toBe(false);
  });
  it("拦截 ATTACH", () => {
    expect(validate("ATTACH 'x.db' AS other").ok).toBe(false);
  });
});

describe("validate 拦截注释", () => {
  it("行注释", () => {
    const r = validate("SELECT 1 -- drop table customers");
    expect(r.ok).toBe(false);
    expect((r as any).reason).toMatch(/注释|comment/i);
  });
  it("块注释", () => {
    expect(validate("SELECT /* x */ 1").ok).toBe(false);
  });
  it("字符串里的 -- 不算注释", () => {
    expect(hasComment("SELECT '--x' AS a")).toBe(false);
    expect(validate("SELECT '--x' AS a").ok).toBe(true);
  });
});

describe("AST 解析失败时回退正则", () => {
  it("解析不了但形似 SELECT → 放行且标记非 AST 路径", () => {
    const r = validate("SELECT * FROM");
    expect(r.ok).toBe(true);
    expect((r as any).viaAst).toBe(false);
  });
  it("解析不了且是写操作 → 仍然拦截", () => {
    expect(validate("INSERT INTO t VALUES").ok).toBe(false);
  });
  it("validateByRegex 单独可用", () => {
    expect(validateByRegex("SELECT 1").ok).toBe(true);
    expect(validateByRegex("VACUUM").ok).toBe(false);
  });
});

describe("stripLiterals", () => {
  it("单双引号字面量都被清空", () => {
    expect(stripLiterals("SELECT 'a', \"b\" FROM t")).toBe("SELECT '', \"\" FROM t");
  });
});

describe("enforceLimit", () => {
  it("缺 LIMIT 时注入", () => {
    expect(enforceLimit("SELECT * FROM customers", 1000)).toBe("SELECT * FROM customers LIMIT 1000");
  });
  it("已有 LIMIT 时不重复注入", () => {
    expect(enforceLimit("SELECT * FROM customers LIMIT 5", 1000)).toBe("SELECT * FROM customers LIMIT 5");
  });
  it("处理末尾分号", () => {
    expect(enforceLimit("SELECT * FROM customers;", 1000)).toBe("SELECT * FROM customers LIMIT 1000");
  });
});

describe("wrapTimeout", () => {
  it("足够快时正常 resolve", async () => {
    await expect(wrapTimeout(100, Promise.resolve(7))).resolves.toBe(7);
  });
  it("超时时抛 timeout", async () => {
    await expect(wrapTimeout(50, new Promise(r => setTimeout(r, 200)))).rejects.toThrow(/timeout/i);
  });
});
