import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { DataSourceSummary } from "@chatbi/shared";
import { DataSourcesPage } from "../pages/DataSourcesPage";
import { DataSourceProvider } from "../dataSourceStore";
import {
  ApiError, createDataSource, deleteDataSource, fetchSchema, getDataSource, listDataSources,
  refreshSchema, testDataSource,
} from "../api";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    listDataSources: vi.fn(), testDataSource: vi.fn(), refreshSchema: vi.fn(),
    fetchSchema: vi.fn(), deleteDataSource: vi.fn(),
    getDataSource: vi.fn(), createDataSource: vi.fn(), updateDataSource: vi.fn(),
  };
});

const ds = (over: Partial<DataSourceSummary> & { id: string; name: string }): DataSourceSummary => ({
  kind: "mysql", target: "mysql://bi_ro@10.0.0.5:3306/sales", status: "ok",
  writePrivilege: "readonly", lastCheckAt: "2026-08-03T10:20:30.000Z", lastCheckError: null,
  schemaFetchedAt: "2026-08-03T10:20:30.000Z", tableCount: 12, ...over,
});

const mount = () => render(
  <MemoryRouter>
    <DataSourceProvider><DataSourcesPage /></DataSourceProvider>
  </MemoryRouter>,
);
const click = (name: RegExp | string) => fireEvent.click(screen.getByRole("button", { name }));

beforeEach(() => {
  localStorage.clear();
  vi.mocked(listDataSources).mockReset().mockResolvedValue([ds({ id: "ds1", name: "销售库" })]);
  vi.mocked(testDataSource).mockReset();
  vi.mocked(refreshSchema).mockReset();
  vi.mocked(fetchSchema).mockReset();
  vi.mocked(deleteDataSource).mockReset();
  vi.mocked(getDataSource).mockReset();
  vi.mocked(createDataSource).mockReset();
});

describe("管理页列表", () => {
  it("渲染名称、类型、脱敏 target、表数量与上次检查时间", async () => {
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    expect(screen.getByText("MySQL")).toBeTruthy();
    expect(screen.getByText("mysql://bi_ro@10.0.0.5:3306/sales")).toBeTruthy();
    expect(screen.getByText("12 张表")).toBeTruthy();
    expect(screen.getByText(/上次检查 2026-08-03 10:20/)).toBeTruthy();
  });

  it("状态异常的行把 lastCheckError 显示出来", async () => {
    vi.mocked(listDataSources).mockResolvedValue([
      ds({ id: "ds1", name: "坏源", status: "error", lastCheckError: "无法连接到 10.0.0.5:3306" }),
    ]);
    mount();
    await waitFor(() => expect(screen.getByText("无法连接到 10.0.0.5:3306")).toBeTruthy());
    expect(screen.getByText("连接失败")).toBeTruthy();
  });

  it("一个源都没有时给空状态", async () => {
    vi.mocked(listDataSources).mockResolvedValue([]);
    mount();
    await waitFor(() => expect(screen.getByTestId("ds-empty")).toBeTruthy());
  });
});

describe("管理页行内操作", () => {
  it("测连成功显示表数量与权限,并重拉列表", async () => {
    vi.mocked(testDataSource).mockResolvedValue({ ok: true, writePrivilege: "readonly", tableCount: 12 });
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    click(/测试连接/);
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("连接正常"));
    expect(screen.getByRole("status").textContent).toContain("12 张表");
    expect(screen.getByRole("status").textContent).toContain("只读");
    expect(vi.mocked(listDataSources).mock.calls.length).toBe(2);
  });

  it("测连失败显示可读消息,原文折在「查看详情」里", async () => {
    vi.mocked(testDataSource).mockRejectedValue(
      new ApiError("CONNECTION_ERROR", "无法连接到 10.0.0.5:3306,请检查地址、端口与网络", "Error: connect ECONNREFUSED"),
    );
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    click(/测试连接/);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("无法连接到 10.0.0.5:3306"));
    // 原文默认折叠:用户第一眼看到的是可读消息,而不是 ECONNREFUSED。
    expect((screen.getByText("查看详情").closest("details") as HTMLDetailsElement).open).toBe(false);
    fireEvent.click(screen.getByText("查看详情"));
    expect(screen.getByText(/ECONNREFUSED/)).toBeTruthy();
  });

  it("刷新结构显示表数与耗时", async () => {
    vi.mocked(refreshSchema).mockResolvedValue({
      tableCount: 12, fetchedAt: "2026-08-03T11:00:00.000Z", elapsedMs: 84,
    });
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    click(/刷新结构/);
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("12 张表"));
    expect(screen.getByRole("status").textContent).toContain("84 ms");
  });

  it("查看结构调 fetchSchema 并渲染表名,再点收起", async () => {
    vi.mocked(fetchSchema).mockResolvedValue({
      fetchedAt: "2026-08-03T10:20:30.000Z",
      schema: [{
        tableName: "orders",
        columns: [{ name: "id", type: "INT", notNull: true, pk: true }],
        foreignKeys: [],
      }],
    });
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    click(/查看结构/);
    await waitFor(() => expect(screen.getByText("orders")).toBeTruthy());
    expect(vi.mocked(fetchSchema)).toHaveBeenCalledWith("ds1");
    click(/收起结构/);
    await waitFor(() => expect(screen.queryByText("orders")).toBeNull());
  });
});

describe("管理页删除", () => {
  it("删除要二次确认,提示看板卡片会失效", async () => {
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    click("删除");
    expect(screen.getByRole("alertdialog").textContent).toContain("引用它的看板卡片会失效");
    expect(vi.mocked(deleteDataSource)).not.toHaveBeenCalled();
  });

  it("确认后才真删,并重拉列表", async () => {
    vi.mocked(deleteDataSource).mockResolvedValue(undefined);
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    click("删除");
    vi.mocked(listDataSources).mockResolvedValue([]);
    click("确认删除");
    await waitFor(() => expect(vi.mocked(deleteDataSource)).toHaveBeenCalledWith("ds1"));
    await waitFor(() => expect(screen.getByTestId("ds-empty")).toBeTruthy());
  });

  it("取消后确认框消失且不删", async () => {
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    click("删除");
    click("取消");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(vi.mocked(deleteDataSource)).not.toHaveBeenCalled();
  });
});

describe("管理页的新建与编辑", () => {
  it("点「新建数据源」打开空表单", async () => {
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    click("新建数据源");
    expect(screen.getByRole("heading", { name: "新建数据源" })).toBeTruthy();
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe("");
  });

  it("点行内「编辑」拉详情并回填", async () => {
    vi.mocked(getDataSource).mockResolvedValue({
      id: "ds1", name: "销售库", kind: "mysql", target: "mysql://bi_ro@10.0.0.5:3306/sales",
      status: "ok", writePrivilege: "readonly", lastCheckAt: null, lastCheckError: null,
      schemaFetchedAt: null, tableCount: 12, hasPassword: true,
      connection: { host: "10.0.0.5", port: 3306, database: "sales", user: "bi_ro", ssl: false },
    });
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    click("编辑");
    await waitFor(() => expect(screen.getByRole("heading", { name: "编辑数据源" })).toBeTruthy());
    expect(vi.mocked(getDataSource)).toHaveBeenCalledWith("ds1");
    expect((screen.getByLabelText("主机") as HTMLInputElement).value).toBe("10.0.0.5");
  });

  it("保存成功后关掉表单并重拉列表", async () => {
    vi.mocked(createDataSource).mockResolvedValue({
      id: "ds2", name: "新库", kind: "sqlite", target: "./data/new.db", status: "ok",
      writePrivilege: "readonly", lastCheckAt: null, lastCheckError: null,
      schemaFetchedAt: null, tableCount: 1, hasPassword: false, connection: { path: "./data/new.db" },
    });
    mount();
    await waitFor(() => expect(screen.getByText("销售库")).toBeTruthy());
    click("新建数据源");
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "新库" } });
    fireEvent.change(screen.getByLabelText("文件路径"), { target: { value: "./data/new.db" } });
    click("保存");
    await waitFor(() => expect(screen.queryByRole("heading", { name: "新建数据源" })).toBeNull());
    expect(vi.mocked(listDataSources).mock.calls.length).toBe(2);
  });
});
