import { Router, type Request, type Response } from "express";
import type { ChatTurn, DrillContext, StreamEvent } from "@chatbi/shared";
import { handleChat, type ChatDeps } from "../chatService";

export function createChatRouter(deps: ChatDeps): Router {
  const router = Router();
  router.post("/", async (req: Request, res: Response) => {
    const { question, history, context } = req.body as {
      question: string; history?: ChatTurn[]; context?: DrillContext;
    };
    if (typeof question !== "string") { res.status(400).json({ error: "question required" }); return; }
    const drill = context && typeof context.lastSql === "string"
      ? { lastSql: context.lastSql, lastColumns: Array.isArray(context.lastColumns) ? context.lastColumns : [] }
      : undefined;
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders?.();
    try {
      for await (const ev of handleChat({ question, history: history ?? [], context: drill, deps })) {
        res.write(`data: ${JSON.stringify(ev)}\n\n`);
      }
    } catch (e) {
      const err: StreamEvent = { type: "error", message: (e as Error).message };
      res.write(`data: ${JSON.stringify(err)}\n\n`);
    } finally {
      res.end();
    }
  });
  return router;
}
