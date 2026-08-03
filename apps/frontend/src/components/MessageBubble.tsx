import type { InsightFact, ResultPayload } from "@chatbi/shared";
import { ResultCard } from "./ResultCard";
import styles from "./MessageBubble.module.css";

export interface Message {
  id: string;
  role: "user" | "assistant" | "notice";
  /** 用户提问、助手侧错误提示,或切源分隔提示。查询意图走 payload.queryIntent。 */
  text: string;
  /** 属于第几个数据源阶段。切源后 epoch 变大,旧阶段的消息不再进 history。 */
  epoch: number;
  payload?: ResultPayload;
  facts?: InsightFact[];
  insight?: string;
}

export function MessageBubble({ message }: { message: Message }) {
  if (message.role === "notice") {
    return (
      <div className={styles.row}>
        <div className={styles.notice} role="status" data-testid="switch-notice">{message.text}</div>
      </div>
    );
  }

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
