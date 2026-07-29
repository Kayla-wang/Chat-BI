import { useState } from "react";
import type { ChatTurn, DrillContext, StreamEvent } from "@chatbi/shared";
import { streamChat } from "../api";
import { MessageBubble, type Message } from "./MessageBubble";

let seq = 0;
const nextId = () => `m${++seq}`;

export function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  /** 向后找最近一条带结果的助手消息,作为下钻上下文。 */
  const drillContext = (): DrillContext | undefined => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const p = messages[i].payload;
      if (p) return { lastSql: p.sql, lastColumns: p.table.columns };
    }
    return undefined;
  };

  const send = () => {
    if (!input.trim() || busy) return;
    const question = input;
    const userId = nextId();
    const assistantId = nextId();
    const context = drillContext();
    const history: ChatTurn[] = messages.map(m => ({
      role: m.role,
      text: m.role === "assistant" ? (m.payload?.queryIntent ?? m.text) : m.text,
    }));

    setInput("");
    setBusy(true);
    setMessages(prev => [
      ...prev,
      { id: userId, role: "user", text: question },
      { id: assistantId, role: "assistant", text: "" },
    ]);

    const patch = (fn: (m: Message) => Message) =>
      setMessages(prev => prev.map(m => (m.id === assistantId ? fn(m) : m)));

    streamChat({
      question, history, context,
      onEvent: (e: StreamEvent) => {
        if (e.type === "result") patch(m => ({ ...m, payload: e.payload }));
        else if (e.type === "insightFacts") patch(m => ({ ...m, facts: e.facts }));
        else if (e.type === "insightDelta") patch(m => ({ ...m, insight: (m.insight ?? "") + e.text }));
        else if (e.type === "error") patch(m => ({ ...m, text: `${m.text}\n[错误] ${e.message}`.trim() }));
      },
    }).finally(() => setBusy(false));
  };

  const hasContext = messages.some(m => m.payload);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", maxWidth: 900, margin: "0 auto" }}>
      <h1>Chat-BI</h1>
      <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
        {messages.map(m => <MessageBubble key={m.id} message={m} />)}
      </div>
      <div style={{ display: "flex", gap: 8, padding: 8 }}>
        <input
          value={input}
          placeholder={hasContext ? "继续追问，例如「只看华东区」" : "输入问题，例如「按月统计订单金额」"}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
          style={{ flex: 1 }}
        />
        <button onClick={send} disabled={busy}>发送</button>
      </div>
    </div>
  );
}
