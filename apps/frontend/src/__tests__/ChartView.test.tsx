import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ChartSpec } from "@chatbi/shared";
import { ChartView } from "../components/ChartView";
import { CHART_PALETTE_LIGHT } from "../theme/chartPalette";

const setOption = vi.fn();
const dispose = vi.fn();
const resize = vi.fn();

vi.mock("echarts", () => ({
  init: vi.fn(() => ({ setOption, dispose, resize })),
}));

beforeEach(() => { setOption.mockClear(); dispose.mockClear(); });

const spec: ChartSpec = {
  chartType: "bar", stack: "none",
  x: { field: "region", role: "categorical", labels: ["华东", "华北"] },
  series: [{
    name: "amount", field: "amount", data: [100, 200],
    format: { kind: "currency", decimals: 0, unit: "元", scale: 1 },
  }],
  notes: [],
};

describe("ChartView", () => {
  it("渲染图表容器", () => {
    render(<ChartView spec={spec} />);
    expect(screen.getByTestId("chart")).toBeTruthy();
  });

  it("把 spec 与浅色调色板交给 specToEchartsOption 的结果传给 setOption", () => {
    render(<ChartView spec={spec} />);
    const option = setOption.mock.calls[0][0];
    expect(option.color).toEqual(CHART_PALETTE_LIGHT);
    expect(option.series[0].type).toBe("bar");
    expect(option.xAxis.data).toEqual(["华东", "华北"]);
  });

  it("卸载时 dispose", () => {
    const { unmount } = render(<ChartView spec={spec} />);
    unmount();
    expect(dispose).toHaveBeenCalled();
  });

  it("spec 变化时重新 setOption", () => {
    const { rerender } = render(<ChartView spec={spec} />);
    rerender(<ChartView spec={{ ...spec, chartType: "line" }} />);
    expect(setOption.mock.calls.at(-1)![0].series[0].type).toBe("line");
  });

  it("window resize 时调用 chart.resize", () => {
    render(<ChartView spec={spec} />);
    resize.mockClear();
    window.dispatchEvent(new Event("resize"));
    expect(resize).toHaveBeenCalled();
  });
});
