# Chat-BI P2a-2 续篇实施计划：前端路由、数据源选择器与管理界面

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 [P2a-2 计划](./2026-07-31-chatbi-p2a2-integration-frontend.md) Task 1–7 建好的后端能力接到界面上——用户能在顶栏选数据源提问、在 `/datasources` 页管理数据源(增删改、测连、刷新结构、看表结构),切源时下钻上下文被清掉。

**Architecture:** 前端引入 `react-router-dom` 两条路由;数据源的「列表 + 当前选中」收进一个 Context(`dataSourceStore.tsx`),顶栏选择器与管理页共用它;`ChatWindow` 收 `dataSourceId` 作为 prop(不直接读 Context,保持可测),`dataSourceId` 变化时 bump epoch,旧 epoch 的消息留在界面上但不再进 history / DrillContext。

**Tech Stack:** React 18 + Vite 5、react-router-dom 6、vitest 1.6 + @testing-library/react、CSS Modules + `theme/tokens.css`

**前序:** [P2a-2 计划](./2026-07-31-chatbi-p2a2-integration-frontend.md) 的 Task 1–7 必须已全部完成(截至 2026-08-03 已完成,基线 `npm test --workspaces` = 后端 373 passed + 3 skipped、前端 81、shared 29)。本篇是它末尾两个空占位符(Task 8 / Task 9 位)的展开,任务号接着编:**Task 8–12**。设计依据:[P2a 设计 spec](../specs/2026-07-31-chatbi-p2-datasource-design.md) 第 8 节、第 9 节「启动期健壮性」、第 12 节。

## Global Constraints

照抄 P2a-2 计划的 Global Constraints,以下几条在本篇尤其常被违反,重述一遍:

- **唯一允许新增的前端依赖是 `react-router-dom`**(已装 `^6.30.4`,连带 `@remix-run/router`)。不引 UI 组件库、不引状态管理库、不引 `@testing-library/jest-dom`——断言用 `expect(...).toBeTruthy()` 风格。
- **视觉规则(P1b 建立)**:颜色只从 `apps/frontend/src/theme/tokens.css` 取 CSS 变量;**不写颜色字面量**;**不用内联 `style={{}}`**;每个组件配自己的 `.module.css`;数字用 `tabular-nums`。现有 tokens 已有 `--positive` / `--negative` / `--warning` / `--text-muted`,状态色直接用,**不新造 token**。
- **`ChartSpec`、`packages/shared/src/renderer.ts`、`InsightPanel` / `ResultCard` / `ChartView` / `DataTable` / `SqlDisclosure` 一律不改。**
- **`StreamEvent` 五种事件不加不减。**
- **中文标点约定**:句内停顿用半角逗号 `,`,冒号用半角 `:`,句末用全角句号 `。`,强调用 `「」`。注释与测试描述用中文。
- **每个任务结束时 `npm test --workspaces` 必须全绿。**
- ESM,相对导入不写扩展名;组件文件用 `.tsx`,纯逻辑用 `.ts`。

## File Structure

```
apps/frontend/src/
  api.ts                          改:streamChat 带 dataSourceId(Task 9,与 ChatWindow 同一笔改,否则类型对不上)
  dataSourceStore.tsx             新:列表 + 当前选中 + localStorage(Task 8)
  routes.tsx                      新:两条路由 + 兜底重定向(Task 9)
  pages/
    ChatPage.tsx                  新:读 Context,把 dataSourceId 喂给 ChatWindow(Task 9)
    DataSourcesPage.tsx           新:列表 + 行内操作 + 展开结构(Task 10)、挂表单(Task 11)
    DataSourcesPage.module.css
  components/
    StatusBadge.tsx               新:状态点 + 写权限警告徽标(Task 8)
    StatusBadge.module.css
    DataSourcePicker.tsx          新:顶栏选择器(Task 9)
    DataSourcePicker.module.css
    SchemaTree.tsx                新:表结构预览,P2b 建模 UI 复用(Task 10)
    SchemaTree.module.css
    DataSourceForm.tsx            新:按 kind 变化的表单 + 测连反馈 + 仍然保存(Task 11)
    DataSourceForm.module.css
    AppShell.tsx                  改:顶栏放选择器 + 「管理」链接(Task 9)
    ChatWindow.tsx                改:收 dataSourceId,切源 bump epoch(Task 9)
    MessageBubble.tsx             改:Message 加 "notice" 角色与 epoch 字段(Task 9)
  App.tsx                         改:BrowserRouter + Provider + AppShell + Routes(Task 9)
```

### Task 8: 数据源 Context 与状态徽标

顶栏选择器、管理页、`ChatPage` 三处都要「列表 + 当前选中」,先把它做成一个 Context,后面的任务只消费。`StatusBadge` 同时被选择器与管理页用,一并做掉。

**Files:**
- Create: `apps/frontend/src/dataSourceStore.tsx`
- Create: `apps/frontend/src/components/StatusBadge.tsx`
- Create: `apps/frontend/src/components/StatusBadge.module.css`
- Test: `apps/frontend/src/__tests__/dataSourceStore.test.tsx`
- Test: `apps/frontend/src/__tests__/StatusBadge.test.tsx`

**Interfaces:**
- Consumes: Task 7 的 `listDataSources(): Promise<DataSourceSummary[]>`(在 `apps/frontend/src/api.ts`);shared 的 `DataSourceSummary`、`DataSourceStatus`、`WritePrivilege`。
- Produces(Task 9–11 按这些名字调用):
  ```ts
  export const SELECTED_KEY = "chatbi.selectedDataSourceId";
  export interface DataSourceStore {
    list: DataSourceSummary[];
    selectedId: string | null;
    selected: DataSourceSummary | null;   // list 里找不到时是 null
    loading: boolean;
    error: string | null;                 // 拉列表失败的可读消息
    select: (id: string) => void;
    reload: () => Promise<void>;          // 永不 reject,失败写进 error
  }
  export function DataSourceProvider(props: { children: ReactNode }): JSX.Element;
  export function useDataSources(): DataSourceStore;   // Provider 外调用会 throw
  export function StatusBadge(props: {
    status: DataSourceStatus;
    writePrivilege?: WritePrivilege | null;
  }): JSX.Element;
  ```

- [ ] **Step 1: 写 dataSourceStore 的失败测试**

创建 `apps/frontend/src/__tests__/dataSourceStore.test.tsx`:

```tsx
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
npm test --workspace=apps/frontend -- dataSourceStore
```

Expected: FAIL,`Failed to resolve import "../dataSourceStore"`。

- [ ] **Step 3: 实现 dataSourceStore**

创建 `apps/frontend/src/dataSourceStore.tsx`:

```tsx
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode,
} from "react";
import type { DataSourceSummary } from "@chatbi/shared";
import { listDataSources } from "./api";

/** 刷新页面后保留用户的选择。键名带 chatbi. 前缀,避免与同源的别的应用撞。 */
export const SELECTED_KEY = "chatbi.selectedDataSourceId";

export interface DataSourceStore {
  list: DataSourceSummary[];
  selectedId: string | null;
  selected: DataSourceSummary | null;
  loading: boolean;
  error: string | null;
  select: (id: string) => void;
  reload: () => Promise<void>;
}

const Ctx = createContext<DataSourceStore | null>(null);

// localStorage 在隐私模式下会抛。读写都兜住:选择记不住比整页白屏好。
const readStored = (): string | null => {
  try { return localStorage.getItem(SELECTED_KEY); } catch { return null; }
};
const writeStored = (id: string | null) => {
  try {
    if (id === null) localStorage.removeItem(SELECTED_KEY);
    else localStorage.setItem(SELECTED_KEY, id);
  } catch { /* 记不住就算了,不影响本次会话 */ }
};

export function DataSourceProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<DataSourceSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(readStored);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const next = await listDataSources();
      setList(next);
      // 以 localStorage 为准做校验:select() 是同步写盘的,所以它总是用户最新的选择;
      // 被删掉的 id 回落到第一个可用源,列表空则回落 null。
      const stored = readStored();
      const keep = stored !== null && next.some(d => d.id === stored);
      const resolved = keep ? stored : (next[0]?.id ?? null);
      if (resolved !== stored) writeStored(resolved);
      setSelectedId(resolved);
      setError(null);
    } catch (e) {
      setError(`无法读取数据源列表:${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const select = useCallback((id: string) => {
    setSelectedId(id);
    writeStored(id);
  }, []);

  const value = useMemo<DataSourceStore>(() => ({
    list,
    selectedId,
    selected: list.find(d => d.id === selectedId) ?? null,
    loading, error, select, reload,
  }), [list, selectedId, loading, error, select, reload]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDataSources(): DataSourceStore {
  const v = useContext(Ctx);
  if (!v) throw new Error("useDataSources 必须在 DataSourceProvider 内使用");
  return v;
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
npm test --workspace=apps/frontend -- dataSourceStore
```

Expected: PASS,8 个用例。

- [ ] **Step 5: 写 StatusBadge 的失败测试**

创建 `apps/frontend/src/__tests__/StatusBadge.test.tsx`:

```tsx
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
```

- [ ] **Step 6: 跑测试确认失败**

```bash
npm test --workspace=apps/frontend -- StatusBadge
```

Expected: FAIL,`Failed to resolve import "../components/StatusBadge"`。

- [ ] **Step 7: 实现 StatusBadge**

创建 `apps/frontend/src/components/StatusBadge.tsx`:

```tsx
import type { DataSourceStatus, WritePrivilege } from "@chatbi/shared";
import styles from "./StatusBadge.module.css";

const STATUS_TEXT: Record<DataSourceStatus, string> = {
  ok: "正常",
  error: "连接失败",
  needs_reconfig: "需重新填写凭据",
  unchecked: "未检查",
};

// readonly 是期望状态,不占视觉;另两种才提示。
const PRIVILEGE_TEXT: Partial<Record<WritePrivilege, string>> = {
  writable: "建议改用只读账号",
  unknown: "写权限未知",
};

export function StatusBadge({ status, writePrivilege }: {
  status: DataSourceStatus;
  writePrivilege?: WritePrivilege | null;
}) {
  const privilege = writePrivilege ? PRIVILEGE_TEXT[writePrivilege] : undefined;
  return (
    <span className={styles.wrap}>
      <span
        className={`${styles.dot} ${styles[status]}`}
        data-testid="status-dot"
        data-status={status}
        aria-hidden="true"
      />
      <span className={styles.label}>{STATUS_TEXT[status]}</span>
      {privilege && (
        <span
          className={`${styles.privilege} ${writePrivilege === "writable" ? styles.warn : styles.muted}`}
          data-testid="privilege-badge"
          data-privilege={writePrivilege}
        >
          {privilege}
        </span>
      )}
    </span>
  );
}
```

创建 `apps/frontend/src/components/StatusBadge.module.css`:

```css
.wrap {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
}

.dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.ok { background: var(--positive); }
.error { background: var(--negative); }
.needs_reconfig { background: var(--warning); }
.unchecked { background: var(--text-muted); }

.label { color: var(--text-muted); }

.privilege {
  padding: 0 var(--sp-2);
  border: 1px solid currentColor;
  border-radius: var(--radius-sm);
  white-space: nowrap;
}

.warn { color: var(--warning); }
.muted { color: var(--text-muted); }
```

- [ ] **Step 8: 跑全量测试与类型检查**

```bash
npm test --workspaces
npx tsc -p apps/frontend --noEmit
git grep -n "style={{" -- apps/frontend/src
git grep -nE "#[0-9a-fA-F]{3,8}\b" -- apps/frontend/src | grep -v "src/theme/"
```

Expected: 前端 81 + 14 = 95 passed,后端 373 passed + 3 skipped,shared 29 passed;`tsc` 无输出;`style={{` 无命中;颜色字面量只剩 P1b 已有的三处 `#ffffff`(不新增)。

- [ ] **Step 9: 提交**

```bash
git add apps/frontend/src/dataSourceStore.tsx apps/frontend/src/components/StatusBadge.tsx \
  apps/frontend/src/components/StatusBadge.module.css \
  apps/frontend/src/__tests__/dataSourceStore.test.tsx apps/frontend/src/__tests__/StatusBadge.test.tsx
git commit -m "feat(frontend): data source context and status badge"
```

---

### Task 9: 路由、顶栏选择器与切源清空下钻上下文

一笔做完「能选源提问」这条链:`streamChat` 带上 `dataSourceId`(后端 Task 5 已经要求它,现在还没人传,所以提问必然报「缺少 dataSourceId」),`ChatWindow` 在切源时断开上下文,顶栏出现选择器,`/datasources` 路由通。

**为什么 api.ts 的改动放在这一任务而不是 Task 8**:`dataSourceId` 是必填字段,加上它的同一刻 `ChatWindow` 就必须传,否则 `tsc` 不过。两处一起改才有一个能编译的中间状态。

**Files:**
- Modify: `apps/frontend/src/api.ts`(`streamChat` 的 opts 加 `dataSourceId`)
- Modify: `apps/frontend/src/components/MessageBubble.tsx`(`Message` 加 `notice` 角色与 `epoch`)
- Modify: `apps/frontend/src/components/MessageBubble.module.css`(加 `.notice`)
- Modify: `apps/frontend/src/components/ChatWindow.tsx`(收 `dataSourceId` prop、切源 bump epoch)
- Modify: `apps/frontend/src/components/AppShell.tsx`(顶栏槽位改成收 `toolbar`)
- Modify: `apps/frontend/src/components/AppShell.module.css`(`.slot` 改成 flex 容器)
- Modify: `apps/frontend/src/App.tsx`(`BrowserRouter` + `DataSourceProvider` + 路由)
- Create: `apps/frontend/src/routes.tsx`
- Create: `apps/frontend/src/dsLabels.ts`(kind 与写权限的中文标签,Task 10 / 11 复用)
- Create: `apps/frontend/src/pages/ChatPage.tsx`
- Create: `apps/frontend/src/pages/DataSourcesPage.tsx`(**本任务只建最小骨架,Task 10 填内容**)
- Create: `apps/frontend/src/components/DataSourcePicker.tsx`
- Create: `apps/frontend/src/components/DataSourcePicker.module.css`
- Test: `apps/frontend/src/__tests__/DataSourcePicker.test.tsx`
- Test: `apps/frontend/src/__tests__/routes.test.tsx`
- Modify test: `apps/frontend/src/__tests__/api.test.ts`(所有 `streamChat` 调用补 `dataSourceId`)
- Modify test: `apps/frontend/src/__tests__/ChatWindow.test.tsx`(所有 `render(<ChatWindow />)` 补 prop,新增切源用例)

**Interfaces:**
- Consumes: Task 8 的 `useDataSources()` / `DataSourceProvider` / `StatusBadge`;Task 7 的 `streamChat`;shared 的 `DataSourceKind`。
- Produces:
  ```ts
  // api.ts
  export function streamChat(opts: {
    question: string;
    dataSourceId: string;          // 新增,必填
    history: ChatTurn[];
    context?: DrillContext;
    onEvent: (e: StreamEvent) => void;
    endpoint?: string;
  }): Promise<void>;

  // MessageBubble.tsx
  export interface Message {
    id: string;
    role: "user" | "assistant" | "notice";   // notice = 切源分隔提示
    text: string;
    epoch: number;                            // 属于第几个数据源阶段
    payload?: ResultPayload;
    facts?: InsightFact[];
    insight?: string;
  }

  // ChatWindow.tsx
  export function ChatWindow(props: {
    dataSourceId: string | null;   // null = 无可用数据源,禁止提问
    dataSourceName?: string;       // 只用于切源提示文案
  }): JSX.Element;

  // routes.tsx
  export function AppRoutes(): JSX.Element;   // "/" → ChatPage,"/datasources" → DataSourcesPage,其余重定向 "/"

  // dsLabels.ts —— 三个组件都要这两张表,只放一份
  export const KIND_LABEL: Record<DataSourceKind, string>;        // sqlite → "SQLite" 等
  export const PRIVILEGE_LABEL: Record<WritePrivilege, string>;    // readonly → "只读" 等

  // components/DataSourcePicker.tsx
  export function DataSourcePicker(): JSX.Element;   // 读 Context,内含「管理」Link

  // pages/ChatPage.tsx
  export function ChatPage(): JSX.Element;
  // pages/DataSourcesPage.tsx
  export function DataSourcesPage(): JSX.Element;
  ```

- [ ] **Step 1: 改 api.test.ts,先让契约变化以失败形式出现**

`apps/frontend/src/__tests__/api.test.ts` 的 `collect()` 补上 `dataSourceId`,并新增一个用例断言它进了请求体。替换文件顶部的 `collect` 定义:

```ts
const collect = (body: string, extra: Record<string, unknown> = {}) => {
  (global as any).fetch = mockFetch(body);
  const events: StreamEvent[] = [];
  return streamChat({
    question: "q", dataSourceId: "ds1", history: [],
    onEvent: e => events.push(e), ...extra,
  }).then(() => events);
};
```

在文件末尾追加:

```ts
describe("streamChat 请求体", () => {
  it("带上 dataSourceId,后端按它取 driver", async () => {
    await collect('data: {"type":"done"}\n\n');
    const body = JSON.parse((global as any).fetch.mock.calls[0][1].body);
    expect(body.dataSourceId).toBe("ds1");
    expect(body.question).toBe("q");
  });

  it("context 缺省时请求体里没有 context 字段", async () => {
    await collect('data: {"type":"done"}\n\n');
    const body = JSON.parse((global as any).fetch.mock.calls[0][1].body);
    expect("context" in body).toBe(false);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
npm test --workspace=apps/frontend -- api.test
```

Expected: FAIL,新用例报 `expect(body.dataSourceId).toBe("ds1")` 得到 `undefined`(旧 `streamChat` 不往 body 里放它)。

- [ ] **Step 3: 改 streamChat 传 dataSourceId**

`apps/frontend/src/api.ts` 的 `streamChat`:签名加字段,body 里加一行。

```ts
export function streamChat(opts: {
  question: string; dataSourceId: string; history: ChatTurn[]; context?: DrillContext;
  onEvent: (e: StreamEvent) => void;
  endpoint?: string;
}): Promise<void> {
```

```ts
        body: JSON.stringify({
          question: opts.question,
          dataSourceId: opts.dataSourceId,
          history: opts.history,
          ...(opts.context ? { context: opts.context } : {}),
        }),
```

- [ ] **Step 4: 跑测试确认通过**

```bash
npm test --workspace=apps/frontend -- api.test
```

Expected: PASS,8 个用例(原 6 + 新 2)。`tsc` 此刻还会在 `ChatWindow.tsx` 报缺 `dataSourceId`——Step 5–8 修掉。

- [ ] **Step 5: 改 ChatWindow.test.tsx,加切源用例**

先把现有 10 个用例里的 `render(<ChatWindow />)` 全部换成带 prop 的形式(4 处 describe 共 10 处):

```tsx
render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
```

`ask()` 之外再加一个重渲染助手,放在 `finish` 定义之后:

```tsx
/** 切源 = 父组件传新的 dataSourceId 重渲染。 */
const switchTo = (view: ReturnType<typeof render>, id: string | null, name?: string) =>
  view.rerender(<ChatWindow dataSourceId={id} dataSourceName={name} />);
```

在文件末尾追加一个 describe:

```tsx
describe("ChatWindow 切换数据源", () => {
  it("请求体里带上当前 dataSourceId", async () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("q");
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].dataSourceId).toBe("ds1");
  });

  it("首次拿到数据源不插分隔提示", async () => {
    const view = render(<ChatWindow dataSourceId={null} />);
    switchTo(view, "ds1", "示例订单库");
    await waitFor(() => expect(screen.queryByTestId("switch-notice")).toBeNull());
  });

  it("有历史消息时切源插入分隔提示", async () => {
    const view = render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("按月统计订单金额");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [{ type: "result", payload: payload("统计每月订单总额", "SELECT 1") }, { type: "done" }]);
    await finish(0);

    switchTo(view, "ds2", "销售库");
    await waitFor(() => expect(screen.getByTestId("switch-notice")).toBeTruthy());
    expect(screen.getByTestId("switch-notice").textContent).toContain("销售库");
    expect(screen.getByRole("status").textContent).toContain("已切换到数据源");
  });

  it("没有历史消息时切源不插提示", async () => {
    const view = render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    switchTo(view, "ds2", "销售库");
    await waitFor(() => expect(screen.getByTestId("empty-state")).toBeTruthy());
    expect(screen.queryByTestId("switch-notice")).toBeNull();
  });

  it("切源后新一轮不带旧源的 context 与 history", async () => {
    const view = render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("按月统计订单金额");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [{ type: "result", payload: payload("统计每月订单总额", "SELECT month FROM orders") }, { type: "done" }]);
    await finish(0);

    switchTo(view, "ds2", "销售库");
    ask("按周看");
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].dataSourceId).toBe("ds2");
    expect(calls[1].context).toBeUndefined();
    expect(calls[1].history).toEqual([]);
  });

  it("切源后旧的图表仍留在界面上", async () => {
    const view = render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("按月统计订单金额");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [{ type: "result", payload: payload("统计每月订单总额", "SELECT 1") }, { type: "done" }]);
    await finish(0);
    switchTo(view, "ds2", "销售库");
    await waitFor(() => expect(screen.getByTestId("switch-notice")).toBeTruthy());
    expect(screen.getByText("统计每月订单总额")).toBeTruthy();
  });

  it("切源后的新一轮之间仍然能下钻", async () => {
    const view = render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("q1");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [{ type: "result", payload: payload("旧意图", "SELECT old") }, { type: "done" }]);
    await finish(0);

    switchTo(view, "ds2", "销售库");
    ask("q2");
    await waitFor(() => expect(calls).toHaveLength(2));
    drive(1, [{ type: "result", payload: payload("新意图", "SELECT new") }, { type: "done" }]);
    await finish(1);

    ask("q3");
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(calls[2].context).toEqual({ lastSql: "SELECT new", lastColumns: ["region", "total"] });
    expect(calls[2].history).toEqual([
      { role: "user", text: "q2" },
      { role: "assistant", text: "新意图" },
    ]);
  });

  it("没有数据源时输入框禁用并提示去选", () => {
    render(<ChatWindow dataSourceId={null} />);
    const box = screen.getByRole("textbox") as HTMLInputElement;
    expect(box.disabled).toBe(true);
    expect(box.placeholder).toContain("请先在顶栏选择数据源");
    expect((screen.getByRole("button", { name: /发送/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("没有数据源时点发送不发请求", () => {
    render(<ChatWindow dataSourceId={null} />);
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));
    expect(calls).toHaveLength(0);
  });
});
```

- [ ] **Step 6: 跑测试确认失败**

```bash
npm test --workspace=apps/frontend -- ChatWindow
```

Expected: FAIL,`calls[0].dataSourceId` 是 `undefined`、`switch-notice` 找不到、输入框没被禁用。

- [ ] **Step 7: 给 Message 加 notice 角色**

`apps/frontend/src/components/MessageBubble.tsx`——`Message` 接口加两个字段,渲染加一个分支:

```tsx
export interface Message {
  id: string;
  role: "user" | "assistant" | "notice";
  /** 用户提问、助手侧错误提示,或切源分隔提示。查询意图走 payload.queryIntent。 */
  text: string;
  /** 属于第几个数据源阶段。切源后 epoch 变大,旧阶段的消息不再进 history。 */
  epoch: number;
  payload?: ResultPayload;
  facts?: InsightFact[];
  insight?: string;
}
```

在 `MessageBubble` 里,`user` 分支之前插入:

```tsx
  if (message.role === "notice") {
    return (
      <div className={styles.row}>
        <div className={styles.notice} role="status" data-testid="switch-notice">{message.text}</div>
      </div>
    );
  }
```

`apps/frontend/src/components/MessageBubble.module.css` 末尾追加:

```css
/* 切源分隔提示:虚线框 + 居中,视觉上明确「上面的上下文断了」。 */
.notice {
  align-self: center;
  max-width: 90%;
  padding: var(--sp-1) var(--sp-3);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  text-align: center;
}
```

- [ ] **Step 8: 改 ChatWindow 收 dataSourceId 并按 epoch 断开上下文**

`apps/frontend/src/components/ChatWindow.tsx` 全文替换为:

```tsx
import { useEffect, useRef, useState } from "react";
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

export function ChatWindow({ dataSourceId, dataSourceName }: {
  dataSourceId: string | null;
  dataSourceName?: string;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  /**
   * 数据源阶段号。放 ref 而不是 state:它只在切源那一刻变,而那一刻 setMessages
   * 已经触发重渲染,再多一个 state 只会多一次渲染和一次时序竞争。
   */
  const epoch = useRef(0);
  const prevId = useRef(dataSourceId);

  // 切源:上一个源的方言与表名对新源无效,带过去模型会在错的 SQL 上改写,
  // 产出必然报错的查询且看起来像模型能力问题。旧消息留在界面上,但不再进 history。
  useEffect(() => {
    if (prevId.current === dataSourceId) return;
    const hadSource = prevId.current !== null;
    prevId.current = dataSourceId;
    if (!hadSource || dataSourceId === null) return;   // 首次拿到源、或源变没了,都不必提示
    epoch.current += 1;
    const text = `已切换到数据源「${dataSourceName ?? dataSourceId}」,后续提问基于新数据源。`;
    setMessages(prev => prev.length === 0
      ? prev
      : [...prev, { id: nextId(), role: "notice", epoch: epoch.current, text }]);
  }, [dataSourceId, dataSourceName]);

  /** 当前数据源阶段里的真实对话轮次(不含分隔提示)。 */
  const currentTurns = (): Message[] =>
    messages.filter(m => m.epoch === epoch.current && m.role !== "notice");

  /** 向后找最近一条带结果的助手消息,作为下钻上下文。 */
  const drillContext = (): DrillContext | undefined => {
    const turns = currentTurns();
    for (let i = turns.length - 1; i >= 0; i--) {
      const p = turns[i].payload;
      if (p) return { lastSql: p.sql, lastColumns: p.table.columns };
    }
    return undefined;
  };

  const send = () => {
    if (!input.trim() || busy || dataSourceId === null) return;
    const question = input;
    const userId = nextId();
    const assistantId = nextId();
    const context = drillContext();
    const history: ChatTurn[] = currentTurns().map(m => ({
      role: m.role === "assistant" ? "assistant" : "user",
      text: m.role === "assistant" ? (m.payload?.queryIntent ?? m.text) : m.text,
    }));
    const stage = epoch.current;

    setInput("");
    setBusy(true);
    setMessages(prev => [
      ...prev,
      { id: userId, role: "user", epoch: stage, text: question },
      { id: assistantId, role: "assistant", epoch: stage, text: "" },
    ]);

    const patch = (fn: (m: Message) => Message) =>
      setMessages(prev => prev.map(m => (m.id === assistantId ? fn(m) : m)));

    streamChat({
      question, dataSourceId, history, context,
      onEvent: (e: StreamEvent) => {
        if (e.type === "result") patch(m => ({ ...m, payload: e.payload }));
        else if (e.type === "insightFacts") patch(m => ({ ...m, facts: e.facts }));
        else if (e.type === "insightDelta") patch(m => ({ ...m, insight: (m.insight ?? "") + e.text }));
        else if (e.type === "error") patch(m => ({ ...m, text: `${m.text}\n[错误] ${e.message}`.trim() }));
      },
    }).finally(() => setBusy(false));
  };

  const ready = dataSourceId !== null;
  const hasContext = currentTurns().some(m => m.payload);
  const placeholder = !ready
    ? "请先在顶栏选择数据源"
    : hasContext ? "继续追问，例如「只看华东区」" : "输入问题，例如「按月统计订单金额」";

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
          placeholder={placeholder}
          disabled={!ready}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
        />
        <button className={styles.send} onClick={send} disabled={busy || !ready}>发送</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 9: 跑测试确认通过**

```bash
npm test --workspace=apps/frontend -- ChatWindow
```

Expected: PASS,19 个用例(原 10 + 新 9)。

- [ ] **Step 10: 写选择器与路由的失败测试**

创建 `apps/frontend/src/__tests__/DataSourcePicker.test.tsx`:

```tsx
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
```

创建 `apps/frontend/src/__tests__/routes.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes } from "../routes";
import { DataSourceProvider } from "../dataSourceStore";
import { listDataSources } from "../api";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, listDataSources: vi.fn() };
});
// 同 ResultCard.test.tsx:jsdom 无 canvas,真实 ECharts 会抛异步异常。
vi.mock("echarts", () => ({
  init: () => ({ setOption: () => {}, dispose: () => {}, resize: () => {} }),
}));

const at = (path: string) => render(
  <MemoryRouter initialEntries={[path]}>
    <DataSourceProvider><AppRoutes /></DataSourceProvider>
  </MemoryRouter>,
);

beforeEach(() => {
  localStorage.clear();
  vi.mocked(listDataSources).mockResolvedValue([]);
});

describe("AppRoutes", () => {
  it("/ 渲染对话页", async () => {
    at("/");
    await waitFor(() => expect(screen.getByTestId("empty-state")).toBeTruthy());
  });

  it("/datasources 渲染管理页", async () => {
    at("/datasources");
    await waitFor(() => expect(screen.getByRole("heading", { name: "数据源管理" })).toBeTruthy());
  });

  it("未知路径回落到对话页", async () => {
    at("/不存在的页面");
    await waitFor(() => expect(screen.getByTestId("empty-state")).toBeTruthy());
  });
});
```

`apps/frontend/src/__tests__/AppShell.test.tsx` 里,把第三个用例换成验证槽位真的收内容:

```tsx
  it("顶栏右侧渲染传入的 toolbar", () => {
    render(<AppShell toolbar={<span>选择器</span>}><div /></AppShell>);
    expect(screen.getByTestId("datasource-slot").textContent).toBe("选择器");
  });
```

- [ ] **Step 11: 跑测试确认失败**

```bash
npm test --workspace=apps/frontend -- DataSourcePicker routes AppShell
```

Expected: FAIL,`../components/DataSourcePicker` 与 `../routes` 都解析不到;`AppShell` 报 `toolbar` 不是它的 prop。

- [ ] **Step 12: 实现共用标签表与选择器**

创建 `apps/frontend/src/dsLabels.ts`(选择器、管理页、表单都要这两张表,只留一份):

```ts
import type { DataSourceKind, WritePrivilege } from "@chatbi/shared";

export const KIND_LABEL: Record<DataSourceKind, string> = {
  sqlite: "SQLite", mysql: "MySQL", postgres: "PostgreSQL",
};

export const PRIVILEGE_LABEL: Record<WritePrivilege, string> = {
  readonly: "只读", writable: "可写", unknown: "未知",
};
```

创建 `apps/frontend/src/components/DataSourcePicker.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useDataSources } from "../dataSourceStore";
import { KIND_LABEL } from "../dsLabels";
import { StatusBadge } from "./StatusBadge";
import styles from "./DataSourcePicker.module.css";

export function DataSourcePicker() {
  const { list, selectedId, selected, loading, error, select } = useDataSources();

  return (
    <div className={styles.wrap}>
      {error ? (
        <span className={styles.hint} role="alert">{error}</span>
      ) : list.length === 0 ? (
        <span className={styles.hint} data-testid="picker-empty">
          {loading ? "正在读取数据源…" : "无可用数据源,请先到「管理」添加"}
        </span>
      ) : (
        <>
          <label className={styles.label} htmlFor="ds-picker">数据源</label>
          <select
            id="ds-picker"
            className={styles.select}
            value={selectedId ?? ""}
            onChange={e => select(e.target.value)}
          >
            {list.map(d => (
              <option key={d.id} value={d.id}>{d.name} · {KIND_LABEL[d.kind]}</option>
            ))}
          </select>
          {selected && <StatusBadge status={selected.status} writePrivilege={selected.writePrivilege} />}
        </>
      )}
      <Link className={styles.manage} to="/datasources">管理</Link>
    </div>
  );
}
```

创建 `apps/frontend/src/components/DataSourcePicker.module.css`:

```css
.wrap {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-size: var(--fs-xs);
}

.label { color: var(--text-muted); }

.select {
  max-width: 220px;
  padding: var(--sp-1) var(--sp-2);
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
}

.hint { color: var(--text-muted); }

.manage {
  color: var(--accent);
  text-decoration: none;
  white-space: nowrap;
}

.manage:hover { text-decoration: underline; }
```

- [ ] **Step 13: AppShell 顶栏收 toolbar**

`apps/frontend/src/components/AppShell.tsx` 全文替换为:

```tsx
import type { ReactNode } from "react";
import styles from "./AppShell.module.css";

export function AppShell({ children, toolbar }: { children: ReactNode; toolbar?: ReactNode }) {
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <h1 className={styles.brand}>Chat-BI</h1>
        {/* 槽位由 App 填 DataSourcePicker:AppShell 不读 Context,保持纯展示好测。 */}
        <div className={styles.slot} data-testid="datasource-slot">{toolbar}</div>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
```

`apps/frontend/src/components/AppShell.module.css` 的 `.slot` 换成:

```css
.slot {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
```

- [ ] **Step 14: 建路由与两个页面,接上 App**

创建 `apps/frontend/src/pages/ChatPage.tsx`:

```tsx
import { ChatWindow } from "../components/ChatWindow";
import { useDataSources } from "../dataSourceStore";

/** 唯一职责:把 Context 里的选中项翻成 ChatWindow 的 prop,让 ChatWindow 保持可单测。 */
export function ChatPage() {
  const { selectedId, selected } = useDataSources();
  return <ChatWindow dataSourceId={selectedId} dataSourceName={selected?.name} />;
}
```

创建 `apps/frontend/src/pages/DataSourcesPage.tsx`(**骨架,Task 10 与 Task 11 往里填**):

```tsx
import styles from "./DataSourcesPage.module.css";

export function DataSourcesPage() {
  return (
    <section className={styles.page}>
      <h2 className={styles.title}>数据源管理</h2>
    </section>
  );
}
```

创建 `apps/frontend/src/pages/DataSourcesPage.module.css`:

```css
.page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--sp-5) 0;
}

.title {
  font-size: var(--fs-xl);
  margin-bottom: var(--sp-4);
}
```

创建 `apps/frontend/src/routes.tsx`:

```tsx
import { Navigate, Route, Routes } from "react-router-dom";
import { ChatPage } from "./pages/ChatPage";
import { DataSourcesPage } from "./pages/DataSourcesPage";

/**
 * 只两条路由。P2c 的分享页 /s/:token 与 dashboard /d/:id 到时候加两行即可,
 * 这也是 P2a 就把路由基建做掉的原因。未知路径回落对话页而不是白屏。
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="/datasources" element={<DataSourcesPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```

`apps/frontend/src/App.tsx` 全文替换为:

```tsx
import { BrowserRouter } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { DataSourcePicker } from "./components/DataSourcePicker";
import { DataSourceProvider } from "./dataSourceStore";
import { AppRoutes } from "./routes";

export const App = () => (
  <BrowserRouter>
    <DataSourceProvider>
      <AppShell toolbar={<DataSourcePicker />}>
        <AppRoutes />
      </AppShell>
    </DataSourceProvider>
  </BrowserRouter>
);
```

- [ ] **Step 15: 跑全量测试、类型检查与视觉规则 grep**

```bash
npm test --workspaces
npx tsc -p apps/frontend --noEmit
git grep -n "style={{" -- apps/frontend/src
git grep -nE "#[0-9a-fA-F]{3,8}\b" -- apps/frontend/src | grep -v "src/theme/"
```

Expected: 前端 95 + 2(api)+ 9(ChatWindow)+ 7(picker)+ 3(routes)= 116 passed,后端与 shared 不变;`tsc` 无输出;两条 grep 无新增命中。

`App.tsx` 不写单测:`BrowserRouter` 在 jsdom 里要真 history,收益低;它的组合关系由 `routes.test.tsx`(路由)与 `DataSourcePicker.test.tsx`(选择器)分别覆盖。

- [ ] **Step 16: 提交**

```bash
git add apps/frontend/package.json apps/frontend/src/api.ts apps/frontend/src/App.tsx \
  apps/frontend/src/routes.tsx apps/frontend/src/dsLabels.ts apps/frontend/src/pages \
  apps/frontend/src/components apps/frontend/src/__tests__ package-lock.json
git commit -m "feat(frontend): routing, data source picker and drill context reset on switch"
```

`package.json` / `package-lock.json` 一起进这一笔:`react-router-dom` 的依赖声明是本任务第一次真正被用到。

---

### Task 10: 表结构预览与管理页列表

`SchemaTree` 先做(P2b 的建模 UI 要复用它,所以从一开始就是独立组件),再把管理页从骨架填成「列表 + 行内操作」。新建 / 编辑表单留给 Task 11。

**Files:**
- Create: `apps/frontend/src/components/SchemaTree.tsx`
- Create: `apps/frontend/src/components/SchemaTree.module.css`
- Modify: `apps/frontend/src/pages/DataSourcesPage.tsx`(骨架 → 列表)
- Modify: `apps/frontend/src/pages/DataSourcesPage.module.css`
- Test: `apps/frontend/src/__tests__/SchemaTree.test.tsx`
- Test: `apps/frontend/src/__tests__/DataSourcesPage.test.tsx`

**Interfaces:**
- Consumes: Task 8 的 `useDataSources()`(要 `list` / `loading` / `error` / `reload`)与 `StatusBadge`;Task 9 的 `KIND_LABEL` / `PRIVILEGE_LABEL`(`src/dsLabels.ts`);Task 7 的 `testDataSource` / `refreshSchema` / `fetchSchema` / `deleteDataSource` / `ApiError`;shared 的 `TableSchema`、`SchemaResponse`。
- Produces:
  ```ts
  export function SchemaTree(props: {
    schema: TableSchema[];
    fetchedAt?: string | null;   // 缺省或 null 时不显示时间行
  }): JSX.Element;
  /** UTC ISO →「2026-08-03 10:20」。管理页的「上次检查」也用它,别再写第二份。 */
  export const fmtIsoMinute: (iso: string) => string;
  ```
  管理页对外只有 `DataSourcesPage()`,内部状态不外露。Task 11 会在它里面挂 `DataSourceForm`。

- [ ] **Step 1: 写 SchemaTree 的失败测试**

创建 `apps/frontend/src/__tests__/SchemaTree.test.tsx`:

```tsx
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
    expect(screen.getByText(/orders/)).toBeTruthy();
    expect(screen.getByText(/3 列/)).toBeTruthy();
    expect(screen.getByText(/regions/)).toBeTruthy();
  });

  it("展开一张表看到列名、类型与主键标记", () => {
    render(<SchemaTree schema={[orders]} />);
    fireEvent.click(screen.getByText(/orders/));
    expect(screen.getByText("region")).toBeTruthy();
    expect(screen.getByText("TEXT", { selector: "td" })).toBeTruthy();
    expect(screen.getByTestId("pk-id").textContent).toContain("主键");
    expect(screen.getByTestId("notnull-region").textContent).toContain("非空");
  });

  it("外键渲染成 列 → 表.列", () => {
    render(<SchemaTree schema={[orders]} />);
    fireEvent.click(screen.getByText(/orders/));
    expect(screen.getByText("region → regions.code")).toBeTruthy();
  });

  it("没有外键时不渲染外键区块", () => {
    render(<SchemaTree schema={[regions]} />);
    fireEvent.click(screen.getByText(/regions/));
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
npm test --workspace=apps/frontend -- SchemaTree
```

Expected: FAIL,`Failed to resolve import "../components/SchemaTree"`。

- [ ] **Step 3: 实现 SchemaTree**

创建 `apps/frontend/src/components/SchemaTree.tsx`:

```tsx
import type { TableSchema } from "@chatbi/shared";
import styles from "./SchemaTree.module.css";

/**
 * UTC ISO 串 → 「2026-08-03 10:20」。故意不用 toLocaleString:
 * 它的输出随宿主 locale 与时区变,测试与截图都不可复现。
 */
export const fmtIsoMinute = (iso: string): string => iso.slice(0, 16).replace("T", " ");

export function SchemaTree({ schema, fetchedAt }: { schema: TableSchema[]; fetchedAt?: string | null }) {
  if (schema.length === 0) {
    return (
      <p className={styles.empty} data-testid="schema-empty">
        暂无表结构,点「刷新结构」抓取一次。
      </p>
    );
  }

  return (
    <div className={styles.wrap}>
      {fetchedAt && (
        <p className={styles.meta} data-testid="schema-fetched-at">
          结构抓取于 {fmtIsoMinute(fetchedAt)}(UTC)
        </p>
      )}
      {schema.map(t => (
        // 用原生 details:键盘可达、无需自己管展开状态,与 SqlDisclosure 一致。
        <details key={t.tableName} className={styles.table}>
          <summary className={styles.summary}>
            <span className={styles.tableName}>{t.tableName}</span>
            <span className={styles.count}>{t.columns.length} 列</span>
          </summary>
          <table className={styles.columns}>
            <tbody>
              {t.columns.map(c => (
                <tr key={c.name}>
                  <td className={styles.colName}>{c.name}</td>
                  <td className={styles.colType}>{c.type}</td>
                  <td className={styles.flags}>
                    {c.pk && <span className={styles.flag} data-testid={`pk-${c.name}`}>主键</span>}
                    {c.notNull && !c.pk && (
                      <span className={styles.flag} data-testid={`notnull-${c.name}`}>非空</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {t.foreignKeys.length > 0 && (
            <ul className={styles.fks} data-testid="fk-list">
              {t.foreignKeys.map(fk => (
                <li key={`${fk.column}-${fk.refTable}-${fk.refColumn}`}>
                  {fk.column} → {fk.refTable}.{fk.refColumn}
                </li>
              ))}
            </ul>
          )}
        </details>
      ))}
    </div>
  );
}
```

`notNull` 与 `pk` 同时为真时只显示「主键」:主键天然非空,两个徽标并排是噪音。测试里 `notnull-id` 不存在正是这个约定。

创建 `apps/frontend/src/components/SchemaTree.module.css`:

```css
.wrap { display: flex; flex-direction: column; gap: var(--sp-2); }

.meta { color: var(--text-muted); font-size: var(--fs-xs); }

.empty { color: var(--text-muted); font-size: var(--fs-sm); }

.table {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.summary {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-3);
  cursor: pointer;
  font-size: var(--fs-sm);
}

.tableName { font-family: var(--font-mono); }

.count { color: var(--text-muted); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }

.columns {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-xs);
}

.columns td {
  padding: var(--sp-1) var(--sp-3);
  border-top: 1px solid var(--border);
}

.colName { font-family: var(--font-mono); }

.colType { color: var(--text-muted); font-family: var(--font-mono); }

.flags { text-align: right; white-space: nowrap; }

.flag {
  margin-left: var(--sp-1);
  padding: 0 var(--sp-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
}

.fks {
  margin: 0;
  padding: var(--sp-2) var(--sp-3) var(--sp-2) var(--sp-5);
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  font-family: var(--font-mono);
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
npm test --workspace=apps/frontend -- SchemaTree
```

Expected: PASS,6 个用例。

- [ ] **Step 5: 写管理页列表的失败测试**

创建 `apps/frontend/src/__tests__/DataSourcesPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { DataSourceSummary } from "@chatbi/shared";
import { DataSourcesPage } from "../pages/DataSourcesPage";
import { DataSourceProvider } from "../dataSourceStore";
import {
  ApiError, deleteDataSource, fetchSchema, listDataSources, refreshSchema, testDataSource,
} from "../api";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    listDataSources: vi.fn(), testDataSource: vi.fn(), refreshSchema: vi.fn(),
    fetchSchema: vi.fn(), deleteDataSource: vi.fn(),
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
    expect(screen.getByRole("alert").textContent).not.toContain("ECONNREFUSED");
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
    await waitFor(() => expect(screen.getByText(/orders/)).toBeTruthy());
    expect(vi.mocked(fetchSchema)).toHaveBeenCalledWith("ds1");
    click(/收起结构/);
    await waitFor(() => expect(screen.queryByText(/orders/)).toBeNull());
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
```

- [ ] **Step 6: 跑测试确认失败**

```bash
npm test --workspace=apps/frontend -- DataSourcesPage
```

Expected: FAIL,页面只有标题,`销售库` 找不到。

- [ ] **Step 7: 把管理页从骨架填成列表**

`apps/frontend/src/pages/DataSourcesPage.tsx` 全文替换为:

```tsx
import { useState } from "react";
import type { SchemaResponse } from "@chatbi/shared";
import {
  ApiError, deleteDataSource, fetchSchema, refreshSchema, testDataSource,
} from "../api";
import { useDataSources } from "../dataSourceStore";
import { KIND_LABEL, PRIVILEGE_LABEL } from "../dsLabels";
import { SchemaTree, fmtIsoMinute } from "../components/SchemaTree";
import { StatusBadge } from "../components/StatusBadge";
import styles from "./DataSourcesPage.module.css";

interface Feedback { ok: boolean; message: string; details?: string }

export function DataSourcesPage() {
  const { list, loading, error, reload } = useDataSources();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<string, Feedback>>({});
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [schema, setSchema] = useState<{ id: string; data: SchemaResponse } | null>(null);

  /**
   * 所有行内操作共用:置 busy 防连点、把 ApiError 翻成「可读消息 + 可折叠原文」、
   * 结束后重拉列表(失败也要拉:status / lastCheckError 是后端刚写进去的)。
   */
  const run = async (id: string, action: () => Promise<string>, opts: { reload?: boolean } = {}) => {
    setBusyId(id);
    try {
      const message = await action();
      if (message) setFeedback(prev => ({ ...prev, [id]: { ok: true, message } }));
    } catch (e) {
      const err = e as ApiError;
      setFeedback(prev => ({ ...prev, [id]: { ok: false, message: err.message, details: err.details } }));
    } finally {
      setBusyId(null);
      if (opts.reload !== false) await reload();
    }
  };

  const onTest = (id: string) => void run(id, async () => {
    const r = await testDataSource(id);
    return `连接正常,${r.tableCount} 张表,账号权限:${PRIVILEGE_LABEL[r.writePrivilege]}。`;
  });

  const onRefresh = (id: string) => void run(id, async () => {
    const r = await refreshSchema(id);
    // 结构面板开着就顺带换成新抓的,否则用户看到的还是旧结构。
    if (schema?.id === id) setSchema({ id, data: await fetchSchema(id) });
    return `已刷新结构,${r.tableCount} 张表,耗时 ${r.elapsedMs} ms。`;
  });

  const onDelete = (id: string) => void run(id, async () => {
    await deleteDataSource(id);
    setConfirmId(null);
    if (schema?.id === id) setSchema(null);
    return "已删除。";
  });

  const toggleSchema = (id: string) => {
    if (schema?.id === id) { setSchema(null); return; }
    void run(id, async () => {
      setSchema({ id, data: await fetchSchema(id) });
      return "";   // 展开成功不需要文字反馈,结构本身就是反馈
    }, { reload: false });
  };

  return (
    <section className={styles.page}>
      <h2 className={styles.title}>数据源管理</h2>

      {error && <p className={styles.fail} role="alert">{error}</p>}
      {loading && list.length === 0 && (
        <p className={styles.hint} data-testid="ds-loading">正在读取数据源…</p>
      )}
      {!loading && !error && list.length === 0 && (
        <p className={styles.hint} data-testid="ds-empty">还没有数据源。</p>
      )}

      <ul className={styles.rows}>
        {list.map(d => {
          const fb = feedback[d.id];
          const busy = busyId === d.id;
          const open = schema?.id === d.id;
          return (
            <li key={d.id} className={styles.row} data-testid={`ds-row-${d.id}`}>
              <div className={styles.head}>
                <span className={styles.name}>{d.name}</span>
                <span className={styles.kind}>{KIND_LABEL[d.kind]}</span>
                <code className={styles.target}>{d.target}</code>
              </div>

              <div className={styles.meta}>
                <StatusBadge status={d.status} writePrivilege={d.writePrivilege} />
                <span>{d.lastCheckAt ? `上次检查 ${fmtIsoMinute(d.lastCheckAt)}` : "从未检查"}</span>
                <span>{d.tableCount === null ? "表数量未知" : `${d.tableCount} 张表`}</span>
              </div>

              {d.lastCheckError && <p className={styles.rowError}>{d.lastCheckError}</p>}

              <div className={styles.actions}>
                <button className={styles.action} disabled={busy} onClick={() => onTest(d.id)}>测试连接</button>
                <button className={styles.action} disabled={busy} onClick={() => onRefresh(d.id)}>刷新结构</button>
                <button className={styles.action} disabled={busy} onClick={() => toggleSchema(d.id)}>
                  {open ? "收起结构" : "查看结构"}
                </button>
                <button className={styles.danger} disabled={busy} onClick={() => setConfirmId(d.id)}>删除</button>
              </div>

              {confirmId === d.id && (
                <div className={styles.confirm} role="alertdialog" aria-label="删除确认">
                  <p>确认删除「{d.name}」?引用它的看板卡片会失效。</p>
                  <div className={styles.actions}>
                    <button className={styles.danger} disabled={busy} onClick={() => onDelete(d.id)}>确认删除</button>
                    <button className={styles.action} onClick={() => setConfirmId(null)}>取消</button>
                  </div>
                </div>
              )}

              {fb && (
                <div className={fb.ok ? styles.ok : styles.fail} role={fb.ok ? "status" : "alert"}>
                  <span>{fb.message}</span>
                  {fb.details && (
                    <details className={styles.details}>
                      <summary>查看详情</summary>
                      <pre className={styles.raw}>{fb.details}</pre>
                    </details>
                  )}
                </div>
              )}

              {open && schema && <SchemaTree schema={schema.data.schema} fetchedAt={schema.data.fetchedAt} />}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
```

`apps/frontend/src/pages/DataSourcesPage.module.css` 追加(`.page` / `.title` 已在 Task 9 建好):

```css
.hint { color: var(--text-muted); font-size: var(--fs-sm); }

.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-3); }

.row {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
}

.head { display: flex; align-items: baseline; gap: var(--sp-3); flex-wrap: wrap; }

.name { font-size: var(--fs-lg); }

.kind {
  padding: 0 var(--sp-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.target { color: var(--text-muted); font-size: var(--fs-xs); font-family: var(--font-mono); }

.meta {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  flex-wrap: wrap;
  color: var(--text-muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.rowError { color: var(--negative); font-size: var(--fs-xs); }

.actions { display: flex; gap: var(--sp-2); flex-wrap: wrap; }

.action, .danger {
  padding: var(--sp-1) var(--sp-3);
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
}

.danger { color: var(--negative); border-color: var(--negative); }

.action:disabled, .danger:disabled { opacity: 0.55; }

.confirm {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-3);
  border: 1px solid var(--negative);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
}

.ok { color: var(--positive); font-size: var(--fs-sm); }

.fail { color: var(--negative); font-size: var(--fs-sm); }

.details { margin-top: var(--sp-1); font-size: var(--fs-xs); }

.raw {
  margin: var(--sp-1) 0 0;
  padding: var(--sp-2);
  background: var(--bg);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-mono);
  white-space: pre-wrap;
}
```

- [ ] **Step 8: 跑全量测试与检查**

```bash
npm test --workspace=apps/frontend -- SchemaTree DataSourcesPage
npm test --workspaces
npx tsc -p apps/frontend --noEmit
git grep -n "style={{" -- apps/frontend/src
git grep -nE "#[0-9a-fA-F]{3,8}\b" -- apps/frontend/src | grep -v "src/theme/"
```

Expected: 前端 116 + 6 + 10 = 132 passed;后端 373 + 3 skipped、shared 29 不变;`tsc` 无输出;两条 grep 无新增命中。

- [ ] **Step 9: 提交**

```bash
git add apps/frontend/src/components/SchemaTree.tsx apps/frontend/src/components/SchemaTree.module.css \
  apps/frontend/src/pages/DataSourcesPage.tsx apps/frontend/src/pages/DataSourcesPage.module.css \
  apps/frontend/src/__tests__/SchemaTree.test.tsx apps/frontend/src/__tests__/DataSourcesPage.test.tsx
git commit -m "feat(frontend): data source list with inline actions and schema preview"
```

---

### Task 11: 新建 / 编辑表单与就地测连

管理页现在只能看和删。这一任务补上增和改:按 kind 变化的字段、就地「测试连接」、失败时的「仍然保存」。

**后端已定的三条行为**(照它写前端,别猜):
1. `POST /api/datasources` 不带 `force` 时会先测连;失败回 `canForce: true` 且**不落库**。带 `force: true` 则跳过测连直接存,并把状态记成 `error`(消息「保存时跳过了连接测试,请点『测试连接』确认」)。
2. `PUT /api/datasources/:id` **不测连**,直接存 + 断掉旧连接。密码三态:字段缺失 = 保留旧密码,`""` = 真的清空,有值 = 换新的。所以密码框留空时**必须不发 password 字段**。
3. 新建时缺密码(非 sqlite)后端回 `UNKNOWN` +「缺少密码:新建连接或更换数据库类型时必须填写密码」;重名回 `DUPLICATE_NAME`。

**Files:**
- Create: `apps/frontend/src/components/DataSourceForm.tsx`
- Create: `apps/frontend/src/components/DataSourceForm.module.css`
- Modify: `apps/frontend/src/pages/DataSourcesPage.tsx`(「新建数据源」按钮 + 行内「编辑」+ 挂表单)
- Modify: `apps/frontend/src/pages/DataSourcesPage.module.css`(加 `.toolbar`)
- Test: `apps/frontend/src/__tests__/DataSourceForm.test.tsx`
- Modify test: `apps/frontend/src/__tests__/DataSourcesPage.test.tsx`(补 3 个集成用例)

**Interfaces:**
- Consumes: Task 7 的 `testDsConfig` / `createDataSource` / `updateDataSource` / `getDataSource` / `ApiError`;Task 9 的 `KIND_LABEL` / `PRIVILEGE_LABEL`;Task 8 的 `useDataSources().reload`;shared 的 `DataSourceDetail`、`DsConfigInput`、`DataSourceKind`。
- Produces:
  ```ts
  export function DataSourceForm(props: {
    initial?: DataSourceDetail;   // 有 = 编辑,无 = 新建
    onSaved: () => void;          // 保存成功;由页面负责 reload + 关表单
    onCancel: () => void;
  }): JSX.Element;
  ```

- [ ] **Step 1: 写表单的失败测试**

创建 `apps/frontend/src/__tests__/DataSourceForm.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { DataSourceDetail } from "@chatbi/shared";
import { DataSourceForm } from "../components/DataSourceForm";
import { ApiError, createDataSource, testDsConfig, updateDataSource } from "../api";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, testDsConfig: vi.fn(), createDataSource: vi.fn(), updateDataSource: vi.fn() };
});

const detail: DataSourceDetail = {
  id: "ds1", name: "销售库", kind: "mysql", target: "mysql://bi_ro@10.0.0.5:3306/sales",
  status: "ok", writePrivilege: "readonly", lastCheckAt: null, lastCheckError: null,
  schemaFetchedAt: null, tableCount: 12, hasPassword: true,
  connection: { host: "10.0.0.5", port: 3306, database: "sales", user: "bi_ro", ssl: false },
};

const onSaved = vi.fn();
const onCancel = vi.fn();
const mount = (initial?: DataSourceDetail) =>
  render(<DataSourceForm initial={initial} onSaved={onSaved} onCancel={onCancel} />);

const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: RegExp | string) => fireEvent.click(screen.getByRole("button", { name }));

/** 新建一个 MySQL 源要填的最少字段。 */
const fillMysql = () => {
  fill("名称", "销售库");
  fireEvent.change(screen.getByLabelText("数据库类型"), { target: { value: "mysql" } });
  fill("主机", "10.0.0.5");
  fill("数据库", "sales");
  fill("用户名", "bi_ro");
  fill("密码", "s3cret");
};

beforeEach(() => {
  onSaved.mockReset();
  onCancel.mockReset();
  vi.mocked(testDsConfig).mockReset();
  vi.mocked(createDataSource).mockReset();
  vi.mocked(updateDataSource).mockReset();
});

describe("表单字段随 kind 变化", () => {
  it("sqlite 只要文件路径", () => {
    mount();
    expect(screen.getByLabelText("文件路径")).toBeTruthy();
    expect(screen.queryByLabelText("主机")).toBeNull();
  });

  it("换成 mysql 出现主机/端口/库/用户/密码/SSL,没有 schema", () => {
    mount();
    fireEvent.change(screen.getByLabelText("数据库类型"), { target: { value: "mysql" } });
    for (const l of ["主机", "端口", "数据库", "用户名", "密码"]) {
      expect(screen.getByLabelText(l)).toBeTruthy();
    }
    expect(screen.getByLabelText("启用 SSL")).toBeTruthy();
    expect(screen.queryByLabelText("schema")).toBeNull();
    expect(screen.queryByLabelText("文件路径")).toBeNull();
  });

  it("postgres 多一个 schema 字段", () => {
    mount();
    fireEvent.change(screen.getByLabelText("数据库类型"), { target: { value: "postgres" } });
    expect(screen.getByLabelText("schema")).toBeTruthy();
  });

  it("端口留空按 kind 用默认值", async () => {
    vi.mocked(createDataSource).mockResolvedValue(detail);
    mount();
    fillMysql();
    click("保存");
    await waitFor(() => expect(vi.mocked(createDataSource)).toHaveBeenCalled());
    expect(vi.mocked(createDataSource).mock.calls[0][1]).toMatchObject({ kind: "mysql", port: 3306 });
  });
});

describe("表单测连", () => {
  it("测连成功显示表数量与权限", async () => {
    vi.mocked(testDsConfig).mockResolvedValue({ ok: true, writePrivilege: "writable", tableCount: 9 });
    mount();
    fillMysql();
    click("测试连接");
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("9 张表"));
    expect(screen.getByRole("status").textContent).toContain("可写");
    expect(vi.mocked(testDsConfig).mock.calls[0][0]).toMatchObject({
      kind: "mysql", host: "10.0.0.5", database: "sales", user: "bi_ro", password: "s3cret", ssl: false,
    });
  });

  it("测连失败显示可读消息,原文折在详情里", async () => {
    vi.mocked(testDsConfig).mockRejectedValue(
      new ApiError("AUTH_ERROR", "认证失败,请检查用户名与密码", "ER_ACCESS_DENIED_ERROR"),
    );
    mount();
    fillMysql();
    click("测试连接");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("认证失败"));
    fireEvent.click(screen.getByText("查看详情"));
    expect(screen.getByText(/ER_ACCESS_DENIED_ERROR/)).toBeTruthy();
  });
});

describe("新建", () => {
  it("名称为空时不发请求,就地提示", () => {
    mount();
    click("保存");
    expect(vi.mocked(createDataSource)).not.toHaveBeenCalled();
    expect(screen.getByTestId("name-error").textContent).toContain("请填写数据源名称");
  });

  it("保存成功回调 onSaved", async () => {
    vi.mocked(createDataSource).mockResolvedValue(detail);
    mount();
    fill("名称", "示例库");
    fill("文件路径", "./data/chatbi.db");
    click("保存");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(vi.mocked(createDataSource).mock.calls[0][0]).toBe("示例库");
    expect(vi.mocked(createDataSource).mock.calls[0][1]).toEqual({ kind: "sqlite", path: "./data/chatbi.db" });
    expect(vi.mocked(createDataSource).mock.calls[0][2]).toBeUndefined();
  });

  it("测连失败但 canForce 时给「仍然保存」,点它带 force 重发", async () => {
    vi.mocked(createDataSource)
      .mockRejectedValueOnce(new ApiError("CONNECTION_ERROR", "无法连接到 10.0.0.5:3306", "ECONNREFUSED", true))
      .mockResolvedValueOnce(detail);
    mount();
    fillMysql();
    click("保存");
    await waitFor(() => expect(screen.getByRole("button", { name: "仍然保存" })).toBeTruthy());
    click("仍然保存");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(vi.mocked(createDataSource).mock.calls[1][2]).toBe(true);
  });

  it("canForce 不为真时不给「仍然保存」", async () => {
    vi.mocked(createDataSource).mockRejectedValue(new ApiError("DB_NOT_FOUND", "数据库 sales 不存在"));
    mount();
    fillMysql();
    click("保存");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("不存在"));
    expect(screen.queryByRole("button", { name: "仍然保存" })).toBeNull();
  });

  it("重名错误落到名称字段旁", async () => {
    vi.mocked(createDataSource).mockRejectedValue(new ApiError("DUPLICATE_NAME", "已有同名数据源"));
    mount();
    fill("名称", "销售库");
    fill("文件路径", "./x.db");
    click("保存");
    await waitFor(() => expect(screen.getByTestId("name-error").textContent).toContain("已有同名数据源"));
  });
});

describe("编辑", () => {
  it("回填已有连接字段,并说明密码留空表示不改", () => {
    mount(detail);
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe("销售库");
    expect((screen.getByLabelText("主机") as HTMLInputElement).value).toBe("10.0.0.5");
    expect((screen.getByLabelText("端口") as HTMLInputElement).value).toBe("3306");
    expect((screen.getByLabelText("用户名") as HTMLInputElement).value).toBe("bi_ro");
    expect((screen.getByLabelText("密码") as HTMLInputElement).value).toBe("");
    expect(screen.getByTestId("password-hint").textContent).toContain("留空表示不修改");
  });

  it("密码留空时请求体里不带 password", async () => {
    vi.mocked(updateDataSource).mockResolvedValue(detail);
    mount(detail);
    click("保存");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const input = vi.mocked(updateDataSource).mock.calls[0][2] as Record<string, unknown>;
    expect("password" in input).toBe(false);
    expect(vi.mocked(updateDataSource).mock.calls[0][0]).toBe("ds1");
  });

  it("填了新密码就带上", async () => {
    vi.mocked(updateDataSource).mockResolvedValue(detail);
    mount(detail);
    fill("密码", "newpass");
    click("保存");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(vi.mocked(updateDataSource).mock.calls[0][2]).toMatchObject({ password: "newpass" });
  });

  it("取消回调 onCancel", () => {
    mount(detail);
    click("取消");
    expect(onCancel).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
npm test --workspace=apps/frontend -- DataSourceForm
```

Expected: FAIL,`Failed to resolve import "../components/DataSourceForm"`。

- [ ] **Step 3: 实现表单**

创建 `apps/frontend/src/components/DataSourceForm.tsx`:

```tsx
import { useState } from "react";
import type { DataSourceDetail, DataSourceKind, DsConfigInput } from "@chatbi/shared";
import { ApiError, createDataSource, testDsConfig, updateDataSource } from "../api";
import { KIND_LABEL, PRIVILEGE_LABEL } from "../dsLabels";
import styles from "./DataSourceForm.module.css";

const KINDS: DataSourceKind[] = ["sqlite", "mysql", "postgres"];
const DEFAULT_PORT: Record<"mysql" | "postgres", number> = { mysql: 3306, postgres: 5432 };

interface Feedback { ok: boolean; message: string; details?: string; canForce?: boolean }

export function DataSourceForm({ initial, onSaved, onCancel }: {
  initial?: DataSourceDetail;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [kind, setKind] = useState<DataSourceKind>(initial?.kind ?? "sqlite");
  const [path, setPath] = useState(initial?.connection.path ?? "");
  const [host, setHost] = useState(initial?.connection.host ?? "");
  const [port, setPort] = useState(initial?.connection.port ? String(initial.connection.port) : "");
  const [database, setDatabase] = useState(initial?.connection.database ?? "");
  const [user, setUser] = useState(initial?.connection.user ?? "");
  const [password, setPassword] = useState("");
  const [ssl, setSsl] = useState(initial?.connection.ssl ?? false);
  const [pgSchema, setPgSchema] = useState(initial?.connection.schema ?? "");
  const [busy, setBusy] = useState(false);
  const [fb, setFb] = useState<Feedback | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);

  const buildInput = (): DsConfigInput => {
    if (kind === "sqlite") return { kind, path: path.trim() };
    const common = {
      host: host.trim(),
      // 留空按 kind 取默认端口:让用户少填一格,又不用在切 kind 时去同步输入框。
      port: port.trim() === "" ? DEFAULT_PORT[kind] : Number(port),
      database: database.trim(),
      user: user.trim(),
      ssl,
      // 空密码 = 不发这个字段。后端把「字段缺失」当作保留旧密码,把 "" 当作清空。
      ...(password === "" ? {} : { password }),
    };
    return kind === "mysql"
      ? { kind, ...common }
      : { kind, ...common, ...(pgSchema.trim() === "" ? {} : { schema: pgSchema.trim() }) };
  };

  const fail = (e: unknown) => {
    const err = e as ApiError;
    // 重名要能定位到出错的输入框,光在底部报错用户会去改连接参数。
    if (err.code === "DUPLICATE_NAME") setNameError(err.message);
    setFb({ ok: false, message: err.message, details: err.details, canForce: err.canForce });
  };

  const test = async () => {
    setBusy(true); setFb(null);
    try {
      const r = await testDsConfig(buildInput());
      setFb({ ok: true, message: `连接正常,${r.tableCount} 张表,账号权限:${PRIVILEGE_LABEL[r.writePrivilege]}。` });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const save = async (force?: boolean) => {
    if (name.trim() === "") { setNameError("请填写数据源名称"); return; }
    setBusy(true); setFb(null); setNameError(null);
    try {
      if (initial) await updateDataSource(initial.id, name.trim(), buildInput());
      else await createDataSource(name.trim(), buildInput(), force);
      onSaved();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className={styles.form} onSubmit={e => { e.preventDefault(); void save(); }}>
      <h3 className={styles.title}>{initial ? "编辑数据源" : "新建数据源"}</h3>

      <div className={styles.field}>
        <label htmlFor="dsf-name">名称</label>
        <input id="dsf-name" className={styles.input} value={name} onChange={e => setName(e.target.value)} />
        {nameError && <p className={styles.fieldError} data-testid="name-error">{nameError}</p>}
      </div>

      <div className={styles.field}>
        <label htmlFor="dsf-kind">数据库类型</label>
        <select
          id="dsf-kind" className={styles.input} value={kind}
          onChange={e => setKind(e.target.value as DataSourceKind)}
        >
          {KINDS.map(k => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
        </select>
      </div>

      {kind === "sqlite" ? (
        <div className={styles.field}>
          <label htmlFor="dsf-path">文件路径</label>
          <input
            id="dsf-path" className={styles.input} value={path}
            placeholder="./data/chatbi.db" onChange={e => setPath(e.target.value)}
          />
        </div>
      ) : (
        <>
          <div className={styles.row}>
            <div className={styles.field}>
              <label htmlFor="dsf-host">主机</label>
              <input id="dsf-host" className={styles.input} value={host} onChange={e => setHost(e.target.value)} />
            </div>
            <div className={styles.fieldNarrow}>
              <label htmlFor="dsf-port">端口</label>
              <input
                id="dsf-port" className={styles.input} value={port} inputMode="numeric"
                placeholder={String(DEFAULT_PORT[kind])} onChange={e => setPort(e.target.value)}
              />
            </div>
          </div>

          <div className={styles.row}>
            <div className={styles.field}>
              <label htmlFor="dsf-database">数据库</label>
              <input
                id="dsf-database" className={styles.input} value={database}
                onChange={e => setDatabase(e.target.value)}
              />
            </div>
            {kind === "postgres" && (
              <div className={styles.field}>
                <label htmlFor="dsf-schema">schema</label>
                <input
                  id="dsf-schema" className={styles.input} value={pgSchema}
                  placeholder="public" onChange={e => setPgSchema(e.target.value)}
                />
              </div>
            )}
          </div>

          <div className={styles.row}>
            <div className={styles.field}>
              <label htmlFor="dsf-user">用户名</label>
              <input id="dsf-user" className={styles.input} value={user} onChange={e => setUser(e.target.value)} />
            </div>
            <div className={styles.field}>
              <label htmlFor="dsf-password">密码</label>
              <input
                id="dsf-password" className={styles.input} type="password" value={password}
                onChange={e => setPassword(e.target.value)}
              />
              {initial?.hasPassword && (
                <p className={styles.hint} data-testid="password-hint">留空表示不修改已保存的密码。</p>
              )}
            </div>
          </div>

          <label className={styles.checkbox} htmlFor="dsf-ssl">
            <input
              id="dsf-ssl" type="checkbox" checked={ssl} onChange={e => setSsl(e.target.checked)}
            />
            启用 SSL
          </label>
        </>
      )}

      <div className={styles.actions}>
        <button type="button" className={styles.action} disabled={busy} onClick={() => void test()}>测试连接</button>
        <button type="submit" className={styles.primary} disabled={busy}>保存</button>
        {fb?.canForce && (
          <button type="button" className={styles.action} disabled={busy} onClick={() => void save(true)}>
            仍然保存
          </button>
        )}
        <button type="button" className={styles.action} onClick={onCancel}>取消</button>
      </div>

      {fb && (
        <div className={fb.ok ? styles.ok : styles.fail} role={fb.ok ? "status" : "alert"}>
          <span>{fb.message}</span>
          {fb.details && (
            <details className={styles.details}>
              <summary>查看详情</summary>
              <pre className={styles.raw}>{fb.details}</pre>
            </details>
          )}
          {fb.canForce && <p className={styles.hint}>库可能只是暂时不可达。点「仍然保存」先存下配置,状态会标成待检查。</p>}
        </div>
      )}
    </form>
  );
}
```

`启用 SSL` 用 `<label>` 包住 `<input type="checkbox">` 且带 `htmlFor`,`getByLabelText("启用 SSL")` 才拿得到那个 checkbox。

创建 `apps/frontend/src/components/DataSourceForm.module.css`:

```css
.form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4);
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
}

.title { font-size: var(--fs-lg); }

.row { display: flex; gap: var(--sp-3); flex-wrap: wrap; }

.field, .fieldNarrow {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  font-size: var(--fs-sm);
}

.field { flex: 1; min-width: 160px; }

.fieldNarrow { width: 96px; }

.input {
  padding: var(--sp-2) var(--sp-3);
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
}

.checkbox {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
}

.actions { display: flex; gap: var(--sp-2); flex-wrap: wrap; }

.action, .primary {
  padding: var(--sp-2) var(--sp-4);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
}

.action {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border-strong);
}

.primary {
  background: var(--accent);
  color: var(--on-accent);
  border: 1px solid var(--accent);
  font-weight: 600;
}

.action:disabled, .primary:disabled { opacity: 0.55; }

.hint { color: var(--text-muted); font-size: var(--fs-xs); }

.fieldError { color: var(--negative); font-size: var(--fs-xs); }

.ok { color: var(--positive); font-size: var(--fs-sm); }

.fail { color: var(--negative); font-size: var(--fs-sm); }

.details { font-size: var(--fs-xs); }

.raw {
  margin: var(--sp-1) 0 0;
  padding: var(--sp-2);
  background: var(--bg);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-mono);
  white-space: pre-wrap;
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
npm test --workspace=apps/frontend -- DataSourceForm
```

Expected: PASS,15 个用例。

- [ ] **Step 5: 写管理页挂表单的失败测试**

在 `apps/frontend/src/__tests__/DataSourcesPage.test.tsx` 里,`vi.mock("../api", …)` 的桩清单补三个:

```tsx
    listDataSources: vi.fn(), testDataSource: vi.fn(), refreshSchema: vi.fn(),
    fetchSchema: vi.fn(), deleteDataSource: vi.fn(),
    getDataSource: vi.fn(), createDataSource: vi.fn(), updateDataSource: vi.fn(),
```

顶部 import 补 `createDataSource, getDataSource`,`beforeEach` 里补 `vi.mocked(getDataSource).mockReset(); vi.mocked(createDataSource).mockReset();`,并在文件末尾追加:

```tsx
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
```

- [ ] **Step 6: 跑测试确认失败**

```bash
npm test --workspace=apps/frontend -- DataSourcesPage
```

Expected: FAIL,找不到「新建数据源」与「编辑」按钮。

- [ ] **Step 7: 管理页挂上表单**

`apps/frontend/src/pages/DataSourcesPage.tsx` 做四处改动:

1. import 补上表单、详情接口与 `getDataSource`:

```tsx
import type { DataSourceDetail, SchemaResponse } from "@chatbi/shared";
import {
  ApiError, deleteDataSource, fetchSchema, getDataSource, refreshSchema, testDataSource,
} from "../api";
import { DataSourceForm } from "../components/DataSourceForm";
```

2. 状态里加表单开关(`null` = 没开;`{ detail }` 的 `detail` 缺省即新建):

```tsx
  const [form, setForm] = useState<{ detail?: DataSourceDetail } | null>(null);
```

3. 加打开编辑的处理器,放在 `toggleSchema` 之后:

```tsx
  const onEdit = (id: string) => void run(id, async () => {
    // 列表里的 summary 没有连接字段,回填必须拿 detail。
    setForm({ detail: await getDataSource(id) });
    return "";
  }, { reload: false });
```

4. 渲染:标题下面加工具栏与表单,行内操作加「编辑」按钮:

```tsx
      <h2 className={styles.title}>数据源管理</h2>

      <div className={styles.toolbar}>
        <button className={styles.action} onClick={() => setForm({})}>新建数据源</button>
      </div>

      {form && (
        <DataSourceForm
          initial={form.detail}
          onSaved={() => { setForm(null); void reload(); }}
          onCancel={() => setForm(null)}
        />
      )}
```

```tsx
                <button className={styles.action} disabled={busy} onClick={() => onEdit(d.id)}>编辑</button>
                <button className={styles.danger} disabled={busy} onClick={() => setConfirmId(d.id)}>删除</button>
```

`apps/frontend/src/pages/DataSourcesPage.module.css` 追加:

```css
.toolbar { display: flex; justify-content: flex-end; margin-bottom: var(--sp-3); }
```

- [ ] **Step 8: 跑全量测试与检查**

```bash
npm test --workspaces
npx tsc -p apps/frontend --noEmit
git grep -n "style={{" -- apps/frontend/src
git grep -nE "#[0-9a-fA-F]{3,8}\b" -- apps/frontend/src | grep -v "src/theme/"
```

Expected: 前端 132 + 15 + 3 = 150 passed;后端 373 + 3 skipped、shared 29 不变;`tsc` 无输出;两条 grep 无新增命中。

- [ ] **Step 9: 提交**

```bash
git add apps/frontend/src/components/DataSourceForm.tsx \
  apps/frontend/src/components/DataSourceForm.module.css \
  apps/frontend/src/pages/DataSourcesPage.tsx apps/frontend/src/pages/DataSourcesPage.module.css \
  apps/frontend/src/__tests__/DataSourceForm.test.tsx apps/frontend/src/__tests__/DataSourcesPage.test.tsx
git commit -m "feat(frontend): data source create/edit form with inline connection test"
```

---

### Task 12: README、部署注意事项与浏览器端回归

代码到这里就齐了。这一任务只做两件事:把新增的两条运行注意事项写进 README(路由需要 history fallback 是最容易在换部署方式时被忘掉的),以及跑一遍自动化测试验不到的浏览器检查。

**Files:**
- Modify: `README.md`(「运行」段、「手动验收清单」段、「已知限制」段)

**Interfaces:** 无新代码。

- [ ] **Step 1: README 的「运行」段补数据源入口**

在 `## 运行` 的第 4 步之后、`模型默认值是 …` 那段之前插入一段:

```markdown
首次启动会在 `apps/backend/data/app.db` 里注册一个内置的「示例订单库」(sqlite),顶栏的数据源选择器默认选它。要接 MySQL / PostgreSQL,点顶栏右侧的「管理」进 `/datasources` 新建:填连接参数 → 「测试连接」→ 保存。选中哪个源,提问就走哪个源。
```

- [ ] **Step 2: README 的「手动验收清单」拆成两段**

把 `## 手动验收清单` 下的引导句与 9 条改成:

```markdown
## 手动验收清单

### A. P1 回归(在「示例订单库」上问,9 条原样)

发版前依次问,人工确认图表类型、数据与洞察:
```

(原来的 9 条一条不动地留在这里,后面追加 B 段)

```markdown
### B. P2a 数据源相关

完整的 15 条在 [P2a 设计 spec 第 12 节](docs/superpowers/specs/2026-07-31-chatbi-p2-datasource-design.md)(含真库方言、错误提示、超时、凭据落盘检查),那份是唯一出处,别在这里抄第二份。每次发版至少跑这三条最小回归:

1. 在 A 源做完一轮下钻,切到 B 源 → 会话里出现「已切换到数据源 B」分隔提示,下一问的 SQL **不是**在 A 的 SQL 上改写(展开「查看 SQL」确认)
2. `strings apps/backend/data/app.db | grep <你填的数据库密码>` → 无命中
3. 删除一个数据源 → 二次确认提到「引用它的看板卡片会失效」,删除后 `schema_cache` 里对应行也没了
```

- [ ] **Step 3: README 的「已知限制」补两条**

在 `## 已知限制` 末尾追加:

```markdown
- 前端现在是 `BrowserRouter` 两条路由(`/` 与 `/datasources`)。Vite dev server 自带 history fallback,但换成任何静态托管(nginx、`serve`、Caddy)都必须把未命中的路径重写到 `index.html`,否则刷新 `/datasources` 会 404。P2c 的分享页 `/s/:token` 同理。
- 数据源列表与选中项在前端是内存 + `localStorage`(键 `chatbi.selectedDataSourceId`)。多标签页同时改数据源不会互相同步,刷新后以服务端列表为准。
- 管理页的连接测试是同步等待的:填了不可达的地址时,「测试连接」会挂到后端超时(`QUERY_TIMEOUT_MS`)才给结果。
```

- [ ] **Step 4: 跑全量自动化验证**

```bash
npm test --workspaces
npx tsc -p apps/frontend --noEmit
npm run build
git grep -n "style={{" -- apps/frontend/src
git grep -nE "#[0-9a-fA-F]{3,8}\b" -- apps/frontend/src | grep -v "src/theme/"
git grep -n "datasource-slot" -- apps/frontend/src
```

Expected: 150 前端 + 373 后端(+3 skipped)+ 29 shared 全绿;`tsc` 与 `build` 无错;`style={{` 无命中;颜色字面量只剩 `src/theme/` 外的三处 `#ffffff`(P1b 遗留,不新增);`datasource-slot` 只在 `AppShell.tsx` 与 `AppShell.test.tsx` 各一处。

- [ ] **Step 5: 浏览器里跑三项自动化验不到的检查**

起前后端(`npm run dev --workspace=apps/backend` + `npm run dev --workspace=apps/frontend`),在 http://localhost:5173 依次确认,把结果记进本文件末尾的「实施期的偏差记录」:

1. **键盘可达**:从顶栏开始按 Tab,能依次走到数据源下拉、「管理」链接、输入框、发送;在 `/datasources` 能走完每行的四个按钮与表单的每个字段,`Enter` 能展开 `<details>` 的「查看结构」与「查看详情」。
2. **200% 缩放**:浏览器缩放到 200%,`/datasources` 的行不重叠、按钮不溢出、表单字段换行而不是被裁掉。
3. **深浅色**:切换系统深浅色,四种状态点(正常 / 连接失败 / 需重新填写凭据 / 未检查)与「建议改用只读账号」徽标在两套配色下都能分辨,且每个状态点旁边都有文字说明(颜色不是唯一信息载体)。

- [ ] **Step 6: 提交**

```bash
git add README.md docs/superpowers/plans/2026-08-03-chatbi-p2a2b-frontend-ui.md
git commit -m "docs: data source UI notes in README and P2a-2 frontend acceptance checks"
```

---

## 本计划完成时的状态

- 顶栏有数据源选择器,选中项刷新页面不丢;源被删掉会自动回落到第一个可用源。
- `/` 与 `/datasources` 两条路由通,未知路径回落对话页;换静态托管要配 history fallback(已写进 README)。
- 切源时会话里出现分隔提示,旧轮次留在界面上但不再进 `history` / `DrillContext`。
- `/datasources` 能增、删、改、测连、刷新结构、看表结构;测连失败给可读消息 + 可折叠原文 + 「仍然保存」。
- 前端测试 150 个;`npm test --workspaces` 全绿;`style={{`、组件内颜色字面量两条 grep 仍零新增命中。
- **P2a 到此代码完备**,剩下的是 spec 第 12 节那 15 条真库人工验收(需要起 MySQL / PG)。

## 自查记录

写完后对着 [P2a 设计 spec](../specs/2026-07-31-chatbi-p2-datasource-design.md) 第 8 / 9 / 12 节逐条核过:

- **spec 第 8 节全覆盖**:路由两条(Task 9)、选择器 + localStorage + 启动校验 + 空列表禁用输入 + 状态点(Task 8/9)、切源清下钻上下文 + 分隔提示(Task 9)、管理页列表六列 + 四个行内操作 + 二次确认提到看板卡片(Task 10)、表单按 kind 变字段 + 就地测连 + 「仍然保存」(Task 11)、`SchemaTree` 拆成独立组件供 P2b 复用(Task 10)、视觉规则用两条 grep 守住(每个任务的验证步骤)。
- **spec 第 9 节的前端部分**:数据源连不上时服务照常启动、列表里显示状态 → 由 `StatusBadge` 的四种状态覆盖;`app.key` 丢失后的 `needs_reconfig` 对应文案「需重新填写凭据」,与 spec 的「凭据无法解密,请重新填写」同义。重试分类是后端 Task 3 的事,本篇不重复。
- **spec 第 12 节**:Task 12 只在 README 放三条最小回归 + 指向 spec,不抄第二份清单(抄了必然与 spec 漂移)。
- **两处对 File Structure 的修正**(发现即回改,而不是留给执行者踩):① `api.ts` 的 `streamChat` 改动从 Task 8 移到 Task 9——`dataSourceId` 必填,和 `ChatWindow` 必须同一笔改才有能编译的中间状态;② 新增 `src/dsLabels.ts`,原本 `KIND_LABEL` / `PRIVILEGE_LABEL` 要在选择器、管理页、表单里各写一份。
- **类型一致性**:`Message.epoch` 是必填,所以 Task 9 把三处构造点(user / assistant / notice)全列了出来;`fmtIsoMinute` 由 `SchemaTree` 导出、管理页复用,没有第二份时间格式化;`StatusBadge` 的 props 在选择器与管理页两处调用签名相同;表单的 `DsConfigInput` 构造与后端 `parseDsConfigInput` 的字段名逐个对齐(含 `schema` 只在 postgres 且非空时才发)。
- **一个刻意的取舍**:`DataSourcesPage.tsx` 到 Task 11 结束约 200 行,是本篇最大的文件。没有再拆是因为「列表行 + 行内操作 + 表单开关」共享 `busy` / `feedback` / 展开态三份状态,拆开就要把这三份状态提上去或者用 Context,得不偿失;真要拆,P2b 加建模入口时再把行抽成 `DataSourceRow`。

## 实施期的偏差记录(2026-08-03 执行时补)

1. **前端测试总数是 149,不是计划里的 150。** Task 9 Step 1 计划新增两个请求体用例,但 `api.test.ts` 里「无 context 时 body 里不出现该字段」**早已存在**(P1 就写了),只补了 `dataSourceId` 那一条。另外那两处 `streamChat` 直调(错误路径的 describe)也要补 `dataSourceId`,计划漏写了。
2. **`SchemaTree` 测试的正则匹配器改成精确字符串。** `screen.getByText(/regions/)` 会同时命中表名 span 与外键行 `region → regions.code`(`<details>` 折叠但内容仍在 DOM 里),报 "Found multiple elements"。改成 `getByText("regions")` —— 外键行的完整文本不等于 `regions`,精确匹配唯一。
3. **「原文不外露」的断言方式改了。** 计划写 `expect(alert.textContent).not.toContain("ECONNREFUSED")`,但原文就在这个 alert 内部的 `<details>` 里,`textContent` 必然包含它。改成断言 `details.open === false`——「默认折叠」才是真正要保的行为。`DataSourceForm` 的同类用例本来就没写这条断言,不受影响。
4. **顺手修了 README「测试」段的过期计数**(后端 171 → 373、前端 67 → 149、全仓 267 → 551 + 3 skipped)。P2a-1 起就已经不准,而 Task 12 正在改同一个文件,留着是错的。
5. **Task 12 Step 5 的三项浏览器检查没跑**(键盘 Tab 走位、200% 缩放、深浅色下状态色可辨)。需要人在真浏览器里看,自动化测试代替不了。三项都还是未勾选状态,验收前请手工过一遍;`StatusBadge` 的「颜色不是唯一信息载体」已有单测兜底(状态点 `aria-hidden` + 文字标签)。
6. 其余 49 个步骤按计划执行,没有别的偏差。每个任务结束时 `npm test --workspaces` 全绿:后端 373 + 3 skipped、前端 149、shared 29;`tsc --noEmit` 与 `npm run build` 均通过;`style={{` 与组件内颜色字面量两条 grep 无新增命中。
