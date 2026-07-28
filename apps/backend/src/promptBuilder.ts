import type { TableSchema, ChatTurn } from "@chatbi/shared";

/** 保留最近 2 轮完整问答(user + assistant = 4 条消息)。*/
const HISTORY_MESSAGE_LIMIT = 4;

const SYSTEM = `你是 SQL 分析助手。根据下方数据库 schema 用自然语言回答用户问题。

规则:
1. 只生成 SELECT 语句,只读。
2. 输出严格 JSON:{"sql": "...", "chartType": "bar|line|pie|table", "explanation": "..."}
3. chartType 选择:时序→line,占比→pie,分组对比→bar,无明显可视化→table。
4. explanation 用一句中文说明你打算查什么。
5. 只输出 JSON,不要 markdown 代码块,不要多余文字。`;

function renderSchema(schema: TableSchema[]): string {
  return schema.map(t => {
    const cols = t.columns.map(c => `  ${c.name} ${c.type}${c.pk ? " PK" : ""}${c.notNull ? " NOT NULL" : ""}`).join("\n");
    const fks = t.foreignKeys.map(f => `  FK ${f.column} -> ${f.refTable}(${f.refColumn})`).join("\n");
    return `TABLE ${t.tableName} (\n${cols}\n${fks ? fks + "\n" : ""})`;
  }).join("\n\n");
}

export function buildPrompt(opts: { question: string; schema: TableSchema[]; history: ChatTurn[] }): string {
  const recent = opts.history.slice(-HISTORY_MESSAGE_LIMIT);
  const historyText = recent.length
    ? recent.map(t => `${t.role}: ${t.text}`).join("\n")
    : "(无)";
  return `${SYSTEM}

数据库 schema:
${renderSchema(opts.schema)}

对话历史(最近 2 轮):
${historyText}

用户问题: ${opts.question}`;
}

export function buildRetryPrompt(prevPrompt: string, feedback: string): string {
  return `${prevPrompt}\n\n上次输出有问题:${feedback}\n请严格按要求只输出 JSON。`;
}
