import { describe, it, expect } from "vitest";
import { dialectFor, SQLITE_DIALECT, MYSQL_DIALECT, POSTGRES_DIALECT } from "../src/datasources/dialect";

describe("quoteIdent", () => {
  it("sqlite 与 postgres 用双引号", () => {
    expect(SQLITE_DIALECT.quoteIdent("order date")).toBe('"order date"');
    expect(POSTGRES_DIALECT.quoteIdent("order date")).toBe('"order date"');
  });
  it("mysql 用反引号", () => {
    expect(MYSQL_DIALECT.quoteIdent("order date")).toBe("`order date`");
  });
  it("转义标识符里的引号,防止拼接被截断", () => {
    expect(POSTGRES_DIALECT.quoteIdent('a"b')).toBe('"a""b"');
    expect(MYSQL_DIALECT.quoteIdent("a`b")).toBe("`a``b`");
  });
});

describe("sqlParserDialect", () => {
  it("三种源各自对应 node-sql-parser 的方言名", () => {
    expect(SQLITE_DIALECT.sqlParserDialect).toBe("sqlite");
    expect(MYSQL_DIALECT.sqlParserDialect).toBe("mysql");
    expect(POSTGRES_DIALECT.sqlParserDialect).toBe("postgresql");
  });
});

describe("promptNotes", () => {
  it("各自举出本方言的时间截断函数", () => {
    expect(SQLITE_DIALECT.promptNotes).toContain("strftime");
    expect(MYSQL_DIALECT.promptNotes).toContain("DATE_FORMAT");
    expect(POSTGRES_DIALECT.promptNotes).toContain("date_trunc");
  });
  it("三段提示互不相同且都非空", () => {
    const all = [SQLITE_DIALECT, MYSQL_DIALECT, POSTGRES_DIALECT].map(d => d.promptNotes);
    expect(new Set(all).size).toBe(3);
    for (const n of all) expect(n.trim().length).toBeGreaterThan(0);
  });
  it("不含别的方言的函数名,避免误导模型", () => {
    expect(MYSQL_DIALECT.promptNotes).not.toContain("strftime");
    expect(POSTGRES_DIALECT.promptNotes).not.toContain("DATE_FORMAT");
  });
});

describe("dialectFor", () => {
  it("按 kind 取到对应方言", () => {
    expect(dialectFor("sqlite")).toBe(SQLITE_DIALECT);
    expect(dialectFor("mysql")).toBe(MYSQL_DIALECT);
    expect(dialectFor("postgres")).toBe(POSTGRES_DIALECT);
  });
});
