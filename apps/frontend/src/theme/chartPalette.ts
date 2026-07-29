import { useEffect, useState } from "react";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/**
 * Okabe-Ito 色觉友好色系派生。
 * 浅色底:去掉原色系里的亮黄(#f0e442,浅底对比度不足),末位换成中性灰。
 * 深色底:去掉原色系里的纯黑,整体提亮。
 */
export const CHART_PALETTE_LIGHT = [
  "#0072b2", "#d55e00", "#009e73", "#cc79a7",
  "#56b4e9", "#e69f00", "#8b6bb1", "#4d4d4d",
];

export const CHART_PALETTE_DARK = [
  "#56b4e9", "#e69f00", "#00b888", "#f49ac2",
  "#9fd8f5", "#ffb861", "#b79ce0", "#bfbfbf",
];

function prefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(DARK_QUERY).matches;
}

export function useChartPalette(): string[] {
  const [dark, setDark] = useState(prefersDark);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = () => setDark(mq.matches);
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);

  return dark ? CHART_PALETTE_DARK : CHART_PALETTE_LIGHT;
}
