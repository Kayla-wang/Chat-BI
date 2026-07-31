import type {
  DataSourceDetail, DataSourceStatus, DataSourceSummary, TableSchema,
} from "@chatbi/shared";
import { connectionView } from "./configInput";
import { targetLabel, type DataSourceRecord } from "./types";

type Cache = { schema: TableSchema[]; fetchedAt: string } | null;

/**
 * 解密失败优先:那时候 config 读不出来,上一次的 ok 已经没有意义。
 * 其余按「测过就看结果、没测过就是 unchecked」。
 */
function statusOf(rec: DataSourceRecord): DataSourceStatus {
  if (rec.configError) return "needs_reconfig";
  if (rec.lastCheckOk === true) return "ok";
  if (rec.lastCheckOk === false) return "error";
  return "unchecked";
}

export function toSummary(rec: DataSourceRecord, cache: Cache): DataSourceSummary {
  return {
    id: rec.id,
    name: rec.name,
    kind: rec.kind,
    // 密码永不出后端:target 由 targetLabel 拼,它只取非敏感字段。
    target: rec.config ? targetLabel(rec.config) : "(凭据无法解密)",
    status: statusOf(rec),
    writePrivilege: rec.writePrivilege,
    lastCheckAt: rec.lastCheckAt,
    lastCheckError: rec.lastCheckError,
    schemaFetchedAt: cache?.fetchedAt ?? null,
    tableCount: cache ? cache.schema.length : null,
  };
}

export function toDetail(rec: DataSourceRecord, cache: Cache): DataSourceDetail {
  const hasPassword = rec.config !== null
    && rec.config.kind !== "sqlite"
    && rec.config.password.length > 0;
  return {
    ...toSummary(rec, cache),
    connection: rec.config ? connectionView(rec.config) : {},
    hasPassword,
  };
}
