import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { TableSchema } from "@chatbi/shared";
import { SchemaTree } from "../components/SchemaTree";

const orders: TableSchema = {
  tableName: "orders",
  columns: [
    { name: "id", type: "INTEGER", notNull: true, pk: true },
    { name: "region", type: "TEXT", notNull: true, pk: false },
    { name: "amount", type: "REAL", notNull: false, pk: false },
  ],
  foreignKeys: [{ column: "region", refTable: "regions", refColumn: "code" }],
};
const regions: TableSchema = {
  tableName: "regions",
  columns: [{ name: "code", type: "TEXT", notNull: true, pk: true }],
  foreignKeys: [],
};

describe("SchemaTree", () => {
  it("列出每张表与它的列数", () => {
    render(<SchemaTree schema={[orders, regions]} />);
    expect(screen.getByText("orders")).toBeTruthy();
    expect(screen.getByText(/3 列/)).toBeTruthy();
    expect(screen.getByText("regions")).toBeTruthy();
  });

  it("展开一张表看到列名、类型与主键标记", () => {
    render(<SchemaTree schema={[orders]} />);
    fireEvent.click(screen.getByText("orders"));
    expect(screen.getByText("region")).toBeTruthy();
    expect(screen.getByText("TEXT", { selector: "td" })).toBeTruthy();
    expect(screen.getByTestId("pk-id").textContent).toContain("主键");
    expect(screen.getByTestId("notnull-region").textContent).toContain("非空");
  });

  it("外键渲染成 列 → 表.列", () => {
    render(<SchemaTree schema={[orders]} />);
    fireEvent.click(screen.getByText("orders"));
    expect(screen.getByText("region → regions.code")).toBeTruthy();
  });

  it("没有外键时不渲染外键区块", () => {
    render(<SchemaTree schema={[regions]} />);
    fireEvent.click(screen.getByText("regions"));
    expect(screen.queryByTestId("fk-list")).toBeNull();
  });

  it("空结构给出刷新引导", () => {
    render(<SchemaTree schema={[]} />);
    expect(screen.getByTestId("schema-empty").textContent).toContain("刷新结构");
  });

  it("fetchedAt 显示成不带时区的可读时间", () => {
    render(<SchemaTree schema={[regions]} fetchedAt="2026-08-03T10:20:30.000Z" />);
    expect(screen.getByTestId("schema-fetched-at").textContent).toContain("2026-08-03 10:20");
  });
});
