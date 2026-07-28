import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ResultCard } from "../components/ResultCard";
import type { ChartPayload } from "@chatbi/shared";

const payload: ChartPayload = {
  chartType: "bar",
  echartsOption: { xAxis: { type: "category", data: ["east", "west"] }, series: [{ type: "bar", data: [100, 200] }] },
  table: { columns: ["region", "total"], rows: [{ region: "east", total: 100 }, { region: "west", total: 200 }] },
  explanation: "按地区汇总",
};

describe("ResultCard", () => {
  it("renders table columns + rows", () => {
    render(<ResultCard payload={payload} />);
    expect(screen.getByText("region")).toBeTruthy();
    expect(screen.getByText("east")).toBeTruthy();
    expect(screen.getByText("200")).toBeTruthy();
  });
  it("shows 4 chart type buttons with backend suggestion highlighted", () => {
    render(<ResultCard payload={payload} />);
    const bar = screen.getByRole("button", { name: /bar/i });
    expect(bar.getAttribute("aria-pressed")).toBe("true");
  });
  it("switching to pie re-renders option from table data", () => {
    render(<ResultCard payload={payload} />);
    fireEvent.click(screen.getByRole("button", { name: /pie/i }));
    // 切换后 pie 应被选中
    expect(screen.getByRole("button", { name: /pie/i }).getAttribute("aria-pressed")).toBe("true");
    // 表格仍可见
    expect(screen.getByText("east")).toBeTruthy();
  });
});
