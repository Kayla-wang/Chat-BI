export const config = {
  port: Number(process.env.PORT ?? 5174),
  dbPath: process.env.DB_PATH ?? "./data/chatbi.db",
  appDbPath: process.env.APP_DB_PATH ?? "./data/app.db",
  appKeyPath: process.env.APP_KEY_PATH ?? "./data/app.key",
  ollamaUrl: process.env.OLLAMA_URL ?? "http://localhost:11434",
  ollamaModel: process.env.OLLAMA_MODEL ?? "llama3.1",
  queryTimeoutMs: Number(process.env.QUERY_TIMEOUT_MS ?? 5000),
  rowLimit: Number(process.env.ROW_LIMIT ?? 1000),
  insightTimeoutMs: Number(process.env.INSIGHT_TIMEOUT_MS ?? 8000),
};
