# Chat-BI P2a-2 实施计划：链路集成与数据源管理界面

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P2a-1 的驱动层接进问答链路与界面——用户能在界面上管理数据源、选中任意一个源提问,并得到按该源方言生成的 SQL 与图表。

**Architecture:** 后端把 `sqlGuard`、`promptBuilder`、`chatService` 从「硬编码 sqlite + 同步查询」改成「按 `Dialect` 参数化 + 异步 driver」,新增 8 个数据源端点,`POST /api/chat` 增加必填 `dataSourceId`;前端引入 `react-router-dom`,加顶栏数据源选择器与 `/datasources` 管理页,切换数据源时清空下钻上下文。

**Tech Stack:** TypeScript 5.4 ESM、Express 4 + SSE、React 18 + Vite 5、react-router-dom 6、vitest 1.6 + @testing-library/react、supertest

**前序:** [P2a-1 计划](./2026-07-31-chatbi-p2a1-persistence-drivers.md) 必须已全部完成 —— 本计划直接消费它的 `registry`、`Dialect`、`DsError`、仓储函数。[设计 spec](../specs/2026-07-31-chatbi-p2-datasource-design.md) 第二部分第 6–9 节与第 12 节。

## Global Constraints

- **Node 20+**、后端与前端都是 **ESM**(`"type": "module"`),相对导入不写扩展名。
- **中文标点约定**(照抄现有代码):句内停顿用**半角逗号** `,`,冒号用**半角** `:`,句末用**全角句号** `。`,强调用 `「」`。注释与测试描述用中文。
- **唯一允许新增的前端依赖是 `react-router-dom`**。不引 UI 组件库、不引状态管理库、不引 `@testing-library/jest-dom`(现有测试用 `expect(...).toBeTruthy()` 风格,照抄)。
- **后端不许再加依赖**。
- **视觉规则(P1b 建立,必须继续成立)**:颜色只从 `apps/frontend/src/theme/tokens.css` 的 CSS 变量取;**不写颜色字面量**;**不用内联 `style={{}}`**;每个组件配自己的 `.module.css`;数字用 `tabular-nums`。现有 tokens 已有 `--positive` / `--negative` / `--warning`,状态色直接用,**不新造**;若确实需要一个浅底色徽标,新增 token 时必须按 WCAG 1.4.3 验算对比度并把结果写进提交信息。
- **`ChartSpec`、`packages/shared/src/renderer.ts`、`InsightPanel` / `ResultCard` / `ChartView` / `DataTable` / `SqlDisclosure` 一律不改**——本计划不碰图表与洞察的渲染。
- **`StreamEvent` 五种事件不加不减**:所有数据源错误走 `error` 事件。
- **每个任务结束时 `npm test --workspaces` 必须全绿**,含 P1 留下的 267 个测试与 P2a-1 新增的那些。
- **API 错误响应统一形状**:`{ code: DsErrorCode; message: string; details?: string; canForce?: boolean }`,`message` 是中文,`details` 是原生原文。

---

### Task 1: sqlGuard 按方言参数化

接远程库是 P2a 引入的**真实新增攻击面**:P1 的根本防线是「只读打开 SQLite 文件」,这个手段在 MySQL / PG 上不存在。现在 `validate()` 硬编码 `database: "sqlite"`,MySQL 的反引号与 PG 的 `::` 转换会被判成解析失败、退回正则兜底——等于最强的那道校验对两种新源直接失效。

**还要补一个现有的洞**:`FORBIDDEN` 只在 `validateByRegex` 里检查,AST 路径完全不查函数名。`SELECT pg_read_file('/etc/passwd')` 是一条合法 SELECT,现在会**直接通过**。

**避免误杀的设计**:函数类禁用词一律要求后面紧跟 `(`——列名叫 `dblink` 的表不会被拦;语句类禁用词(`COPY`、`LOAD DATA`)只在**行首**匹配。

**Files:**
- Modify: `apps/backend/src/sqlGuard.ts`
- Modify: `apps/backend/tests/sqlGuard.test.ts`(现有断言全部保留,只加 dialect 参数)
- Test: 同上

**Interfaces:**
- Consumes: `Dialect`、`dialectFor`、`SQLITE_DIALECT`、`MYSQL_DIALECT`、`POSTGRES_DIALECT`(P2a-1 Task 4)
- Produces:
  - `validate(sql: string, dialect: Dialect): { ok: true; sql: string; viaAst: boolean } | { ok: false; reason: string }`
  - `validateByRegex(sql: string, dialect: Dialect): { ok: true; sql: string } | { ok: false; reason: string }`
  - `stripLiterals`、`hasComment`、`enforceLimit`、`wrapTimeout` 签名不变

- [ ] **Step 1: 给现有测试加 dialect 参数,先让它红**

`apps/backend/tests/sqlGuard.test.ts` 里每一处 `validate(x)` 改成 `validate(x, SQLITE_DIALECT)`,`validateByRegex(x)` 改成 `validateByRegex(x, SQLITE_DIALECT)`,顶部加:

```ts
import { SQLITE_DIALECT, MYSQL_DIALECT, POSTGRES_DIALECT } from "../src/datasources/dialect";
```

**一条断言都不许删。** P1 的 `SELECT '已delete' AS status` 不被误杀、堆叠查询被拦、注释被拦这些全部要继续通过。

- [ ] **Step 2: 追加方言相关的新测试**

在 `sqlGuard.test.ts` 末尾追加:

```ts
describe("按方言解析 AST", () => {
  it("MySQL 的反引号标识符走 AST 而不是退回正则", () => {
    const r = validate("SELECT `order date` FROM `orders`", MYSQL_DIALECT);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.viaAst).toBe(true);
  });
  it("PostgreSQL 的 :: 类型转换走 AST", () => {
    const r = validate("SELECT SUM(amount)::numeric FROM orders", POSTGRES_DIALECT);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.viaAst).toBe(true);
  });
});

describe("MySQL 特有的逃逸口", () => {
  it("拦 INTO OUTFILE", () => {
    expect(validate("SELECT * FROM orders INTO OUTFILE '/tmp/x'", MYSQL_DIALECT).ok).toBe(false);
  });
  it("拦 INTO DUMPFILE", () => {
    expect(validate("SELECT a FROM t INTO DUMPFILE '/tmp/x'", MYSQL_DIALECT).ok).toBe(false);
  });
  it("拦 LOAD_FILE 函数", () => {
    expect(validate("SELECT LOAD_FILE('/etc/passwd') AS x", MYSQL_DIALECT).ok).toBe(false);
  });
  it("不误杀名叫 load_file 的列", () => {
    expect(validate("SELECT load_file FROM audit", MYSQL_DIALECT).ok).toBe(true);
  });
});

describe("PostgreSQL 特有的逃逸口", () => {
  it("拦 pg_read_file", () => {
    expect(validate("SELECT pg_read_file('/etc/passwd') AS x", POSTGRES_DIALECT).ok).toBe(false);
  });
  it("拦 dblink", () => {
    expect(validate("SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(x int)", POSTGRES_DIALECT).ok).toBe(false);
  });
  it("拦 pg_sleep", () => {
    expect(validate("SELECT pg_sleep(100) AS x", POSTGRES_DIALECT).ok).toBe(false);
  });
  it("拦行首的 COPY", () => {
    expect(validateByRegex("COPY orders TO '/tmp/x'", POSTGRES_DIALECT).ok).toBe(false);
  });
  it("不误杀名叫 dblink 的列", () => {
    expect(validate("SELECT dblink FROM connections", POSTGRES_DIALECT).ok).toBe(true);
  });
  it("不误杀字符串字面量里的 pg_read_file", () => {
    expect(validate("SELECT 'pg_read_file(x)' AS note", POSTGRES_DIALECT).ok).toBe(true);
  });
});

describe("跨方言不互相污染", () => {
  it("sqlite 不因为 MySQL 的词表被拦", () => {
    expect(validate("SELECT load_file FROM t", SQLITE_DIALECT).ok).toBe(true);
  });
  it("MySQL 不因为 PG 的词表被拦", () => {
    expect(validate("SELECT dblink FROM t", MYSQL_DIALECT).ok).toBe(true);
  });
});
```

- [ ] **Step 3: 运行确认失败**

Run: `npx vitest --root apps/backend run tests/sqlGuard.test.ts`
Expected: FAIL —— `validate` 只接受一个参数,新增的方言测试全红。

- [ ] **Step 4: 改 `sqlGuard.ts`**

在 `SELECT_HEAD` 下面加方言词表,并把它接进两条路径:

```ts
import type { Dialect } from "./datasources/dialect";
import type { DataSourceKind } from "./datasources/types";

/**
 * 方言特有的逃逸口。这些都是「一条合法 SELECT 内部就能触发」的能力,
 * AST 只判断「是不是 SELECT」拦不住,必须显式列。
 *
 * 函数类一律要求后面紧跟 `(`,免得误杀名叫 dblink 的列;
 * 语句类只在行首匹配,因为 AST 已经保证了是 SELECT。
 */
const DIALECT_FORBIDDEN: Record<DataSourceKind, RegExp[]> = {
  sqlite: [],
  mysql: [
    /\binto\s+(outfile|dumpfile)\b/i,
    /\b(load_file)\s*\(/i,
    /^\s*load\s+data\b/i,
  ],
  postgres: [
    /\b(pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|dblink|dblink_exec|pg_sleep|lo_import|lo_export)\s*\(/i,
    /^\s*copy\b/i,
  ],
};

function dialectViolation(bareSql: string, dialect: Dialect): string | null {
  for (const re of DIALECT_FORBIDDEN[dialect.kind]) {
    if (re.test(bareSql)) return `${dialect.kind} forbidden construct detected`;
  }
  return null;
}
```

`validateByRegex` 与 `validate` 都加 `dialect` 参数,并在**两条路径**上做方言检查:

```ts
export function validateByRegex(sql: string, dialect: Dialect):
  { ok: true; sql: string } | { ok: false; reason: string } {
  const trimmed = sql.trim().replace(/;\s*$/, "");
  const bare = stripLiterals(trimmed);
  if (bare.includes(";")) return { ok: false, reason: "stacked queries not allowed" };
  if (!SELECT_HEAD.test(bare)) return { ok: false, reason: "only SELECT / WITH...SELECT allowed" };
  if (FORBIDDEN.test(bare)) return { ok: false, reason: "write/DDL keyword detected" };
  const bad = dialectViolation(bare, dialect);
  if (bad) return { ok: false, reason: bad };
  return { ok: true, sql: trimmed };
}

export function validate(sql: string, dialect: Dialect):
  { ok: true; sql: string; viaAst: boolean } | { ok: false; reason: string } {
  if (hasComment(sql)) return { ok: false, reason: "SQL 注释不被允许（comment not allowed）" };
  const trimmed = sql.trim().replace(/;\s*$/, "");

  // 方言禁用词在 AST 路径上同样要查:pg_read_file(...) 是一条合法 SELECT。
  const bad = dialectViolation(stripLiterals(trimmed), dialect);
  if (bad) return { ok: false, reason: bad };

  let ast: unknown;
  try {
    ast = parser.astify(trimmed, { database: dialect.sqlParserDialect });
  } catch {
    const fallback = validateByRegex(trimmed, dialect);
    return fallback.ok ? { ...fallback, viaAst: false } : fallback;
  }

  if (Array.isArray(ast)) {
    if (ast.length !== 1) return { ok: false, reason: "stacked queries not allowed" };
    ast = ast[0];
  }
  const type = (ast as { type?: string })?.type;
  if (type !== "select") {
    return { ok: false, reason: `only SELECT allowed, got ${type ?? "unknown"}` };
  }
  return { ok: true, sql: trimmed, viaAst: true };
}
```

`COPY` 那条只在 `validateByRegex` 生效即可(AST 路径下 `COPY` 会被 `type !== "select"` 拦掉),但因为 `dialectViolation` 在 `validate` 开头就跑了一遍,行首 `COPY` 两条路径都拦——更保守,可以接受。

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest --root apps/backend run tests/sqlGuard.test.ts`
Expected: PASS —— 原有断言全绿 + 新增 15 个。

- [ ] **Step 6: 提交**

```bash
git add apps/backend/src/sqlGuard.ts apps/backend/tests/sqlGuard.test.ts
git commit -m "feat(backend): parameterize sqlGuard by dialect and close per-dialect escapes"
```

---

### Task 2: promptBuilder 注入方言提示

P2a 的 SQL 仍然由 LLM 写,所以方言差异只能靠 prompt 告知。不告知的后果很具体:模型在 MySQL 上写 `strftime`,查询报错,白耗一轮重试。

**Files:**
- Modify: `apps/backend/src/promptBuilder.ts`
- Modify: `apps/backend/tests/promptBuilder.test.ts`

**Interfaces:**
- Consumes: `Dialect`、`MYSQL_DIALECT`、`POSTGRES_DIALECT`、`SQLITE_DIALECT`(P2a-1 Task 4)
- Produces: `buildPrompt(opts: { question: string; schema: TableSchema[]; history: ChatTurn[]; dialect: Dialect; context?: DrillContext }): string`
- 不变:`buildRetryPrompt(prevPrompt, feedback)`、`buildInsightPrompt(facts, question, format)`

- [ ] **Step 1: 给现有测试补 dialect,并加新断言**

`apps/backend/tests/promptBuilder.test.ts` 里每处 `buildPrompt({ ... })` 补上 `dialect: SQLITE_DIALECT`,顶部加导入。然后追加:

```ts
import { SQLITE_DIALECT, MYSQL_DIALECT, POSTGRES_DIALECT } from "../src/datasources/dialect";

describe("方言提示", () => {
  const base = { question: "按月统计订单金额", schema: [], history: [] };

  it("把方言提示原文放进 prompt", () => {
    const p = buildPrompt({ ...base, dialect: MYSQL_DIALECT });
    expect(p).toContain(MYSQL_DIALECT.promptNotes);
  });

  it("MySQL 提示里是 DATE_FORMAT,不出现 strftime", () => {
    const p = buildPrompt({ ...base, dialect: MYSQL_DIALECT });
    expect(p).toContain("DATE_FORMAT");
    expect(p).not.toContain("strftime");
  });

  it("PostgreSQL 提示里是 date_trunc", () => {
    expect(buildPrompt({ ...base, dialect: POSTGRES_DIALECT })).toContain("date_trunc");
  });

  it("换方言时 prompt 真的变了", () => {
    const a = buildPrompt({ ...base, dialect: SQLITE_DIALECT });
    const b = buildPrompt({ ...base, dialect: POSTGRES_DIALECT });
    expect(a).not.toBe(b);
  });

  it("与方言无关的规则仍然在(只读、只输出 JSON)", () => {
    const p = buildPrompt({ ...base, dialect: POSTGRES_DIALECT });
    expect(p).toContain("只生成 SELECT");
    expect(p).toContain("只输出 JSON");
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest --root apps/backend run tests/promptBuilder.test.ts`
Expected: FAIL —— `dialect` 不是 `buildPrompt` 的参数,新断言全红。

- [ ] **Step 3: 改 `promptBuilder.ts`**

`SYSTEM` 常量一个字不改(那些规则与方言无关)。只改 `buildPrompt` 的签名与拼装:

```ts
export function buildPrompt(opts: {
  question: string; schema: TableSchema[]; history: ChatTurn[];
  dialect: Dialect; context?: DrillContext;
}): string {
  const recent = opts.history.slice(-HISTORY_MESSAGE_LIMIT);
  const historyText = recent.length
    ? recent.map(t => `${t.role}: ${t.text}`).join("\n")
    : "(无)";
  return `${SYSTEM}

${opts.dialect.promptNotes}

数据库 schema:
${renderSchema(opts.schema)}
${renderDrill(opts.context)}
对话历史(最近 2 轮):
${historyText}

用户问题: ${opts.question}`;
}
```

顶部加 `import type { Dialect } from "./datasources/dialect";`。

方言提示放在通用规则**之后**、schema **之前**:紧挨着 schema 能让模型把「这是什么库」和「有哪些表」连起来读。

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest --root apps/backend run tests/promptBuilder.test.ts`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add apps/backend/src/promptBuilder.ts apps/backend/tests/promptBuilder.test.ts
git commit -m "feat(backend): inject dialect notes into the SQL prompt"
```

---

### Task 3: chatService 异步化与按错误码分类重试

**这是本计划里最容易被漏掉的正确性改动。** 现有 `chatService` 的 `attempt` 循环对**任何**执行异常都重试一轮——那是为「LLM 写错 SQL」设计的:把错误原因喂回模型让它改。接了远程库以后这个行为有害:连不上库、认证失败、超时,重试只是让用户多等一个完整超时,而错误与 SQL 内容毫无关系。

另外 `wrapTimeout` 从 `chatService` **移走**——超时现在由 driver 下推到服务端(`statement_timeout` / `max_execution_time`),`chatService` 再套一层只会让两个超时互相干扰。

**Files:**
- Modify: `apps/backend/src/chatService.ts`
- Modify: `apps/backend/tests/chatService.test.ts`

**Interfaces:**
- Consumes: `Dialect`(P2a-1 Task 4);`DsError`、`isRetryable`(P2a-1 Task 4);`validate`(Task 1);`buildPrompt`(Task 2)
- Produces:
  - `interface ChatDeps { db: { getSchema(): Promise<TableSchema[]>; runQuery(sql: string, limit: number): Promise<{ rows: Row[]; truncated: boolean }> }; dialect: Dialect; llm: { chatStream(prompt: string): AsyncIterable<string> } }`
  - `handleChat(opts)` 签名不变(`{ question, history, context?, deps }`),仍然 `AsyncIterable<StreamEvent>`

- [ ] **Step 1: 改现有测试的假 deps 为异步,并把重试用例改成抛 DsError**

现有 `chatService.test.ts` 的假 db 是同步的,全部改成 `async`。**「SQL 执行报错时重试一轮」这条断言要保留**,但假 db 现在必须抛 `DsError("SQL_ERROR", ...)` 而不是裸 `Error`——因为分类重试只认 `DsError`。这是**改断言的前提条件,不是删断言**。

- [ ] **Step 2: 追加分类重试的新测试**

在 `chatService.test.ts` 末尾追加:

```ts
import { DsError } from "../src/datasources/errors";
import { SQLITE_DIALECT } from "../src/datasources/dialect";
import type { TableSchema } from "@chatbi/shared";

const SCHEMA: TableSchema[] = [{
  tableName: "orders",
  columns: [
    { name: "order_date", type: "TEXT", notNull: false, pk: false },
    { name: "total_amount", type: "REAL", notNull: false, pk: false },
  ],
  foreignKeys: [],
}];

/** 每次调用都吐同一段合法 JSON 的假 LLM,并记下被调了几次。 */
function countingLlm(): { chatStream(p: string): AsyncIterable<string>; calls: number } {
  const obj = JSON.stringify({
    sql: "SELECT order_date, total_amount FROM orders",
    explanation: "查订单",
    chartType: "line", dimensions: ["order_date"], measures: ["total_amount"],
  });
  const llm = {
    calls: 0,
    chatStream(_p: string): AsyncIterable<string> {
      llm.calls++;
      return (async function* () { yield obj; })();
    },
  };
  return llm;
}

const collect = async (it: AsyncIterable<StreamEvent>): Promise<StreamEvent[]> => {
  const out: StreamEvent[] = [];
  for await (const e of it) out.push(e);
  return out;
};

describe("按错误码决定是否重试", () => {
  const run = (runQuery: () => Promise<never>, llm = countingLlm()) => ({
    llm,
    events: collect(handleChat({
      question: "按月统计订单金额", history: [],
      deps: { db: { getSchema: async () => SCHEMA, runQuery }, dialect: SQLITE_DIALECT, llm },
    })),
  });

  it("SQL_ERROR 重试一轮(LLM 被调两次)", async () => {
    const { llm, events } = run(async () => { throw new DsError("SQL_ERROR", "SQL 执行失败", "syntax error"); });
    const evs = await events;
    expect(llm.calls).toBe(2);
    expect(evs.at(-1)).toMatchObject({ type: "error" });
  });

  it("CONNECTION_ERROR 不重试(LLM 只被调一次)", async () => {
    const { llm, events } = run(async () => {
      throw new DsError("CONNECTION_ERROR", "无法连接到数据库,请检查地址、端口与网络", "ECONNREFUSED");
    });
    const evs = await events;
    expect(llm.calls).toBe(1);
    expect(evs.at(-1)).toMatchObject({ type: "error", message: expect.stringContaining("无法连接") });
  });

  it("TIMEOUT 不重试", async () => {
    const { llm } = run(async () => { throw new DsError("TIMEOUT", "查询超时"); });
    await new Promise(r => setTimeout(r, 0));
    expect(llm.calls).toBe(1);
  });

  it("SCHEMA_STALE 会重试,最终错误提示带刷新结构", async () => {
    const { llm, events } = run(async () => {
      throw new DsError("SCHEMA_STALE", "表或列不存在;表结构可能已变更,试试刷新结构", "no such column");
    });
    const evs = await events;
    expect(llm.calls).toBe(2);
    expect(evs.at(-1)).toMatchObject({ type: "error", message: expect.stringContaining("刷新结构") });
  });

  it("错误消息给人看的是中文,原生原文只喂回模型", async () => {
    const { events } = run(async () => {
      throw new DsError("AUTH_ERROR", "认证失败,请检查用户名与密码", "ER_ACCESS_DENIED_ERROR");
    });
    const last = (await events).at(-1) as { type: string; message: string };
    expect(last.message).not.toContain("ER_ACCESS_DENIED");
  });

  it("裸 Error(驱动层的 bug)当作 UNKNOWN,不重试", async () => {
    const { llm } = run(async () => { throw new Error("某个没被映射的错误"); });
    await new Promise(r => setTimeout(r, 0));
    expect(llm.calls).toBe(1);
  });
});

describe("取 schema 失败", () => {
  it("直接报错,一次 LLM 都不调", async () => {
    const llm = countingLlm();
    const evs = await collect(handleChat({
      question: "任意问题", history: [],
      deps: {
        db: {
          getSchema: async () => { throw new DsError("CONNECTION_ERROR", "无法连接到数据库"); },
          runQuery: async () => ({ rows: [], truncated: false }),
        },
        dialect: SQLITE_DIALECT, llm,
      },
    }));
    expect(llm.calls).toBe(0);
    expect(evs).toEqual([{ type: "error", message: "无法连接到数据库" }]);
  });
});
```

- [ ] **Step 3: 运行确认失败**

Run: `npx vitest --root apps/backend run tests/chatService.test.ts`
Expected: FAIL —— `deps.dialect` 不被接受,分类重试还没实现。

- [ ] **Step 4: 改 `chatService.ts`**

顶部导入换成:

```ts
import type { Dialect } from "./datasources/dialect";
import { DsError, isRetryable } from "./datasources/errors";
import { validate, enforceLimit } from "./sqlGuard";   // wrapTimeout 不再需要
```

`ChatDeps` 改成:

```ts
export interface ChatDeps {
  db: {
    getSchema(): Promise<TableSchema[]>;
    /** 超时由 driver 下推到服务端,这里不再包 wrapTimeout。 */
    runQuery(sql: string, limit: number): Promise<{ rows: Row[]; truncated: boolean }>;
  };
  dialect: Dialect;
  llm: { chatStream(prompt: string): AsyncIterable<string> };
}
```

`handleChat` 开头改成先安全地取 schema:

```ts
export async function* handleChat(opts: {
  question: string; history: ChatTurn[]; context?: DrillContext; deps: ChatDeps;
}): AsyncIterable<StreamEvent> {
  let schema: TableSchema[];
  try {
    schema = await opts.deps.db.getSchema();
  } catch (e) {
    // 连不上库就别去问模型了,省一次无用的推理。
    yield { type: "error", message: toDsError(e).message };
    return;
  }
  let prompt = buildPrompt({
    question: opts.question, schema, history: opts.history,
    dialect: opts.deps.dialect, context: opts.context,
  });
```

`validate` 调用改成 `validate(parsed.sql, opts.deps.dialect)`。查询执行那一段整体换成:

```ts
    const probeSql = enforceLimit(v.sql, config.rowLimit + 1);
    let out: { rows: Row[]; truncated: boolean };
    try {
      out = await opts.deps.db.runQuery(probeSql, config.rowLimit);
    } catch (e) {
      const err = toDsError(e);
      // 只有与 SQL 内容相关的错误值得把原因喂回模型;连不上、认证失败、超时重试都是白等。
      if (attempt === 0 && isRetryable(err.code)) {
        prompt = buildRetryPrompt(prompt, `SQL 执行报错:${err.details ?? err.message},请修正 SQL`);
        continue;
      }
      yield { type: "error", message: err.message };
      return;
    }
```

文件末尾加一个小工具函数:

```ts
/** 驱动层的契约是一律抛 DsError;裸 Error 说明有 bug,按 UNKNOWN 处理且不重试。 */
function toDsError(e: unknown): DsError {
  return e instanceof DsError
    ? e
    : new DsError("UNKNOWN", `SQL 执行失败:${(e as Error).message}`, (e as Error).message);
}
```

喂回模型的是 `err.details`(原生英文原文,对改 SQL 更有用),给用户看的是 `err.message`(中文)。

- [ ] **Step 5: 运行确认通过**

Run: `npx vitest --root apps/backend run tests/chatService.test.ts`
Expected: PASS —— 原有断言全绿 + 新增 8 个。

- [ ] **Step 6: 跑全量后端测试**

Run: `npx vitest --root apps/backend run`
Expected: FAIL 是允许的,且只应发生在 `tests/chat.route.test.ts`(它还在用旧的同步 deps)—— Task 5 会修。若有别的文件失败,先查清再往下走。

- [ ] **Step 7: 提交**

```bash
git add apps/backend/src/chatService.ts apps/backend/tests/chatService.test.ts
git commit -m "feat(backend): async chat deps and error-code-driven retry"
```

---

### Task 4: 数据源 API 的契约类型与输入合并

先把纯逻辑做掉:API 响应形状(前后端共用)、请求体解析、以及**改密码时的三态语义**——字段缺失=不改、`""`=真的设成空、有值=换新的。这块不需要数据库也不需要 express,单测最便宜,而且它是「密码不外泄」与「改名不清密码」两个正确性点的落点。

**Files:**
- Modify: `packages/shared/src/types.ts`
- Create: `apps/backend/src/datasources/configInput.ts`
- Test: `apps/backend/tests/configInput.test.ts`

**Interfaces:**
- Consumes: `DsConfig`、`DataSourceKind`、`WritePrivilege`、`DsErrorCode`、`TableSchema`(均在 `@chatbi/shared`,P2a-1 已加)
- Produces —— `packages/shared/src/types.ts`:
  - `type DataSourceStatus = "ok" | "error" | "needs_reconfig" | "unchecked"`
  - `interface DataSourceSummary { id: string; name: string; kind: DataSourceKind; target: string; status: DataSourceStatus; writePrivilege: WritePrivilege | null; lastCheckAt: string | null; lastCheckError: string | null; schemaFetchedAt: string | null; tableCount: number | null }`
  - `interface DataSourceConnectionView { path?: string; host?: string; port?: number; database?: string; user?: string; ssl?: boolean; schema?: string }` —— **没有 password 字段**
  - `interface DataSourceDetail extends DataSourceSummary { connection: DataSourceConnectionView; hasPassword: boolean }`
  - `type DsConfigInput` —— 与 `DsConfig` 同构,但 `password` 可选(PUT 时缺失表示不改)
  - `interface DsApiError { code: DsErrorCode; message: string; details?: string; canForce?: boolean }`
  - `interface TestConnectionOk { ok: true; writePrivilege: WritePrivilege; tableCount: number }`
  - `interface SchemaResponse { schema: TableSchema[]; fetchedAt: string | null }`
  - `interface RefreshSchemaResponse { tableCount: number; fetchedAt: string; elapsedMs: number }`
- Produces —— `apps/backend/src/datasources/configInput.ts`:
  - `function parseDsConfigInput(body: unknown): DsConfigInput | null`
  - `function mergeConfig(existing: DsConfig | null, input: DsConfigInput): DsConfig` —— 缺 password 且无旧值时抛 `DsError("UNKNOWN", ...)`
  - `function connectionView(config: DsConfig): DataSourceConnectionView`

- [ ] **Step 1: 写失败的测试**

Create `apps/backend/tests/configInput.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { parseDsConfigInput, mergeConfig, connectionView } from "../src/datasources/configInput";
import type { DsConfig } from "@chatbi/shared";

const mysqlSaved: DsConfig = {
  kind: "mysql", host: "10.0.0.5", port: 3306, database: "sales",
  user: "bi_ro", password: "老密码", ssl: false,
};

describe("parseDsConfigInput", () => {
  it("接受完整的 mysql 输入", () => {
    expect(parseDsConfigInput({
      kind: "mysql", host: "h", port: 3306, database: "d", user: "u", password: "p", ssl: true,
    })).toMatchObject({ kind: "mysql", host: "h", port: 3306, ssl: true });
  });
  it("接受省略 password 的输入(表示不改)", () => {
    const r = parseDsConfigInput({ kind: "mysql", host: "h", port: 3306, database: "d", user: "u", ssl: false });
    expect(r).not.toBeNull();
    expect(r!.kind === "mysql" && r!.password).toBeUndefined();
  });
  it("接受 sqlite 的路径", () => {
    expect(parseDsConfigInput({ kind: "sqlite", path: "./a.db" })).toEqual({ kind: "sqlite", path: "./a.db" });
  });
  it("postgres 的 schema 可选", () => {
    const r = parseDsConfigInput({
      kind: "postgres", host: "h", port: 5432, database: "d", user: "u", password: "p", ssl: false, schema: "bi",
    });
    expect(r).toMatchObject({ kind: "postgres", schema: "bi" });
  });
  it("端口是字符串数字时转成 number", () => {
    const r = parseDsConfigInput({ kind: "mysql", host: "h", port: "3306", database: "d", user: "u", ssl: false });
    expect(r!.kind === "mysql" && r!.port).toBe(3306);
  });
  it("kind 不认识返回 null", () => {
    expect(parseDsConfigInput({ kind: "oracle", host: "h" })).toBeNull();
  });
  it("缺必填字段返回 null", () => {
    expect(parseDsConfigInput({ kind: "mysql", host: "h", port: 3306 })).toBeNull();
    expect(parseDsConfigInput({ kind: "sqlite" })).toBeNull();
  });
  it("端口不是数字返回 null", () => {
    expect(parseDsConfigInput({ kind: "mysql", host: "h", port: "abc", database: "d", user: "u", ssl: false })).toBeNull();
  });
  it("不是对象返回 null", () => {
    expect(parseDsConfigInput(null)).toBeNull();
    expect(parseDsConfigInput("mysql")).toBeNull();
  });
});

describe("mergeConfig 的密码三态", () => {
  it("password 字段缺失 = 保留旧密码", () => {
    const input = parseDsConfigInput({
      kind: "mysql", host: "新地址", port: 3306, database: "sales", user: "bi_ro", ssl: false,
    })!;
    const merged = mergeConfig(mysqlSaved, input);
    expect(merged).toMatchObject({ host: "新地址", password: "老密码" });
  });
  it("password 是空字符串 = 真的把密码设成空", () => {
    const input = parseDsConfigInput({
      kind: "mysql", host: "h", port: 3306, database: "d", user: "u", password: "", ssl: false,
    })!;
    expect(mergeConfig(mysqlSaved, input).kind === "mysql"
      && (mergeConfig(mysqlSaved, input) as { password: string }).password).toBe("");
  });
  it("password 有值 = 换成新的", () => {
    const input = parseDsConfigInput({
      kind: "mysql", host: "h", port: 3306, database: "d", user: "u", password: "新密码", ssl: false,
    })!;
    expect((mergeConfig(mysqlSaved, input) as { password: string }).password).toBe("新密码");
  });
  it("换了 kind 时不继承旧密码", () => {
    const input = parseDsConfigInput({
      kind: "postgres", host: "h", port: 5432, database: "d", user: "u", password: "p", ssl: false,
    })!;
    expect(mergeConfig(mysqlSaved, input).kind).toBe("postgres");
  });
  it("新建时缺密码就报错,不静默存空密码", () => {
    const input = parseDsConfigInput({
      kind: "mysql", host: "h", port: 3306, database: "d", user: "u", ssl: false,
    })!;
    expect(() => mergeConfig(null, input)).toThrow(/密码/);
  });
  it("换 kind 且缺密码同样报错", () => {
    const input = parseDsConfigInput({
      kind: "postgres", host: "h", port: 5432, database: "d", user: "u", ssl: false,
    })!;
    expect(() => mergeConfig(mysqlSaved, input)).toThrow(/密码/);
  });
  it("sqlite 不需要密码", () => {
    expect(mergeConfig(null, { kind: "sqlite", path: "./a.db" })).toEqual({ kind: "sqlite", path: "./a.db" });
  });
});

describe("connectionView", () => {
  it("给出非敏感字段,且绝对没有 password", () => {
    const v = connectionView(mysqlSaved);
    expect(v).toEqual({ host: "10.0.0.5", port: 3306, database: "sales", user: "bi_ro", ssl: false });
    expect(JSON.stringify(v)).not.toContain("老密码");
    expect("password" in v).toBe(false);
  });
  it("sqlite 只给路径", () => {
    expect(connectionView({ kind: "sqlite", path: "./a.db" })).toEqual({ path: "./a.db" });
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest --root apps/backend run tests/configInput.test.ts`
Expected: FAIL,解析不到 `../src/datasources/configInput`。

- [ ] **Step 3: 往 `packages/shared/src/types.ts` 追加 API 契约类型**

```ts
export type DataSourceStatus = "ok" | "error" | "needs_reconfig" | "unchecked";

export interface DataSourceSummary {
  id: string;
  name: string;
  kind: DataSourceKind;
  /** 脱敏摘要,例如 mysql://bi_ro@10.0.0.5:3306/sales。永不含密码。 */
  target: string;
  status: DataSourceStatus;
  writePrivilege: WritePrivilege | null;
  lastCheckAt: string | null;
  lastCheckError: string | null;
  schemaFetchedAt: string | null;
  tableCount: number | null;
}

/** 回给前端表单回填用的连接字段。故意没有 password。 */
export interface DataSourceConnectionView {
  path?: string; host?: string; port?: number;
  database?: string; user?: string; ssl?: boolean; schema?: string;
}

export interface DataSourceDetail extends DataSourceSummary {
  connection: DataSourceConnectionView;
  hasPassword: boolean;
}

/** 与 DsConfig 同构,但 password 可选:PUT 时字段缺失表示「不改密码」。 */
export type DsConfigInput =
  | { kind: "sqlite"; path: string }
  | { kind: "mysql"; host: string; port: number; database: string; user: string; password?: string; ssl: boolean }
  | { kind: "postgres"; host: string; port: number; database: string; user: string; password?: string; ssl: boolean; schema?: string };

export interface DsApiError {
  code: DsErrorCode;
  message: string;
  /** 原生错误原文,前端折叠在「查看详情」里。 */
  details?: string;
  /** 测连失败但配置可能没错时为 true,前端给「仍然保存」。 */
  canForce?: boolean;
}

export interface TestConnectionOk {
  ok: true;
  writePrivilege: WritePrivilege;
  tableCount: number;
}

export interface SchemaResponse { schema: TableSchema[]; fetchedAt: string | null }

export interface RefreshSchemaResponse { tableCount: number; fetchedAt: string; elapsedMs: number }
```

- [ ] **Step 4: 写 `datasources/configInput.ts`**

```ts
import type { DataSourceConnectionView, DsConfig, DsConfigInput } from "@chatbi/shared";
import { DsError } from "./errors";

const str = (v: unknown): string | null => (typeof v === "string" && v.length > 0 ? v : null);
const bool = (v: unknown): boolean => v === true;

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  return null;
}

/** 解析请求体。返回 null 表示请求不合法,由路由回 400。 */
export function parseDsConfigInput(body: unknown): DsConfigInput | null {
  if (typeof body !== "object" || body === null) return null;
  const b = body as Record<string, unknown>;

  if (b.kind === "sqlite") {
    const path = str(b.path);
    return path ? { kind: "sqlite", path } : null;
  }

  if (b.kind === "mysql" || b.kind === "postgres") {
    const host = str(b.host);
    const port = num(b.port);
    const database = str(b.database);
    const user = str(b.user);
    if (!host || port === null || !database || !user) return null;
    // password 允许缺失(不改)或为空字符串(设为空),两者要区分,所以不能用 str()。
    const password = typeof b.password === "string" ? b.password : undefined;
    const common = { host, port, database, user, ssl: bool(b.ssl) };
    return b.kind === "mysql"
      ? { kind: "mysql", ...common, ...(password === undefined ? {} : { password }) }
      : {
          kind: "postgres", ...common,
          ...(password === undefined ? {} : { password }),
          ...(str(b.schema) ? { schema: str(b.schema)! } : {}),
        };
  }

  return null;
}

/**
 * 密码三态:字段缺失 = 保留旧值;`""` = 真的设成空;有值 = 换新的。
 * 换了 kind 时不继承旧密码——不同库的凭据没有关系。
 */
export function mergeConfig(existing: DsConfig | null, input: DsConfigInput): DsConfig {
  if (input.kind === "sqlite") return { kind: "sqlite", path: input.path };

  if (input.password !== undefined) return { ...input, password: input.password } as DsConfig;

  const inherit = existing && existing.kind === input.kind ? existing.password : undefined;
  if (inherit === undefined) {
    throw new DsError("UNKNOWN", "缺少密码:新建连接或更换数据库类型时必须填写密码");
  }
  return { ...input, password: inherit } as DsConfig;
}

/** 回给前端的连接字段,故意丢掉 password。 */
export function connectionView(config: DsConfig): DataSourceConnectionView {
  if (config.kind === "sqlite") return { path: config.path };
  const { host, port, database, user, ssl } = config;
  return config.kind === "postgres" && config.schema
    ? { host, port, database, user, ssl, schema: config.schema }
    : { host, port, database, user, ssl };
}
```

- [ ] **Step 5: 运行确认通过**

Run: `npx vitest --root apps/backend run tests/configInput.test.ts`
Expected: PASS,19 个测试。

- [ ] **Step 6: 提交**

```bash
git add packages/shared/src/types.ts apps/backend/src/datasources/configInput.ts apps/backend/tests/configInput.test.ts
git commit -m "feat(shared,backend): data source API contract types and config input merging"
```

---

> **本计划的范围已收窄为「后端集成」:Task 5–6 补齐于 2026-07-31,前端三个任务移到
> [P2a-3 计划](./2026-07-31-chatbi-p2a3-datasource-ui.md)。** 原因是五个任务全填进这一份会让它
> 涨到 2400 行以上,超过「单份计划 ~2000 行就该拆」的界线;而「后端 API 全部就位」本身
> 就是一个能独立验收的阶段(用 curl 就能验完 8 个端点)。
>
> ## Task 1–4 实施期的偏差记录(2026-07-31 执行时补)
>
> - **Task 1 一提交就会让 3 个文件变红**,不只计划里写的 `chat.route.test.ts`:`validate` 变成必传 `dialect` 后,`chatService.test.ts` 与 `acceptance.pipeline.test.ts` 也会在运行时炸(`dialect.kind` 读到 undefined)。计划 Task 3 Step 6 只预告了 `chat.route` 一个。
> - **`acceptance.pipeline.test.ts` / `chat.route.test.ts` / `server.ts` 的 deps 已就地改成异步 + 带 `dialect`**,否则全套回不了绿。`server.ts` 仍然是 P1 的单一 SQLite 连接 + `SQLITE_DIALECT`,**没有**接 registry——那是缺失的 Task 5 的事,已在代码里留注释说明。
> - **Task 3 里那条「SQL 执行报错重试一次后报错」的断言按计划要求做了前提改造**:假 db 改抛 `DsError("SCHEMA_STALE", …, "no such column: bad")`。用户可见消息现在是中文,所以原来的 `/no such column/` 断言挪到「重试 prompt 里含原生原文」上——原意(失败原因要到达模型)完整保留。
> - **`vitest.config.ts` 加了 `pool: "forks"`,这是修 bug 不是偏好**:`better-sqlite3` 的原生插件在 4 个以上 vitest worker **线程**里同时加载时,进程退出阶段段错误(exit 139,测试全过但 summary 打不完),5 次里崩 2 次。P2a 把碰 better-sqlite3 的测试文件从 3 个涨到 7 个,越过了阈值。改子进程池后连跑 5 次全净。
> - **`configInput.test.ts` 是 18 个测试**,计划里写的 19 个是数错了(断言条数没变)。

### Task 5: chat 路由按 dataSourceId 取 driver

`POST /api/chat` 现在必须说清「问哪个库」。路由不再接一个现成的 `ChatDeps`,而是接 `registry` + `llm`,每轮请求按 `dataSourceId` 组装 deps —— dialect 从 driver 上拿,schema 走 registry 的缓存。

**为什么 `dataSourceId` 缺失走 SSE `error` 而不是 400**:前端的 `streamChat` 遇到 `!res.ok` 只会报「服务器返回 400」,把中文原因丢了;走 `error` 事件则能把「缺少 dataSourceId」直接显示在会话里。`question` 缺失继续回 400(P1 行为,不动)——它是前端 bug,不是用户能看懂的错误。

**Files:**
- Modify: `apps/backend/src/routes/chat.ts`
- Modify: `apps/backend/src/server.ts`(deps 换成 registry;`SQLITE_DIALECT` 的临时导入去掉)
- Modify: `apps/backend/tests/chat.route.test.ts`
- Modify: `apps/backend/tests/acceptance.pipeline.test.ts`(改用真 sqlite driver,顺带验证 driver→chatService 这段真实链路)

**Interfaces:**
- Consumes: `DataSourceRegistry`、`Driver`(P2a-1 Task 8 / Task 4);`DsError`(P2a-1 Task 4);`ChatDeps`(P2a-2 Task 3);`config.queryTimeoutMs`
- Produces:
  - `interface ChatRouterDeps { registry: Pick<DataSourceRegistry, "get" | "schemaFor">; llm: ChatDeps["llm"] }`
  - `createChatRouter(deps: ChatRouterDeps): Router` —— 签名变了,不再收 `ChatDeps`
  - `POST /api/chat` body:`{ question: string; dataSourceId: string; history?: ChatTurn[]; context?: DrillContext }`

- [ ] **Step 1: 改现有路由测试,先让它红**

`apps/backend/tests/chat.route.test.ts` 的 `makeDeps` 整体换成假 registry。把顶部 `SQLITE_DIALECT` 的导入删掉(不再需要),`Driver` 的假实现里带上它:

```ts
import { describe, it, expect, vi } from "vitest";
import express from "express";
import request from "supertest";
import { createChatRouter } from "../src/routes/chat";
import { SQLITE_DIALECT } from "../src/datasources/dialect";
import { DsError } from "../src/datasources/errors";
import type { Driver } from "../src/datasources/driver";
import type { StreamEvent } from "@chatbi/shared";

/** 假 driver:只要能报 kind / dialect / runQuery 就够路由用。 */
function fakeDriver(): Driver {
  return {
    kind: "sqlite", dialect: SQLITE_DIALECT,
    testConnection: async () => ({ ok: true as const, writePrivilege: "readonly" as const }),
    introspect: async () => [],
    runQuery: vi.fn(async () => ({ rows: [{ a: 1 }], truncated: false })),
    probeWritePrivilege: async () => "readonly" as const,
    close: async () => { /* 假 driver 无需关闭 */ },
  };
}

function makeDeps(chatStream: (prompt: string) => AsyncIterable<string>, driver = fakeDriver()) {
  return {
    driver,
    registry: {
      get: vi.fn(async (id: string) => {
        if (id !== "ds1") throw new DsError("NOT_FOUND", "数据源不存在,可能已被删除");
        return driver;
      }),
      schemaFor: vi.fn(async () => []),
    },
    llm: { chatStream },
  };
}
```

`app(deps)` 保持原样(仍然 `createChatRouter(deps as any)`)。现有 4 条断言里凡是 `.send({ question: "q", history: [] })` 的,补上 `dataSourceId: "ds1"`。**一条断言都不删**:SSE 事件序列、缺 question 回 400、context 进 prompt、畸形 context 被忽略,全部要继续通过。

- [ ] **Step 2: 追加 dataSourceId 相关的新测试**

在 `chat.route.test.ts` 末尾追加:

```ts
describe("dataSourceId", () => {
  it("按 id 从 registry 取 driver", async () => {
    const deps = makeDeps(async function* () { yield llmJson; });
    await request(app(deps)).post("/api/chat").send({ question: "q", dataSourceId: "ds1", history: [] });
    expect(deps.registry.get).toHaveBeenCalledWith("ds1");
  });

  it("缺 dataSourceId 时走 SSE error,不是 400", async () => {
    const deps = makeDeps(async function* () { /* 不该被调用 */ });
    const res = await request(app(deps)).post("/api/chat").send({ question: "q", history: [] });
    expect(res.status).toBe(200);
    const events = readSse(res.text);
    expect(events).toEqual([{ type: "error", message: "缺少 dataSourceId,请先在顶栏选择数据源" }]);
    expect(deps.registry.get).not.toHaveBeenCalled();
  });

  it("id 不存在时把 DsError 的中文消息发成 error 事件", async () => {
    const deps = makeDeps(async function* () { /* 不该被调用 */ });
    const res = await request(app(deps)).post("/api/chat")
      .send({ question: "q", dataSourceId: "nope", history: [] });
    const events = readSse(res.text);
    expect(events).toEqual([{ type: "error", message: "数据源不存在,可能已被删除" }]);
  });

  it("schema 走 registry 的缓存,不直接调 driver.introspect", async () => {
    const driver = fakeDriver();
    const deps = makeDeps(async function* () { yield llmJson; }, driver);
    await request(app(deps)).post("/api/chat").send({ question: "q", dataSourceId: "ds1", history: [] });
    expect(deps.registry.schemaFor).toHaveBeenCalledWith("ds1");
  });

  it("查询带上 config 的超时值", async () => {
    const driver = fakeDriver();
    const deps = makeDeps(async function* () { yield llmJson; }, driver);
    await request(app(deps)).post("/api/chat").send({ question: "q", dataSourceId: "ds1", history: [] });
    const [, limit, timeout] = (driver.runQuery as any).mock.calls[0];
    expect(limit).toBe(1000);
    expect(timeout).toBe(5000);
  });
});
```

- [ ] **Step 3: 运行确认失败**

Run: `npx vitest --root apps/backend run tests/chat.route.test.ts`
Expected: FAIL —— 路由还在把 `deps` 当 `ChatDeps` 用,`deps.db` 是 undefined。

- [ ] **Step 4: 改 `routes/chat.ts`**

整个文件替换成:

```ts
import { Router, type Request, type Response } from "express";
import type { ChatTurn, DrillContext, StreamEvent } from "@chatbi/shared";
import { handleChat, type ChatDeps } from "../chatService";
import type { DataSourceRegistry } from "../datasources/registry";
import { DsError } from "../datasources/errors";
import { config } from "../config";

/**
 * 路由不再收现成的 ChatDeps:每轮请求要按 dataSourceId 取 driver,
 * dialect 与连接都跟着那个源走。
 */
export interface ChatRouterDeps {
  registry: Pick<DataSourceRegistry, "get" | "schemaFor">;
  llm: ChatDeps["llm"];
}

export function createChatRouter(deps: ChatRouterDeps): Router {
  const router = Router();
  router.post("/", async (req: Request, res: Response) => {
    const { question, dataSourceId, history, context } = req.body as {
      question: string; dataSourceId?: string; history?: ChatTurn[]; context?: DrillContext;
    };
    if (typeof question !== "string") { res.status(400).json({ error: "question required" }); return; }

    const drill = context && typeof context.lastSql === "string"
      ? { lastSql: context.lastSql, lastColumns: Array.isArray(context.lastColumns) ? context.lastColumns : [] }
      : undefined;

    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders?.();
    const send = (ev: StreamEvent) => res.write(`data: ${JSON.stringify(ev)}\n\n`);

    // 缺 id 走 error 事件而不是 400:前端只会把 400 显示成「服务器返回 400」,中文原因就丢了。
    if (typeof dataSourceId !== "string" || dataSourceId === "") {
      send({ type: "error", message: "缺少 dataSourceId,请先在顶栏选择数据源" });
      res.end();
      return;
    }

    try {
      const driver = await deps.registry.get(dataSourceId);
      const chatDeps: ChatDeps = {
        db: {
          // schema 走 registry:它管缓存缺失时 introspect 一次并写回。
          getSchema: () => deps.registry.schemaFor(dataSourceId),
          runQuery: (sql, limit) => driver.runQuery(sql, limit, config.queryTimeoutMs),
        },
        dialect: driver.dialect,
        llm: deps.llm,
      };
      for await (const ev of handleChat({ question, history: history ?? [], context: drill, deps: chatDeps })) {
        send(ev);
      }
    } catch (e) {
      // registry.get 的失败(NOT_FOUND / DECRYPT_ERROR)在这里;DsError 的 message 已是中文。
      send({ type: "error", message: e instanceof DsError ? e.message : (e as Error).message });
    } finally {
      res.end();
    }
  });
  return router;
}
```

- [ ] **Step 5: 运行确认通过**

Run: `npx vitest --root apps/backend run tests/chat.route.test.ts`
Expected: PASS —— 原有 4 条 + 新增 5 条。

- [ ] **Step 6: 改 `server.ts` 用 registry 装 chat 路由**

`startServer` 里那段「P1 的单一只读连接」整体删掉,换成 registry。同时删掉 `SQLITE_DIALECT` 与 `DbClient` 的临时导入(`DbClient` 仍被 `bootstrapApp` 用到,**不要删那处**):

```ts
export function startServer() {
  let app: { appDb: AppDb; registry: DataSourceRegistry; key: Buffer };
  try {
    app = bootstrapApp();
  } catch (e) {
    console.error("启动准备失败:", (e as Error).message);
    process.exit(1);
  }

  const server = express();
  server.use(express.json());
  server.use("/api/chat", createChatRouter({ registry: app.registry, llm: new LlmClient() }));

  const shutdown = async (): Promise<void> => {
    await app.registry.closeAll();
    app.appDb.close();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  server.listen(config.port, "localhost", () => console.log(`backend on http://localhost:${config.port}`));
}
```

注意**启动时不再做 schema 自检**:P1 那句 `db.getSchema()` 是为「只有一个库」设计的,现在做等于把 N 个源的连接在启动时全建一遍(spec 第 9 节明确不做启动全量测连)。源连不上要在列表里显示状态,而不是让服务起不来。

- [ ] **Step 7: 把验收测试改成走真 sqlite driver**

`apps/backend/tests/acceptance.pipeline.test.ts` 现在用同步 `DbClient` 包了一层假的 async。改成用真 driver,这样这条验收链路覆盖到 `driver → chatService`:

顶部导入加 `import { createSqliteDriver } from "../src/datasources/drivers/sqlite";`,`beforeAll` 里建 driver,`ask()` 里的 deps 换成:

```ts
  const deps = {
    db: {
      getSchema: () => driver.introspect(),
      runQuery: (s: string, limit: number) => driver.runQuery(s, limit, 5000),
    },
    dialect: driver.dialect,
    llm: { /* 原样不动 */ },
  };
```

`beforeAll` / `afterAll` 改成:

```ts
let db: DbClient;                       // 保留:第 8 条断言要用可读连接数行数
let driver: ReturnType<typeof createSqliteDriver>;

beforeAll(() => {
  mkdirSync(tmpDir, { recursive: true });
  const writable = new DbClient(dbPath);
  migrate(writable);
  writable.close();
  db = new DbClient(dbPath, { readonly: true });
  driver = createSqliteDriver({ kind: "sqlite", path: dbPath });
});
afterAll(async () => {
  await driver.close();
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});
```

`SQLITE_DIALECT` 的导入可以删掉(dialect 现在从 driver 上取)。8 条验收断言一条不动。

- [ ] **Step 8: 跑全量后端测试**

Run: `npx vitest --root apps/backend run`
Expected: PASS,MySQL/PG 各 1 skip。

- [ ] **Step 9: 真启动一次,确认 chat 链路仍然活着**

Run: `npm run dev --workspace=apps/backend`,另开一个终端:

```bash
# 拿到内置源的 id(需要 Ollama 在跑;没有 Ollama 时只验前两步)
curl -s -X POST http://localhost:5174/api/chat -H 'Content-Type: application/json' \
  -d '{"question":"按月统计订单金额","history":[]}'
```

Expected: 返回 `data: {"type":"error","message":"缺少 dataSourceId,请先在顶栏选择数据源"}`。带上一个不存在的 id 应得「数据源不存在」。**真实 id 要等 Task 6 的 `GET /api/datasources` 才能拿到**,所以这一步只验错误分支;完整链路在 Task 6 Step 9 一起验。

- [ ] **Step 10: 提交**

```bash
git add apps/backend/src/routes/chat.ts apps/backend/src/server.ts \
        apps/backend/tests/chat.route.test.ts apps/backend/tests/acceptance.pipeline.test.ts
git commit -m "feat(backend): chat route resolves driver by dataSourceId"
```

---

### Task 6: 数据源的 8 个端点

一个文件 8 个端点,是本计划最大的一块。**先做视图层的纯函数**(记录 → `DataSourceSummary` / `DataSourceDetail`),再做路由——`status` 的派生规则是最容易写错又最容易单测的部分。

**与 spec 第 10 节布局的一处细化**:spec 只列了 `routes/datasources.ts`。这里多一个 `datasources/view.ts` 放 `toSummary` / `toDetail`,理由和 P2a-1 把 `targetLabel` 放 `types.ts` 一样:`status` 派生是纯逻辑,塞进路由就只能靠 supertest 间接测。

**status 的派生规则(顺序不能换)**:

| 条件 | status |
|---|---|
| `configError`(解密失败) | `needs_reconfig` |
| `lastCheckOk === false` | `error` |
| `lastCheckOk === true` | `ok` |
| `lastCheckAt === null`(从没测过) | `unchecked` |

解密失败优先:这时候连 config 都读不出来,上一次的 `ok` 已经没有意义。

**Files:**
- Create: `apps/backend/src/datasources/view.ts`
- Create: `apps/backend/src/routes/datasources.ts`
- Modify: `apps/backend/src/server.ts`(挂 `/api/datasources`)
- Test: `apps/backend/tests/dsView.test.ts`
- Test: `apps/backend/tests/datasources.route.test.ts`

**Interfaces:**
- Consumes: `AppDb`(P2a-1 Task 1);仓储的 7 个函数与 `DuplicateNameError`(P2a-1 Task 3);`DataSourceRecord`、`targetLabel`(P2a-1 Task 3);`Driver`、`DataSourceRegistry`(P2a-1 Task 4 / Task 8);`DsError`(P2a-1 Task 4);`parseDsConfigInput`、`mergeConfig`、`connectionView`(P2a-2 Task 4);`DataSourceSummary`、`DataSourceDetail`、`DsApiError`、`TestConnectionOk`、`SchemaResponse`、`RefreshSchemaResponse`(P2a-2 Task 4)
- Produces:
  - `function toSummary(rec: DataSourceRecord, cache: { schema: TableSchema[]; fetchedAt: string } | null): DataSourceSummary`
  - `function toDetail(rec: DataSourceRecord, cache: { schema: TableSchema[]; fetchedAt: string } | null): DataSourceDetail`
  - `interface DsRouterDeps { db: AppDb; key: Buffer; registry: DataSourceRegistry; createDriver?: (config: DsConfig) => Driver }`
  - `function createDataSourcesRouter(deps: DsRouterDeps): Router`

- [ ] **Step 1: 写视图层的失败测试**

Create `apps/backend/tests/dsView.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { toSummary, toDetail } from "../src/datasources/view";
import type { DataSourceRecord } from "../src/datasources/types";
import type { TableSchema } from "@chatbi/shared";

const base: DataSourceRecord = {
  id: "ds1", name: "销售库", kind: "mysql", owner: "local",
  config: {
    kind: "mysql", host: "10.0.0.5", port: 3306, database: "sales",
    user: "bi_ro", password: "s3cret", ssl: false,
  },
  configError: false, writePrivilege: "readonly",
  createdAt: "2026-07-01T00:00:00.000Z", updatedAt: "2026-07-01T00:00:00.000Z",
  lastCheckAt: "2026-07-02T00:00:00.000Z", lastCheckOk: true, lastCheckError: null,
};

const schema: TableSchema[] = [
  { tableName: "orders", columns: [{ name: "id", type: "int", notNull: true, pk: true }], foreignKeys: [] },
  { tableName: "customers", columns: [], foreignKeys: [] },
];
const cache = { schema, fetchedAt: "2026-07-02T01:00:00.000Z" };

describe("toSummary 的 status 派生", () => {
  it("测过且成功 → ok", () => {
    expect(toSummary(base, cache).status).toBe("ok");
  });
  it("测过且失败 → error", () => {
    expect(toSummary({ ...base, lastCheckOk: false, lastCheckError: "连不上" }, cache).status).toBe("error");
  });
  it("从没测过 → unchecked", () => {
    expect(toSummary({ ...base, lastCheckAt: null, lastCheckOk: null }, null).status).toBe("unchecked");
  });
  it("解密失败 → needs_reconfig,盖掉上一次的 ok", () => {
    const broken = { ...base, config: null, configError: true };
    expect(toSummary(broken, cache).status).toBe("needs_reconfig");
  });
});

describe("toSummary 的其余字段", () => {
  it("target 是脱敏摘要,不含密码", () => {
    const s = toSummary(base, cache);
    expect(s.target).toBe("mysql://bi_ro@10.0.0.5:3306/sales");
    expect(JSON.stringify(s)).not.toContain("s3cret");
  });
  it("解密失败时 target 给出可读占位,不是空字符串", () => {
    expect(toSummary({ ...base, config: null, configError: true }, null).target).toBe("(凭据无法解密)");
  });
  it("tableCount 来自缓存的表数量", () => {
    expect(toSummary(base, cache).tableCount).toBe(2);
  });
  it("没有缓存时 tableCount 与 schemaFetchedAt 都是 null", () => {
    const s = toSummary(base, null);
    expect(s.tableCount).toBeNull();
    expect(s.schemaFetchedAt).toBeNull();
  });
  it("带上 name / kind / writePrivilege / lastCheck 两项", () => {
    const s = toSummary({ ...base, lastCheckOk: false, lastCheckError: "连不上" }, cache);
    expect(s).toMatchObject({
      id: "ds1", name: "销售库", kind: "mysql",
      writePrivilege: "readonly",
      lastCheckAt: "2026-07-02T00:00:00.000Z", lastCheckError: "连不上",
    });
  });
});

describe("toDetail", () => {
  it("在 summary 之上补 connection 与 hasPassword,且没有 password", () => {
    const d = toDetail(base, cache);
    expect(d.connection).toEqual({
      host: "10.0.0.5", port: 3306, database: "sales", user: "bi_ro", ssl: false,
    });
    expect(d.hasPassword).toBe(true);
    expect(JSON.stringify(d)).not.toContain("s3cret");
  });
  it("sqlite 的 connection 只有 path,hasPassword 为 false", () => {
    const lite: DataSourceRecord = {
      ...base, kind: "sqlite", config: { kind: "sqlite", path: "./data/chatbi.db" },
    };
    const d = toDetail(lite, null);
    expect(d.connection).toEqual({ path: "./data/chatbi.db" });
    expect(d.hasPassword).toBe(false);
  });
  it("空密码算没有密码", () => {
    const d = toDetail({ ...base, config: { ...base.config as any, password: "" } }, null);
    expect(d.hasPassword).toBe(false);
  });
  it("解密失败时 connection 是空对象,hasPassword 为 false", () => {
    const d = toDetail({ ...base, config: null, configError: true }, null);
    expect(d.connection).toEqual({});
    expect(d.hasPassword).toBe(false);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest --root apps/backend run tests/dsView.test.ts`
Expected: FAIL,解析不到 `../src/datasources/view`。

- [ ] **Step 3: 写 `datasources/view.ts`**

```ts
import type {
  DataSourceDetail, DataSourceStatus, DataSourceSummary, TableSchema,
} from "@chatbi/shared";
import { connectionView } from "./configInput";
import { targetLabel, type DataSourceRecord } from "./types";

type Cache = { schema: TableSchema[]; fetchedAt: string } | null;

/**
 * 解密失败优先:那时候 config 读不出来,上一次的 ok 已经没有意义。
 * 其余按「测过就看结果、没测过就是 unchecked」。
 */
function statusOf(rec: DataSourceRecord): DataSourceStatus {
  if (rec.configError) return "needs_reconfig";
  if (rec.lastCheckOk === true) return "ok";
  if (rec.lastCheckOk === false) return "error";
  return "unchecked";
}

export function toSummary(rec: DataSourceRecord, cache: Cache): DataSourceSummary {
  return {
    id: rec.id,
    name: rec.name,
    kind: rec.kind,
    // 密码永不出后端:target 由 targetLabel 拼,它只取非敏感字段。
    target: rec.config ? targetLabel(rec.config) : "(凭据无法解密)",
    status: statusOf(rec),
    writePrivilege: rec.writePrivilege,
    lastCheckAt: rec.lastCheckAt,
    lastCheckError: rec.lastCheckError,
    schemaFetchedAt: cache?.fetchedAt ?? null,
    tableCount: cache ? cache.schema.length : null,
  };
}

export function toDetail(rec: DataSourceRecord, cache: Cache): DataSourceDetail {
  const hasPassword = rec.config !== null
    && rec.config.kind !== "sqlite"
    && rec.config.password.length > 0;
  return {
    ...toSummary(rec, cache),
    connection: rec.config ? connectionView(rec.config) : {},
    hasPassword,
  };
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest --root apps/backend run tests/dsView.test.ts`
Expected: PASS,12 个测试。

- [ ] **Step 5: 提交视图层**

```bash
git add apps/backend/src/datasources/view.ts apps/backend/tests/dsView.test.ts
git commit -m "feat(backend): data source summary/detail view mapping"
```

- [ ] **Step 6: 写路由的失败测试**

用真 `app.db`(临时目录)+ 注入的假 driver:仓储与迁移是真的,只有「连远程库」这一步是假的。这样密码脱敏、409、级联删除都是真行为。

Create `apps/backend/tests/datasources.route.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import express from "express";
import request from "supertest";
import { openAppDb, type AppDb } from "../src/appDb/index";
import { runMigrations } from "../src/appDb/migrations";
import { createDataSource, getSchemaCache } from "../src/appDb/dataSourceRepo";
import { createRegistry } from "../src/datasources/registry";
import { createDataSourcesRouter } from "../src/routes/datasources";
import { SQLITE_DIALECT } from "../src/datasources/dialect";
import { DsError } from "../src/datasources/errors";
import type { Driver } from "../src/datasources/driver";
import type { DsConfig } from "../src/datasources/types";
import type { TableSchema } from "@chatbi/shared";

const tmpDir = join(process.cwd(), ".tmp-test-dsroute");
const key = randomBytes(32);
let db: AppDb;

const SCHEMA: TableSchema[] = [
  { tableName: "orders", columns: [{ name: "id", type: "int", notNull: true, pk: true }], foreignKeys: [] },
  { tableName: "customers", columns: [], foreignKeys: [] },
];

const mysqlBody = {
  kind: "mysql", host: "10.0.0.5", port: 3306, database: "sales",
  user: "bi_ro", password: "s3cret", ssl: false,
};

/** 可控的假 driver:testConnection 的成败与 introspect 的返回都能摆。 */
function fakeDriver(over: Partial<{ ok: boolean; writePrivilege: "readonly" | "writable" | "unknown" }> = {}) {
  const d = {
    kind: "mysql" as const, dialect: SQLITE_DIALECT,
    closed: 0,
    testConnection: vi.fn(async () =>
      over.ok === false
        ? { ok: false as const, code: "AUTH_ERROR" as const, message: "认证失败,请检查用户名与密码", details: "ER_ACCESS_DENIED_ERROR" }
        : { ok: true as const, writePrivilege: over.writePrivilege ?? "readonly" }),
    introspect: vi.fn(async () => SCHEMA),
    runQuery: async () => ({ rows: [], truncated: false }),
    probeWritePrivilege: async () => over.writePrivilege ?? "readonly",
    close: async () => { d.closed++; },
  };
  return d;
}

function makeApp(createDriver: (config: DsConfig) => Driver) {
  const registry = createRegistry({ db, key, createDriver });
  const router = createDataSourcesRouter({ db, key, registry, createDriver });
  return { app: express().use(express.json()).use("/api/datasources", router), registry };
}

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  db = openAppDb(join(tmpDir, "app.db"));
  runMigrations(db);
});
afterEach(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

describe("GET /api/datasources", () => {
  it("空库返回空数组", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const res = await request(app).get("/api/datasources");
    expect(res.status).toBe(200);
    expect(res.body).toEqual([]);
  });

  it("列出已存的源,带 target 与 status,且不含密码", async () => {
    createDataSource(db, key, { name: "销售库", config: mysqlBody as DsConfig });
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const res = await request(app).get("/api/datasources");
    expect(res.body).toHaveLength(1);
    expect(res.body[0]).toMatchObject({
      name: "销售库", kind: "mysql",
      target: "mysql://bi_ro@10.0.0.5:3306/sales",
      status: "unchecked",
    });
    expect(JSON.stringify(res.body)).not.toContain("s3cret");
  });
});

describe("POST /api/datasources", () => {
  it("测连成功则落库,顺带写 schema 缓存并返回表数量", async () => {
    const driver = fakeDriver();
    const { app } = makeApp(() => driver as unknown as Driver);
    const res = await request(app).post("/api/datasources").send({ name: "销售库", ...mysqlBody });
    expect(res.status).toBe(201);
    expect(res.body).toMatchObject({ name: "销售库", status: "ok", tableCount: 2 });
    expect(driver.introspect).toHaveBeenCalled();
    expect(getSchemaCache(db, res.body.id)!.schema).toEqual(SCHEMA);
  });

  it("响应体里没有密码,只有 hasPassword", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const res = await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody });
    expect(JSON.stringify(res.body)).not.toContain("s3cret");
    expect(res.body.hasPassword).toBe(true);
    expect(res.body.connection.password).toBeUndefined();
  });

  it("测连失败则不落库,返回 400 与 canForce", async () => {
    const { app } = makeApp(() => fakeDriver({ ok: false }) as unknown as Driver);
    const res = await request(app).post("/api/datasources").send({ name: "连不上的", ...mysqlBody });
    expect(res.status).toBe(400);
    expect(res.body).toMatchObject({
      code: "AUTH_ERROR", message: "认证失败,请检查用户名与密码",
      details: "ER_ACCESS_DENIED_ERROR", canForce: true,
    });
    expect((await request(app).get("/api/datasources")).body).toEqual([]);
  });

  it("force: true 时跳过测连直接存,状态记为 error", async () => {
    const driver = fakeDriver({ ok: false });
    const { app } = makeApp(() => driver as unknown as Driver);
    const res = await request(app).post("/api/datasources")
      .send({ name: "先存着", ...mysqlBody, force: true });
    expect(res.status).toBe(201);
    expect(res.body.status).toBe("error");
    expect(driver.testConnection).not.toHaveBeenCalled();
  });

  it("有写权限的账号照样存,但 writePrivilege 记为 writable", async () => {
    const { app } = makeApp(() => fakeDriver({ writePrivilege: "writable" }) as unknown as Driver);
    const res = await request(app).post("/api/datasources").send({ name: "可写库", ...mysqlBody });
    expect(res.body.writePrivilege).toBe("writable");
  });

  it("同名冲突返回 409 与中文消息,不是 SQLite 原生报错", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    await request(app).post("/api/datasources").send({ name: "重名", ...mysqlBody });
    const res = await request(app).post("/api/datasources").send({ name: "重名", ...mysqlBody });
    expect(res.status).toBe(409);
    expect(res.body.message).toContain("已有同名数据源");
    expect(res.body.message).not.toContain("UNIQUE");
  });

  it("缺 name 返回 400", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    expect((await request(app).post("/api/datasources").send(mysqlBody)).status).toBe(400);
  });

  it("配置不合法返回 400", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const res = await request(app).post("/api/datasources").send({ name: "x", kind: "oracle" });
    expect(res.status).toBe(400);
  });

  it("新建时缺密码返回 400,不静默存空密码", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const { password, ...noPw } = mysqlBody;
    const res = await request(app).post("/api/datasources").send({ name: "x", ...noPw });
    expect(res.status).toBe(400);
    expect(res.body.message).toContain("密码");
  });
});

describe("PUT /api/datasources/:id", () => {
  const seed = async (app: express.Express) =>
    (await request(app).post("/api/datasources").send({ name: "原名", ...mysqlBody })).body.id;

  it("改名保留旧密码(password 字段缺失)", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = await seed(app);
    const { password, ...noPw } = mysqlBody;
    const res = await request(app).put(`/api/datasources/${id}`).send({ name: "新名", ...noPw });
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({ name: "新名", hasPassword: true });
  });

  it("显式传空密码则真的清空(hasPassword 变 false)", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = await seed(app);
    const res = await request(app).put(`/api/datasources/${id}`).send({ name: "原名", ...mysqlBody, password: "" });
    expect(res.body.hasPassword).toBe(false);
  });

  it("改完之后 registry 里的旧连接被关掉", async () => {
    const made: ReturnType<typeof fakeDriver>[] = [];
    const { app, registry } = makeApp(() => { const d = fakeDriver(); made.push(d); return d as unknown as Driver; });
    const id = await seed(app);
    await registry.get(id);                       // 先建一个活连接
    const before = made.length;
    await request(app).put(`/api/datasources/${id}`).send({ name: "改了", ...mysqlBody });
    expect(made.slice(0, before).some(d => d.closed > 0)).toBe(true);
  });

  it("id 不存在返回 404", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const res = await request(app).put("/api/datasources/nope").send({ name: "x", ...mysqlBody });
    expect(res.status).toBe(404);
    expect(res.body.code).toBe("NOT_FOUND");
  });

  it("改成已存在的名字返回 409", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    await request(app).post("/api/datasources").send({ name: "占用中", ...mysqlBody });
    const id = (await request(app).post("/api/datasources").send({ name: "待改", ...mysqlBody })).body.id;
    const res = await request(app).put(`/api/datasources/${id}`).send({ name: "占用中", ...mysqlBody });
    expect(res.status).toBe(409);
  });
});

describe("DELETE /api/datasources/:id", () => {
  it("删掉后列表为空,schema 缓存跟着走", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = (await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody })).body.id;
    expect(getSchemaCache(db, id)).not.toBeNull();
    expect((await request(app).delete(`/api/datasources/${id}`)).status).toBe(204);
    expect((await request(app).get("/api/datasources")).body).toEqual([]);
    expect(getSchemaCache(db, id)).toBeNull();
  });

  it("删不存在的返回 404", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    expect((await request(app).delete("/api/datasources/nope")).status).toBe(404);
  });
});

describe("POST /api/datasources/test(未保存的表单)", () => {
  it("成功返回写权限与表数量,并关掉临时连接", async () => {
    const driver = fakeDriver();
    const { app } = makeApp(() => driver as unknown as Driver);
    const res = await request(app).post("/api/datasources/test").send(mysqlBody);
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ ok: true, writePrivilege: "readonly", tableCount: 2 });
    expect(driver.closed).toBe(1);      // 不留悬空连接
  });

  it("失败返回 400 与可读消息 + 原文详情", async () => {
    const { app } = makeApp(() => fakeDriver({ ok: false }) as unknown as Driver);
    const res = await request(app).post("/api/datasources/test").send(mysqlBody);
    expect(res.status).toBe(400);
    expect(res.body).toMatchObject({ code: "AUTH_ERROR", details: "ER_ACCESS_DENIED_ERROR" });
  });

  it("不落库", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    await request(app).post("/api/datasources/test").send(mysqlBody);
    expect((await request(app).get("/api/datasources")).body).toEqual([]);
  });
});

describe("POST /api/datasources/:id/test(已存源)", () => {
  it("成功时把结果记进 lastCheck", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = (await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody })).body.id;
    const res = await request(app).post(`/api/datasources/${id}/test`);
    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
    const list = (await request(app).get("/api/datasources")).body;
    expect(list[0]).toMatchObject({ status: "ok", lastCheckError: null });
  });

  it("失败时状态变 error 并记下原因", async () => {
    let fail = false;
    const { app } = makeApp(() => (fail ? fakeDriver({ ok: false }) : fakeDriver()) as unknown as Driver);
    const id = (await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody })).body.id;
    fail = true;
    await request(app).post(`/api/datasources/${id}/test`);
    const list = (await request(app).get("/api/datasources")).body;
    expect(list[0].status).toBe("error");
    expect(list[0].lastCheckError).toContain("认证失败");
  });

  it("id 不存在返回 404", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    expect((await request(app).post("/api/datasources/nope/test")).status).toBe(404);
  });
});

describe("刷新与读取表结构", () => {
  it("refresh-schema 重抓并返回表数量与耗时", async () => {
    const driver = fakeDriver();
    const { app } = makeApp(() => driver as unknown as Driver);
    const id = (await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody })).body.id;
    const before = driver.introspect.mock.calls.length;
    const res = await request(app).post(`/api/datasources/${id}/refresh-schema`);
    expect(res.status).toBe(200);
    expect(res.body.tableCount).toBe(2);
    expect(res.body.fetchedAt).toBeTruthy();
    expect(typeof res.body.elapsedMs).toBe("number");
    expect(driver.introspect.mock.calls.length).toBe(before + 1);
  });

  it("GET :id/schema 返回缓存的结构与时间戳", async () => {
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = (await request(app).post("/api/datasources").send({ name: "x", ...mysqlBody })).body.id;
    const res = await request(app).get(`/api/datasources/${id}/schema`);
    expect(res.status).toBe(200);
    expect(res.body.schema).toEqual(SCHEMA);
    expect(res.body.fetchedAt).toBeTruthy();
  });

  it("没有缓存时返回空数组与 null 时间戳,不是 404", async () => {
    createDataSource(db, key, { name: "没测过", config: mysqlBody as DsConfig });
    const { app } = makeApp(() => fakeDriver() as unknown as Driver);
    const id = (await request(app).get("/api/datasources")).body[0].id;
    const res = await request(app).get(`/api/datasources/${id}/schema`);
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ schema: [], fetchedAt: null });
  });

  it("解密失败的源报 DECRYPT_ERROR 而不是 500", async () => {
    createDataSource(db, key, { name: "换过钥匙", config: mysqlBody as DsConfig });
    const otherKey = randomBytes(32);
    const registry = createRegistry({ db, key: otherKey, createDriver: () => fakeDriver() as unknown as Driver });
    const app = express().use(express.json()).use("/api/datasources",
      createDataSourcesRouter({ db, key: otherKey, registry, createDriver: () => fakeDriver() as unknown as Driver }));
    const id = (await request(app).get("/api/datasources")).body[0].id;
    const res = await request(app).post(`/api/datasources/${id}/refresh-schema`);
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("DECRYPT_ERROR");
  });
});
```

- [ ] **Step 7: 运行确认失败**

Run: `npx vitest --root apps/backend run tests/datasources.route.test.ts`
Expected: FAIL,解析不到 `../src/routes/datasources`。

- [ ] **Step 8: 写 `routes/datasources.ts`**

三条贯穿全文件的规则,先定下来再看端点:

1. **错误只有一处出口。** 每个 handler 用 `handle()` 包一层,`DsError` 与仓储的 `DuplicateNameError` 抛出来就自动翻成 `{ code, message, details?, canForce? }`;`NOT_FOUND` → 404、`DUPLICATE_NAME` → 409、其余 → 400,只有真 bug 才 500。这样端点里能直接 `throw`,不必每处写一遍 `res.status(...)`。
2. **临时连接自己关,长连接交给 registry。** 「测未保存的表单」与「新建时先测连」这两处的 config 还没有 id,不能进 registry,所以走 `make(config)` 并在 `finally` 里 `close()`;已存源一律 `registry.get(id)`,顺带白拿 `NOT_FOUND` / `DECRYPT_ERROR`。
3. **写完库再读一次。** `recordCheck` / `putSchemaCache` 之后回给前端的 detail 必须重新 `getDataSource`,否则 `status` 还是写之前的值。

```ts
export interface DsRouterDeps {
  db: AppDb;
  key: Buffer;
  registry: DataSourceRegistry;
  /** 测未保存的表单要在 registry 之外临时建连接;测试注入假 driver 也走这里。 */
  createDriver?: (config: DsConfig) => Driver;
}

/** 记录不存在是 404,重名是 409,其余数据源错误都是 400——500 只留给真 bug。 */
function statusFor(code: DsErrorCode): number {
  if (code === "NOT_FOUND") return 404;
  if (code === "DUPLICATE_NAME") return 409;
  return 400;
}

function asDsError(e: unknown): DsError {
  if (e instanceof DsError) return e;
  // 仓储的重名异常在这里翻成统一错误形状,SQLite 的 UNIQUE 原文不外泄。
  if (e instanceof DuplicateNameError) return new DsError("DUPLICATE_NAME", e.message);
  return new DsError("UNKNOWN", "服务器内部错误", (e as Error).message);
}

/** 一次连接干两件事:测通 + 抓结构。临时连接不进 registry,所以自己关。 */
async function probe(config: DsConfig): Promise<{ writePrivilege: WritePrivilege; schema: TableSchema[] }> {
  const driver = make(config);
  try {
    const r = await driver.testConnection();
    if (!r.ok) throw new DsError(r.code, r.message, r.details);
    return { writePrivilege: r.writePrivilege, schema: await driver.introspect() };
  } finally {
    await driver.close().catch(() => { /* 本来就没连上 */ });
  }
}
```

八个端点的关键点(完整实现见 `apps/backend/src/routes/datasources.ts`):

| 端点 | 要点 |
|---|---|
| `GET /` | `listDataSources` 后逐条配 `getSchemaCache`,过 `toSummary` |
| `POST /test` | `mergeConfig(null, input)`:未保存的表单没有旧密码可继承,缺密码直接 400 |
| `POST /` | `force !== true` 才 `probe`;失败 `sendDsError(..., { canForce: true })` 且**不落库**;成功后 `createDataSource` + `putSchemaCache` + `recordCheck({ ok: true })` |
| `PUT /:id` | `mergeConfig(existing.config, input)` 管密码三态;写完 `registry.invalidate(id)` |
| `DELETE /:id` | 先 `invalidate` 再删记录(sqlite 要先放掉文件句柄),`schema_cache` 靠外键级联 |
| `POST /:id/test` | 走 `registry.get`;失败时 `recordCheck({ ok: false })` **并 invalidate**——连不上的连接别留在池子里 |
| `POST /:id/refresh-schema` | `registry.refreshSchema` + `Date.now()` 差值给 `elapsedMs` |
| `GET /:id/schema` | 没缓存回 `{ schema: [], fetchedAt: null }`,不是 404;id 不存在才 404 |

`force: true` 存下来的源要 `recordCheck({ ok: false, error: "保存时跳过了连接测试,请点「测试连接」确认" })`。不能什么都不写:`lastCheckOk` 留 `null` 的话 `status` 会是 `unchecked`,而用户明明已经看到过一次失败,列表里再显示「未测试」是在骗人。

- [ ] **Step 9: 运行确认通过**

Run: `npx vitest --root apps/backend run tests/datasources.route.test.ts`
Expected: PASS,28 个测试。

- [ ] **Step 10: 挂到 `server.ts`**

```ts
  server.use("/api/datasources", createDataSourcesRouter({
    db: app.appDb, key: app.key, registry: app.registry,
  }));
```

- [ ] **Step 11: 跑全量并真启动一次验 8 个端点**

Run: `npx tsc --noEmit -p apps/backend && npm test --workspaces`
Expected: 后端 373 + 前端 67 + shared 29,MySQL/PG 各 1 skip。

再 `PORT=5201 npx tsx apps/backend/src/server.ts`,另开终端按顺序 curl:列表 → `POST /test`(sqlite 指向 `./data/chatbi.db`)→ 新建 → 重名(应 409 `DUPLICATE_NAME`)→ 改名 → `:id/test` → `refresh-schema` → `:id/schema` → 404 分支(`PUT/DELETE/GET` 一个不存在的 id)→ 删除 → 带真实 id 打一次 `/api/chat`。

**两个环境坑**:①Git Bash 下 `curl -d` 里的中文会乱码,那是终端编码,不是服务端 bug——验中文看 `GET /` 里内置源的名字;②`npx tsx` 起的服务 `kill` 掉的是 npx 外壳,tsx 子进程还占着端口,收尾用 `netstat -ano | grep ":<port> "` 找 PID 再 `taskkill //PID <pid> //F`。

- [ ] **Step 12: 提交**

```bash
git add apps/backend/src/routes/datasources.ts apps/backend/src/server.ts \
        apps/backend/src/datasources/errors.ts packages/shared/src/types.ts \
        apps/backend/tests/datasources.route.test.ts
git commit -m "feat(backend,shared): data source management endpoints"
```

---

<!--TASK7-->

---

<!--TASK8-->

---

<!--TASK9-->

---

<!--CLOSING-->
