import { describe, it, expect } from "vitest";
import {
  validate, validateByRegex, stripLiterals, hasComment, enforceLimit, wrapTimeout,
} from "../src/sqlGuard";
import { SQLITE_DIALECT, MYSQL_DIALECT, POSTGRES_DIALECT } from "../src/datasources/dialect";

describe("validate 放行只读查询", () => {
  it("普通 SELECT", () => {
    const r = validate("SELECT * FROM customers", SQLITE_DIALECT);
    expect(r.ok).toBe(true);
    expect((r as any).sql).toBe("SELECT * FROM customers");
  });
  it("WITH ... SELECT (CTE)", () => {
    expect(validate("WITH t AS (SELECT 1 AS a) SELECT * FROM t", SQLITE_DIALECT).ok).toBe(true);
  });
  it("带聚合与分组的真实查询", () => {
    const sql = "SELECT region, SUM(total_amount) AS amount FROM orders o "
      + "JOIN customers c ON c.customer_id = o.customer_id GROUP BY region ORDER BY amount DESC";
    expect(validate(sql, SQLITE_DIALECT).ok).toBe(true);
  });
  it("末尾单个分号可接受", () => {
    const r = validate("SELECT 1;", SQLITE_DIALECT);
    expect(r.ok).toBe(true);
    expect((r as any).sql).toBe("SELECT 1");
  });
  it("字符串字面量里的关键字不误杀", () => {
    expect(validate("SELECT '已delete' AS status", SQLITE_DIALECT).ok).toBe(true);
    expect(validate("SELECT id FROM t WHERE note = 'drop table'", SQLITE_DIALECT).ok).toBe(true);
  });
  it("列名含关键字前缀不误杀", () => {
    expect(validate("SELECT update_time, create_at FROM orders", SQLITE_DIALECT).ok).toBe(true);
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
    expect(validate(sql, SQLITE_DIALECT).ok).toBe(false);
  });
  it("拦截堆叠查询", () => {
    expect(validate("SELECT 1; DROP TABLE customers", SQLITE_DIALECT).ok).toBe(false);
    expect(validate("SELECT 1; PRAGMA database_list", SQLITE_DIALECT).ok).toBe(false);
  });
  it("拦截 ATTACH", () => {
    expect(validate("ATTACH 'x.db' AS other", SQLITE_DIALECT).ok).toBe(false);
  });
});

describe("validate 拦截注释", () => {
  it("行注释", () => {
    const r = validate("SELECT 1 -- drop table customers", SQLITE_DIALECT);
    expect(r.ok).toBe(false);
    expect((r as any).reason).toMatch(/注释|comment/i);
  });
  it("块注释", () => {
    expect(validate("SELECT /* x */ 1", SQLITE_DIALECT).ok).toBe(false);
  });
  it("字符串里的 -- 不算注释", () => {
    expect(hasComment("SELECT '--x' AS a")).toBe(false);
    expect(validate("SELECT '--x' AS a", SQLITE_DIALECT).ok).toBe(true);
  });
});

describe("AST 解析失败时回退正则", () => {
  it("解析不了但形似 SELECT → 放行且标记非 AST 路径", () => {
    const r = validate("SELECT * FROM", SQLITE_DIALECT);
    expect(r.ok).toBe(true);
    expect((r as any).viaAst).toBe(false);
  });
  it("解析不了且是写操作 → 仍然拦截", () => {
    expect(validate("INSERT INTO t VALUES", SQLITE_DIALECT).ok).toBe(false);
  });
  it("validateByRegex 单独可用", () => {
    expect(validateByRegex("SELECT 1", SQLITE_DIALECT).ok).toBe(true);
    expect(validateByRegex("VACUUM", SQLITE_DIALECT).ok).toBe(false);
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

describe("按方言解析 AST", () => {
  it("MySQL 的反引号标识符走 AST 而不是退回正则", () => {
    const r = validate("SELECT `order date` FROM `orders`", MYSQL_DIALECT);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.viaAst).toBe(true);
  });
  it("PostgreSQL 的 :: 类型转换走 AST", () => {
    const r = validate("SELECT SUM(amount)::numeric FROM orders", POSTGRES_DIALECT);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.viaAst).toBe(true);
  });
});

describe("MySQL 特有的逃逸口", () => {
  it("拦 INTO OUTFILE", () => {
    expect(validate("SELECT * FROM orders INTO OUTFILE '/tmp/x'", MYSQL_DIALECT).ok).toBe(false);
  });
  it("拦 INTO DUMPFILE", () => {
    expect(validate("SELECT a FROM t INTO DUMPFILE '/tmp/x'", MYSQL_DIALECT).ok).toBe(false);
  });
  it("拦 LOAD_FILE 函数", () => {
    expect(validate("SELECT LOAD_FILE('/etc/passwd') AS x", MYSQL_DIALECT).ok).toBe(false);
  });
  it("不误杀名叫 load_file 的列", () => {
    expect(validate("SELECT load_file FROM audit", MYSQL_DIALECT).ok).toBe(true);
  });
});

describe("PostgreSQL 特有的逃逸口", () => {
  it("拦 pg_read_file", () => {
    expect(validate("SELECT pg_read_file('/etc/passwd') AS x", POSTGRES_DIALECT).ok).toBe(false);
  });
  it("拦 dblink", () => {
    expect(validate("SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(x int)", POSTGRES_DIALECT).ok).toBe(false);
  });
  it("拦 pg_sleep", () => {
    expect(validate("SELECT pg_sleep(100) AS x", POSTGRES_DIALECT).ok).toBe(false);
  });
  it("拦行首的 COPY", () => {
    expect(validateByRegex("COPY orders TO '/tmp/x'", POSTGRES_DIALECT).ok).toBe(false);
  });
  it("不误杀名叫 dblink 的列", () => {
    expect(validate("SELECT dblink FROM connections", POSTGRES_DIALECT).ok).toBe(true);
  });
  it("不误杀字符串字面量里的 pg_read_file", () => {
    expect(validate("SELECT 'pg_read_file(x)' AS note", POSTGRES_DIALECT).ok).toBe(true);
  });
});

describe("跨方言不互相污染", () => {
  it("sqlite 不因为 MySQL 的词表被拦", () => {
    expect(validate("SELECT load_file FROM t", SQLITE_DIALECT).ok).toBe(true);
  });
  it("MySQL 不因为 PG 的词表被拦", () => {
    expect(validate("SELECT dblink FROM t", MYSQL_DIALECT).ok).toBe(true);
  });
});
