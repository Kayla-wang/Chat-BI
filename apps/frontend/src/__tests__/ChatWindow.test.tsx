import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ChatWindow } from "../components/ChatWindow";
import { streamChat } from "../api";
import type { ResultPayload, StreamEvent } from "@chatbi/shared";

vi.mock("../api", () => ({ streamChat: vi.fn() }));
// 同 ResultCard.test.tsx:jsdom 无 canvas,真实 ECharts 会抛异步异常。
vi.mock("echarts", () => ({
  init: () => ({ setOption: () => {}, dispose: () => {}, resize: () => {} }),
}));

/** 每次调用记录 opts,并把 onEvent 存下来由测试驱动。 */
let calls: any[] = [];
let resolvers: (() => void)[] = [];

beforeEach(() => {
  calls = [];
  resolvers = [];
  vi.mocked(streamChat).mockImplementation((opts: any) => {
    calls.push(opts);
    return new Promise<void>(res => resolvers.push(res));
  });
});

const CURRENCY = { kind: "currency" as const, decimals: 0, unit: "元", scale: 1 as const };

const payload = (queryIntent: string, sql: string): ResultPayload => ({
  spec: {
    chartType: "bar", stack: "none",
    x: { field: "region", role: "categorical", labels: ["华东"] },
    series: [{ name: "total", field: "total", data: [100], format: CURRENCY }],
    notes: [],
  },
  table: { columns: ["region", "total"], rows: [{ region: "华东", total: 100 }] },
  queryIntent, sql,
});

const ask = (text: string) => {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /发送/ }));
};

const drive = (i: number, events: StreamEvent[]) => act(() => {
  for (const e of events) calls[i].onEvent(e);
});

const finish = (i: number) => act(async () => { resolvers[i](); });

/** 切源 = 父组件传新的 dataSourceId 重渲染。 */
const switchTo = (view: ReturnType<typeof render>, id: string | null, name?: string) =>
  view.rerender(<ChatWindow dataSourceId={id} dataSourceName={name} />);

describe("ChatWindow 单轮", () => {
  it("提交后显示用户问题", async () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("各地区销售额");
    await waitFor(() => expect(screen.getByText("各地区销售额")).toBeTruthy());
  });

  it("result → 表格,insightDelta → 洞察文本", async () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("各地区销售额");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [
      { type: "result", payload: payload("按地区汇总", "SELECT region FROM orders") },
      { type: "insightFacts", facts: [{ kind: "total", series: "total", value: 100 }] },
      { type: "insightDelta", text: "华东" },
      { type: "insightDelta", text: "区领先。" },
      { type: "done" },
    ]);
    await waitFor(() => expect(screen.getByText("按地区汇总")).toBeTruthy());
    expect(screen.getByText("华东", { selector: "td" })).toBeTruthy();
    expect(screen.getByTestId("insight-text").textContent).toBe("华东区领先。");
  });

  it("error 事件渲染成文本,不吞掉整轮", async () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("q");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [{ type: "error", message: "Ollama 未运行" }]);
    await waitFor(() => expect(screen.getByText(/\[错误\] Ollama 未运行/)).toBeTruthy());
  });
});

describe("ChatWindow 多轮与下钻", () => {
  it("第二轮带上第一轮的 sql 作为 context", async () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("按月统计订单金额");
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].context).toBeUndefined();
    drive(0, [
      { type: "result", payload: payload("统计每月订单总额", "SELECT month, SUM(x) AS amount FROM orders GROUP BY month") },
      { type: "done" },
    ]);
    await finish(0);

    ask("只看华东区");
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].context).toEqual({
      lastSql: "SELECT month, SUM(x) AS amount FROM orders GROUP BY month",
      lastColumns: ["region", "total"],
    });
  });

  it("history 里助手侧用的是 queryIntent", async () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("q1");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [{ type: "result", payload: payload("意图一", "SELECT 1") }, { type: "done" }]);
    await finish(0);
    ask("q2");
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].history).toEqual([
      { role: "user", text: "q1" },
      { role: "assistant", text: "意图一" },
    ]);
  });

  it("两轮的事件各自只更新自己的气泡", async () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("q1");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [
      { type: "result", payload: payload("意图一", "SELECT 1") },
      { type: "insightDelta", text: "洞察一" },
      { type: "done" },
    ]);
    await finish(0);

    ask("q2");
    await waitFor(() => expect(calls).toHaveLength(2));
    drive(1, [
      { type: "result", payload: payload("意图二", "SELECT 2") },
      { type: "insightDelta", text: "洞察二" },
      { type: "done" },
    ]);
    await waitFor(() => expect(screen.getByText("意图二")).toBeTruthy());

    const texts = screen.getAllByTestId("insight-text").map(n => n.textContent);
    expect(texts).toEqual(["洞察一", "洞察二"]);
    expect(screen.getByText("意图一")).toBeTruthy();
  });

  it("上一轮未结束时发送被忽略", async () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("q1");
    await waitFor(() => expect(calls).toHaveLength(1));
    ask("q2");
    expect(calls).toHaveLength(1);
  });
});

describe("ChatWindow 空状态", () => {
  it("没有消息时显示引导与示例问题", () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    expect(screen.getByTestId("empty-state")).toBeTruthy();
    expect(screen.getByText(/按月统计订单金额/)).toBeTruthy();
  });

  it("提问后空状态消失", async () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("q");
    await waitFor(() => expect(screen.queryByTestId("empty-state")).toBeNull());
  });

  it("错误消息带 alert 语义", async () => {
    render(<ChatWindow dataSourceId="ds1" dataSourceName="示例订单库" />);
    ask("q");
    await waitFor(() => expect(calls).toHaveLength(1));
    drive(0, [{ type: "error", message: "Ollama 未运行" }]);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Ollama 未运行"));
  });
});

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
