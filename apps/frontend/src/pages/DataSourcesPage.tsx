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
