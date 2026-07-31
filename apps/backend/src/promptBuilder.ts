import type { TableSchema, ChatTurn, DrillContext, InsightFact, ValueFormat } from "@chatbi/shared";
import { renderFactsLines } from "./facts";
import type { Dialect } from "./datasources/dialect";

/** 保留最近 2 轮完整问答(user + assistant = 4 条消息)。*/
const HISTORY_MESSAGE_LIMIT = 4;

const SYSTEM = `你是 SQL 分析助手。根据下方数据库 schema 用自然语言回答用户问题。

规则:
1. 只生成 SELECT 语句,只读,不要写 SQL 注释。
2. 输出严格 JSON,字段如下:
   {"sql":"...","explanation":"...","chartType":"bar|line|pie|table","dimensions":["列名"],"measures":["列名"],"seriesBy":"列名(可省略)","stack":"none|normal|percent"}
3. dimensions / measures / seriesBy 里填的必须是 sql 结果列的**别名**,不是原表列名。
4. dimensions 首个元素作为 x 轴;measures 是要画的数值列。
5. chartType 选择:时序→line,占比→pie,分组对比→bar,无明显可视化→table。
6. 需要按某个维度拆成多条系列时(例如各区域各一条折线),把该维度放进 seriesBy。
7. stack 仅在 chartType 为 bar 时有意义:需要堆叠对比用 normal,需要看占比结构用 percent,否则 none。
8. explanation 用一句中文说明你打算查什么。
9. 只输出 JSON,不要 markdown 代码块,不要多余文字。`;

function renderSchema(schema: TableSchema[]): string {
  return schema.map(t => {
    const cols = t.columns.map(c => `  ${c.name} ${c.type}${c.pk ? " PK" : ""}${c.notNull ? " NOT NULL" : ""}`).join("\n");
    const fks = t.foreignKeys.map(f => `  FK ${f.column} -> ${f.refTable}(${f.refColumn})`).join("\n");
    return `TABLE ${t.tableName} (\n${cols}\n${fks ? fks + "\n" : ""})`;
  }).join("\n\n");
}

function renderDrill(context?: DrillContext): string {
  if (!context) return "";
  return `
上一轮查询(用户可能要在此基础上细化):
SQL: ${context.lastSql}
结果列: ${context.lastColumns.join(", ")}

若用户的问题是对上一轮的细化(追加筛选、更换时间粒度、增加拆分维度),
请在上面的 SQL 基础上改写;若是全新问题,忽略上一轮。
`;
}

export function buildPrompt(opts: {
  question: string; schema: TableSchema[]; history: ChatTurn[];
  dialect: Dialect; context?: DrillContext;
}): string {
  const recent = opts.history.slice(-HISTORY_MESSAGE_LIMIT);
  const historyText = recent.length
    ? recent.map(t => `${t.role}: ${t.text}`).join("\n")
    : "(无)";
  // 方言提示放在通用规则之后、schema 之前:紧挨着 schema 能让模型把
  // 「这是什么库」和「有哪些表」连起来读。
  return `${SYSTEM}

${opts.dialect.promptNotes}

数据库 schema:
${renderSchema(opts.schema)}
${renderDrill(opts.context)}
对话历史(最近 2 轮):
${historyText}

用户问题: ${opts.question}`;
}

export function buildRetryPrompt(prevPrompt: string, feedback: string): string {
  return `${prevPrompt}\n\n上次输出有问题:${feedback}\n请严格按要求只输出 JSON。`;
}

export function buildInsightPrompt(
  facts: InsightFact[], question: string, format: ValueFormat,
): string {
  const lines = renderFactsLines(facts, format).filter(Boolean).map(l => `- ${l}`).join("\n");
  return `以下是系统已经算好的事实,请用 2-3 句中文串成一段连贯的分析。

严格约束:
- 不得引入任何未在下方列出的数字
- 不得逐条罗列,要串成自然的句子
- 不得给出业务建议或结论性判断
- 只输出这段分析文字,不要 JSON,不要标题

用户问题: ${question}
事实:
${lines}`;
}
