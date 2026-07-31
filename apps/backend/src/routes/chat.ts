import { Router, type Request, type Response } from "express";
import type { ChatTurn, DrillContext, StreamEvent } from "@chatbi/shared";
import { handleChat, type ChatDeps } from "../chatService";
import type { DataSourceRegistry } from "../datasources/registry";
import { DsError } from "../datasources/errors";
import { config } from "../config";

/**
 * 路由不再收现成的 ChatDeps:每轮请求要按 dataSourceId 取 driver,
 * dialect 与连接都跟着那个源走。
 */
export interface ChatRouterDeps {
  registry: Pick<DataSourceRegistry, "get" | "schemaFor">;
  llm: ChatDeps["llm"];
}

export function createChatRouter(deps: ChatRouterDeps): Router {
  const router = Router();
  router.post("/", async (req: Request, res: Response) => {
    const { question, dataSourceId, history, context } = req.body as {
      question: string; dataSourceId?: string; history?: ChatTurn[]; context?: DrillContext;
    };
    if (typeof question !== "string") { res.status(400).json({ error: "question required" }); return; }

    const drill = context && typeof context.lastSql === "string"
      ? { lastSql: context.lastSql, lastColumns: Array.isArray(context.lastColumns) ? context.lastColumns : [] }
      : undefined;

    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders?.();
    const send = (ev: StreamEvent) => res.write(`data: ${JSON.stringify(ev)}\n\n`);

    // 缺 id 走 error 事件而不是 400:前端只会把 400 显示成「服务器返回 400」,中文原因就丢了。
    if (typeof dataSourceId !== "string" || dataSourceId === "") {
      send({ type: "error", message: "缺少 dataSourceId,请先在顶栏选择数据源" });
      res.end();
      return;
    }

    try {
      const driver = await deps.registry.get(dataSourceId);
      const chatDeps: ChatDeps = {
        db: {
          // schema 走 registry:它管缓存缺失时 introspect 一次并写回。
          getSchema: () => deps.registry.schemaFor(dataSourceId),
          runQuery: (sql, limit) => driver.runQuery(sql, limit, config.queryTimeoutMs),
        },
        dialect: driver.dialect,
        llm: deps.llm,
      };
      for await (const ev of handleChat({ question, history: history ?? [], context: drill, deps: chatDeps })) {
        send(ev);
      }
    } catch (e) {
      // registry.get 的失败(NOT_FOUND / DECRYPT_ERROR)在这里;DsError 的 message 已是中文。
      send({ type: "error", message: e instanceof DsError ? e.message : (e as Error).message });
    } finally {
      res.end();
    }
  });
  return router;
}
