import type { DataSourceConnectionView, DsConfig, DsConfigInput } from "@chatbi/shared";
import { DsError } from "./errors";

const str = (v: unknown): string | null => (typeof v === "string" && v.length > 0 ? v : null);
const bool = (v: unknown): boolean => v === true;

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  return null;
}

/** 解析请求体。返回 null 表示请求不合法,由路由回 400。 */
export function parseDsConfigInput(body: unknown): DsConfigInput | null {
  if (typeof body !== "object" || body === null) return null;
  const b = body as Record<string, unknown>;

  if (b.kind === "sqlite") {
    const path = str(b.path);
    return path ? { kind: "sqlite", path } : null;
  }

  if (b.kind === "mysql" || b.kind === "postgres") {
    const host = str(b.host);
    const port = num(b.port);
    const database = str(b.database);
    const user = str(b.user);
    if (!host || port === null || !database || !user) return null;
    // password 允许缺失(不改)或为空字符串(设为空),两者要区分,所以不能用 str()。
    const password = typeof b.password === "string" ? b.password : undefined;
    const common = { host, port, database, user, ssl: bool(b.ssl) };
    return b.kind === "mysql"
      ? { kind: "mysql", ...common, ...(password === undefined ? {} : { password }) }
      : {
          kind: "postgres", ...common,
          ...(password === undefined ? {} : { password }),
          ...(str(b.schema) ? { schema: str(b.schema)! } : {}),
        };
  }

  return null;
}

/**
 * 密码三态:字段缺失 = 保留旧值;`""` = 真的设成空;有值 = 换新的。
 * 换了 kind 时不继承旧密码——不同库的凭据没有关系。
 */
export function mergeConfig(existing: DsConfig | null, input: DsConfigInput): DsConfig {
  if (input.kind === "sqlite") return { kind: "sqlite", path: input.path };

  if (input.password !== undefined) return { ...input, password: input.password } as DsConfig;

  const inherit = existing && existing.kind === input.kind ? existing.password : undefined;
  if (inherit === undefined) {
    throw new DsError("UNKNOWN", "缺少密码:新建连接或更换数据库类型时必须填写密码");
  }
  return { ...input, password: inherit } as DsConfig;
}

/** 回给前端的连接字段,故意丢掉 password。 */
export function connectionView(config: DsConfig): DataSourceConnectionView {
  if (config.kind === "sqlite") return { path: config.path };
  const { host, port, database, user, ssl } = config;
  return config.kind === "postgres" && config.schema
    ? { host, port, database, user, ssl, schema: config.schema }
    : { host, port, database, user, ssl };
}
