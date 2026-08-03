import { ChatWindow } from "../components/ChatWindow";
import { useDataSources } from "../dataSourceStore";

/** 唯一职责:把 Context 里的选中项翻成 ChatWindow 的 prop,让 ChatWindow 保持可单测。 */
export function ChatPage() {
  const { selectedId, selected } = useDataSources();
  return <ChatWindow dataSourceId={selectedId} dataSourceName={selected?.name} />;
}
