import type { ChartSeries, TimeGrain } from "@chatbi/shared";
import { parseTemporal } from "./columnTypes";

const YEAR_ONLY = /^\d{4}$/;
const QUARTER_KEY = /^(\d{4})-Q([1-4])$/;
const MONTH_ONLY = /^\d{4}-\d{2}$/;
const DAY_MS = 86400000;

const pad = (n: number) => String(n).padStart(2, "0");

/** 键的字符串形态优先;只有完整日期才用间隔区分 day / week。 */
export function inferGrain(keys: string[]): TimeGrain {
  if (keys.every(k => YEAR_ONLY.test(k))) return "year";
  if (keys.every(k => QUARTER_KEY.test(k))) return "quarter";
  if (keys.every(k => MONTH_ONLY.test(k))) return "month";
  const ts = keys.map(k => parseTemporal(k)).filter((d): d is Date => d !== null)
    .map(d => d.getTime()).sort((a, b) => a - b);
  if (ts.length < 2) return "day";
  const gaps: number[] = [];
  for (let i = 1; i < ts.length; i++) gaps.push((ts[i] - ts[i - 1]) / DAY_MS);
  gaps.sort((a, b) => a - b);
  const median = gaps[Math.floor(gaps.length / 2)];
  return median >= 5 ? "week" : "day";
}

export function toTickKey(d: Date, grain: TimeGrain): string {
  const y = d.getUTCFullYear();
  if (grain === "year") return String(y);
  if (grain === "quarter") return `${y}-Q${Math.floor(d.getUTCMonth() / 3) + 1}`;
  if (grain === "month") return `${y}-${pad(d.getUTCMonth() + 1)}`;
  if (grain === "week") {
    const monday = new Date(d.getTime() - ((d.getUTCDay() + 6) % 7) * DAY_MS);
    return `${monday.getUTCFullYear()}-${pad(monday.getUTCMonth() + 1)}-${pad(monday.getUTCDate())}`;
  }
  return `${y}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

function keyToDate(key: string, grain: TimeGrain): Date {
  const q = QUARTER_KEY.exec(key);
  if (q) return new Date(Date.UTC(Number(q[1]), (Number(q[2]) - 1) * 3, 1));
  return parseTemporal(key) ?? new Date(Date.UTC(1970, 0, 1));
}

function step(d: Date, grain: TimeGrain): Date {
  const y = d.getUTCFullYear(), m = d.getUTCMonth(), day = d.getUTCDate();
  if (grain === "year") return new Date(Date.UTC(y + 1, m, day));
  if (grain === "quarter") return new Date(Date.UTC(y, m + 3, day));
  if (grain === "month") return new Date(Date.UTC(y, m + 1, day));
  return new Date(d.getTime() + (grain === "week" ? 7 : 1) * DAY_MS);
}

export function enumerateTicks(from: string, to: string, grain: TimeGrain): string[] {
  const end = keyToDate(to, grain).getTime();
  const out: string[] = [];
  let cur = keyToDate(from, grain);
  while (cur.getTime() <= end && out.length < 5000) {
    out.push(toTickKey(cur, grain));
    cur = step(cur, grain);
  }
  return out;
}

export function fillGaps(opts: {
  tickKeys: string[]; rowKeys: string[]; series: ChartSeries[];
}): { series: ChartSeries[]; filled: number } {
  const index = new Map(opts.rowKeys.map((k, i) => [k, i]));
  const series = opts.series.map(s => {
    const fill = s.format.kind === "percent" ? null : 0;
    return {
      ...s,
      data: opts.tickKeys.map(k => {
        const i = index.get(k);
        return i === undefined ? fill : s.data[i] ?? fill;
      }),
    };
  });
  return { series, filled: opts.tickKeys.length - opts.rowKeys.length };
}
