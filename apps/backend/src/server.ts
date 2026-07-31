import express from "express";
import { realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { DbClient } from "./dbClient";
import { LlmClient } from "./llmClient";
import { migrate } from "./migrate";
import { createChatRouter } from "./routes/chat";
import { config } from "./config";
import { openAppDb, type AppDb } from "./appDb/index";
import { runMigrations } from "./appDb/migrations";
import { loadKey } from "./appDb/secrets";
import { ensureBuiltinDataSource } from "./appDb/bootstrap";
import { createRegistry, type DataSourceRegistry } from "./datasources/registry";

/**
 * 启动期的准备工作,不监听端口——所以可以在测试里直接调。
 * 顺序有依赖:业务库要先存在(内置源指向它),密钥要先有(内置源的 config 要加密)。
 */
export function bootstrapApp(paths: {
  dbPath?: string; appDbPath?: string; appKeyPath?: string;
} = {}): { appDb: AppDb; registry: DataSourceRegistry; key: Buffer } {
  const dbPath = paths.dbPath ?? config.dbPath;

  // 1. 示例业务库:先用可写连接建表灌数据,关掉后只读连接才打得开。
  const writable = new DbClient(dbPath);
  try {
    migrate(writable);
  } finally {
    writable.close();
  }

  // 2. 密钥。3. 元数据库与迁移。4. 内置示例源。
  const key = loadKey(paths.appKeyPath ?? config.appKeyPath);
  const appDb = openAppDb(paths.appDbPath ?? config.appDbPath);
  runMigrations(appDb);
  ensureBuiltinDataSource(appDb, key, { path: dbPath });

  // 5. registry:不建任何连接。
  const registry = createRegistry({ db: appDb, key });
  return { appDb, registry, key };
}

export function startServer() {
  let app: { appDb: AppDb; registry: DataSourceRegistry; key: Buffer };
  try {
    app = bootstrapApp();
  } catch (e) {
    console.error("启动准备失败:", (e as Error).message);
    process.exit(1);
  }

  // P2a-2 会把 chat 的 deps 换成按 dataSourceId 取 driver;
  // 现在先保持 P1 的行为不变,避免这一步就改动问答链路。
  const db = new DbClient(config.dbPath, { readonly: true });
  try { db.getSchema(); } catch (e) { console.error("schema self-check failed:", e); process.exit(1); }

  const deps = {
    db: {
      getSchema: () => db.getSchema(),
      runQuery: (sql: string, limit: number) => db.runQuery(sql, limit),
    },
    llm: new LlmClient(),
  };
  const server = express();
  server.use(express.json());
  server.use("/api/chat", createChatRouter(deps));

  const shutdown = async (): Promise<void> => {
    await app.registry.closeAll();
    app.appDb.close();
    db.close();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  server.listen(config.port, "localhost", () => console.log(`backend on http://localhost:${config.port}`));
}

/** 直接执行本文件时启动(跨平台:比较规范化的 file URL,Windows 下同样成立)。*/
function isMainModule(): boolean {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    return import.meta.url === pathToFileURL(realpathSync(entry)).href;
  } catch {
    return false;
  }
}

if (isMainModule()) startServer();
