import type { ChartType, ChartPayload, Row } from "@chatbi/shared";

export function assemble(opts: {
  rows: Row[]; chartType: ChartType; columns: string[]; explanation: string;
}): ChartPayload {
  const { rows, chartType, columns, explanation } = opts;
  const table = { columns, rows };
  let echartsOption: object;

  if (chartType === "table") {
    echartsOption = {};
  } else if (chartType === "pie") {
    const data = rows.map(r => ({ name: String(r[columns[0]]), value: Number(r[columns[1]]) }));
    echartsOption = { tooltip: { trigger: "item" }, series: [{ type: "pie", data }] };
  } else {
    const data = rows.map(r => r[columns[1]]);
    const echartsType = chartType; // "bar" | "line"
    echartsOption = {
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: rows.map(r => String(r[columns[0]])) },
      yAxis: { type: "value" },
      series: [{ type: echartsType, data }],
    };
  }
  return { chartType, echartsOption, table, explanation };
}
