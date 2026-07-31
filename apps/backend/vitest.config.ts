import { defineConfig } from "vitest/config";

/**
 * pool: "forks" 是必须的,不是偏好。better-sqlite3 的原生插件在多个 worker
 * **线程**里同时加载时,进程退出阶段会段错误(exit 139):测试全过、summary 都没打完
 * 就崩。P2a 之前只有 3 个测试文件碰 better-sqlite3,恰好在阈值下面;现在有 7 个,
 * 4 个以上并行就必崩。改用子进程池后各自独立地址空间,问题消失。
 */
export default defineConfig({
  test: { environment: "node", pool: "forks" },
});
