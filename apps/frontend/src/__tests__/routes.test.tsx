import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes } from "../routes";
import { DataSourceProvider } from "../dataSourceStore";
import { listDataSources } from "../api";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, listDataSources: vi.fn() };
});
// 同 ResultCard.test.tsx:jsdom 无 canvas,真实 ECharts 会抛异步异常。
vi.mock("echarts", () => ({
  init: () => ({ setOption: () => {}, dispose: () => {}, resize: () => {} }),
}));

const at = (path: string) => render(
  <MemoryRouter initialEntries={[path]}>
    <DataSourceProvider><AppRoutes /></DataSourceProvider>
  </MemoryRouter>,
);

beforeEach(() => {
  localStorage.clear();
  vi.mocked(listDataSources).mockResolvedValue([]);
});

describe("AppRoutes", () => {
  it("/ 渲染对话页", async () => {
    at("/");
    await waitFor(() => expect(screen.getByTestId("empty-state")).toBeTruthy());
  });

  it("/datasources 渲染管理页", async () => {
    at("/datasources");
    await waitFor(() => expect(screen.getByRole("heading", { name: "数据源管理" })).toBeTruthy());
  });

  it("未知路径回落到对话页", async () => {
    at("/不存在的页面");
    await waitFor(() => expect(screen.getByTestId("empty-state")).toBeTruthy());
  });
});
