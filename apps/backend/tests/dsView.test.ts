import { describe, it, expect } from "vitest";
import { toSummary, toDetail } from "../src/datasources/view";
import type { DataSourceRecord } from "../src/datasources/types";
import type { TableSchema } from "@chatbi/shared";

const base: DataSourceRecord = {
  id: "ds1", name: "销售库", kind: "mysql", owner: "local",
  config: {
    kind: "mysql", host: "10.0.0.5", port: 3306, database: "sales",
    user: "bi_ro", password: "s3cret", ssl: false,
  },
  configError: false, writePrivilege: "readonly",
  createdAt: "2026-07-01T00:00:00.000Z", updatedAt: "2026-07-01T00:00:00.000Z",
  lastCheckAt: "2026-07-02T00:00:00.000Z", lastCheckOk: true, lastCheckError: null,
};

const schema: TableSchema[] = [
  { tableName: "orders", columns: [{ name: "id", type: "int", notNull: true, pk: true }], foreignKeys: [] },
  { tableName: "customers", columns: [], foreignKeys: [] },
];
const cache = { schema, fetchedAt: "2026-07-02T01:00:00.000Z" };

describe("toSummary 的 status 派生", () => {
  it("测过且成功 → ok", () => {
    expect(toSummary(base, cache).status).toBe("ok");
  });
  it("测过且失败 → error", () => {
    expect(toSummary({ ...base, lastCheckOk: false, lastCheckError: "连不上" }, cache).status).toBe("error");
  });
  it("从没测过 → unchecked", () => {
    expect(toSummary({ ...base, lastCheckAt: null, lastCheckOk: null }, null).status).toBe("unchecked");
  });
  it("解密失败 → needs_reconfig,盖掉上一次的 ok", () => {
    const broken = { ...base, config: null, configError: true };
    expect(toSummary(broken, cache).status).toBe("needs_reconfig");
  });
});

describe("toSummary 的其余字段", () => {
  it("target 是脱敏摘要,不含密码", () => {
    const s = toSummary(base, cache);
    expect(s.target).toBe("mysql://bi_ro@10.0.0.5:3306/sales");
    expect(JSON.stringify(s)).not.toContain("s3cret");
  });
  it("解密失败时 target 给出可读占位,不是空字符串", () => {
    expect(toSummary({ ...base, config: null, configError: true }, null).target).toBe("(凭据无法解密)");
  });
  it("tableCount 来自缓存的表数量", () => {
    expect(toSummary(base, cache).tableCount).toBe(2);
  });
  it("没有缓存时 tableCount 与 schemaFetchedAt 都是 null", () => {
    const s = toSummary(base, null);
    expect(s.tableCount).toBeNull();
    expect(s.schemaFetchedAt).toBeNull();
  });
  it("带上 name / kind / writePrivilege / lastCheck 两项", () => {
    const s = toSummary({ ...base, lastCheckOk: false, lastCheckError: "连不上" }, cache);
    expect(s).toMatchObject({
      id: "ds1", name: "销售库", kind: "mysql",
      writePrivilege: "readonly",
      lastCheckAt: "2026-07-02T00:00:00.000Z", lastCheckError: "连不上",
    });
  });
});

describe("toDetail", () => {
  it("在 summary 之上补 connection 与 hasPassword,且没有 password", () => {
    const d = toDetail(base, cache);
    expect(d.connection).toEqual({
      host: "10.0.0.5", port: 3306, database: "sales", user: "bi_ro", ssl: false,
    });
    expect(d.hasPassword).toBe(true);
    expect(JSON.stringify(d)).not.toContain("s3cret");
  });
  it("sqlite 的 connection 只有 path,hasPassword 为 false", () => {
    const lite: DataSourceRecord = {
      ...base, kind: "sqlite", config: { kind: "sqlite", path: "./data/chatbi.db" },
    };
    const d = toDetail(lite, null);
    expect(d.connection).toEqual({ path: "./data/chatbi.db" });
    expect(d.hasPassword).toBe(false);
  });
  it("空密码算没有密码", () => {
    const d = toDetail({ ...base, config: { ...base.config as any, password: "" } }, null);
    expect(d.hasPassword).toBe(false);
  });
  it("解密失败时 connection 是空对象,hasPassword 为 false", () => {
    const d = toDetail({ ...base, config: null, configError: true }, null);
    expect(d.connection).toEqual({});
    expect(d.hasPassword).toBe(false);
  });
});
