import { describe, it, expect } from "vitest";
import { validate, enforceLimit, wrapTimeout } from "../src/sqlGuard";

describe("validate", () => {
  it("accepts plain select", () => {
    expect(validate("SELECT * FROM customers")).toEqual({ ok: true, sql: "SELECT * FROM customers" });
  });
  it("rejects INSERT", () => {
    expect(validate("INSERT INTO customers VALUES (1,'x')").ok).toBe(false);
  });
  it("rejects UPDATE", () => {
    expect(validate("UPDATE customers SET name='x'").ok).toBe(false);
  });
  it("rejects DELETE", () => {
    expect(validate("DELETE FROM customers").ok).toBe(false);
  });
  it("rejects DROP / CREATE / ALTER (DDL)", () => {
    expect(validate("DROP TABLE customers").ok).toBe(false);
    expect(validate("CREATE TABLE x (id int)").ok).toBe(false);
    expect(validate("ALTER TABLE customers ADD col int").ok).toBe(false);
  });
  it("rejects stacked queries (semicolon after select)", () => {
    expect(validate("SELECT 1; DROP TABLE customers").ok).toBe(false);
  });
  it("rejects PRAGMA attached after select", () => {
    expect(validate("SELECT 1; PRAGMA database_list").ok).toBe(false);
  });
  it("rejects attach / detach", () => {
    expect(validate("ATTACH 'x.db' AS other").ok).toBe(false);
  });
  it("allows WITH ... select (CTE)", () => {
    expect(validate("WITH t AS (SELECT 1) SELECT * FROM t").ok).toBe(true);
  });
});

describe("enforceLimit", () => {
  it("adds LIMIT when absent", () => {
    expect(enforceLimit("SELECT * FROM customers", 1000)).toBe("SELECT * FROM customers LIMIT 1000");
  });
  it("does not double-add LIMIT when present", () => {
    expect(enforceLimit("SELECT * FROM customers LIMIT 5", 1000)).toBe("SELECT * FROM customers LIMIT 5");
  });
  it("handles trailing semicolon", () => {
    expect(enforceLimit("SELECT * FROM customers;", 1000)).toBe("SELECT * FROM customers LIMIT 1000");
  });
});

describe("wrapTimeout", () => {
  it("resolves when promise fast enough", async () => {
    await expect(wrapTimeout(100, Promise.resolve(7))).resolves.toBe(7);
  });
  it("rejects with timeout error when slow", async () => {
    const slow = new Promise(r => setTimeout(r, 200));
    await expect(wrapTimeout(50, slow)).rejects.toThrow(/timeout/i);
  });
});
