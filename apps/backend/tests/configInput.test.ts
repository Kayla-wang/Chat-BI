import { describe, it, expect } from "vitest";
import { parseDsConfigInput, mergeConfig, connectionView } from "../src/datasources/configInput";
import type { DsConfig } from "@chatbi/shared";

const mysqlSaved: DsConfig = {
  kind: "mysql", host: "10.0.0.5", port: 3306, database: "sales",
  user: "bi_ro", password: "老密码", ssl: false,
};

describe("parseDsConfigInput", () => {
  it("接受完整的 mysql 输入", () => {
    expect(parseDsConfigInput({
      kind: "mysql", host: "h", port: 3306, database: "d", user: "u", password: "p", ssl: true,
    })).toMatchObject({ kind: "mysql", host: "h", port: 3306, ssl: true });
  });
  it("接受省略 password 的输入(表示不改)", () => {
    const r = parseDsConfigInput({ kind: "mysql", host: "h", port: 3306, database: "d", user: "u", ssl: false });
    expect(r).not.toBeNull();
    expect(r!.kind === "mysql" && r!.password).toBeUndefined();
  });
  it("接受 sqlite 的路径", () => {
    expect(parseDsConfigInput({ kind: "sqlite", path: "./a.db" })).toEqual({ kind: "sqlite", path: "./a.db" });
  });
  it("postgres 的 schema 可选", () => {
    const r = parseDsConfigInput({
      kind: "postgres", host: "h", port: 5432, database: "d", user: "u", password: "p", ssl: false, schema: "bi",
    });
    expect(r).toMatchObject({ kind: "postgres", schema: "bi" });
  });
  it("端口是字符串数字时转成 number", () => {
    const r = parseDsConfigInput({ kind: "mysql", host: "h", port: "3306", database: "d", user: "u", ssl: false });
    expect(r!.kind === "mysql" && r!.port).toBe(3306);
  });
  it("kind 不认识返回 null", () => {
    expect(parseDsConfigInput({ kind: "oracle", host: "h" })).toBeNull();
  });
  it("缺必填字段返回 null", () => {
    expect(parseDsConfigInput({ kind: "mysql", host: "h", port: 3306 })).toBeNull();
    expect(parseDsConfigInput({ kind: "sqlite" })).toBeNull();
  });
  it("端口不是数字返回 null", () => {
    expect(parseDsConfigInput({ kind: "mysql", host: "h", port: "abc", database: "d", user: "u", ssl: false })).toBeNull();
  });
  it("不是对象返回 null", () => {
    expect(parseDsConfigInput(null)).toBeNull();
    expect(parseDsConfigInput("mysql")).toBeNull();
  });
});

describe("mergeConfig 的密码三态", () => {
  it("password 字段缺失 = 保留旧密码", () => {
    const input = parseDsConfigInput({
      kind: "mysql", host: "新地址", port: 3306, database: "sales", user: "bi_ro", ssl: false,
    })!;
    const merged = mergeConfig(mysqlSaved, input);
    expect(merged).toMatchObject({ host: "新地址", password: "老密码" });
  });
  it("password 是空字符串 = 真的把密码设成空", () => {
    const input = parseDsConfigInput({
      kind: "mysql", host: "h", port: 3306, database: "d", user: "u", password: "", ssl: false,
    })!;
    expect(mergeConfig(mysqlSaved, input).kind === "mysql"
      && (mergeConfig(mysqlSaved, input) as { password: string }).password).toBe("");
  });
  it("password 有值 = 换成新的", () => {
    const input = parseDsConfigInput({
      kind: "mysql", host: "h", port: 3306, database: "d", user: "u", password: "新密码", ssl: false,
    })!;
    expect((mergeConfig(mysqlSaved, input) as { password: string }).password).toBe("新密码");
  });
  it("换了 kind 时不继承旧密码", () => {
    const input = parseDsConfigInput({
      kind: "postgres", host: "h", port: 5432, database: "d", user: "u", password: "p", ssl: false,
    })!;
    expect(mergeConfig(mysqlSaved, input).kind).toBe("postgres");
  });
  it("新建时缺密码就报错,不静默存空密码", () => {
    const input = parseDsConfigInput({
      kind: "mysql", host: "h", port: 3306, database: "d", user: "u", ssl: false,
    })!;
    expect(() => mergeConfig(null, input)).toThrow(/密码/);
  });
  it("换 kind 且缺密码同样报错", () => {
    const input = parseDsConfigInput({
      kind: "postgres", host: "h", port: 5432, database: "d", user: "u", ssl: false,
    })!;
    expect(() => mergeConfig(mysqlSaved, input)).toThrow(/密码/);
  });
  it("sqlite 不需要密码", () => {
    expect(mergeConfig(null, { kind: "sqlite", path: "./a.db" })).toEqual({ kind: "sqlite", path: "./a.db" });
  });
});

describe("connectionView", () => {
  it("给出非敏感字段,且绝对没有 password", () => {
    const v = connectionView(mysqlSaved);
    expect(v).toEqual({ host: "10.0.0.5", port: 3306, database: "sales", user: "bi_ro", ssl: false });
    expect(JSON.stringify(v)).not.toContain("老密码");
    expect("password" in v).toBe(false);
  });
  it("sqlite 只给路径", () => {
    expect(connectionView({ kind: "sqlite", path: "./a.db" })).toEqual({ path: "./a.db" });
  });
});
