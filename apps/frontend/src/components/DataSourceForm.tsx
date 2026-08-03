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
