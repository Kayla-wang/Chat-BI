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
