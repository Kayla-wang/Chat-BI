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
