import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "../components/StatusBadge";

describe("StatusBadge 状态", () => {
  it("四种状态各自的文案与 data-status", () => {
    const cases = [
      ["ok", "正常"],
      ["error", "连接失败"],
      ["needs_reconfig", "需重新填写凭据"],
      ["unchecked", "未检查"],
    ] as const;
    for (const [status, text] of cases) {
      const { unmount } = render(<StatusBadge status={status} />);
      expect(screen.getByText(text)).toBeTruthy();
      expect(screen.getByTestId("status-dot").getAttribute("data-status")).toBe(status);
      unmount();
    }
  });

  it("状态点是装饰性的,状态靠文字表达(颜色不是唯一信息载体)", () => {
    render(<StatusBadge status="error" />);
    expect(screen.getByTestId("status-dot").getAttribute("aria-hidden")).toBe("true");
    expect(screen.getByText("连接失败")).toBeTruthy();
  });
});

describe("StatusBadge 写权限", () => {
  it("writable 挂只读账号警告", () => {
    render(<StatusBadge status="ok" writePrivilege="writable" />);
    const badge = screen.getByTestId("privilege-badge");
    expect(badge.textContent).toBe("建议改用只读账号");
    expect(badge.getAttribute("data-privilege")).toBe("writable");
  });

  it("unknown 挂中性的「写权限未知」", () => {
    render(<StatusBadge status="ok" writePrivilege="unknown" />);
    expect(screen.getByTestId("privilege-badge").textContent).toBe("写权限未知");
  });

  it("readonly 不挂任何权限徽标", () => {
    render(<StatusBadge status="ok" writePrivilege="readonly" />);
    expect(screen.queryByTestId("privilege-badge")).toBeNull();
  });

  it("writePrivilege 缺省或为 null 时不挂徽标", () => {
    const { unmount } = render(<StatusBadge status="ok" />);
    expect(screen.queryByTestId("privilege-badge")).toBeNull();
    unmount();
    render(<StatusBadge status="ok" writePrivilege={null} />);
    expect(screen.queryByTestId("privilege-badge")).toBeNull();
  });
});
