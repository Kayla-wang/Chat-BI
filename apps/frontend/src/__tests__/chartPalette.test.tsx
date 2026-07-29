import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  CHART_PALETTE_LIGHT, CHART_PALETTE_DARK, useChartPalette,
} from "../theme/chartPalette";

const stubMatchMedia = (matches: boolean) => {
  (window as any).matchMedia = vi.fn().mockReturnValue({
    matches, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  });
};

function Probe() {
  return <span data-testid="palette">{useChartPalette().join(",")}</span>;
}
const readPalette = () => {
  render(<Probe />);
  return screen.getByTestId("palette").textContent!.split(",");
};

afterEach(() => { delete (window as any).matchMedia; });

describe("调色板常量", () => {
  it("浅色与深色各 8 色", () => {
    expect(CHART_PALETTE_LIGHT).toHaveLength(8);
    expect(CHART_PALETTE_DARK).toHaveLength(8);
  });
  it("全部是 6 位十六进制", () => {
    for (const c of [...CHART_PALETTE_LIGHT, ...CHART_PALETTE_DARK]) {
      expect(c).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });
  it("同一档位的浅色与深色不同", () => {
    expect(CHART_PALETTE_LIGHT).not.toEqual(CHART_PALETTE_DARK);
  });
  it("色板内部无重复", () => {
    expect(new Set(CHART_PALETTE_LIGHT).size).toBe(8);
    expect(new Set(CHART_PALETTE_DARK).size).toBe(8);
  });
  it("不与语义色撞色(避免某条系列被误读为错误/成功)", () => {
    const semantic = ["#1a7f52", "#b42318", "#4fbf8b", "#f97066"];
    for (const s of semantic) {
      expect(CHART_PALETTE_LIGHT).not.toContain(s);
      expect(CHART_PALETTE_DARK).not.toContain(s);
    }
  });
});

describe("useChartPalette", () => {
  it("matchMedia 缺失时回落到浅色", () => {
    expect(readPalette()).toEqual(CHART_PALETTE_LIGHT);
  });
  it("深色偏好时返回深色板", () => {
    stubMatchMedia(true);
    expect(readPalette()).toEqual(CHART_PALETTE_DARK);
  });
  it("浅色偏好时返回浅色板", () => {
    stubMatchMedia(false);
    expect(readPalette()).toEqual(CHART_PALETTE_LIGHT);
  });
});
