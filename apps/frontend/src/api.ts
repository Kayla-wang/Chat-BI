import type { ChatTurn, DrillContext, StreamEvent } from "@chatbi/shared";

export function streamChat(opts: {
  question: string; history: ChatTurn[]; context?: DrillContext;
  onEvent: (e: StreamEvent) => void;
  endpoint?: string;
}): Promise<void> {
  const url = opts.endpoint ?? "/api/chat";
  return (async () => {
    let res: Response;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: opts.question,
          history: opts.history,
          ...(opts.context ? { context: opts.context } : {}),
        }),
      });
    } catch (e) {
      opts.onEvent({ type: "error", message: `网络错误:${(e as Error).message}` });
      return;
    }
    if (!res.ok || !res.body) { opts.onEvent({ type: "error", message: `服务器返回 ${res.status}` }); return; }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        for (const line of block.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          try { opts.onEvent(JSON.parse(line.slice(6))); } catch { /* skip */ }
        }
      }
    }
  })();
}
