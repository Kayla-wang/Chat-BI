import type { ValueFormat, TimeGrain } from "./types";

const SCALE_SUFFIX: Record<number, string> = { 1: "", 10000: "万", 100000000: "亿" };

function group(n: string): string {
  const [int, frac] = n.split(".");
  const sign = int.startsWith("-") ? "-" : "";
  const digits = sign ? int.slice(1) : int;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac ? `${sign}${grouped}.${frac}` : `${sign}${grouped}`;
}

export function formatValue(v: number | null, f: ValueFormat): string {
  if (v === null || Number.isNaN(v)) return "—";
  if (f.kind === "percent") return `${v.toFixed(f.decimals)}%`;
  const scale = f.scale ?? 1;
  const scaled = v / scale;
  const num = group(scaled.toFixed(f.decimals));
  const suffix = SCALE_SUFFIX[scale] ?? "";
  if (f.kind === "currency") return `${num} ${suffix}${f.unit ?? ""}`.replace(/\s+$/, "");
  return suffix ? `${num} ${suffix}` : num;
}

export function formatTimeLabel(tickKey: string, grain: TimeGrain, crossYear: boolean): string {
  if (grain === "year") return `${tickKey}年`;
  if (grain === "quarter") {
    const [y, q] = tickKey.split("-");
    return crossYear ? `${y}${q}` : q;
  }
  const [y, m, d] = tickKey.split("-");
  const month = Number(m);
  if (grain === "month") return crossYear ? `${y}年${month}月` : `${month}月`;
  const day = Number(d);
  return crossYear ? `${y}年${month}月${day}日` : `${month}月${day}日`;
}
