import type { InsightFact, ValueFormat } from "./types";
import { formatValue } from "./format";

const DIR_TEXT = { up: "上涨", down: "下降", flat: "基本持平" } as const;

export function renderFactsLines(facts: InsightFact[], format: ValueFormat): string[] {
  return facts.map(f => {
    switch (f.kind) {
      case "trend":
        return f.dir === "flat"
          ? `趋势：系列「${f.series}」基本持平（${f.from} → ${f.to}）`
          : `趋势：系列「${f.series}」${DIR_TEXT[f.dir]} ${Math.abs(f.pct).toFixed(1)}%（${f.from} → ${f.to}）`;
      case "trendAbs":
        return `趋势：系列「${f.series}」净变化 ${formatValue(f.delta, format)}（${f.from} → ${f.to}）`;
      case "peak": return `峰值：${f.label} ${formatValue(f.value, format)}`;
      case "trough": return `谷值：${f.label} ${formatValue(f.value, format)}`;
      case "topShare": return `头部占比：${f.label} ${f.pct.toFixed(1)}%`;
      case "concentration": return `集中度：头部 ${f.topN} 项合计 ${f.pct.toFixed(1)}%`;
      case "total": return `总量：${formatValue(f.value, format)}`;
      case "seriesGap": return `系列差距：${f.high} 是 ${f.low} 的 ${f.ratio.toFixed(1)} 倍`;
      case "truncated": return `结果已截断至 ${f.limit} 行`;
      case "empty": return "没有符合条件的记录";
      default: return "";
    }
  });
}

export function renderFactsTemplate(facts: InsightFact[], format: ValueFormat): string {
  const lines = renderFactsLines(facts, format).filter(Boolean);
  return lines.length ? `${lines.join("；")}。` : "没有可用的分析结果。";
}
