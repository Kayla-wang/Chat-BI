import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import express from "express";
import request from "supertest";
import { openAppDb, type AppDb } from "../src/appDb/index";
import { runMigrations } from "../src/appDb/migrations";
import { createDataSource, getSchemaCache } from "../src/appDb/dataSourceRepo";
import { createRegistry } from "../src/datasources/registry";
import { createDataSourcesRouter } from "../src/routes/datasources";
import { SQLITE_DIALECT } from "../src/datasources/dialect";
import type { Driver } from "../src/datasources/driver";
import type { DsConfig } from "../src/datasources/types";
import type { TableSchema } from "@chatbi/shared";

const tmpDir = join(process.cwd(), ".tmp-test-dsroute");
const key = randomBytes(32);
let db: AppDb;

const SCHEMA: TableSchema[] = [
  { tableName: "orders", columns: [{ name: "id", type: "int", notNull: true, pk: true }], foreignKeys: [] },
  { tableName: "customers", columns: [], foreignKeys: [] },
];

const mysqlBody = {
  kind: "mysql", host: "10.0.0.5", port: 3306, database: "sales",
  user: "bi_ro", password: "s3cret", ssl: false,
};

/** 可控的假 driver:testConnection 的成败与 introspect 的返回都能摆。 */
function fakeDriver(over: Partial<{ ok: boolean; writePrivilege: "readonly" | "writable" | "unknown" }> = {}) {
  const d = {
    kind: "mysql" as const, dialect: SQLITE_DIALECT,
    closed: 0,
    testConnection: vi.fn(async () =>
      over.ok === false
        ? { ok: false as const, code: "AUTH_ERROR" as const, message: "认证失败,请检查用户名与密码", details: "ER_ACCESS_DENIED_ERROR" }
        : { ok: true as const, writePrivilege: over.writePrivilege ?? "readonly" }),
    introspect: vi.fn(async () => SCHEMA),
    runQuery: async () => ({ rows: [], truncated: false }),
    probeWritePrivilege: async () => over.writePrivilege ?? "readonly",
    close: async () => { d.closed++; },
  };
  return d;
}

function makeApp(createDriver: (config: DsConfig) => Driver) {
  const registry = createRegistry({ db, key, createDriver });
  const router = createDataSourcesRouter({ db, key, registry, createDriver });
  return { app: express().use(express.json()).use("/api/datasources", router), registry };
}

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  db = openAppDb(join(tmpDir, "app.db"));
  runMigrations(db);
});
afterEach(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

describe("GET /api/datasources", () => {
  it("空库返回空数组", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const res = await request(app).get("/api/datasources");
    expect(res.status).toBe(200);
    expect(res.body).toEqual([]);
  });

  it("列出已存的源,带 target 与 status,且不含密码", async () => {
    createDataSource(db, key, { name: "销售库", config: mysqlBody as DsConfig });
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const res = await request(app).get("/api/datasources");
    expect(res.body).toHaveLength(1);
    expect(res.body[0]).toMatchObject({
      name: "销售库", kind: "mysql",
      target: "mysql://bi_ro@10.0.0.5:3306/sales",
      status: "unchecked",
    });
    expect(JSON.stringify(res.body)).not.toContain("s3cret");
  });
});

describe("POST /api/datasources", () => {
  it("测连成功则落库,顺带写 schema 缓存并返回表数量", async () => {
    const driver = fakeDriver();
    const { app } = makeApp(() => driver as unknown as Driver);
    const res = await request(app).post("/api/datasources").send({ name: "销售库", ...mysqlBody });
    expect(res.status).toBe(201);
    expect(res.body).toMatchObject({ name: "销售库", status: "ok", tableCount: 2 });
    expect(driver.introspect).toHaveBeenCalled();
    expect(getSchemaCache(db, res.body.id)!.schema).toEqual(SCHEMA);
  });

  it("响应体里没有密码,只有 hasPassword", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const res = await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody });
    expect(JSON.stringify(res.body)).not.toContain("s3cret");
    expect(res.body.hasPassword).toBe(true);
    expect(res.body.connection.password).toBeUndefined();
  });

  it("测连失败则不落库,返回 400 与 canForce", async () => {
    const { app } = makeApp(() => fakeDriver({ ok: false }) as unknown as Driver);
    const res = await request(app).post("/api/datasources").send({ name: "连不上的", ...mysqlBody });
    expect(res.status).toBe(400);
    expect(res.body).toMatchObject({
      code: "AUTH_ERROR", message: "认证失败,请检查用户名与密码",
      details: "ER_ACCESS_DENIED_ERROR", canForce: true,
    });
    expect((await request(app).get("/api/datasources")).body).toEqual([]);
  });

  it("force: true 时跳过测连直接存,状态记为 error", async () => {
    const driver = fakeDriver({ ok: false });
    const { app } = makeApp(() => driver as unknown as Driver);
    const res = await request(app).post("/api/datasources")
      .send({ name: "先存着", ...mysqlBody, force: true });
    expect(res.status).toBe(201);
    expect(res.body.status).toBe("error");
    expect(driver.testConnection).not.toHaveBeenCalled();
  });

  it("有写权限的账号照样存,但 writePrivilege 记为 writable", async () => {
    const { app } = makeApp(() => fakeDriver({ writePrivilege: "writable" }) as unknown as Driver);
    const res = await request(app).post("/api/datasources").send({ name: "可写库", ...mysqlBody });
    expect(res.body.writePrivilege).toBe("writable");
  });

  it("同名冲突返回 409 与中文消息,不是 SQLite 原生报错", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    await request(app).post("/api/datasources").send({ name: "重名", ...mysqlBody });
    const res = await request(app).post("/api/datasources").send({ name: "重名", ...mysqlBody });
    expect(res.status).toBe(409);
    expect(res.body.message).toContain("已有同名数据源");
    expect(res.body.message).not.toContain("UNIQUE");
  });

  it("缺 name 返回 400", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    expect((await request(app).post("/api/datasources").send(mysqlBody)).status).toBe(400);
  });

  it("配置不合法返回 400", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const res = await request(app).post("/api/datasources").send({ name: "x", kind: "oracle" });
    expect(res.status).toBe(400);
  });

  it("新建时缺密码返回 400,不静默存空密码", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const { password, ...noPw } = mysqlBody;
    const res = await request(app).post("/api/datasources").send({ name: "x", ...noPw });
    expect(res.status).toBe(400);
    expect(res.body.message).toContain("密码");
  });
});

describe("PUT /api/datasources/:id", () => {
  const seed = async (app: express.Express) =>
    (await request(app).post("/api/datasources").send({ name: "原名", ...mysqlBody })).body.id;

  it("改名保留旧密码(password 字段缺失)", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = await seed(app);
    const { password, ...noPw } = mysqlBody;
    const res = await request(app).put(`/api/datasources/${id}`).send({ name: "新名", ...noPw });
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({ name: "新名", hasPassword: true });
  });

  it("显式传空密码则真的清空(hasPassword 变 false)", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = await seed(app);
    const res = await request(app).put(`/api/datasources/${id}`).send({ name: "原名", ...mysqlBody, password: "" });
    expect(res.body.hasPassword).toBe(false);
  });

  it("改完之后 registry 里的旧连接被关掉", async () => {
    const made: ReturnType<typeof fakeDriver>[] = [];
    const { app, registry } = makeApp(() => { const d = fakeDriver(); made.push(d); return d as unknown as Driver; });
    const id = await seed(app);
    await registry.get(id);                       // 先建一个活连接
    const before = made.length;
    await request(app).put(`/api/datasources/${id}`).send({ name: "改了", ...mysqlBody });
    expect(made.slice(0, before).some(d => d.closed > 0)).toBe(true);
  });

  it("id 不存在返回 404", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const res = await request(app).put("/api/datasources/nope").send({ name: "x", ...mysqlBody });
    expect(res.status).toBe(404);
    expect(res.body.code).toBe("NOT_FOUND");
  });

  it("改成已存在的名字返回 409", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    await request(app).post("/api/datasources").send({ name: "占用中", ...mysqlBody });
    const id = (await request(app).post("/api/datasources").send({ name: "待改", ...mysqlBody })).body.id;
    const res = await request(app).put(`/api/datasources/${id}`).send({ name: "占用中", ...mysqlBody });
    expect(res.status).toBe(409);
  });
});

describe("DELETE /api/datasources/:id", () => {
  it("删掉后列表为空,schema 缓存跟着走", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = (await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody })).body.id;
    expect(getSchemaCache(db, id)).not.toBeNull();
    expect((await request(app).delete(`/api/datasources/${id}`)).status).toBe(204);
    expect((await request(app).get("/api/datasources")).body).toEqual([]);
    expect(getSchemaCache(db, id)).toBeNull();
  });

  it("删不存在的返回 404", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    expect((await request(app).delete("/api/datasources/nope")).status).toBe(404);
  });
});

describe("POST /api/datasources/test(未保存的表单)", () => {
  it("成功返回写权限与表数量,并关掉临时连接", async () => {
    const driver = fakeDriver();
    const { app } = makeApp(() => driver as unknown as Driver);
    const res = await request(app).post("/api/datasources/test").send(mysqlBody);
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ ok: true, writePrivilege: "readonly", tableCount: 2 });
    expect(driver.closed).toBe(1);      // 不留悬空连接
  });

  it("失败返回 400 与可读消息 + 原文详情", async () => {
    const { app } = makeApp(() => fakeDriver({ ok: false }) as unknown as Driver);
    const res = await request(app).post("/api/datasources/test").send(mysqlBody);
    expect(res.status).toBe(400);
    expect(res.body).toMatchObject({ code: "AUTH_ERROR", details: "ER_ACCESS_DENIED_ERROR" });
  });

  it("不落库", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    await request(app).post("/api/datasources/test").send(mysqlBody);
    expect((await request(app).get("/api/datasources")).body).toEqual([]);
  });
});

describe("POST /api/datasources/:id/test(已存源)", () => {
  it("成功时把结果记进 lastCheck", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = (await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody })).body.id;
    const res = await request(app).post(`/api/datasources/${id}/test`);
    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
    const list = (await request(app).get("/api/datasources")).body;
    expect(list[0]).toMatchObject({ status: "ok", lastCheckError: null });
  });

  it("失败时状态变 error 并记下原因", async () => {
    let fail = false;
    const { app } = makeApp(() => (fail ? fakeDriver({ ok: false }) : fakeDriver()) as unknown as Driver);
    const id = (await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody })).body.id;
    fail = true;
    await request(app).post(`/api/datasources/${id}/test`);
    const list = (await request(app).get("/api/datasources")).body;
    expect(list[0].status).toBe("error");
    expect(list[0].lastCheckError).toContain("认证失败");
  });

  it("id 不存在返回 404", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    expect((await request(app).post("/api/datasources/nope/test")).status).toBe(404);
  });
});

describe("刷新与读取表结构", () => {
  it("refresh-schema 重抓并返回表数量与耗时", async () => {
    const driver = fakeDriver();
    const { app } = makeApp(() => driver as unknown as Driver);
    const id = (await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody })).body.id;
    const before = driver.introspect.mock.calls.length;
    const res = await request(app).post(`/api/datasources/${id}/refresh-schema`);
    expect(res.status).toBe(200);
    expect(res.body.tableCount).toBe(2);
    expect(res.body.fetchedAt).toBeTruthy();
    expect(typeof res.body.elapsedMs).toBe("number");
    expect(driver.introspect.mock.calls.length).toBe(before + 1);
  });

  it("GET :id/schema 返回缓存的结构与时间戳", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = (await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody })).body.id;
    const res = await request(app).get(`/api/datasources/${id}/schema`);
    expect(res.status).toBe(200);
    expect(res.body.schema).toEqual(SCHEMA);
    expect(res.body.fetchedAt).toBeTruthy();
  });

  it("没有缓存时返回空数组与 null 时间戳,不是 404", async () => {
    createDataSource(db, key, { name: "没测过", config: mysqlBody as DsConfig });
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = (await request(app).get("/api/datasources")).body[0].id;
    const res = await request(app).get(`/api/datasources/${id}/schema`);
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ schema: [], fetchedAt: null });
  });

  it("解密失败的源报 DECRYPT_ERROR 而不是 500", async () => {
    createDataSource(db, key, { name: "换过钥匙", config: mysqlBody as DsConfig });
    const otherKey = randomBytes(32);
    const registry = createRegistry({ db, key: otherKey, createDriver: () => fakeDriver() as unknown as Driver });
    const app = express().use(express.json()).use("/api/datasources",
      createDataSourcesRouter({ db, key: otherKey, registry, createDriver: () => fakeDriver() as unknown as Driver }));
    const id = (await request(app).get("/api/datasources")).body[0].id;
    const res = await request(app).post(`/api/datasources/${id}/refresh-schema`);
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("DECRYPT_ERROR");
  });
});
