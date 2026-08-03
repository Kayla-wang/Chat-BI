import type {
  ChatTurn, DataSourceDetail, DataSourceSummary, DrillContext, DsApiError, DsConfigInput,
  DsErrorCode, RefreshSchemaResponse, SchemaResponse, StreamEvent, TestConnectionOk,
} from "@chatbi/shared";

export function streamChat(opts: {
  question: string; dataSourceId: string; history: ChatTurn[]; context?: DrillContext;
  onEvent: (e: StreamEvent) => void;
  endpoint?: string;
}): Promise<void> {
  const url = opts.endpoint ?? "/api/chat";
  return (async () => {
    let res: Response;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: opts.question,
          dataSourceId: opts.dataSourceId,
          history: opts.history,
          ...(opts.context ? { context: opts.context } : {}),
        }),
      });
    } catch (e) {
      opts.onEvent({ type: "error", message: `网络错误:${(e as Error).message}` });
      return;
    }
    if (!res.ok || !res.body) { opts.onEvent({ type: "error", message: `服务器返回 ${res.status}` }); return; }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        for (const line of block.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          try { opts.onEvent(JSON.parse(line.slice(6))); } catch { /* skip */ }
        }
      }
    }
  })();
}

/** 带 code 的错误。界面按 code 决定提示语与可用操作,所以不能退化成普通 Error。 */
export class ApiError extends Error {
  constructor(
    readonly code: DsErrorCode,
    message: string,
    readonly details?: string,
    readonly canForce?: boolean,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const DS_BASE = "/api/datasources";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${DS_BASE}${path}`, init);
  } catch (e) {
    throw new ApiError("UNKNOWN", `网络错误:${(e as Error).message}`);
  }
  if (res.status === 204) return undefined as T;   // 删除没有响应体
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    // 真 500 常常回 HTML,把 SyntaxError 甩给用户等于没有提示。
    throw new ApiError("UNKNOWN", res.ok ? "服务器返回了无法解析的内容" : `服务器返回 ${res.status}`);
  }
  if (!res.ok) {
    const e = (body ?? {}) as DsApiError;
    throw new ApiError(e.code ?? "UNKNOWN", e.message ?? `服务器返回 ${res.status}`, e.details, e.canForce);
  }
  return body as T;
}

const send = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const listDataSources = (): Promise<DataSourceSummary[]> => request("");
export const getDataSource = (id: string): Promise<DataSourceDetail> => request(`/${id}`);

// 后端的 parseDsConfigInput 从 body 顶层读字段,所以这里把 input 摊平,不套一层 config。
export const testDsConfig = (input: DsConfigInput): Promise<TestConnectionOk> =>
  request("/test", send("POST", { ...input }));

export const createDataSource = (name: string, input: DsConfigInput, force?: boolean): Promise<DataSourceDetail> =>
  request("", send("POST", { name, ...input, ...(force ? { force: true } : {}) }));

export const updateDataSource = (id: string, name: string, input: DsConfigInput): Promise<DataSourceDetail> =>
  request(`/${id}`, send("PUT", { name, ...input }));

export const deleteDataSource = (id: string): Promise<void> => request(`/${id}`, { method: "DELETE" });
export const testDataSource = (id: string): Promise<TestConnectionOk> => request(`/${id}/test`, { method: "POST" });
export const refreshSchema = (id: string): Promise<RefreshSchemaResponse> =>
  request(`/${id}/refresh-schema`, { method: "POST" });
export const fetchSchema = (id: string): Promise<SchemaResponse> => request(`/${id}/schema`);
