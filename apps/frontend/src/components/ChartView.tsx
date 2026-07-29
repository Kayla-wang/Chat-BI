import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import type { ChartSpec } from "@chatbi/shared";
import { specToEchartsOption } from "@chatbi/shared";
import { useChartPalette } from "../theme/chartPalette";
import styles from "./ChartView.module.css";

export function ChartView({ spec }: { spec: ChartSpec }) {
  const palette = useChartPalette();
  const ref = useRef<HTMLDivElement>(null);
  const option = useMemo(() => specToEchartsOption(spec, palette), [spec, palette]);

  useEffect(() => {
    if (!ref.current) return;
    let chart: echarts.ECharts | undefined;
    try {
      chart = echarts.init(ref.current);
      chart.setOption(option as echarts.EChartsOption, true);
    } catch { /* jsdom 无 canvas:忽略 */ }

    const onResize = () => { try { chart?.resize(); } catch { /* 同上 */ } };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      try { chart?.dispose(); } catch { /* 同上 */ }
    };
  }, [option]);

  return <div ref={ref} className={styles.canvas} data-testid="chart" />;
}
