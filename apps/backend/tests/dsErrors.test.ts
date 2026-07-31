import { describe, it, expect } from "vitest";
import { mapMysqlError, mapPgError, mapSqliteError, isRetryable, DsError } from "../src/datasources/errors";

const mysqlErr = (code: string, message = "boom") => Object.assign(new Error(message), { code });
const pgErr = (code: string, message = "boom") => Object.assign(new Error(message), { code });

describe("mapMysqlError", () => {
  const cases: [string, string][] = [
    ["ECONNREFUSED", "CONNECTION_ERROR"],
    ["ENOTFOUND", "CONNECTION_ERROR"],
    ["ETIMEDOUT", "CONNECTION_ERROR"],
    ["ER_ACCESS_DENIED_ERROR", "AUTH_ERROR"],
    ["ER_BAD_DB_ERROR", "DB_NOT_FOUND"],
    ["ER_QUERY_TIMEOUT", "TIMEOUT"],
    ["ER_NO_SUCH_TABLE", "SCHEMA_STALE"],
    ["ER_BAD_FIELD_ERROR", "SCHEMA_STALE"],
    ["ER_PARSE_ERROR", "SQL_ERROR"],
    ["ER_TABLEACCESS_DENIED_ERROR", "PERMISSION_ERROR"],
  ];
  for (const [code, expected] of cases) {
    it(`${code} → ${expected}`, () => {
      expect(mapMysqlError(mysqlErr(code)).code).toBe(expected);
    });
  }
  it("未知错误码归入 UNKNOWN 并保留原文", () => {
    const e = mapMysqlError(mysqlErr("ER_SOMETHING_NEW", "原始英文消息"));
    expect(e.code).toBe("UNKNOWN");
    expect(e.details).toContain("原始英文消息");
  });
  it("消息是可读中文,不是原始错误码", () => {
    const e = mapMysqlError(mysqlErr("ECONNREFUSED"));
    expect(e.message).toMatch(/无法连接/);
    expect(e.message).not.toContain("ECONNREFUSED");
  });
});

describe("mapPgError", () => {
  const cases: [string, string][] = [
    ["28P01", "AUTH_ERROR"],
    ["28000", "AUTH_ERROR"],
    ["3D000", "DB_NOT_FOUND"],
    ["57014", "TIMEOUT"],
    ["42P01", "SCHEMA_STALE"],
    ["42703", "SCHEMA_STALE"],
    ["42601", "SQL_ERROR"],
    ["42501", "PERMISSION_ERROR"],
    ["25006", "PERMISSION_ERROR"],
  ];
  for (const [code, expected] of cases) {
    it(`SQLSTATE ${code} → ${expected}`, () => {
      expect(mapPgError(pgErr(code)).code).toBe(expected);
    });
  }
  it("网络层错误没有 SQLSTATE,按连接错误处理", () => {
    expect(mapPgError(pgErr("ECONNREFUSED")).code).toBe("CONNECTION_ERROR");
  });
  it("只读事务拒绝写入时给出解释性消息", () => {
    expect(mapPgError(pgErr("25006")).message).toMatch(/只读/);
  });
});

describe("mapSqliteError", () => {
  it("打不开文件 → DB_NOT_FOUND", () => {
    expect(mapSqliteError(mysqlErr("SQLITE_CANTOPEN")).code).toBe("DB_NOT_FOUND");
  });
  it("只读连接拒绝写 → PERMISSION_ERROR", () => {
    expect(mapSqliteError(mysqlErr("SQLITE_READONLY")).code).toBe("PERMISSION_ERROR");
  });
  it("表不存在 → SCHEMA_STALE", () => {
    expect(mapSqliteError(mysqlErr("SQLITE_ERROR", "no such table: orders")).code).toBe("SCHEMA_STALE");
  });
  it("列不存在 → SCHEMA_STALE", () => {
    expect(mapSqliteError(mysqlErr("SQLITE_ERROR", "no such column: amt")).code).toBe("SCHEMA_STALE");
  });
  it("其它语法错 → SQL_ERROR", () => {
    expect(mapSqliteError(mysqlErr("SQLITE_ERROR", 'near "FROM": syntax error')).code).toBe("SQL_ERROR");
  });
  it("wrapTimeout 抛的超时 → TIMEOUT", () => {
    expect(mapSqliteError(new Error("query timeout")).code).toBe("TIMEOUT");
  });
  it("已经是 DsError 时原样返回,不二次包装", () => {
    const original = new DsError("TIMEOUT", "超时了");
    expect(mapSqliteError(original)).toBe(original);
  });
});

describe("isRetryable", () => {
  it("SQL 相关的错误值得把原因喂回模型重试一轮", () => {
    expect(isRetryable("SQL_ERROR")).toBe(true);
    expect(isRetryable("SCHEMA_STALE")).toBe(true);
  });
  it("连接、认证、超时、权限、解密都不该重试", () => {
    for (const c of ["CONNECTION_ERROR", "AUTH_ERROR", "DB_NOT_FOUND", "NOT_FOUND", "TIMEOUT",
      "PERMISSION_ERROR", "DECRYPT_ERROR", "UNKNOWN"] as const) {
      expect(isRetryable(c)).toBe(false);
    }
  });
});
