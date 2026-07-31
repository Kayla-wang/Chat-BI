import type { DataSourceKind } from "./types";

export interface Dialect {
  kind: DataSourceKind;
  quoteIdent(name: string): string;
  /** node-sql-parser 的 database 选项;方言不对会把合法 SQL 判成解析失败。 */
  sqlParserDialect: "sqlite" | "mysql" | "postgresql";
  /** 注入 LLM 提示词,告诉它本次要写哪种方言。 */
  promptNotes: string;
}

const dq = (name: string): string => `"${name.replace(/"/g, '""')}"`;
const bq = (name: string): string => `\`${name.replace(/`/g, "``")}\``;

export const SQLITE_DIALECT: Dialect = {
  kind: "sqlite",
  quoteIdent: dq,
  sqlParserDialect: "sqlite",
  promptNotes: `本次目标数据库是 SQLite。
- 按月/按日截断时间用 strftime,例如 strftime('%Y-%m', order_date)。
- 标识符用双引号,例如 "order date"。
- 日期是文本,比较时用 'YYYY-MM-DD' 格式的字符串。`,
};

export const MYSQL_DIALECT: Dialect = {
  kind: "mysql",
  quoteIdent: bq,
  sqlParserDialect: "mysql",
  promptNotes: `本次目标数据库是 MySQL。
- 按月截断时间用 DATE_FORMAT(order_date, '%Y-%m');按周用 DATE_FORMAT(order_date, '%x-W%v')。
- 标识符用反引号,例如 \`order date\`。
- 不要使用 SQLite 或 PostgreSQL 特有的函数。`,
};

export const POSTGRES_DIALECT: Dialect = {
  kind: "postgres",
  quoteIdent: dq,
  sqlParserDialect: "postgresql",
  promptNotes: `本次目标数据库是 PostgreSQL。
- 按月截断时间用 to_char(date_trunc('month', order_date), 'YYYY-MM')。
- 标识符用双引号,例如 "order date";未加引号的标识符会被折成小写。
- 整数相除要显式转换,例如 SUM(a)::numeric / SUM(b)。`,
};

export function dialectFor(kind: DataSourceKind): Dialect {
  switch (kind) {
    case "sqlite": return SQLITE_DIALECT;
    case "mysql": return MYSQL_DIALECT;
    case "postgres": return POSTGRES_DIALECT;
  }
}
