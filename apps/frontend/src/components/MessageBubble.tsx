import type { InsightFact, ResultPayload } from "@chatbi/shared";
import { ResultCard } from "./ResultCard";
import styles from "./MessageBubble.module.css";

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
  if (message.role === "user") {
    return (
      <div className={styles.row}>
        <div className={styles.user}>{message.text}</div>
      </div>
    );
  }

  return (
    <div className={`${styles.row} ${styles.assistant}`}>
      {message.payload && <div className={styles.intent}>{message.payload.queryIntent}</div>}
      {message.text && <div className={styles.error} role="alert">{message.text}</div>}
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
