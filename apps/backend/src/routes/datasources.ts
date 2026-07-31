import { Router, type Request, type Response } from "express";
import type { DsApiError, TableSchema, WritePrivilege } from "@chatbi/shared";
import type { AppDb } from "../appDb/index";
import {
  createDataSource, deleteDataSource, getDataSource, getSchemaCache,
  listDataSources, putSchemaCache, recordCheck, updateDataSource, DuplicateNameError,
} from "../appDb/dataSourceRepo";
import { mergeConfig, parseDsConfigInput } from "../datasources/configInput";
import { DsError, type DsErrorCode } from "../datasources/errors";
import type { Driver } from "../datasources/driver";
import { createDriverFor } from "../datasources/drivers/index";
import type { DataSourceRegistry } from "../datasources/registry";
import type { DsConfig } from "../datasources/types";
import { toDetail, toSummary } from "../datasources/view";

export interface DsRouterDeps {
  db: AppDb;
  key: Buffer;
  registry: DataSourceRegistry;
  /** 测未保存的表单要在 registry 之外临时建连接;测试注入假 driver 也走这里。 */
  createDriver?: (config: DsConfig) => Driver;
}

/** 记录不存在是 404,重名是 409,其余数据源错误都是 400——500 只留给真 bug。 */
function statusFor(code: DsErrorCode): number {
  if (code === "NOT_FOUND") return 404;
  if (code === "DUPLICATE_NAME") return 409;
  return 400;
}

function asDsError(e: unknown): DsError {
  if (e instanceof DsError) return e;
  // 仓储的重名异常在这里翻成统一错误形状,SQLite 的 UNIQUE 原文不外泄。
  if (e instanceof DuplicateNameError) return new DsError("DUPLICATE_NAME", e.message);
  return new DsError("UNKNOWN", "服务器内部错误", (e as Error).message);
}

function sendDsError(res: Response, e: DsError, extra?: { canForce?: boolean }): void {
  const body: DsApiError = {
    code: e.code,
    message: e.message,
    ...(e.details ? { details: e.details } : {}),
    ...(extra?.canForce ? { canForce: true } : {}),
  };
  res.status(e.code === "UNKNOWN" && e.message === "服务器内部错误" ? 500 : statusFor(e.code)).json(body);
}

const badRequest = (res: Response, message: string): void => {
  const body: DsApiError = { code: "UNKNOWN", message };
  res.status(400).json(body);
};

/** 所有 handler 共用:抛出来的 DsError / DuplicateNameError 统一翻成错误响应。 */
const handle = (fn: (req: Request, res: Response) => Promise<void>) =>
  async (req: Request, res: Response): Promise<void> => {
    try {
      await fn(req, res);
    } catch (e) {
      sendDsError(res, asDsError(e));
    }
  };

export function createDataSourcesRouter(deps: DsRouterDeps): Router {
  const make = deps.createDriver ?? createDriverFor;
  const router = Router();

  /** 一次连接干两件事:测通 + 抓结构。临时连接不进 registry,所以自己关。 */
  async function probe(config: DsConfig): Promise<{ writePrivilege: WritePrivilege; schema: TableSchema[] }> {
    const driver = make(config);
    try {
      const r = await driver.testConnection();
      if (!r.ok) throw new DsError(r.code, r.message, r.details);
      return { writePrivilege: r.writePrivilege, schema: await driver.introspect() };
    } finally {
      await driver.close().catch(() => { /* 本来就没连上 */ });
    }
  }

  /** 落库后重新读一次:lastCheck 与 schema 缓存都是刚写的,要回给前端最新状态。 */
  function detailOf(id: string) {
    const rec = getDataSource(deps.db, deps.key, id);
    if (!rec) throw new DsError("NOT_FOUND", "数据源不存在,可能已被删除");
    return toDetail(rec, getSchemaCache(deps.db, id));
  }

  function requireRecord(id: string) {
    const rec = getDataSource(deps.db, deps.key, id);
    if (!rec) throw new DsError("NOT_FOUND", "数据源不存在,可能已被删除");
    return rec;
  }

  function readName(body: unknown): string | null {
    const raw = (body as { name?: unknown })?.name;
    return typeof raw === "string" && raw.trim() !== "" ? raw.trim() : null;
  }

  router.get("/", handle(async (_req, res) => {
    const list = listDataSources(deps.db, deps.key)
      .map(rec => toSummary(rec, getSchemaCache(deps.db, rec.id)));
    res.json(list);
  }));

  // 放在 /:id/test 之前只是可读性,两者段数不同不会互相吃掉。
  router.post("/test", handle(async (req, res) => {
    const input = parseDsConfigInput(req.body);
    if (!input) { badRequest(res, "连接配置不完整或不支持的数据库类型"); return; }
    const r = await probe(mergeConfig(null, input));   // 未保存的表单没有旧密码可继承
    res.json({ ok: true, writePrivilege: r.writePrivilege, tableCount: r.schema.length });
  }));

  router.post("/", handle(async (req, res) => {
    const name = readName(req.body);
    if (!name) { badRequest(res, "请填写数据源名称"); return; }
    const input = parseDsConfigInput(req.body);
    if (!input) { badRequest(res, "连接配置不完整或不支持的数据库类型"); return; }
    const config = mergeConfig(null, input);

    let probed: { writePrivilege: WritePrivilege; schema: TableSchema[] } | null = null;
    if ((req.body as { force?: unknown }).force !== true) {
      try {
        probed = await probe(config);
      } catch (e) {
        // 不落库,免得攒一堆连不上的僵尸源;但「库临时不可达而配置没错」是真事,
        // 所以带上 canForce,前端给「仍然保存」。
        sendDsError(res, asDsError(e), { canForce: true });
        return;
      }
    }

    const rec = createDataSource(deps.db, deps.key, {
      name, config,
      ...(probed ? { writePrivilege: probed.writePrivilege } : {}),
    });
    if (probed) {
      putSchemaCache(deps.db, rec.id, probed.schema);
      recordCheck(deps.db, rec.id, { ok: true, writePrivilege: probed.writePrivilege });
    } else {
      // force 存下来的源没测过,状态记成 error 才不会在列表里假装可用。
      recordCheck(deps.db, rec.id, { ok: false, error: "保存时跳过了连接测试,请点「测试连接」确认" });
    }
    res.status(201).json(detailOf(rec.id));
  }));

  router.put("/:id", handle(async (req, res) => {
    const existing = requireRecord(req.params.id);
    const name = readName(req.body);
    if (!name) { badRequest(res, "请填写数据源名称"); return; }
    const input = parseDsConfigInput(req.body);
    if (!input) { badRequest(res, "连接配置不完整或不支持的数据库类型"); return; }

    // 密码三态在 mergeConfig 里:字段缺失继承旧值,`""` 真的清空。
    updateDataSource(deps.db, deps.key, existing.id, { name, config: mergeConfig(existing.config, input) });
    // 凭据可能已经换了,旧连接必须丢掉——否则后续查询还在用旧密码的那条连接。
    await deps.registry.invalidate(existing.id);
    res.json(detailOf(existing.id));
  }));

  router.delete("/:id", handle(async (req, res) => {
    await deps.registry.invalidate(req.params.id);   // 先断连接再删记录(sqlite 要释放文件句柄)
    if (!deleteDataSource(deps.db, req.params.id)) {
      throw new DsError("NOT_FOUND", "数据源不存在,可能已被删除");
    }
    res.status(204).end();                           // schema_cache 靠外键级联删掉
  }));

  router.post("/:id/test", handle(async (req, res) => {
    const id = requireRecord(req.params.id).id;
    const driver = await deps.registry.get(id);      // 解密失败在这里抛 DECRYPT_ERROR
    const r = await driver.testConnection();
    if (!r.ok) {
      recordCheck(deps.db, id, { ok: false, error: r.message });
      await deps.registry.invalidate(id);            // 连不上的连接别留在池子里
      sendDsError(res, new DsError(r.code, r.message, r.details));
      return;
    }
    const schema = await driver.introspect();
    putSchemaCache(deps.db, id, schema);
    recordCheck(deps.db, id, { ok: true, writePrivilege: r.writePrivilege });
    res.json({ ok: true, writePrivilege: r.writePrivilege, tableCount: schema.length });
  }));

  router.post("/:id/refresh-schema", handle(async (req, res) => {
    const id = requireRecord(req.params.id).id;
    const startedAt = Date.now();
    const { schema, fetchedAt } = await deps.registry.refreshSchema(id);
    // elapsedMs 是给界面显示「抓了 1.2 秒」的,大库上这个数字就是用户的等待感。
    res.json({ tableCount: schema.length, fetchedAt, elapsedMs: Date.now() - startedAt });
  }));

  router.get("/:id/schema", handle(async (req, res) => {
    const id = requireRecord(req.params.id).id;
    const cache = getSchemaCache(deps.db, id);
    // 没抓过不是错误:界面照常渲染空表列表 + 一个「刷新结构」按钮。
    res.json({ schema: cache?.schema ?? [], fetchedAt: cache?.fetchedAt ?? null });
  }));

  return router;
}
