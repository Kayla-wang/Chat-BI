import { describe, it, expect } from "vitest";
import { buildPrompt, buildInsightPrompt } from "../src/promptBuilder";
import type { TableSchema, ChatTurn, InsightFact, ValueFormat } from "@chatbi/shared";
import { SQLITE_DIALECT, MYSQL_DIALECT, POSTGRES_DIALECT } from "../src/datasources/dialect";

const schema: TableSchema[] = [{
  tableName: "orders",
  columns: [
    { name: "id", type: "INTEGER", notNull: true, pk: true },
    { name: "amount", type: "REAL", notNull: false, pk: false },
  ],
  foreignKeys: [{ column: "cust_id", refTable: "customers", refColumn: "id" }],
}];

describe("buildPrompt", () => {
  it("injects schema table/column names", () => {
    const p = buildPrompt({ question: "orders 总额", schema, history: [] , dialect: SQLITE_DIALECT });
    expect(p).toContain("orders");
    expect(p).toContain("amount");
    expect(p).toContain("cust_id");
  });
  it("includes the user question verbatim", () => {
    const p = buildPrompt({ question: "各地区上季度销售额", schema, history: [] , dialect: SQLITE_DIALECT });
    expect(p).toContain("各地区上季度销售额");
  });
  it("truncates history to the last 4 messages (2 full rounds)", () => {
    const history: ChatTurn[] = [
      { role: "user", text: "q1" }, { role: "assistant", text: "a1" },
      { role: "user", text: "q2" }, { role: "assistant", text: "a2" },
      { role: "user", text: "q3" }, { role: "assistant", text: "a3" },
      { role: "user", text: "q4" }, { role: "assistant", text: "a4" },
    ];
    const p = buildPrompt({ question: "q5", schema, history , dialect: SQLITE_DIALECT });
    expect(p).toContain("q3"); expect(p).toContain("q4");
    expect(p).not.toContain("q1"); expect(p).not.toContain("q2");
  });
  it("demands strict JSON output with sql/chartType/explanation", () => {
    const p = buildPrompt({ question: "x", schema, history: [] , dialect: SQLITE_DIALECT });
    expect(p).toMatch(/strict.*JSON|"sql"/i);
    expect(p).toMatch(/chartType/);
    expect(p).toMatch(/explanation/);
  });
  it("lists chartType allowed values", () => {
    const p = buildPrompt({ question: "x", schema, history: [] , dialect: SQLITE_DIALECT });
    expect(p).toMatch(/bar|line|pie|table/);
  });
});

describe("buildPrompt 图表 hint 字段", () => {
  it("要求输出 dimensions/measures/seriesBy/stack", () => {
    const p = buildPrompt({ question: "x", schema, history: [] , dialect: SQLITE_DIALECT });
    expect(p).toContain("dimensions");
    expect(p).toContain("measures");
    expect(p).toContain("seriesBy");
    expect(p).toContain("stack");
  });
  it("说明 hint 列名必须是结果列别名", () => {
    const p = buildPrompt({ question: "x", schema, history: [] , dialect: SQLITE_DIALECT });
    expect(p).toMatch(/别名/);
  });
  it("列出 stack 的取值", () => {
    const p = buildPrompt({ question: "x", schema, history: [] , dialect: SQLITE_DIALECT });
    expect(p).toMatch(/normal/);
    expect(p).toMatch(/percent/);
  });
});

describe("buildPrompt 下钻上下文", () => {
  const context = {
    lastSql: "SELECT strftime('%Y-%m', order_date) AS month, SUM(total_amount) AS amount FROM orders GROUP BY month",
    lastColumns: ["month", "amount"],
  };
  it("有 context 时注入上轮 SQL 与结果列", () => {
    const p = buildPrompt({ question: "只看华东区", schema, history: [], context , dialect: SQLITE_DIALECT });
    expect(p).toContain("上一轮查询");
    expect(p).toContain("SUM(total_amount) AS amount");
    expect(p).toContain("month, amount");
    expect(p).toMatch(/细化/);
  });
  it("无 context 时完全不出现上一轮段落", () => {
    const p = buildPrompt({ question: "只看华东区", schema, history: [] , dialect: SQLITE_DIALECT });
    expect(p).not.toContain("上一轮查询");
  });
});

describe("buildInsightPrompt", () => {
  const FORMAT: ValueFormat = { kind: "currency", decimals: 0, unit: "元", scale: 1 };
  const facts: InsightFact[] = [
    { kind: "trend", series: "金额", dir: "up", pct: 23.4, from: "1月", to: "3月" },
    { kind: "peak", series: "金额", label: "3月", value: 128400 },
  ];
  it("逐条列出事实且数值已格式化", () => {
    const p = buildInsightPrompt(facts, "按月统计订单金额", FORMAT);
    expect(p).toContain("上涨 23.4%");
    expect(p).toContain("128,400 元");
  });
  it("带上用户问题", () => {
    expect(buildInsightPrompt(facts, "按月统计订单金额", FORMAT)).toContain("按月统计订单金额");
  });
  it("写明不得引入未列出的数字", () => {
    const p = buildInsightPrompt(facts, "q", FORMAT);
    expect(p).toMatch(/不得引入/);
    expect(p).toMatch(/不得逐条罗列/);
  });
});

describe("方言提示", () => {
  const base = { question: "按月统计订单金额", schema: [], history: [] };

  it("把方言提示原文放进 prompt", () => {
    const p = buildPrompt({ ...base, dialect: MYSQL_DIALECT });
    expect(p).toContain(MYSQL_DIALECT.promptNotes);
  });

  it("MySQL 提示里是 DATE_FORMAT,不出现 strftime", () => {
    const p = buildPrompt({ ...base, dialect: MYSQL_DIALECT });
    expect(p).toContain("DATE_FORMAT");
    expect(p).not.toContain("strftime");
  });

  it("PostgreSQL 提示里是 date_trunc", () => {
    expect(buildPrompt({ ...base, dialect: POSTGRES_DIALECT })).toContain("date_trunc");
  });

  it("换方言时 prompt 真的变了", () => {
    const a = buildPrompt({ ...base, dialect: SQLITE_DIALECT });
    const b = buildPrompt({ ...base, dialect: POSTGRES_DIALECT });
    expect(a).not.toBe(b);
  });

  it("与方言无关的规则仍然在(只读、只输出 JSON)", () => {
    const p = buildPrompt({ ...base, dialect: POSTGRES_DIALECT });
    expect(p).toContain("只生成 SELECT");
    expect(p).toContain("只输出 JSON");
  });
});
