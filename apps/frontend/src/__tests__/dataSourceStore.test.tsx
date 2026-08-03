import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { DataSourceSummary } from "@chatbi/shared";
import { DataSourceProvider, SELECTED_KEY, useDataSources } from "../dataSourceStore";
import { listDataSources } from "../api";

// 只桩 listDataSources,其余导出(ApiError 等)保持真实,免得连带坏掉别处。
vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, listDataSources: vi.fn() };
});

const ds = (id: string, name: string): DataSourceSummary => ({
  id, name, kind: "sqlite", target: `./data/${id}.db`, status: "ok",
  writePrivilege: "readonly", lastCheckAt: null, lastCheckError: null,
  schemaFetchedAt: null, tableCount: 3,
});

/** 探针组件:把 store 的每个字段摊成一个可断言的节点。 */
function Probe() {
  const { list, selectedId, selected, loading, error, select, reload } = useDataSources();
  return (
    <div>
      <span data-testid="ids">{list.map(d => d.id).join(",")}</span>
      <span data-testid="selected">{selectedId ?? "-"}</span>
      <span data-testid="selected-name">{selected?.name ?? "-"}</span>
      <span data-testid="loading">{loading ? "yes" : "no"}</span>
      <span data-testid="error">{error ?? "-"}</span>
      <button onClick={() => select("ds2")}>选 ds2</button>
      <button onClick={() => void reload()}>重载</button>
    </div>
  );
}

const mount = () => render(<DataSourceProvider><Probe /></DataSourceProvider>);
const at = (id: string) => screen.getByTestId(id).textContent;
const settled = () => waitFor(() => expect(at("loading")).toBe("no"));

beforeEach(() => {
  localStorage.clear();
  vi.mocked(listDataSources).mockReset();
});

describe("dataSourceStore 初始加载", () => {
  it("挂载后拉列表,默认选中第一个并写进 localStorage", async () => {
    vi.mocked(listDataSources).mockResolvedValue([ds("ds1", "示例订单库"), ds("ds2", "销售库")]);
    mount();
    await settled();
    expect(at("ids")).toBe("ds1,ds2");
    expect(at("selected")).toBe("ds1");
    expect(at("selected-name")).toBe("示例订单库");
    expect(localStorage.getItem(SELECTED_KEY)).toBe("ds1");
  });

  it("localStorage 里的 id 仍在列表中时优先它", async () => {
    localStorage.setItem(SELECTED_KEY, "ds2");
    vi.mocked(listDataSources).mockResolvedValue([ds("ds1", "示例订单库"), ds("ds2", "销售库")]);
    mount();
    await settled();
    expect(at("selected")).toBe("ds2");
    expect(at("selected-name")).toBe("销售库");
  });

  it("记住的源已被删掉时回落第一个,并覆写 localStorage", async () => {
    localStorage.setItem(SELECTED_KEY, "已删掉的源");
    vi.mocked(listDataSources).mockResolvedValue([ds("ds1", "示例订单库")]);
    mount();
    await settled();
    expect(at("selected")).toBe("ds1");
    expect(localStorage.getItem(SELECTED_KEY)).toBe("ds1");
  });

  it("列表为空时 selectedId 是 null,并清掉 localStorage", async () => {
    localStorage.setItem(SELECTED_KEY, "ds1");
    vi.mocked(listDataSources).mockResolvedValue([]);
    mount();
    await settled();
    expect(at("selected")).toBe("-");
    expect(at("selected-name")).toBe("-");
    expect(localStorage.getItem(SELECTED_KEY)).toBeNull();
  });

  it("拉取失败时给可读消息,loading 落回 false", async () => {
    vi.mocked(listDataSources).mockRejectedValue(new Error("服务器返回 500"));
    mount();
    await settled();
    expect(at("error")).toContain("无法读取数据源列表");
    expect(at("error")).toContain("服务器返回 500");
    expect(at("ids")).toBe("");
  });
});

describe("dataSourceStore 切换与重载", () => {
  it("select() 改选中并持久化", async () => {
    vi.mocked(listDataSources).mockResolvedValue([ds("ds1", "示例订单库"), ds("ds2", "销售库")]);
    mount();
    await settled();
    fireEvent.click(screen.getByRole("button", { name: /选 ds2/ }));
    await waitFor(() => expect(at("selected")).toBe("ds2"));
    expect(localStorage.getItem(SELECTED_KEY)).toBe("ds2");
  });

  it("reload() 能看到新增的源,且不动当前选中", async () => {
    vi.mocked(listDataSources).mockResolvedValue([ds("ds1", "示例订单库")]);
    mount();
    await settled();
    vi.mocked(listDataSources).mockResolvedValue([ds("ds1", "示例订单库"), ds("ds2", "销售库")]);
    fireEvent.click(screen.getByRole("button", { name: /重载/ }));
    await waitFor(() => expect(at("ids")).toBe("ds1,ds2"));
    expect(at("selected")).toBe("ds1");
  });

  it("reload() 后当前源消失则回落第一个", async () => {
    localStorage.setItem(SELECTED_KEY, "ds2");
    vi.mocked(listDataSources).mockResolvedValue([ds("ds1", "示例订单库"), ds("ds2", "销售库")]);
    mount();
    await settled();
    expect(at("selected")).toBe("ds2");
    vi.mocked(listDataSources).mockResolvedValue([ds("ds1", "示例订单库")]);
    fireEvent.click(screen.getByRole("button", { name: /重载/ }));
    await waitFor(() => expect(at("selected")).toBe("ds1"));
    expect(localStorage.getItem(SELECTED_KEY)).toBe("ds1");
  });
});
