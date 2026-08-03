import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AppShell } from "../components/AppShell";

describe("AppShell", () => {
  it("渲染产品名与 banner 语义", () => {
    render(<AppShell><div /></AppShell>);
    expect(screen.getByRole("banner")).toBeTruthy();
    expect(screen.getByText("Chat-BI")).toBeTruthy();
  });
  it("children 落在 main 区域", () => {
    render(<AppShell><p>内容</p></AppShell>);
    expect(screen.getByRole("main").textContent).toContain("内容");
  });
  it("顶栏右侧渲染传入的 toolbar", () => {
    render(<AppShell toolbar={<span>选择器</span>}><div /></AppShell>);
    expect(screen.getByTestId("datasource-slot").textContent).toBe("选择器");
  });
});
