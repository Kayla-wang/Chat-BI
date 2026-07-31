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

<!--TASK5-->

---

<!--TASK6-->

---

<!--TASK7-->

---

<!--TASK8-->

---

<!--TASK9-->

---

<!--CLOSING-->
