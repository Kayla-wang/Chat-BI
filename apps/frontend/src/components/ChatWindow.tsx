import { useEffect, useRef, useState } from "react";
import type { ChatTurn, DrillContext, StreamEvent } from "@chatbi/shared";
import { streamChat } from "../api";
import { MessageBubble, type Message } from "./MessageBubble";
import styles from "./ChatWindow.module.css";

const EXAMPLES = [
  "按月统计订单金额",
  "各产品类别销售额占比",
  "按月看各区域销售额",
];

let seq = 0;
const nextId = () => `m${++seq}`;

export function ChatWindow({ dataSourceId, dataSourceName }: {
  dataSourceId: string | null;
  dataSourceName?: string;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  /**
   * 数据源阶段号。放 ref 而不是 state:它只在切源那一刻变,而那一刻 setMessages
   * 已经触发重渲染,再多一个 state 只会多一次渲染和一次时序竞争。
   */
  const epoch = useRef(0);
  const prevId = useRef(dataSourceId);

  // 切源:上一个源的方言与表名对新源无效,带过去模型会在错的 SQL 上改写,
  // 产出必然报错的查询且看起来像模型能力问题。旧消息留在界面上,但不再进 history。
  useEffect(() => {
    if (prevId.current === dataSourceId) return;
    const hadSource = prevId.current !== null;
    prevId.current = dataSourceId;
    if (!hadSource || dataSourceId === null) return;   // 首次拿到源、或源变没了,都不必提示
    epoch.current += 1;
    const text = `已切换到数据源「${dataSourceName ?? dataSourceId}」,后续提问基于新数据源。`;
    setMessages(prev => prev.length === 0
      ? prev
      : [...prev, { id: nextId(), role: "notice", epoch: epoch.current, text }]);
  }, [dataSourceId, dataSourceName]);

  /** 当前数据源阶段里的真实对话轮次(不含分隔提示)。 */
  const currentTurns = (): Message[] =>
    messages.filter(m => m.epoch === epoch.current && m.role !== "notice");

  /** 向后找最近一条带结果的助手消息,作为下钻上下文。 */
  const drillContext = (): DrillContext | undefined => {
    const turns = currentTurns();
    for (let i = turns.length - 1; i >= 0; i--) {
      const p = turns[i].payload;
      if (p) return { lastSql: p.sql, lastColumns: p.table.columns };
    }
    return undefined;
  };

  const send = () => {
    if (!input.trim() || busy || dataSourceId === null) return;
    const question = input;
    const userId = nextId();
    const assistantId = nextId();
    const context = drillContext();
    const history: ChatTurn[] = currentTurns().map(m => ({
      role: m.role === "assistant" ? "assistant" : "user",
      text: m.role === "assistant" ? (m.payload?.queryIntent ?? m.text) : m.text,
    }));
    const stage = epoch.current;

    setInput("");
    setBusy(true);
    setMessages(prev => [
      ...prev,
      { id: userId, role: "user", epoch: stage, text: question },
      { id: assistantId, role: "assistant", epoch: stage, text: "" },
    ]);

    const patch = (fn: (m: Message) => Message) =>
      setMessages(prev => prev.map(m => (m.id === assistantId ? fn(m) : m)));

    streamChat({
      question, dataSourceId, history, context,
      onEvent: (e: StreamEvent) => {
        if (e.type === "result") patch(m => ({ ...m, payload: e.payload }));
        else if (e.type === "insightFacts") patch(m => ({ ...m, facts: e.facts }));
        else if (e.type === "insightDelta") patch(m => ({ ...m, insight: (m.insight ?? "") + e.text }));
        else if (e.type === "error") patch(m => ({ ...m, text: `${m.text}\n[错误] ${e.message}`.trim() }));
      },
    }).finally(() => setBusy(false));
  };

  const ready = dataSourceId !== null;
  const hasContext = currentTurns().some(m => m.payload);
  const placeholder = !ready
    ? "请先在顶栏选择数据源"
    : hasContext ? "继续追问，例如「只看华东区」" : "输入问题，例如「按月统计订单金额」";

  return (
    <div className={styles.window}>
      <div className={styles.stream}>
        {messages.length === 0 ? (
          <div className={styles.empty} data-testid="empty-state">
            <p className={styles.emptyTitle}>用中文问一个关于订单数据的问题</p>
            <ul className={styles.examples}>
              {EXAMPLES.map(e => <li key={e}>「{e}」</li>)}
            </ul>
          </div>
        ) : (
          messages.map(m => <MessageBubble key={m.id} message={m} />)
        )}
      </div>

      <div className={styles.composer}>
        <input
          className={styles.input}
          value={input}
          placeholder={placeholder}
          disabled={!ready}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
        />
        <button className={styles.send} onClick={send} disabled={busy || !ready}>发送</button>
      </div>
    </div>
  );
}
