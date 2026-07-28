// 让根目录 `npx vitest run` 复用各 workspace 自己的 vitest 配置
// (后端 node 环境、前端 jsdom + RTL cleanup),而不是用同一份默认配置跑全仓。
export default [
  "packages/shared",
  "apps/backend",
  "apps/frontend",
];
