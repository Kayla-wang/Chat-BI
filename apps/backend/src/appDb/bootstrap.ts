import type { AppDb } from "./index";
import { createDataSource, listDataSources } from "./dataSourceRepo";
import type { DataSourceRecord } from "../datasources/types";

const BUILTIN_NAME = "示例订单库";

/**
 * 首次启动时给一个能立刻提问的源,保住「开箱即跑」。
 * 只在完全没有数据源时插入:用户删掉它之后,只要还有别的源,重启不会招它回来。
 */
export function ensureBuiltinDataSource(
  db: AppDb, key: Buffer, opts: { path: string; name?: string },
): DataSourceRecord | null {
  if (listDataSources(db, key).length > 0) return null;
  return createDataSource(db, key, {
    name: opts.name ?? BUILTIN_NAME,
    config: { kind: "sqlite", path: opts.path },
    writePrivilege: "readonly",
  });
}
