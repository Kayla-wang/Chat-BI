import type { InsightFact, ResultPayload } from "@chatbi/shared";
import { ResultCard } from "./ResultCard";

export interface Message {
  id: string;
  role: "user" | "assistant";
  /** 用户提问,或助手侧的错误提示。查询意图走 payload.queryIntent。 */
  text: string;
  payload?: ResultPayload;
  facts?: InsightFact[];
  insight?: string;
}

export function MessageBubble({ message }: { message: Message }) {
  return (
    <div style={{
      margin: "8px 0",
      alignSelf: message.role === "user" ? "flex-end" : "flex-start",
      maxWidth: "80%",
    }}>
      {message.payload && (
        <div style={{ whiteSpace: "pre-wrap" }}>{message.payload.queryIntent}</div>
      )}
      {message.text && (
        <div style={{ fontWeight: message.role === "user" ? 600 : 400, whiteSpace: "pre-wrap" }}>
          {message.text}
        </div>
      )}
      {message.payload && (
        <ResultCard
          payload={message.payload}
          insight={message.insight ?? ""}
          facts={message.facts ?? []}
        />
      )}
    </div>
  );
}
