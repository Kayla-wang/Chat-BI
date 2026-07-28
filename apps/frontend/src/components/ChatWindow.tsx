import { useState } from "react";
import type { ChatTurn, StreamEvent } from "@chatbi/shared";
import { streamChat } from "../api";
import { MessageBubble, type Message } from "./MessageBubble";

export function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const send = () => {
    if (!input.trim() || busy) return;
    const question = input;
    setInput("");
    setBusy(true);
    setMessages(m => [...m, { role: "user", text: question }, { role: "assistant", text: "" }]);
    const history: ChatTurn[] = messages.map(m => ({ role: m.role, text: m.text }));
    const assistantIdx = messages.length + 1;
    streamChat({
      question, history,
      onEvent: (e: StreamEvent) => {
        if (e.type === "explanationDelta") {
          setMessages(m => { const n = [...m]; n[assistantIdx] = { ...n[assistantIdx], text: n[assistantIdx].text + e.text }; return n; });
        } else if (e.type === "result") {
          setMessages(m => { const n = [...m]; n[assistantIdx] = { ...n[assistantIdx], payload: e.payload }; return n; });
        } else if (e.type === "error") {
          setMessages(m => { const n = [...m]; n[assistantIdx] = { ...n[assistantIdx], text: (n[assistantIdx]?.text ?? "") + `\n[错误] ${e.message}` }; return n; });
          setBusy(false);
        }
      },
    }).finally(() => setBusy(false));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", maxWidth: 900, margin: "0 auto" }}>
      <h1>Chat-BI</h1>
      <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
        {messages.map((m, i) => <MessageBubble key={i} message={m} />)}
      </div>
      <div style={{ display: "flex", gap: 8, padding: 8 }}>
        <input value={input} placeholder="输入问题" onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === "Enter" && send()} style={{ flex: 1 }} />
        <button onClick={send} disabled={busy}>发送</button>
      </div>
    </div>
  );
}
