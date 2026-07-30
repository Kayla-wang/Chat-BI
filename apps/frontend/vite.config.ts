import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// 后端端口:优先 BACKEND_PORT,回落到 PORT(两个进程可共用一个变量),再回落 5174。
const backendPort = process.env.BACKEND_PORT ?? process.env.PORT ?? "5174";
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": `http://localhost:${backendPort}` } },
});
