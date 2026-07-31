export type Row = Record<string, string | number | null>;

export type ChartType = "bar" | "line" | "pie" | "table";
export type ColumnRole = "temporal" | "categorical" | "numeric";
export type TimeGrain = "day" | "week" | "month" | "quarter" | "year";
export type StackMode = "none" | "normal" | "percent";

export interface TableSchema {
  tableName: string;
  columns: { name: string; type: string; notNull: boolean; pk: boolean }[];
  foreignKeys: { column: string; refTable: string; refColumn: string }[];
}

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

/** 数值展示口径。percent 的值已是百分数(41.2 表示 41.2%)。 */
export interface ValueFormat {
  kind: "number" | "currency" | "percent";
  decimals: number;
  unit?: string;
  scale?: 1 | 10000 | 100000000;
}

export interface ChartSeries {
  name: string;
  field: string;
  data: (number | null)[];
  format: ValueFormat;
}

export interface ChartSpec {
  chartType: ChartType;
  stack: StackMode;
  x: {
    field: string;
    role: "temporal" | "categorical";
    labels: string[];
    grain?: TimeGrain;
  };
  series: ChartSeries[];
  notes: string[];
}

/** LLM 输出的图表语义提示——不可信,inferChartSpec 会逐字段校验。 */
export interface ChartHint {
  chartType: ChartType;
  dimensions: string[];
  measures: string[];
  seriesBy?: string;
  stack?: StackMode;
}

export type InsightFact =
  | { kind: "trend"; series: string; dir: "up" | "down" | "flat"; pct: number; from: string; to: string }
  | { kind: "trendAbs"; series: string; delta: number; from: string; to: string }
  | { kind: "peak"; series: string; label: string; value: number }
  | { kind: "trough"; series: string; label: string; value: number }
  | { kind: "topShare"; series: string; label: string; pct: number }
  | { kind: "concentration"; series: string; topN: number; pct: number }
  | { kind: "total"; series: string; value: number }
  | { kind: "seriesGap"; high: string; low: string; ratio: number }
  | { kind: "truncated"; limit: number }
  | { kind: "empty" };

export interface DrillContext {
  lastSql: string;
  lastColumns: string[];
}

export interface ResultPayload {
  spec: ChartSpec;
  table: { columns: string[]; rows: Row[] };
  queryIntent: string;
  sql: string;
}

export type StreamEvent =
  | { type: "result"; payload: ResultPayload }
  | { type: "insightFacts"; facts: InsightFact[] }
  | { type: "insightDelta"; text: string }
  | { type: "done" }
  | { type: "error"; message: string; raw?: string };

export type DataSourceKind = "sqlite" | "mysql" | "postgres";

export type WritePrivilege = "readonly" | "writable" | "unknown";

/**
 * 数据源连接参数。前端表单构造它、后端加密存它,所以放在共享契约里。
 * ssl 只有开关:自定义 CA 与客户端证书不在 P2a 范围。
 */
export type DsConfig =
  | { kind: "sqlite"; path: string }
  | { kind: "mysql"; host: string; port: number; database: string; user: string; password: string; ssl: boolean }
  | { kind: "postgres"; host: string; port: number; database: string; user: string; password: string; ssl: boolean; schema?: string };

/** 数据源相关的错误分类。前端按它决定要不要提示「刷新结构」「重新配置凭据」等。 */
export type DsErrorCode =
  | "CONNECTION_ERROR"
  | "AUTH_ERROR"
  | "DB_NOT_FOUND"     // 目标库/文件不存在
  | "NOT_FOUND"        // 我们自己的数据源记录不存在
  | "TIMEOUT"
  | "SQL_ERROR"
  | "SCHEMA_STALE"     // SQL_ERROR 的一种:表或列不存在,提示用户刷新结构
  | "PERMISSION_ERROR"
  | "DECRYPT_ERROR"
  | "UNKNOWN";
