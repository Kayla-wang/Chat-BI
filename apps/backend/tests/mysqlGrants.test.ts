import { describe, it, expect } from "vitest";
import { parseMysqlGrants } from "../src/datasources/drivers/mysql";

describe("parseMysqlGrants", () => {
  it("只有 SELECT 与 USAGE 时判为只读", () => {
    expect(parseMysqlGrants([
      "GRANT USAGE ON *.* TO `bi_ro`@`%`",
      "GRANT SELECT ON `sales`.* TO `bi_ro`@`%`",
    ])).toBe("readonly");
  });

  it("有 INSERT 时判为可写", () => {
    expect(parseMysqlGrants([
      "GRANT SELECT, INSERT ON `sales`.* TO `app`@`%`",
    ])).toBe("writable");
  });

  it("ALL PRIVILEGES 判为可写", () => {
    expect(parseMysqlGrants(["GRANT ALL PRIVILEGES ON *.* TO `root`@`localhost`"])).toBe("writable");
  });

  it("只看 GRANT 与 ON 之间的权限段,不被库名误导", () => {
    expect(parseMysqlGrants([
      "GRANT SELECT ON `insert_logs`.* TO `bi_ro`@`%`",
    ])).toBe("readonly");
  });

  it("认不出格式时返回 unknown,不谎称安全", () => {
    expect(parseMysqlGrants(["这不是一条 grant"])).toBe("unknown");
    expect(parseMysqlGrants([])).toBe("unknown");
  });

  it("多条里只要有一条可写就判可写", () => {
    expect(parseMysqlGrants([
      "GRANT SELECT ON `a`.* TO `u`@`%`",
      "GRANT DELETE ON `b`.* TO `u`@`%`",
    ])).toBe("writable");
  });
});
