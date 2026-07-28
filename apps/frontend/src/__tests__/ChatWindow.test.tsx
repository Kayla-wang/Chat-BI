import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ChatWindow } from "../components/ChatWindow";
import { streamChat } from "../api";
import type { StreamEvent } from "@chatbi/shared";

// ESM 下 require 不可用,按计划的备选方案用 vi.mock 工厂拦截 streamChat,
// 由测试自己驱动事件流。
vi.mock("../api", () => ({ streamChat: vi.fn() }));

let cb: ((e: StreamEvent) => void) | null = null;

beforeEach(() => {
  cb = null;
  vi.mocked(streamChat).mockImplementation((opts: any) => {
    cb = opts.onEvent;
    return Promise.resolve();
  });
});

describe("ChatWindow", () => {
  it("shows user question after submit", async () => {
    render(<ChatWindow />);
    fireEvent.change(screen.getByPlaceholderText(/输入问题/), { target: { value: "各地区销售额" } });
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));
    await waitFor(() => expect(screen.getByText("各地区销售额")).toBeTruthy());
  });
  it("streams explanation then shows table", async () => {
    render(<ChatWindow />);
    fireEvent.change(screen.getByPlaceholderText(/输入问题/), { target: { value: "q" } });
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));
    await waitFor(() => expect(cb).toBeTruthy());
    act(() => {
      cb!({ type: "explanationDelta", text: "按" });
      cb!({ type: "explanationDelta", text: "地区" });
      cb!({ type: "result", payload: { chartType: "bar", echartsOption: {}, table: { columns: ["region", "total"], rows: [{ region: "east", total: 100 }] }, explanation: "按地区" } });
    });
    await waitFor(() => expect(screen.getByText("按地区")).toBeTruthy());
    await waitFor(() => expect(screen.getByText("east")).toBeTruthy(), { timeout: 2000 });
  });
});
