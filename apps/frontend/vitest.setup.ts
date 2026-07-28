import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// RTL 的自动 cleanup 只在 vitest globals 打开时生效,这里显式挂载,
// 避免多个 it() 的 render 结果堆叠在同一个 document 上。
afterEach(() => cleanup());
