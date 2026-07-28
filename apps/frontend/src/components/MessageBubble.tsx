import type { ChartPayload } from "@chatbi/shared";
import { ResultCard } from "./ResultCard";

export interface Message { role: "user" | "assistant"; text: string; payload?: ChartPayload; }

export function MessageBubble({ message }: { message: Message }) {
  return (
    <div style={{ margin: "8px 0", alignSelf: message.role === "user" ? "flex-end" : "flex-start", maxWidth: "80%" }}>
      <div style={{ fontWeight: message.role === "user" ? 600 : 400, whiteSpace: "pre-wrap" }}>{message.text}</div>
      {message.payload && <ResultCard payload={message.payload} />}
    </div>
  );
}
