import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { DataSourceSummary } from "@chatbi/shared";
import { DataSourcePicker } from "../components/DataSourcePicker";
import { DataSourceProvider } from "../dataSourceStore";
import { listDataSources } from "../api";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, listDataSources: vi.fn() };
});

const ds = (over: Partial<DataSourceSummary> & { id: string; name: string }): DataSourceSummary => ({
  kind: "sqlite", target: "./data/x.db", status: "ok", writePrivilege: "readonly",
  lastCheckAt: null, lastCheckError: null, schemaFetchedAt: null, tableCount: null, ...over,
});

const mount = () => render(
  <MemoryRouter>
    <DataSourceProvider><DataSourcePicker /></DataSourceProvider>
  </MemoryRouter>,
);

beforeEach(() => {
  localStorage.clear();
  vi.mocked(listDataSources).mockReset();
});

describe("DataSourcePicker", () => {
  it("列出所有源,选中第一个,选项文案带类型", async () => {
    vi.mocked(listDataSources).mockResolvedValue([
      ds({ id: "ds1", name: "示例订单库" }),
      ds({ id: "ds2", name: "销售库", kind: "mysql" }),
    ]);
    mount();
    const box = await waitFor(() => screen.getByLabelText("数据源") as HTMLSelectElement);
    expect(box.value).toBe("ds1");
    expect(screen.getByRole("option", { name: /销售库 · MySQL/ })).toBeTruthy();
  });

  it("换选项后选中项与持久化都跟着变", async () => {
    vi.mocked(listDataSources).mockResolvedValue([
      ds({ id: "ds1", name: "示例订单库" }),
      ds({ id: "ds2", name: "销售库", kind: "postgres" }),
    ]);
    mount();
    const box = await waitFor(() => screen.getByLabelText("数据源") as HTMLSelectElement);
    fireEvent.change(box, { target: { value: "ds2" } });
    await waitFor(() => expect(box.value).toBe("ds2"));
    expect(localStorage.getItem("chatbi.selectedDataSourceId")).toBe("ds2");
  });

  it("选中源状态异常时挂状态徽标", async () => {
    vi.mocked(listDataSources).mockResolvedValue([
      ds({ id: "ds1", name: "坏源", status: "error", lastCheckError: "无法连接" }),
    ]);
    mount();
    await waitFor(() => expect(screen.getByText("连接失败")).toBeTruthy());
  });

  it("有写权限的源挂只读账号警告", async () => {
    vi.mocked(listDataSources).mockResolvedValue([
      ds({ id: "ds1", name: "可写源", writePrivilege: "writable" }),
    ]);
    mount();
    await waitFor(() => expect(screen.getByTestId("privilege-badge").textContent).toBe("建议改用只读账号"));
  });

  it("列表为空时提示去添加,不渲染下拉框", async () => {
    vi.mocked(listDataSources).mockResolvedValue([]);
    mount();
    await waitFor(() => expect(screen.getByTestId("picker-empty").textContent).toContain("无可用数据源"));
    expect(screen.queryByLabelText("数据源")).toBeNull();
  });

  it("拉列表失败时给 alert 提示", async () => {
    vi.mocked(listDataSources).mockRejectedValue(new Error("服务器返回 500"));
    mount();
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("无法读取数据源列表"));
  });

  it("「管理」链接指向 /datasources", async () => {
    vi.mocked(listDataSources).mockResolvedValue([ds({ id: "ds1", name: "示例订单库" })]);
    mount();
    const link = await waitFor(() => screen.getByRole("link", { name: "管理" }));
    expect(link.getAttribute("href")).toBe("/datasources");
  });
});
