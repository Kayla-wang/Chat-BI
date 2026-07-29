import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataTable } from "../components/DataTable";
import type { Row } from "@chatbi/shared";

const columns = ["region", "total"];
const rows: Row[] = [{ region: "华东", total: 100 }, { region: "华北", total: 200 }];
const many = (n: number): Row[] =>
  Array.from({ length: n }, (_, i) => ({ region: `r${i}`, total: i }));

describe("DataTable", () => {
  it("渲染表头与数据", () => {
    render(<DataTable columns={columns} rows={rows} />);
    expect(screen.getByText("region")).toBeTruthy();
    expect(screen.getByText("华北")).toBeTruthy();
    expect(screen.getByText("200")).toBeTruthy();
  });

  it("summary 报告行列数", () => {
    render(<DataTable columns={columns} rows={rows} />);
    expect(screen.getByText("数据表格（2 行 × 2 列）")).toBeTruthy();
  });

  it("不超过 20 行默认展开", () => {
    render(<DataTable columns={columns} rows={many(20)} />);
    expect(screen.getByTestId("data-table").hasAttribute("open")).toBe(true);
  });

  it("超过 20 行默认收起", () => {
    render(<DataTable columns={columns} rows={many(21)} />);
    expect(screen.getByTestId("data-table").hasAttribute("open")).toBe(false);
  });

  it("超过上限只渲染前 100 行并提示剩余数量", () => {
    render(<DataTable columns={columns} rows={many(120)} />);
    expect(screen.getByText(/仅显示前 100 行/)).toBeTruthy();
    expect(screen.getByText(/另有 20 行未展示/)).toBeTruthy();
    expect(screen.queryByText("r119")).toBeNull();
    expect(screen.getByText("r99")).toBeTruthy();
  });

  it("maxRows 可覆盖", () => {
    render(<DataTable columns={columns} rows={many(5)} maxRows={2} />);
    expect(screen.queryByText("r4")).toBeNull();
    expect(screen.getByText(/另有 3 行未展示/)).toBeTruthy();
  });

  it("空结果集仍渲染表头,并报告 0 行", () => {
    render(<DataTable columns={columns} rows={[]} />);
    expect(screen.getByText("数据表格（0 行 × 2 列）")).toBeTruthy();
    expect(screen.getByText("region")).toBeTruthy();
  });

  it("null 单元格渲染为破折号", () => {
    render(<DataTable columns={columns} rows={[{ region: "华东", total: null }]} />);
    expect(screen.getByText("—")).toBeTruthy();
  });
});
