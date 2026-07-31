import type { TableSchema } from "@chatbi/shared";
import type { AppDb } from "../appDb/index";
import { getDataSource, getSchemaCache, putSchemaCache } from "../appDb/dataSourceRepo";
import type { Driver } from "./driver";
import { DsError } from "./errors";
import type { DsConfig } from "./types";
import { createDriverFor } from "./drivers/index";

export interface DataSourceRegistry {
  get(id: string): Promise<Driver>;
  /** 读缓存;缺失时 introspect 一次并写回。 */
  schemaFor(id: string): Promise<TableSchema[]>;
  /** 无条件重抓并覆盖缓存。 */
  refreshSchema(id: string): Promise<{ schema: TableSchema[]; fetchedAt: string }>;
  /** 数据源被编辑或删除后调用:关掉旧连接,免得继续用旧凭据。 */
  invalidate(id: string): Promise<void>;
  closeAll(): Promise<void>;
}

export function createRegistry(deps: {
  db: AppDb;
  key: Buffer;
  createDriver?: (config: DsConfig) => Driver;
}): DataSourceRegistry {
  const make = deps.createDriver ?? createDriverFor;
  // 单用户,不做连接池:一个数据源一个长连接,复用成本远低于每次重连的延迟。
  const live = new Map<string, Driver>();

  async function get(id: string): Promise<Driver> {
    const cached = live.get(id);
    if (cached) return cached;
    const rec = getDataSource(deps.db, deps.key, id);
    if (!rec) throw new DsError("NOT_FOUND", `数据源不存在:${id}`);
    if (!rec.config) throw new DsError("DECRYPT_ERROR", "凭据无法解密,请重新填写连接信息");
    const driver = make(rec.config);
    live.set(id, driver);
    return driver;
  }

  return {
    get,

    async schemaFor(id) {
      const cached = getSchemaCache(deps.db, id);
      if (cached) return cached.schema;
      const schema = await (await get(id)).introspect();
      putSchemaCache(deps.db, id, schema);
      return schema;
    },

    async refreshSchema(id) {
      const schema = await (await get(id)).introspect();
      putSchemaCache(deps.db, id, schema);
      return { schema, fetchedAt: getSchemaCache(deps.db, id)!.fetchedAt };
    },

    async invalidate(id) {
      const driver = live.get(id);
      if (!driver) return;
      live.delete(id);
      await driver.close().catch(() => { /* 已断开 */ });
    },

    async closeAll() {
      const all = [...live.values()];
      live.clear();
      await Promise.all(all.map(d => d.close().catch(() => { /* 已断开 */ })));
    },
  };
}
