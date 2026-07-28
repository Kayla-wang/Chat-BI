import express from "express";
import { realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { DbClient } from "./dbClient";
import { LlmClient } from "./llmClient";
import { migrate } from "./migrate";
import { createChatRouter } from "./routes/chat";
import { config } from "./config";

export function startServer() {
  const db = new DbClient(config.dbPath);
  migrate(db);
  // schema 启动自检:失败立即退出
  try { db.getSchema(); } catch (e) { console.error("schema self-check failed:", e); process.exit(1); }

  const deps = {
    db: { getSchema: () => db.getSchema(), runQuery: (sql: string) => db.runQuery(sql) },
    llm: new LlmClient(),
  };
  const app = express();
  app.use(express.json());
  app.use("/api/chat", createChatRouter(deps));
  app.listen(5174, "localhost", () => console.log("backend on http://localhost:5174"));
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
