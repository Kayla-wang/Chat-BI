import express from "express";
import { realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { DbClient } from "./dbClient";
import { LlmClient } from "./llmClient";
import { migrate } from "./migrate";
import { createChatRouter } from "./routes/chat";
import { config } from "./config";

export function startServer() {
  // 先用可写连接建表灌数据,关掉后再开只读连接——只读连接打不开不存在的文件。
  const writable = new DbClient(config.dbPath);
  try {
    migrate(writable);
  } catch (e) {
    console.error("migration failed:", e);
    process.exit(1);
  } finally {
    writable.close();
  }

  const db = new DbClient(config.dbPath, { readonly: true });
  try { db.getSchema(); } catch (e) { console.error("schema self-check failed:", e); process.exit(1); }

  const deps = {
    db: {
      getSchema: () => db.getSchema(),
      runQuery: (sql: string, limit: number) => db.runQuery(sql, limit),
    },
    llm: new LlmClient(),
  };
  const app = express();
  app.use(express.json());
  app.use("/api/chat", createChatRouter(deps));
  app.listen(config.port, "localhost", () => console.log(`backend on http://localhost:${config.port}`));
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
