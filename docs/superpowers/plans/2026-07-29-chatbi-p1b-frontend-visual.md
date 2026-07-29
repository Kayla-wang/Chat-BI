# Chat-BI P1b 前端与视觉 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P1a 留下的裸 inline style 前端换成一套真正的设计系统:CSS 变量 + CSS Modules、深浅色两套值、色觉障碍下可区分的图表调色板,并把 `ResultCard` 拆成职责单一的小组件。

**Architecture:** 颜色/字号/间距全部收进 `theme/tokens.css` 的 CSS 变量,组件里不写任何颜色字面量;深浅色靠 `prefers-color-scheme` 切换同名变量的值。图表调色板是 TS 常量(ECharts 需要显式色值数组,吃不到 CSS 变量),由 `useChartPalette` 钩子跟随深浅色返回对应数组。`ResultCard` 从「一个文件干四件事」拆成容器 + `ChartView` / `SqlDisclosure` / `InsightPanel` / `DataTable`。

**Tech Stack:** React 18 + TypeScript + Vite 5(CSS Modules 原生支持,不引入 Tailwind)+ ECharts 5 + Vitest + React Testing Library。

## Global Constraints

- 前置条件:**P1a 已全部完成并合并**。本计划依赖 P1a 定下的 `ChartSpec` / `InsightFact` / `ResultPayload` 契约与 `specToEchartsOption` / `renderFactsLines`。
- 设计文档:`docs/superpowers/specs/2026-07-28-chatbi-p1-analysis-loop-design.md` 第 6 节。
- **不引入 Tailwind 或任何 CSS 框架**;用 Vite 原生的 CSS Modules + CSS 变量。
- **组件里不写颜色字面量**,一律引用 `var(--*)`。唯一例外是 `theme/chartPalette.ts`——ECharts 的 `color` 配置需要真实色值数组。
- 数字一律 `font-variant-numeric: tabular-nums`(表格、坐标轴、洞察里的数值)。
- 间距用 4px 基准的 6 档:`--sp-1` 4px、`--sp-2` 8px、`--sp-3` 12px、`--sp-4` 16px、`--sp-5` 24px、`--sp-6` 32px。
- 深浅色各一套变量值,通过 `@media (prefers-color-scheme: dark)` 切换;不做手动切换开关(P1 不引入偏好持久化)。
- **涨跌不上色**:洞察与图表统一用中性 `--accent`,涨跌只靠文字表达。`--positive` / `--negative` 仅用于「错误」「成功」这类状态提示,不用于表达数据方向。
- 图表调色板取 **Okabe-Ito** 色觉友好色系派生,浅色 8 色 + 深色 8 色。
- **不改任何后端文件**,不改 `packages/shared`,不改 `api.ts` 的请求契约。
- 每个 Task 以 TDD 五步推进(写失败测试 → 跑红 → 实现 → 跑绿 → 提交)。断言样式时**只断言结构与语义**(role、aria、data-testid、类名是否挂上),不断言具体像素值。
- 提交信息英文,前缀 `feat:` / `refactor:` / `style:` / `test:` / `chore:`。
- 工作分支沿用 `p1-analysis-loop`。

---

## File Structure

```
apps/frontend/
├─ tsconfig.json               # 修改:加 "types": ["vite/client"] 让 TS 认识 *.module.css
├─ index.html                  # 修改:补 lang / meta color-scheme
└─ src/
   ├─ main.tsx                 # 修改:import 全局样式
   ├─ App.tsx                  # 修改:渲染 AppShell
   ├─ theme/
   │  ├─ tokens.css            # 新增:CSS 变量(色/字/间距/圆角/阴影),含深色覆盖
   │  ├─ global.css            # 新增:reset + base 排版 + tabular-nums
   │  └─ chartPalette.ts       # 新增:浅/深两套 8 色 + useChartPalette
   └─ components/
      ├─ AppShell.tsx          # 新增:顶栏 + 布局容器
      ├─ AppShell.module.css
      ├─ ChatWindow.tsx        # 修改:去掉 inline style,套 CSS Modules
      ├─ ChatWindow.module.css
      ├─ MessageBubble.tsx     # 修改:用户/助手气泡区分
      ├─ MessageBubble.module.css
      ├─ ResultCard.tsx        # 修改:只做容器 + segmented control
      ├─ ResultCard.module.css
      ├─ ChartView.tsx         # 新增:ECharts 生命周期 + resize(notes 留在 ResultCard)
      ├─ ChartView.module.css
      ├─ SqlDisclosure.tsx     # 新增:SQL 折叠
      ├─ SqlDisclosure.module.css
      ├─ InsightPanel.tsx      # 修改:样式化,事实列表拆出去
      ├─ InsightPanel.module.css  # FactList 复用同一个样式表
      ├─ FactList.tsx          # 新增:计算依据列表
      ├─ DataTable.tsx         # 新增:折叠表格 + 前 100 行截断提示
      └─ DataTable.module.css
```

**测试文件**沿用 `apps/frontend/src/__tests__/`,新增 `ChartView.test.tsx`、`DataTable.test.tsx`、`SqlDisclosure.test.tsx`、`chartPalette.test.tsx`、`AppShell.test.tsx`。

P1a 已有的 `InsightPanel.test.tsx` / `ChatWindow.test.tsx` / `api.test.ts` **一条断言都不改就应通过**——这是本计划没把行为改坏的主要证据。唯一需要改的是 `ResultCard.test.tsx`:图表类型按钮的可见文案从 `bar/line/pie/table` 改成中文「柱状/折线/饼图/表格」,所以按名字取按钮的选择器要跟着改。这是文案变化,不是行为变化;Task 5 会逐条说明改哪几行。

---

### Task 1: 设计 tokens + 全局样式 + AppShell

**Files:**
- Create: `apps/frontend/src/theme/tokens.css`
- Create: `apps/frontend/src/theme/global.css`
- Create: `apps/frontend/src/components/AppShell.tsx`
- Create: `apps/frontend/src/components/AppShell.module.css`
- Modify: `apps/frontend/tsconfig.json`(加 `types: ["vite/client"]`)
- Modify: `apps/frontend/src/main.tsx`(import 全局样式)
- Modify: `apps/frontend/src/App.tsx`
- Modify: `apps/frontend/index.html`(`lang` + `color-scheme`)
- Test: `apps/frontend/src/__tests__/AppShell.test.tsx`

**Interfaces:**
- Consumes: P1a 的 `ChatWindow`
- Produces: `AppShell({ children }: { children: ReactNode })`;全套 CSS 变量(下面列全)

**为什么先做 tokens**:后面 6 个任务的每个 `*.module.css` 都要引用这些变量。变量名一旦定下就不该再改,所以第一个任务把名字全部固定。

**CSS Modules 的 TS 支持**:Vite 自带 `vite/client` 类型声明,里面有 `*.module.css` 的模块声明。加到 `tsconfig.json` 的 `types` 里就够,不用自己写 `.d.ts`。Vitest 默认对 `.module.css` 返回一个按 key 回显的代理对象,所以测试里 `styles.foo` 有值但不会真的应用样式——这正好,我们只断言结构。

- [ ] **Step 1: 写失败测试 `apps/frontend/src/__tests__/AppShell.test.tsx`**

```tsx
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
  it("顶栏右侧留了数据源占位", () => {
    render(<AppShell><div /></AppShell>);
    expect(screen.getByTestId("datasource-slot")).toBeTruthy();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/frontend run src/__tests__/AppShell.test.tsx`
Expected: FAIL，`Failed to resolve import "../components/AppShell"`

- [ ] **Step 3: 创建 `apps/frontend/src/theme/tokens.css`**

```css
:root {
  color-scheme: light dark;

  /* 中性色阶 */
  --bg: #f7f8fa;
  --surface: #ffffff;
  --surface-raised: #ffffff;
  --border: #e3e6eb;
  --border-strong: #c9cfd8;
  --text: #1c2128;
  --text-muted: #6b7280;

  /* 语义色。注意:positive / negative 只用于状态提示,不用于表达数据涨跌。 */
  --accent: #0072b2;
  --accent-weak: #e6f1f9;
  --positive: #1a7f52;
  --negative: #b42318;
  --warning: #b45309;

  /* 排版 */
  --font-sans: system-ui, -apple-system, "Segoe UI", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "Cascadia Mono", Consolas, monospace;
  --fs-xs: 12px;
  --fs-sm: 13px;
  --fs-md: 14px;
  --fs-lg: 16px;
  --fs-xl: 20px;
  --lh-tight: 1.35;
  --lh-normal: 1.6;

  /* 间距:4px 基准 6 档 */
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 24px;
  --sp-6: 32px;

  /* 圆角与阴影各 2 档 */
  --radius-sm: 6px;
  --radius-md: 10px;
  --shadow-sm: 0 1px 2px rgba(16, 24, 40, 0.06);
  --shadow-md: 0 4px 16px rgba(16, 24, 40, 0.1);
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171c;
    --surface: #1b1f26;
    --surface-raised: #22272f;
    --border: #2c333d;
    --border-strong: #3d4653;
    --text: #e6e9ee;
    --text-muted: #9aa4b2;

    --accent: #56b4e9;
    --accent-weak: #1d2b36;
    --positive: #4fbf8b;
    --negative: #f97066;
    --warning: #f5a524;

    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4);
    --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.5);
  }
}
```

- [ ] **Step 4: 创建 `apps/frontend/src/theme/global.css`**

```css
@import "./tokens.css";

*, *::before, *::after { box-sizing: border-box; }

html, body, #root { height: 100%; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: var(--fs-md);
  line-height: var(--lh-normal);
  -webkit-font-smoothing: antialiased;
}

/* BI 界面的数字必须等宽对齐:表格列、坐标轴、洞察里的数值 */
table, pre, code, [data-numeric] {
  font-variant-numeric: tabular-nums;
}

h1, h2, h3 { margin: 0; line-height: var(--lh-tight); font-weight: 600; }

button {
  font: inherit;
  color: inherit;
  cursor: pointer;
}
button:disabled { cursor: not-allowed; opacity: 0.55; }

input { font: inherit; }

:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

summary { cursor: pointer; }
```

- [ ] **Step 5: 创建 `apps/frontend/src/components/AppShell.module.css`**

```css
.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.brand {
  font-size: var(--fs-lg);
  letter-spacing: 0.01em;
}

.slot {
  font-size: var(--fs-xs);
  color: var(--text-muted);
}

.main {
  flex: 1;
  min-height: 0;
  width: 100%;
  max-width: 960px;
  margin: 0 auto;
  padding: 0 var(--sp-4);
  display: flex;
  flex-direction: column;
}
```

- [ ] **Step 6: 创建 `apps/frontend/src/components/AppShell.tsx`**

```tsx
import type { ReactNode } from "react";
import styles from "./AppShell.module.css";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <h1 className={styles.brand}>Chat-BI</h1>
        {/* P2 的数据源切换入口先占位 */}
        <span className={styles.slot} data-testid="datasource-slot">示例库 · SQLite</span>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
```

- [ ] **Step 7: 接线**

`apps/frontend/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "jsx": "react-jsx",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "types": ["vite/client"]
  },
  "include": ["src"]
}
```

`apps/frontend/src/main.tsx` 顶部加一行 import:

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import "./theme/global.css";
import { App } from "./App";
createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
```

`apps/frontend/src/App.tsx` 全量替换:

```tsx
import { AppShell } from "./components/AppShell";
import { ChatWindow } from "./components/ChatWindow";

export const App = () => <AppShell><ChatWindow /></AppShell>;
```

`apps/frontend/index.html`:`<html lang="zh-CN">`,`<head>` 里加 `<meta name="color-scheme" content="light dark" />`。

- [ ] **Step 8: 跑测试确认通过**

Run: `npx vitest --root apps/frontend run`
Expected: 全绿。`ChatWindow.test.tsx` 直接渲染 `ChatWindow` 而不经过 `AppShell`,所以不受影响;但它断言的 `getByText("Chat-BI")` 会失败——因为标题已移到 `AppShell`。把 `ChatWindow` 里的 `<h1>Chat-BI</h1>` 删掉(Task 6 会重写这个文件,这里先删标题即可),并删掉 `ChatWindow.test.tsx` 里对标题的断言(P1a 版本没有这条断言,若确实没有则无需改动)。

- [ ] **Step 9: 提交**

```bash
git add apps/frontend/src/theme apps/frontend/src/components/AppShell.tsx \
  apps/frontend/src/components/AppShell.module.css apps/frontend/src/__tests__/AppShell.test.tsx \
  apps/frontend/tsconfig.json apps/frontend/src/main.tsx apps/frontend/src/App.tsx apps/frontend/index.html
git commit -m "feat(frontend): design tokens, global styles and app shell"
```

### Task 2: 图表调色板 + ChartView 提取

**Files:**
- Create: `apps/frontend/src/theme/chartPalette.ts`
- Create: `apps/frontend/src/components/ChartView.tsx`
- Create: `apps/frontend/src/components/ChartView.module.css`
- Test: `apps/frontend/src/__tests__/chartPalette.test.tsx`
- Test: `apps/frontend/src/__tests__/ChartView.test.tsx`

**Interfaces:**
- Consumes: P1a 的 `ChartSpec` 与 `specToEchartsOption`
- Produces:
  - `CHART_PALETTE_LIGHT: string[]`、`CHART_PALETTE_DARK: string[]`(各 8 色)
  - `useChartPalette(): string[]`
  - `ChartView({ spec }: { spec: ChartSpec })`

**调色板取 Okabe-Ito 派生。** Okabe-Ito 是公开的色觉障碍友好色系(deuteranopia / protanopia 下相邻色仍可区分)。原色系里的纯黑和亮黄在深/浅底上各有一个不可用,所以两套各自替换掉那两个位置:浅色把黄换成中性灰、深色把黑换成浅灰。

**调色板必须是 TS 常量而不是 CSS 变量**:ECharts 的 `color` 配置要真实色值数组,读不到 `var(--*)`。深浅色切换靠 `useChartPalette` 监听 `prefers-color-scheme` 返回不同数组。

**jsdom 里没有 `matchMedia`**,所以 `useChartPalette` 必须对它缺失的情况有兜底(默认浅色),否则所有渲染 `ChartView` 的测试都会崩。

- [ ] **Step 1: 写失败测试 `apps/frontend/src/__tests__/chartPalette.test.tsx`**

用一个探针组件读钩子返回值,不依赖 `@testing-library/react` 的 `renderHook`(不同大版本导出位置不一样,探针在所有版本都work)。文件后缀因此是 `.tsx`。

```tsx
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
```

文件名用 `chartPalette.test.tsx`(含 JSX),`Files` 一节里的路径也按这个改。

- [ ] **Step 2: 写失败测试 `apps/frontend/src/__tests__/ChartView.test.tsx`**

`echarts` 整个 mock 掉,这样能直接断言传给 `setOption` 的 option。

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ChartSpec } from "@chatbi/shared";
import { ChartView } from "../components/ChartView";
import { CHART_PALETTE_LIGHT } from "../theme/chartPalette";

const setOption = vi.fn();
const dispose = vi.fn();
const resize = vi.fn();

vi.mock("echarts", () => ({
  init: vi.fn(() => ({ setOption, dispose, resize })),
}));

beforeEach(() => { setOption.mockClear(); dispose.mockClear(); });

const spec: ChartSpec = {
  chartType: "bar", stack: "none",
  x: { field: "region", role: "categorical", labels: ["华东", "华北"] },
  series: [{
    name: "amount", field: "amount", data: [100, 200],
    format: { kind: "currency", decimals: 0, unit: "元", scale: 1 },
  }],
  notes: [],
};

describe("ChartView", () => {
  it("渲染图表容器", () => {
    render(<ChartView spec={spec} />);
    expect(screen.getByTestId("chart")).toBeTruthy();
  });

  it("把 spec 与浅色调色板交给 specToEchartsOption 的结果传给 setOption", () => {
    render(<ChartView spec={spec} />);
    const option = setOption.mock.calls[0][0];
    expect(option.color).toEqual(CHART_PALETTE_LIGHT);
    expect(option.series[0].type).toBe("bar");
    expect(option.xAxis.data).toEqual(["华东", "华北"]);
  });

  it("卸载时 dispose", () => {
    const { unmount } = render(<ChartView spec={spec} />);
    unmount();
    expect(dispose).toHaveBeenCalled();
  });

  it("spec 变化时重新 setOption", () => {
    const { rerender } = render(<ChartView spec={spec} />);
    rerender(<ChartView spec={{ ...spec, chartType: "line" }} />);
    expect(setOption.mock.calls.at(-1)![0].series[0].type).toBe("line");
  });

  it("window resize 时调用 chart.resize", () => {
    render(<ChartView spec={spec} />);
    resize.mockClear();
    window.dispatchEvent(new Event("resize"));
    expect(resize).toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: 跑测试确认失败**

Run: `npx vitest --root apps/frontend run src/__tests__/chartPalette.test.tsx src/__tests__/ChartView.test.tsx`
Expected: FAIL，两个 `Failed to resolve import`

- [ ] **Step 4: 创建 `apps/frontend/src/theme/chartPalette.ts`**

```ts
import { useEffect, useState } from "react";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/**
 * Okabe-Ito 色觉友好色系派生。
 * 浅色底:去掉原色系里的亮黄(#f0e442,浅底对比度不足),末位换成中性灰。
 * 深色底:去掉原色系里的纯黑,整体提亮。
 */
export const CHART_PALETTE_LIGHT = [
  "#0072b2", "#d55e00", "#009e73", "#cc79a7",
  "#56b4e9", "#e69f00", "#8b6bb1", "#4d4d4d",
];

export const CHART_PALETTE_DARK = [
  "#56b4e9", "#e69f00", "#00b888", "#f49ac2",
  "#9fd8f5", "#ffb861", "#b79ce0", "#bfbfbf",
];

function prefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(DARK_QUERY).matches;
}

export function useChartPalette(): string[] {
  const [dark, setDark] = useState(prefersDark);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = () => setDark(mq.matches);
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);

  return dark ? CHART_PALETTE_DARK : CHART_PALETTE_LIGHT;
}
```

- [ ] **Step 5: 创建 `apps/frontend/src/components/ChartView.module.css`**

```css
.canvas {
  width: 100%;
  height: 320px;
}
```

- [ ] **Step 6: 创建 `apps/frontend/src/components/ChartView.tsx`**

```tsx
import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import type { ChartSpec } from "@chatbi/shared";
import { specToEchartsOption } from "@chatbi/shared";
import { useChartPalette } from "../theme/chartPalette";
import styles from "./ChartView.module.css";

export function ChartView({ spec }: { spec: ChartSpec }) {
  const palette = useChartPalette();
  const ref = useRef<HTMLDivElement>(null);
  const option = useMemo(() => specToEchartsOption(spec, palette), [spec, palette]);

  useEffect(() => {
    if (!ref.current) return;
    let chart: echarts.ECharts | undefined;
    try {
      chart = echarts.init(ref.current);
      chart.setOption(option as echarts.EChartsOption, true);
    } catch { /* jsdom 无 canvas:忽略 */ }

    const onResize = () => { try { chart?.resize(); } catch { /* 同上 */ } };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      try { chart?.dispose(); } catch { /* 同上 */ }
    };
  }, [option]);

  return <div ref={ref} className={styles.canvas} data-testid="chart" />;
}
```

- [ ] **Step 7: 跑测试确认通过**

Run: `npx vitest --root apps/frontend run src/__tests__/chartPalette.test.tsx src/__tests__/ChartView.test.tsx`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add apps/frontend/src/theme/chartPalette.ts apps/frontend/src/components/ChartView.tsx \
  apps/frontend/src/components/ChartView.module.css \
  apps/frontend/src/__tests__/chartPalette.test.tsx apps/frontend/src/__tests__/ChartView.test.tsx
git commit -m "feat(frontend): colorblind-safe chart palette and extracted ChartView"
```

### Task 3: SqlDisclosure 与 DataTable 提取

**Files:**
- Create: `apps/frontend/src/components/SqlDisclosure.tsx`
- Create: `apps/frontend/src/components/SqlDisclosure.module.css`
- Create: `apps/frontend/src/components/DataTable.tsx`
- Create: `apps/frontend/src/components/DataTable.module.css`
- Test: `apps/frontend/src/__tests__/SqlDisclosure.test.tsx`
- Test: `apps/frontend/src/__tests__/DataTable.test.tsx`

**Interfaces:**
- Consumes: P1a 的 `Row`
- Produces:
  - `SqlDisclosure({ sql }: { sql: string })`
  - `DataTable({ columns, rows, maxRows }: { columns: string[]; rows: Row[]; maxRows?: number })`,`maxRows` 默认 100
  - `export const MAX_TABLE_ROWS = 100`(从 `ResultCard` 挪过来,Task 5 会删掉那边的副本)

**折叠默认状态的规则**:`DataTable` 在 `rows.length <= 20` 时默认展开,超过则默认收起。小结果集用户想直接看数字,大结果集展开会把图表挤出视野。`SqlDisclosure` 一律默认收起——它是核对用的,不是主线信息。

- [ ] **Step 1: 写失败测试 `apps/frontend/src/__tests__/SqlDisclosure.test.tsx`**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SqlDisclosure } from "../components/SqlDisclosure";

const SQL = "SELECT region, SUM(total_amount) AS amount FROM orders GROUP BY region";

describe("SqlDisclosure", () => {
  it("summary 是「查看 SQL」", () => {
    render(<SqlDisclosure sql={SQL} />);
    expect(screen.getByText("查看 SQL")).toBeTruthy();
  });
  it("默认收起", () => {
    render(<SqlDisclosure sql={SQL} />);
    expect(screen.getByTestId("sql-disclosure").hasAttribute("open")).toBe(false);
  });
  it("SQL 原文在 DOM 里,可被核对", () => {
    render(<SqlDisclosure sql={SQL} />);
    expect(screen.getByText(/GROUP BY region/)).toBeTruthy();
  });
  it("空 SQL 时不渲染", () => {
    const { container } = render(<SqlDisclosure sql="" />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: 写失败测试 `apps/frontend/src/__tests__/DataTable.test.tsx`**

```tsx
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
```

- [ ] **Step 3: 跑测试确认失败**

Run: `npx vitest --root apps/frontend run src/__tests__/SqlDisclosure.test.tsx src/__tests__/DataTable.test.tsx`
Expected: FAIL，两个 `Failed to resolve import`

- [ ] **Step 4: 创建 `apps/frontend/src/components/SqlDisclosure.module.css`**

```css
.wrap {
  margin-top: var(--sp-3);
  font-size: var(--fs-sm);
}

.summary {
  color: var(--text-muted);
  padding: var(--sp-1) 0;
}
.summary:hover { color: var(--text); }

.code {
  margin: var(--sp-2) 0 0;
  padding: var(--sp-3);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  line-height: var(--lh-normal);
  white-space: pre-wrap;
  overflow-x: auto;
}
```

- [ ] **Step 5: 创建 `apps/frontend/src/components/SqlDisclosure.tsx`**

```tsx
import styles from "./SqlDisclosure.module.css";

export function SqlDisclosure({ sql }: { sql: string }) {
  if (!sql) return null;
  return (
    <details className={styles.wrap} data-testid="sql-disclosure">
      <summary className={styles.summary}>查看 SQL</summary>
      <pre className={styles.code}>{sql}</pre>
    </details>
  );
}
```

- [ ] **Step 6: 创建 `apps/frontend/src/components/DataTable.module.css`**

```css
.wrap {
  margin-top: var(--sp-3);
}

.summary {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  padding: var(--sp-1) 0;
}
.summary:hover { color: var(--text); }

.scroll {
  margin-top: var(--sp-2);
  max-height: 320px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}

.table th,
.table td {
  padding: var(--sp-2) var(--sp-3);
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.table th {
  position: sticky;
  top: 0;
  background: var(--surface-raised);
  color: var(--text-muted);
  font-weight: 600;
  font-size: var(--fs-xs);
  letter-spacing: 0.02em;
}

.table tbody tr:last-child td { border-bottom: none; }

.numeric { text-align: right; }

.hint {
  margin: var(--sp-2) 0 0;
  color: var(--text-muted);
  font-size: var(--fs-xs);
}
```

- [ ] **Step 7: 创建 `apps/frontend/src/components/DataTable.tsx`**

```tsx
import type { Row } from "@chatbi/shared";
import styles from "./DataTable.module.css";

export const MAX_TABLE_ROWS = 100;
const DEFAULT_OPEN_THRESHOLD = 20;

const cell = (v: Row[string]) =>
  v === null || v === undefined ? "—" : String(v);

export function DataTable({ columns, rows, maxRows = MAX_TABLE_ROWS }: {
  columns: string[]; rows: Row[]; maxRows?: number;
}) {
  const shown = rows.slice(0, maxRows);
  const hidden = rows.length - shown.length;

  return (
    <details
      className={styles.wrap}
      data-testid="data-table"
      open={rows.length <= DEFAULT_OPEN_THRESHOLD}
    >
      <summary className={styles.summary}>
        数据表格（{rows.length} 行 × {columns.length} 列）
      </summary>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr>{columns.map(c => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i}>
                {columns.map(c => {
                  const v = r[c];
                  const numeric = typeof v === "number";
                  return (
                    <td key={c} className={numeric ? styles.numeric : undefined} data-numeric={numeric || undefined}>
                      {cell(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hidden > 0 && (
        <p className={styles.hint}>仅显示前 {maxRows} 行,另有 {hidden} 行未展示</p>
      )}
    </details>
  );
}
```

- [ ] **Step 8: 跑测试确认通过**

Run: `npx vitest --root apps/frontend run src/__tests__/SqlDisclosure.test.tsx src/__tests__/DataTable.test.tsx`
Expected: PASS。`ResultCard.test.tsx` 此时还在用自己那份表格实现,仍应通过;Task 5 才切换过去。

- [ ] **Step 9: 提交**

```bash
git add apps/frontend/src/components/SqlDisclosure.tsx apps/frontend/src/components/SqlDisclosure.module.css \
  apps/frontend/src/components/DataTable.tsx apps/frontend/src/components/DataTable.module.css \
  apps/frontend/src/__tests__/SqlDisclosure.test.tsx apps/frontend/src/__tests__/DataTable.test.tsx
git commit -m "feat(frontend): extract SqlDisclosure and DataTable with sticky header"
```

### Task 4: InsightPanel 样式化 + FactList 提取

**Files:**
- Create: `apps/frontend/src/components/FactList.tsx`
- Create: `apps/frontend/src/components/InsightPanel.module.css`
- Modify: `apps/frontend/src/components/InsightPanel.tsx`(全量替换)
- Modify: `apps/frontend/src/__tests__/InsightPanel.test.tsx`(**追加**用例,P1a 的 5 个用例全部保留且仍应通过)

**Interfaces:**
- Consumes: P1a 的 `InsightFact` `ValueFormat` `renderFactsLines`
- Produces:
  - `FactList({ facts, format }: { facts: InsightFact[]; format?: ValueFormat })`
  - `InsightPanel({ text, facts, format }: { text: string; facts: InsightFact[]; format?: ValueFormat })`(签名不变)

**行为完全不变**,只是把事实列表挪进 `FactList` 并套上样式。P1a 那 5 个用例是这次重构没改坏行为的证据,一条都不许改。

**`DEFAULT_FORMAT` 跟着搬进 `FactList`**,`InsightPanel` 只负责透传 `format`。

- [ ] **Step 1: 追加失败测试到 `apps/frontend/src/__tests__/InsightPanel.test.tsx`**

文件末尾追加,并在顶部补 `import { FactList } from "../components/FactList";`:

```tsx
describe("FactList", () => {
  it("逐条渲染,summary 报告项数", () => {
    render(<FactList facts={facts} format={CURRENCY} />);
    expect(screen.getByText("计算依据（2 项）")).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
  it("默认收起", () => {
    render(<FactList facts={facts} format={CURRENCY} />);
    expect(screen.getByTestId("fact-list").hasAttribute("open")).toBe(false);
  });
  it("没有事实时不渲染", () => {
    const { container } = render(<FactList facts={[]} format={CURRENCY} />);
    expect(container.firstChild).toBeNull();
  });
  it("不传 format 时按普通数值渲染", () => {
    render(<FactList facts={[{ kind: "total", series: "s", value: 1234 }]} />);
    expect(screen.getByText(/1,234/)).toBeTruthy();
  });
});

describe("InsightPanel 结构", () => {
  it("标题是「洞察」", () => {
    render(<InsightPanel text="x" facts={[]} format={CURRENCY} />);
    expect(screen.getByRole("heading", { name: "洞察" })).toBeTruthy();
  });
  it("洞察区是独立的 region,便于屏幕阅读器跳转", () => {
    render(<InsightPanel text="x" facts={[]} format={CURRENCY} />);
    expect(screen.getByRole("region", { name: "洞察" })).toBeTruthy();
  });
  it("format 透传给 FactList", () => {
    render(<InsightPanel text="x" facts={[{ kind: "total", series: "s", value: 128400 }]} format={CURRENCY} />);
    expect(screen.getByText(/128,400 元/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/frontend run src/__tests__/InsightPanel.test.tsx`
Expected: FAIL，`Failed to resolve import "../components/FactList"`

- [ ] **Step 3: 创建 `apps/frontend/src/components/FactList.tsx`**

```tsx
import type { InsightFact, ValueFormat } from "@chatbi/shared";
import { renderFactsLines } from "@chatbi/shared";
import styles from "./InsightPanel.module.css";

const DEFAULT_FORMAT: ValueFormat = { kind: "number", decimals: 0, scale: 1 };

export function FactList({ facts, format }: {
  facts: InsightFact[]; format?: ValueFormat;
}) {
  const lines = renderFactsLines(facts, format ?? DEFAULT_FORMAT).filter(Boolean);
  if (lines.length === 0) return null;
  return (
    <details className={styles.facts} data-testid="fact-list">
      <summary className={styles.factsSummary}>计算依据（{lines.length} 项）</summary>
      <ul className={styles.factItems}>
        {lines.map(l => <li key={l} data-numeric>{l}</li>)}
      </ul>
    </details>
  );
}
```

- [ ] **Step 4: 创建 `apps/frontend/src/components/InsightPanel.module.css`**

```css
.panel {
  margin-top: var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  background: var(--accent-weak);
  border-left: 3px solid var(--accent);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

.title {
  font-size: var(--fs-xs);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: var(--sp-2);
}

.text {
  margin: 0;
  font-size: var(--fs-md);
  line-height: var(--lh-normal);
  white-space: pre-wrap;
  font-variant-numeric: tabular-nums;
}

.facts {
  margin-top: var(--sp-3);
  font-size: var(--fs-sm);
}

.factsSummary {
  color: var(--text-muted);
}
.factsSummary:hover { color: var(--text); }

.factItems {
  margin: var(--sp-2) 0 0;
  padding-left: var(--sp-5);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-normal);
}
```

- [ ] **Step 5: 全量替换 `apps/frontend/src/components/InsightPanel.tsx`**

```tsx
import type { InsightFact, ValueFormat } from "@chatbi/shared";
import { FactList } from "./FactList";
import styles from "./InsightPanel.module.css";

export function InsightPanel({ text, facts, format }: {
  text: string; facts: InsightFact[]; format?: ValueFormat;
}) {
  if (!text && facts.length === 0) return null;
  return (
    <section className={styles.panel} aria-label="洞察">
      <h3 className={styles.title}>洞察</h3>
      <p className={styles.text} data-testid="insight-text">{text}</p>
      <FactList facts={facts} format={format} />
    </section>
  );
}
```

- [ ] **Step 6: 跑测试确认通过**

Run: `npx vitest --root apps/frontend run src/__tests__/InsightPanel.test.tsx src/__tests__/ResultCard.test.tsx`
Expected: PASS。P1a 那 5 个用例一条都不该改动就通过——如果需要改,说明重构改了行为,回退重做。

`aria-label="洞察"` 让 `<section>` 拿到 `region` role,同时 `<h3>` 仍是 `heading`,两个查询都能命中。

- [ ] **Step 7: 提交**

```bash
git add apps/frontend/src/components/InsightPanel.tsx apps/frontend/src/components/InsightPanel.module.css \
  apps/frontend/src/components/FactList.tsx apps/frontend/src/__tests__/InsightPanel.test.tsx
git commit -m "refactor(frontend): style insight panel and extract FactList"
```

### Task 5: ResultCard 重组为容器 + segmented control

**Files:**
- Modify: `apps/frontend/src/components/ResultCard.tsx`(全量替换)
- Create: `apps/frontend/src/components/ResultCard.module.css`
- Modify: `apps/frontend/src/__tests__/ResultCard.test.tsx`(只改按钮选择器与新增两条断言)

**Interfaces:**
- Consumes: Task 2 的 `ChartView`、Task 3 的 `SqlDisclosure` / `DataTable`、Task 4 的 `InsightPanel`
- Produces: `ResultCard({ payload, insight, facts }: { payload: ResultPayload; insight: string; facts: InsightFact[] })`(签名不变)

**`ResultCard` 从 100 多行缩到只做三件事**:持有当前图表类型、按类型覆盖 `spec`、把四个子组件按顺序摆好。ECharts 生命周期、表格、SQL、洞察全部不再是它的事。

**按钮保留 `<button aria-pressed>` 语义**,只是视觉上做成 segmented control。不换成 `role="radiogroup"`——`aria-pressed` 的切换语义更贴近「这是个视图开关」,而且 P1a 的断言方式可以继续用。

**可见文案改中文**:`折线 / 柱状 / 饼图 / 表格`,顺序按设计文档的 mockup。这会让 P1a 里 `getByRole("button", { name: /bar/i })` 这类选择器失配,Step 1 逐条改。

- [ ] **Step 1: 改 `apps/frontend/src/__tests__/ResultCard.test.tsx` 的选择器**

只做这几处替换,其余断言原样保留:

| 原来 | 改成 |
|---|---|
| `{ name: /bar/i }` | `{ name: "柱状" }` |
| `{ name: /line/i }` | `{ name: "折线" }` |
| `{ name: /pie/i }` | `{ name: "饼图" }` |
| `{ name: /table/i }` | `{ name: "表格" }` |

并追加两条断言,确认子组件确实被用上了(而不是 `ResultCard` 里还留着自己的实现):

```tsx
describe("ResultCard 组合子组件", () => {
  it("表格由 DataTable 渲染", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    expect(screen.getByTestId("data-table")).toBeTruthy();
  });
  it("SQL 由 SqlDisclosure 渲染", () => {
    render(<ResultCard payload={payload()} insight="" facts={[]} />);
    expect(screen.getByTestId("sql-disclosure")).toBeTruthy();
  });
});
```

注意 P1a 那条「超过 100 行只渲染前 100 行并提示」的用例现在由 `DataTable` 承担实现,断言文案不变,仍应通过。

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/frontend run src/__tests__/ResultCard.test.tsx`
Expected: FAIL，`Unable to find an accessible element with the role "button" and name "柱状"`

- [ ] **Step 3: 创建 `apps/frontend/src/components/ResultCard.module.css`**

```css
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  padding: var(--sp-4);
  margin-top: var(--sp-2);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
}

/* segmented control:一组按钮拼成一条,只有外框和分隔线 */
.segmented {
  display: inline-flex;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.segment {
  border: none;
  background: var(--surface);
  color: var(--text-muted);
  padding: var(--sp-1) var(--sp-3);
  font-size: var(--fs-sm);
  line-height: 1.8;
}

.segment + .segment {
  border-left: 1px solid var(--border);
}

.segment:hover {
  background: var(--bg);
  color: var(--text);
}

.segment[aria-pressed="true"] {
  background: var(--accent);
  color: #ffffff;
  font-weight: 600;
}

.notes {
  margin: var(--sp-2) 0 0;
  padding: 0;
  list-style: none;
}

.note {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-normal);
}
```

`.segment[aria-pressed="true"]` 里的 `#ffffff` 是本计划里唯一允许的颜色字面量:选中态文字要在 `--accent` 上保证对比度,深浅色两套 accent 都是中等深度的蓝,白字在两者上都够。

- [ ] **Step 4: 全量替换 `apps/frontend/src/components/ResultCard.tsx`**

```tsx
import { useMemo, useState } from "react";
import type { ChartType, InsightFact, ResultPayload } from "@chatbi/shared";
import { ChartView } from "./ChartView";
import { SqlDisclosure } from "./SqlDisclosure";
import { InsightPanel } from "./InsightPanel";
import { DataTable } from "./DataTable";
import styles from "./ResultCard.module.css";

const TYPES: { type: ChartType; label: string }[] = [
  { type: "line", label: "折线" },
  { type: "bar", label: "柱状" },
  { type: "pie", label: "饼图" },
  { type: "table", label: "表格" },
];

export function ResultCard({ payload, insight, facts }: {
  payload: ResultPayload; insight: string; facts: InsightFact[];
}) {
  const [type, setType] = useState<ChartType>(payload.spec.chartType);

  // 切类型不重算数据,只覆盖 chartType;stack 只对 bar 有意义。
  const spec = useMemo(() => ({
    ...payload.spec,
    chartType: type,
    stack: type === "bar" ? payload.spec.stack : ("none" as const),
  }), [payload.spec, type]);

  return (
    <div className={styles.card}>
      <div className={styles.toolbar}>
        <div className={styles.segmented} role="group" aria-label="图表类型">
          {TYPES.map(t => (
            <button
              key={t.type}
              type="button"
              className={styles.segment}
              aria-pressed={type === t.type}
              onClick={() => setType(t.type)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {type !== "table" && <ChartView spec={spec} />}

      {payload.spec.notes.length > 0 && (
        <ul className={styles.notes}>
          {payload.spec.notes.map(n => (
            <li key={n} className={styles.note} data-testid="note">ⓘ {n}</li>
          ))}
        </ul>
      )}

      <SqlDisclosure sql={payload.sql} />
      <InsightPanel text={insight} facts={facts} format={payload.spec.series[0]?.format} />
      <DataTable columns={payload.table.columns} rows={payload.table.rows} />
    </div>
  );
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `npx vitest --root apps/frontend run`
Expected: 全绿。`ChatWindow.test.tsx` 里 `getByText("华东", { selector: "td" })` 仍应命中——`DataTable` 渲染的还是 `<td>`。

- [ ] **Step 6: 提交**

```bash
git add apps/frontend/src/components/ResultCard.tsx apps/frontend/src/components/ResultCard.module.css \
  apps/frontend/src/__tests__/ResultCard.test.tsx
git commit -m "refactor(frontend): ResultCard as thin container with segmented control"
```

### Task 6: MessageBubble 与 ChatWindow 样式化

**Files:**
- Modify: `apps/frontend/src/components/MessageBubble.tsx`(全量替换)
- Create: `apps/frontend/src/components/MessageBubble.module.css`
- Modify: `apps/frontend/src/components/ChatWindow.tsx`(全量替换)
- Create: `apps/frontend/src/components/ChatWindow.module.css`
- Modify: `apps/frontend/src/__tests__/ChatWindow.test.tsx`(**追加**空状态用例,P1a 的 6 个用例一条不改)

**Interfaces:**
- Consumes: Task 5 的 `ResultCard`
- Produces: `MessageBubble({ message }: { message: Message })`、`ChatWindow()`;`Message` 接口原样不动

**行为唯一的新增是空状态提示**:没有任何消息时,消息区显示一段引导文案和三个示例问题(纯文本,不可点击——可点击就变成新交互了,不在本计划范围)。其余全部是样式改动,P1a 的 6 个 `ChatWindow` 用例一条都不许改。

**`ChatWindow` 里的 `<h1>Chat-BI</h1>` 删掉**(Task 1 已移到 `AppShell`)。

- [ ] **Step 1: 追加失败测试到 `apps/frontend/src/__tests__/ChatWindow.test.tsx`**

```tsx
describe("ChatWindow 空状态", () => {
  it("没有消息时显示引导与示例问题", () => {
    render(<ChatWindow />);
    expect(screen.getByTestId("empty-state")).toBeTruthy();
    expect(screen.getByText(/按月统计订单金额/)).toBeTruthy();
  });

  it("提问后空状态消失", async () => {
    render(<ChatWindow />);
    ask("q");
    await waitFor(() => expect(screen.queryByTestId("empty-state")).toBeNull());
  });

  it("错误消息带 alert 语义", async () => {
    render(<ChatWindow />);
    ask("q");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [{ type: "error", message: "Ollama 未运行" }]);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Ollama 未运行"));
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest --root apps/frontend run src/__tests__/ChatWindow.test.tsx`
Expected: FAIL，`Unable to find an element by: [data-testid="empty-state"]`

- [ ] **Step 3: 创建 `apps/frontend/src/components/MessageBubble.module.css`**

```css
.row {
  display: flex;
  flex-direction: column;
  margin: var(--sp-4) 0;
  max-width: 100%;
}

.user {
  align-self: flex-end;
  max-width: 80%;
  padding: var(--sp-2) var(--sp-4);
  background: var(--accent);
  color: #ffffff;
  border-radius: var(--radius-md) var(--radius-md) var(--sp-1) var(--radius-md);
  white-space: pre-wrap;
}

.assistant {
  align-self: stretch;
}

.intent {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin-bottom: var(--sp-1);
  white-space: pre-wrap;
}

.error {
  margin-top: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border-left: 3px solid var(--negative);
  background: var(--surface);
  color: var(--negative);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  font-size: var(--fs-sm);
  white-space: pre-wrap;
}
```

选中态和用户气泡上的 `#ffffff` 与 Task 5 同理:accent 底上的文字色,深浅色两套都成立。

- [ ] **Step 4: 全量替换 `apps/frontend/src/components/MessageBubble.tsx`**

```tsx
import type { InsightFact, ResultPayload } from "@chatbi/shared";
import { ResultCard } from "./ResultCard";
import styles from "./MessageBubble.module.css";

export interface Message {
  id: string;
  role: "user" | "assistant";
  /** 用户提问,或助手侧的错误提示。查询意图走 payload.queryIntent。 */
  text: string;
  payload?: ResultPayload;
  facts?: InsightFact[];
  insight?: string;
}

export function MessageBubble({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className={styles.row}>
        <div className={styles.user}>{message.text}</div>
      </div>
    );
  }

  return (
    <div className={`${styles.row} ${styles.assistant}`}>
      {message.payload && <div className={styles.intent}>{message.payload.queryIntent}</div>}
      {message.text && <div className={styles.error} role="alert">{message.text}</div>}
      {message.payload && (
        <ResultCard
          payload={message.payload}
          insight={message.insight ?? ""}
          facts={message.facts ?? []}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 5: 创建 `apps/frontend/src/components/ChatWindow.module.css`**

```css
.window {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: var(--sp-4) 0;
}

.empty {
  margin: auto;
  text-align: center;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-normal);
}

.emptyTitle {
  font-size: var(--fs-lg);
  color: var(--text);
  margin-bottom: var(--sp-3);
}

.examples {
  margin: 0;
  padding: 0;
  list-style: none;
}

.examples li {
  padding: var(--sp-1) 0;
}

.composer {
  display: flex;
  gap: var(--sp-2);
  padding: var(--sp-3) 0 var(--sp-5);
  border-top: 1px solid var(--border);
  background: var(--bg);
}

.input {
  flex: 1;
  padding: var(--sp-2) var(--sp-3);
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
}

.input::placeholder { color: var(--text-muted); }

.send {
  padding: var(--sp-2) var(--sp-5);
  background: var(--accent);
  color: #ffffff;
  border: none;
  border-radius: var(--radius-sm);
  font-weight: 600;
}

.send:hover:not(:disabled) { filter: brightness(1.08); }
```

- [ ] **Step 6: 全量替换 `apps/frontend/src/components/ChatWindow.tsx`**

只有三处与 P1a 不同:去掉 `<h1>`、加空状态、换成 CSS Modules。逻辑(id 定位、下钻上下文、事件处理)一字不改。

```tsx
import { useState } from "react";
import type { ChatTurn, DrillContext, StreamEvent } from "@chatbi/shared";
import { streamChat } from "../api";
import { MessageBubble, type Message } from "./MessageBubble";
import styles from "./ChatWindow.module.css";

const EXAMPLES = [
  "按月统计订单金额",
  "各产品类别销售额占比",
  "按月看各区域销售额",
];

let seq = 0;
const nextId = () => `m${++seq}`;

export function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  /** 向后找最近一条带结果的助手消息,作为下钻上下文。 */
  const drillContext = (): DrillContext | undefined => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const p = messages[i].payload;
      if (p) return { lastSql: p.sql, lastColumns: p.table.columns };
    }
    return undefined;
  };

  const send = () => {
    if (!input.trim() || busy) return;
    const question = input;
    const userId = nextId();
    const assistantId = nextId();
    const context = drillContext();
    const history: ChatTurn[] = messages.map(m => ({
      role: m.role,
      text: m.role === "assistant" ? (m.payload?.queryIntent ?? m.text) : m.text,
    }));

    setInput("");
    setBusy(true);
    setMessages(prev => [
      ...prev,
      { id: userId, role: "user", text: question },
      { id: assistantId, role: "assistant", text: "" },
    ]);

    const patch = (fn: (m: Message) => Message) =>
      setMessages(prev => prev.map(m => (m.id === assistantId ? fn(m) : m)));

    streamChat({
      question, history, context,
      onEvent: (e: StreamEvent) => {
        if (e.type === "result") patch(m => ({ ...m, payload: e.payload }));
        else if (e.type === "insightFacts") patch(m => ({ ...m, facts: e.facts }));
        else if (e.type === "insightDelta") patch(m => ({ ...m, insight: (m.insight ?? "") + e.text }));
        else if (e.type === "error") patch(m => ({ ...m, text: `${m.text}\n[错误] ${e.message}`.trim() }));
      },
    }).finally(() => setBusy(false));
  };

  const hasContext = messages.some(m => m.payload);

  return (
    <div className={styles.window}>
      <div className={styles.stream}>
        {messages.length === 0 ? (
          <div className={styles.empty} data-testid="empty-state">
            <p className={styles.emptyTitle}>用中文问一个关于订单数据的问题</p>
            <ul className={styles.examples}>
              {EXAMPLES.map(e => <li key={e}>「{e}」</li>)}
            </ul>
          </div>
        ) : (
          messages.map(m => <MessageBubble key={m.id} message={m} />)
        )}
      </div>

      <div className={styles.composer}>
        <input
          className={styles.input}
          value={input}
          placeholder={hasContext ? "继续追问，例如「只看华东区」" : "输入问题，例如「按月统计订单金额」"}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
        />
        <button className={styles.send} onClick={send} disabled={busy}>发送</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: 跑测试确认通过**

Run: `npx vitest --root apps/frontend run`
Expected: 全绿(api / chartPalette / ChartView / SqlDisclosure / DataTable / InsightPanel / ResultCard / ChatWindow / AppShell 九个文件)

- [ ] **Step 8: 提交**

```bash
git add apps/frontend/src/components/MessageBubble.tsx apps/frontend/src/components/MessageBubble.module.css \
  apps/frontend/src/components/ChatWindow.tsx apps/frontend/src/components/ChatWindow.module.css \
  apps/frontend/src/__tests__/ChatWindow.test.tsx
git commit -m "feat(frontend): style chat stream, composer and empty state"
```

### Task 7: 深浅色、可访问性与收尾验收

**Files:**
- Modify: `README.md`(新增「界面」小节;把「开箱即跑」那条特性补上深浅色)
- 可能 Modify: 上面任意 `*.module.css`(修对比度问题时)

**Interfaces:**
- Consumes: 前面 6 个任务
- Produces: 无新接口。这是 P1b 的收口任务。

- [ ] **Step 1: 静态检查——组件里不该再有颜色字面量和 inline style**

```bash
# 颜色字面量:只允许 theme/ 下的文件,以及三处 accent 底上的 #ffffff
git grep -nE "#[0-9a-fA-F]{3,8}\b" -- apps/frontend/src | grep -v "src/theme/"

# inline style:应该只在 __tests__ 里可能出现,src/components 下必须为空
git grep -n "style={{" -- apps/frontend/src/components
```

Expected:
- 第一条只剩 `ResultCard.module.css`、`MessageBubble.module.css`、`ChatWindow.module.css` 里的 `#ffffff`
- 第二条**无输出**。有输出就说明某个组件还没迁完,回到对应任务修掉。

- [ ] **Step 2: 全量测试与类型检查**

```bash
npx vitest --root packages/shared run
npx vitest --root apps/backend run
npx vitest --root apps/frontend run
npm run build --workspaces --if-present
```

Expected: 全绿、无 TS 错误。后端一行没动,它绿着就说明本计划确实没越界。

- [ ] **Step 3: 对比度核对**

用浏览器 devtools 的对比度检查器(或任意 WCAG 对比度工具)逐项确认,浅色和深色各查一遍。目标:正文 ≥ 4.5:1,大字号与非文本边框 ≥ 3:1。

| 组合 | 变量 | 要求 |
|---|---|---|
| 正文 / 页面底 | `--text` / `--bg` | ≥ 4.5 |
| 正文 / 卡片底 | `--text` / `--surface` | ≥ 4.5 |
| 次要文字 / 卡片底 | `--text-muted` / `--surface` | ≥ 4.5 |
| 洞察正文 / 洞察底 | `--text` / `--accent-weak` | ≥ 4.5 |
| 洞察标题 / 洞察底 | `--accent` / `--accent-weak` | ≥ 4.5 |
| 用户气泡文字 / 气泡底 | `#ffffff` / `--accent` | ≥ 4.5 |
| 选中的 segment / 其底色 | `#ffffff` / `--accent` | ≥ 4.5 |
| 错误文字 / 卡片底 | `--negative` / `--surface` | ≥ 4.5 |
| 表头文字 / 表头底 | `--text-muted` / `--surface-raised` | ≥ 4.5 |
| 边框 / 卡片底 | `--border-strong` / `--surface` | ≥ 3 |

不达标的项直接调 `tokens.css` 里对应变量的明度,不要在组件里打补丁。改完重跑 Step 2。

- [ ] **Step 4: 键盘与缩放**

- 从地址栏按 Tab 走一遍:输入框 → 发送 → 图表类型四个 segment → 查看 SQL → 计算依据 → 数据表格。每一站都要有可见的 `:focus-visible` 轮廓。
- 浏览器缩放到 200%:顶栏不重叠,消息区仍可滚动,表格横向出现滚动条而不是撑破布局。
- 只用键盘展开/收起三个 `<details>`(Enter 或 Space)。

- [ ] **Step 5: 深浅色与色觉模拟**

- 系统切到深色 → 刷新页面:界面整体变深,**图表配色跟着换成深色板**(这一条最容易漏——`useChartPalette` 是靠 `matchMedia` 事件切的,不刷新也应生效,两种都试)。
- devtools 的 Rendering 面板里开 `Emulate vision deficiencies` → `Deuteranopia` 和 `Protanopia`,看验收清单第 4 条(按月看各区域销售额)的多条折线:相邻两条必须能分辨。分辨不出就调整 `chartPalette.ts` 里相邻两档的顺序(把差异大的两色排到相邻位置),不要加第 9 色。
- 同一状态下确认:洞察里的涨跌**没有**用颜色表达,只有文字。

- [ ] **Step 6: 按 P1 验收清单跑一遍真实链路**

启 `ollama serve` + 后端 + 前端,过 README 里 9 条手动验收。P1b 重点看第 4、5、9 条:多系列图例可读、百分比堆叠 y 轴 0–100%、「查看 SQL」与「计算依据」都能展开核对。

- [ ] **Step 7: 更新 README**

「特性」小节把最后一条改成:

```markdown
- **开箱即跑**:首次启动自动建表并灌入示例订单数据,不用自备数据源;界面跟随系统深浅色。
```

新增一小节:

```markdown
## 界面

- 设计 tokens 集中在 `apps/frontend/src/theme/tokens.css`,组件通过 CSS 变量取色,不写颜色字面量。
- 深浅色跟随系统 `prefers-color-scheme`,不提供手动开关。
- 图表调色板取 Okabe-Ito 色觉友好色系派生(`theme/chartPalette.ts`),浅色深色各一套 8 色。
- 涨跌不用颜色表达——中式涨红跌绿与国际涨绿跌红相反,统一用文字说明,避免误读。
- 数字统一 `tabular-nums` 等宽对齐(表格、坐标轴、洞察)。
```

- [ ] **Step 8: 提交**

```bash
git add README.md apps/frontend/src/theme apps/frontend/src/components
git commit -m "chore(frontend): contrast and a11y pass; docs: describe design system"
```

- [ ] **Step 9: P1 整体完成确认**

P1a + P1b 都做完后,逐项确认:

- 三个 workspace 测试全绿,`npm run build --workspaces --if-present` 无错
- `git grep -n "style={{" -- apps/frontend/src/components` 无输出
- `git grep -nE "#[0-9a-fA-F]{3,8}" -- apps/frontend/src | grep -v src/theme/` 只剩三处 `#ffffff`
- `git grep -n chartAssembler` / `explanationDelta` / `ChartPayload` 均无结果
- README 的 9 条手动验收全部人工过一遍,深浅色各一遍
- 与 spec 第 8 节对照,P1a 的 6 项与 P1b 的 4 项工作流全部落地

至此 P1「分析闭环」完成。P2(数据源适配层、语义层/指标层、元数据持久化、dashboard 编排)需要重新走 brainstorming,不在本计划范围。
