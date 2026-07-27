export type Row = Record<string, string | number | null>;

export type ChartType = "bar" | "line" | "pie" | "table";

export interface TableSchema {
  tableName: string;
  columns: { name: string; type: string; notNull: boolean; pk: boolean }[];
  foreignKeys: { column: string; refTable: string; refColumn: string }[];
}

export interface ChartPayload {
  chartType: ChartType;
  echartsOption: object;
  table: { columns: string[]; rows: Row[] };
  explanation: string;
}

export type StreamEvent =
  | { type: "explanationDelta"; text: string }
  | { type: "result"; payload: ChartPayload }
  | { type: "error"; message: string; raw?: string };

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}
