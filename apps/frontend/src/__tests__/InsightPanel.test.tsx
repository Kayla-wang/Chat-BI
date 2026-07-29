import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { InsightPanel } from "../components/InsightPanel";
import type { InsightFact } from "@chatbi/shared";

const CURRENCY = { kind: "currency" as const, decimals: 0, unit: "元", scale: 1 as const };
const facts: InsightFact[] = [
  { kind: "trend", series: "金额", dir: "up", pct: 23.4, from: "1月", to: "3月" },
  { kind: "peak", series: "金额", label: "3月", value: 128400 },
];

describe("InsightPanel", () => {
  it("展示洞察文本", () => {
    render(<InsightPanel text="上半年上涨明显。" facts={[]} format={CURRENCY} />);
    expect(screen.getByTestId("insight-text").textContent).toBe("上半年上涨明显。");
  });

  it("计算依据逐条列出,数值已格式化", () => {
    render(<InsightPanel text="x" facts={facts} format={CURRENCY} />);
    expect(screen.getByText(/计算依据（2 项）/)).toBeTruthy();
    expect(screen.getByText(/上涨 23\.4%/)).toBeTruthy();
    expect(screen.getByText(/128,400 元/)).toBeTruthy();
  });

  it("没有事实时不渲染计算依据折叠", () => {
    render(<InsightPanel text="x" facts={[]} format={CURRENCY} />);
    expect(screen.queryByText(/计算依据/)).toBeNull();
  });

  it("既无文本又无事实时整块不渲染", () => {
    const { container } = render(<InsightPanel text="" facts={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("不传 format 时按普通数值渲染,不崩", () => {
    render(<InsightPanel text="x" facts={[{ kind: "total", series: "s", value: 1234 }]} />);
    expect(screen.getByText(/1,234/)).toBeTruthy();
  });
});
