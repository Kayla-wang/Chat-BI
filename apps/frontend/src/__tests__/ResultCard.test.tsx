import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ResultCard } from "../components/ResultCard";
import type { ResultPayload, InsightFact } from "@chatbi/shared";

// jsdom 没有 canvas,真实 ECharts 的动画帧会在组件 try/catch 之外抛异步异常。
// 按计划的口径「不测 ECharts 绘制,只测传给它的 option」——option 由
// packages/shared 的 renderer 测试覆盖,这里只需要一个空实现。
vi.mock("echarts", () => ({
  init: () => ({ setOption: () => {}, dispose: () => {}, resize: () => {} }),
}));

const CURRENCY = { kind: "currency" as const, decimals: 0, unit: "元", scale: 1 as const };

const payload = (over: Partial<ResultPayload> = {}): ResultPayload => ({
  spec: {
    chartType: "bar", stack: "none",
    x: { field: "region", role: "categorical", labels: ["华东", "华北"] },
    series: [{ name: "total", field: "total", data: [100, 200], format: CURRENCY }],
    notes: [],
  },
  table: {
    columns: ["region", "total"],
    rows: [{ region: "华东", total: 100 }, { region: "华北", total: 200 }],
  },
  queryIntent: "按地区汇总",
  sql: "SELECT region, SUM(total) AS total FROM orders GROUP BY region",
  ...over,
});

const facts: InsightFact[] = [{ kind: "total", series: "total", value: 300 }];

describe("ResultCard 表格与切换", () => {
  it("渲染表头与数据行", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    expect(screen.getByText("region")).toBeTruthy();
    expect(screen.getByText("华东")).toBeTruthy();
    expect(screen.getByText("200")).toBeTruthy();
  });

  it("4 个图表类型按钮,后端建议的那个高亮", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    expect(screen.getByRole("button", { name: /bar/i }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /pie/i }).getAttribute("aria-pressed")).toBe("false");
  });

  it("切到 pie 后高亮转移,表格仍在", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    fireEvent.click(screen.getByRole("button", { name: /pie/i }));
    expect(screen.getByRole("button", { name: /pie/i }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("华东")).toBeTruthy();
  });

  it("切到 table 时图表容器消失", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    expect(screen.queryByTestId("chart")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /table/i }));
    expect(screen.queryByTestId("chart")).toBeNull();
  });

  it("后端建议 table 时也能切成图表(series 已备好)", () => {
    const p = payload();
    p.spec.chartType = "table";
    render(<ResultCard payload={p} insight="" facts={[]} />);
    expect(screen.queryByTestId("chart")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /bar/i }));
    expect(screen.queryByTestId("chart")).toBeTruthy();
  });
});

describe("ResultCard notes / SQL / 大表格", () => {
  it("notes 逐条展示", () => {
    const p = payload();
    p.spec.notes = ["已补齐 2 个无数据的时间点（按 0 计）", "结果已截断至 1000 行"];
    render(<ResultCard payload={p} insight="" facts={[]} />);
    expect(screen.getAllByTestId("note")).toHaveLength(2);
  });

  it("查看 SQL 折叠区里是校验后的 SQL", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    expect(screen.getByText(/查看 SQL/)).toBeTruthy();
    expect(screen.getByText(/GROUP BY region/)).toBeTruthy();
  });

  it("超过 100 行只渲染前 100 行并提示", () => {
    const rows = Array.from({ length: 120 }, (_, i) => ({ region: `r${i}`, total: i }));
    render(<ResultCard payload={payload({ table: { columns: ["region", "total"], rows } })}
      insight="" facts={[]} />);
    expect(screen.getByText(/另有 20 行未展示/)).toBeTruthy();
    expect(screen.queryByText("r119")).toBeNull();
  });

  it("洞察文本与计算依据一起挂在卡片里", () => {
    render(<ResultCard payload={payload()} insight="华东区领先。" facts={facts} />);
    expect(screen.getByTestId("insight-text").textContent).toBe("华东区领先。");
    expect(screen.getByText(/计算依据/)).toBeTruthy();
  });
});
