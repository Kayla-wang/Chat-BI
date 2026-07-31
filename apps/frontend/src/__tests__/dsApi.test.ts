import { describe, it, expect, vi, beforeEach } from "vitest";
import type { DataSourceSummary } from "@chatbi/shared";
import {
  ApiError, createDataSource, deleteDataSource, fetchSchema, getDataSource,
  listDataSources, refreshSchema, testDataSource, testDsConfig, updateDataSource,
} from "../api";

const summary: DataSourceSummary = {
  id: "ds1", name: "示例订单库", kind: "sqlite", target: "./data/chatbi.db",
  status: "ok", writePrivilege: "readonly", lastCheckAt: "2026-07-31T00:00:00.000Z",
  lastCheckError: null, schemaFetchedAt: "2026-07-31T00:00:00.000Z", tableCount: 3,
};

/** 只桩 fetch:客户端的职责是拼 URL、摊平 body、翻错误,不需要真服务器。 */
function stub(res: { status?: number; json?: unknown; notJson?: boolean; reject?: string }) {
  const f = res.reject
    ? vi.fn().mockRejectedValue(new Error(res.reject))
    : vi.fn().mockResolvedValue({
        ok: (res.status ?? 200) < 400,
        status: res.status ?? 200,
        json: () => res.notJson
          ? Promise.reject(new SyntaxError("Unexpected token <"))
          : Promise.resolve(res.json),
      } as any);
  (global as any).fetch = f;
  return f;
}
const call = () => (global as any).fetch.mock.calls[0];
const bodyOf = () => JSON.parse(call()[1].body);
const mysqlInput = { kind: "mysql" as const, host: "10.0.0.5", port: 3306, database: "sales", user: "bi_ro", ssl: false };

beforeEach(() => { (global as any).fetch = undefined; });

describe("列表与详情", () => {
  it("列表原样返回,URL 不带尾斜杠", async () => {
    stub({ json: [summary] });
    expect(await listDataSources()).toEqual([summary]);
    expect(call()[0]).toBe("/api/datasources");
  });

  it("详情按 id 拼路径", async () => {
    stub({ json: { ...summary, connection: { path: "./data/chatbi.db" }, hasPassword: false } });
    expect((await getDataSource("ds1")).hasPassword).toBe(false);
    expect(call()[0]).toBe("/api/datasources/ds1");
  });
});

describe("新建与修改的请求体", () => {
  it("请求体是扁平的:name 与连接字段同层", async () => {
    stub({ status: 201, json: summary });
    await createDataSource("销售库", { ...mysqlInput, password: "pw" });
    expect(bodyOf()).toEqual({ name: "销售库", ...mysqlInput, password: "pw" });
    expect(call()[1].method).toBe("POST");
  });

  it("force 只在为 true 时出现", async () => {
    stub({ status: 201, json: summary });
    await createDataSource("库", { kind: "sqlite", path: "./a.db" });
    expect("force" in bodyOf()).toBe(false);
    stub({ status: 201, json: summary });
    await createDataSource("库", { kind: "sqlite", path: "./a.db" }, true);
    expect(bodyOf().force).toBe(true);
  });

  it("不改密码时请求体里没有 password 字段", async () => {
    stub({ json: summary });
    await updateDataSource("ds1", "销售库", mysqlInput);
    expect("password" in bodyOf()).toBe(false);
    expect(call()[1].method).toBe("PUT");
    expect(call()[0]).toBe("/api/datasources/ds1");
  });

  it("密码显式为空字符串时原样送出(与缺失是两回事)", async () => {
    stub({ json: summary });
    await updateDataSource("ds1", "销售库", { ...mysqlInput, password: "" });
    expect(bodyOf().password).toBe("");
  });
});

describe("四个动作端点", () => {
  it("测未保存的表单打 /test 且不带 name", async () => {
    stub({ json: { ok: true, writePrivilege: "readonly", tableCount: 3 } });
    expect((await testDsConfig({ kind: "sqlite", path: "./a.db" })).tableCount).toBe(3);
    expect(call()[0]).toBe("/api/datasources/test");
    expect("name" in bodyOf()).toBe(false);
  });

  it("重测已存源打 /:id/test", async () => {
    stub({ json: { ok: true, writePrivilege: "unknown", tableCount: 1 } });
    await testDataSource("ds1");
    expect(call()[0]).toBe("/api/datasources/ds1/test");
    expect(call()[1].method).toBe("POST");
  });

  it("刷新结构与读结构各打各的路径", async () => {
    stub({ json: { tableCount: 3, fetchedAt: "2026-07-31T00:00:00.000Z", elapsedMs: 12 } });
    expect((await refreshSchema("ds1")).elapsedMs).toBe(12);
    expect(call()[0]).toBe("/api/datasources/ds1/refresh-schema");
    stub({ json: { schema: [], fetchedAt: null } });
    expect((await fetchSchema("ds1")).fetchedAt).toBeNull();
    expect(call()[0]).toBe("/api/datasources/ds1/schema");
  });

  it("删除的 204 不去解析响应体", async () => {
    stub({ status: 204, notJson: true });
    await expect(deleteDataSource("ds1")).resolves.toBeUndefined();
    expect(call()[1].method).toBe("DELETE");
  });
});

describe("错误翻译", () => {
  const caught = async (p: Promise<unknown>) => await p.then(() => null, (e: unknown) => e as ApiError);

  it("404 抛 ApiError 并带 code", async () => {
    stub({ status: 404, json: { code: "NOT_FOUND", message: "数据源不存在,可能已被删除" } });
    const e = await caught(getDataSource("nope"));
    expect(e instanceof ApiError).toBe(true);
    expect(e!.code).toBe("NOT_FOUND");
    expect(e!.message).toBe("数据源不存在,可能已被删除");
  });

  it("details 与 canForce 原样透传", async () => {
    stub({ status: 400, json: { code: "CONNECTION_ERROR", message: "无法连接", details: "ECONNREFUSED", canForce: true } });
    const e = await caught(createDataSource("库", { kind: "sqlite", path: "./a.db" }));
    expect(e!.details).toBe("ECONNREFUSED");
    expect(e!.canForce).toBe(true);
  });

  it("响应不是 JSON 时给中文兜底消息,不冒出 SyntaxError", async () => {
    stub({ status: 500, notJson: true });
    const e = await caught(listDataSources());
    expect(e instanceof ApiError).toBe(true);
    expect(e!.message).toContain("500");
  });

  it("fetch 自己抛错时也是 ApiError", async () => {
    stub({ reject: "offline" });
    const e = await caught(listDataSources());
    expect(e instanceof ApiError).toBe(true);
    expect(e!.code).toBe("UNKNOWN");
    expect(e!.message).toContain("offline");
  });
});
