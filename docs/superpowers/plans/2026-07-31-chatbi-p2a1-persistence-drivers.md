# Chat-BI P2a-1 实施计划：元数据持久化与三驱动数据源层

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在后端建立独立的应用元数据库与一个窄口驱动抽象,使 Chat-BI 能连接并只读查询 SQLite / MySQL / PostgreSQL 三种数据源。

**Architecture:** 新建 `apps/backend/src/appDb/`(可写的 `app.db`:记版本迁移、AES-256-GCM 凭据加密、数据源仓储)与 `apps/backend/src/datasources/`(五方法 `Driver` 接口、三成员 `Dialect`、原生错误码映射、三个 driver 实现、按 id 懒建连接的 registry)。本计划**只做后端基座**,不改 chat 链路、不改前端——那些在 P2a-2。本计划完成时 `app.db` 能存取加密的数据源、三个 driver 都通过同一套契约测试。

**Tech Stack:** TypeScript 5.4 ESM、better-sqlite3 12(app.db 与 sqlite driver)、mysql2(promise 接口)、pg、node:crypto、vitest 1.6

**前序文档:** [设计 spec](../specs/2026-07-31-chatbi-p2-datasource-design.md) —— 第二部分第 1–5 节与第 10–11 节

## Global Constraints

- **Node 20+**(`better-sqlite3` 12 的下限);本机是 v24。
- **ESM**:`apps/backend/package.json` 有 `"type": "module"`。所有相对导入**不写扩展名**(现有代码风格,`tsx`/`vitest` 都能解析)。
- **纯 CJS 依赖必须默认导入再取属性**:`node-sql-parser` 已踩过这个坑(见 `sqlGuard.ts` 顶部注释)。`pg` 同为 CJS,写 `import pg from "pg"; const { Client } = pg;`,**不要**写 `import { Client } from "pg"`——测试里能过,真实启动会抛 `SyntaxError`。`mysql2/promise` 有正确的 ESM 导出,可以具名导入。
- **配置只读 `process.env`,不接 dotenv**(项目既有决定)。新增环境变量必须在 `config.ts` 里给默认值。
- **中文标点约定**(项目既有风格,照抄):句内停顿用**半角逗号** `,`,冒号用**半角** `:`,句末用**全角句号** `。`,强调用 `「」`。注释与测试描述都用中文。
- **测试描述用中文**,`describe` / `it` 的字符串是中文短句(见 `tests/dbClient.test.ts`)。
- **只允许新增两个后端依赖**:`mysql2`、`pg`(以及 `@types/pg`)。不引 knex、不引 dotenv、不引 nanoid(用 `crypto.randomUUID()`)。
- **临时目录约定**:测试用 `join(process.cwd(), ".tmp-test")`,`afterEach` 里 `rmSync`。根 `.gitignore` 已有 `.tmp-*/`。
- **`packages/shared` 只许追加数据源契约类型**(`DataSourceKind`、`WritePrivilege`、`DsConfig`)。这三个是**前后端共用的请求契约**——P2a-2 的前端表单要构造 `DsConfig` 发给后端,两边各定义一份联合类型是真实的重复。`TableSchema`、`Row`、`ChartSpec`、`StreamEvent` 沿用现有定义,一个字段都不加;`renderer.ts` 不动。`src/index.ts` 已经 `export * from "./types"`,追加即自动导出。
- **不改 `ChartSpec` 与 `packages/shared/src/renderer.ts`**(spec 的贯穿约束 2)。
- **每个任务结束时 `npx vitest --root apps/backend run` 必须全绿**,包括 P1 留下的 171 个后端测试。

---

### Task 1: app.db 连接与记版本的迁移框架

`app.db` 存**我们的**元数据(数据源、schema 缓存,以后加语义模型与看板),和被分析的业务库 `chatbi.db` 彻底分开。现有 `migrate.ts` 只无条件跑示例业务数据的 DDL,不记版本,**不动它**。

**与 spec 的一处细化**:spec 第 1 节的 `MIGRATIONS` 草稿里每条是 `{ id, name, sql }`。这里改成 `{ id, name, up(db) }`——因为 Task 9 的「内置示例源」迁移必须**加密** config 后再插入,纯 SQL 字符串做不到。纯 DDL 的迁移写成 `up: db => db.raw.exec(SQL)`,形状统一。

**Files:**
- Create: `apps/backend/src/appDb/index.ts`
- Create: `apps/backend/src/appDb/migrations.ts`
- Modify: `apps/backend/src/config.ts`(加 `appDbPath`)
- Test: `apps/backend/tests/appDb.migrations.test.ts`

**Interfaces:**
- Consumes: 无(本计划第一个任务)
- Produces:
  - `interface AppDb { raw: Database; close(): void }`
  - `function openAppDb(path: string): AppDb` —— 建父目录、开可写连接、`PRAGMA journal_mode = WAL`、`PRAGMA foreign_keys = ON`
  - `interface Migration { id: number; name: string; up(db: AppDb): void }`
  - `const MIGRATIONS: Migration[]` —— 本任务含 id 1、2
  - `function runMigrations(db: AppDb, migrations?: Migration[]): number[]` —— 返回本次实际应用的 id 列表
  - `config.appDbPath: string`
- **边界约定**:`AppDb.raw` 是 better-sqlite3 实例,**只允许 `src/appDb/` 目录下的文件访问**。目录外一律通过 Task 3 的仓储函数。

- [ ] **Step 1: 写失败的测试**

Create `apps/backend/tests/appDb.migrations.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { openAppDb, type AppDb } from "../src/appDb/index";
import { runMigrations, MIGRATIONS, type Migration } from "../src/appDb/migrations";

const tmpDir = join(process.cwd(), ".tmp-test");
const dbPath = join(tmpDir, "app.db");
let db: AppDb;

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  db = openAppDb(dbPath);
});
afterEach(() => {
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

const tableNames = (d: AppDb): string[] =>
  (d.raw.prepare("SELECT name FROM sqlite_master WHERE type='table'").all() as { name: string }[])
    .map(r => r.name);

describe("openAppDb", () => {
  it("打开外键约束", () => {
    expect(db.raw.pragma("foreign_keys", { simple: true })).toBe(1);
  });
});

describe("runMigrations", () => {
  it("空库跑到最新,建出两张表与版本表", () => {
    const applied = runMigrations(db);
    expect(applied).toEqual([1, 2]);
    expect(tableNames(db)).toEqual(
      expect.arrayContaining(["schema_migrations", "data_sources", "schema_cache"]),
    );
  });

  it("重复跑是幂等的,第二次什么也不应用", () => {
    runMigrations(db);
    expect(runMigrations(db)).toEqual([]);
  });

  it("只补跑缺失的那几号", () => {
    const first: Migration = MIGRATIONS[0];
    runMigrations(db, [first]);
    expect(runMigrations(db)).toEqual(MIGRATIONS.slice(1).map(m => m.id));
  });

  it("中途失败时整批回滚,已成功的那条也不留痕", () => {
    const boom: Migration = {
      id: 999, name: "boom",
      up: () => { throw new Error("故意失败"); },
    };
    expect(() => runMigrations(db, [...MIGRATIONS, boom])).toThrow(/迁移 999 .*boom/);
    expect(tableNames(db)).not.toContain("data_sources");
    expect(tableNames(db)).not.toContain("schema_migrations");
  });

  it("data_sources 的 name 唯一", () => {
    runMigrations(db);
    const ins = db.raw.prepare(
      `INSERT INTO data_sources
        (id, name, kind, config_cipher, config_iv, config_tag, created_at, updated_at)
       VALUES (?, 'dup', 'sqlite', x'00', x'00', x'00', '', '')`,
    );
    ins.run("a");
    expect(() => ins.run("b")).toThrow(/UNIQUE/i);
  });

  it("删数据源时级联删掉 schema_cache", () => {
    runMigrations(db);
    db.raw.prepare(
      `INSERT INTO data_sources
        (id, name, kind, config_cipher, config_iv, config_tag, created_at, updated_at)
       VALUES ('s1', 'n', 'sqlite', x'00', x'00', x'00', '', '')`,
    ).run();
    db.raw.prepare(
      "INSERT INTO schema_cache (data_source_id, schema_json, fetched_at) VALUES ('s1', '[]', '')",
    ).run();
    db.raw.prepare("DELETE FROM data_sources WHERE id = 's1'").run();
    expect(db.raw.prepare("SELECT COUNT(*) AS n FROM schema_cache").get()).toEqual({ n: 0 });
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest --root apps/backend run tests/appDb.migrations.test.ts`
Expected: FAIL,报无法解析 `../src/appDb/index`。

- [ ] **Step 3: 写 `appDb/index.ts`**

```ts
import Database from "better-sqlite3";
import type { Database as RawDb } from "better-sqlite3";
import { dirname } from "node:path";
import { mkdirSync } from "node:fs";

/**
 * 应用元数据库的可写连接。`raw` 只允许 src/appDb/ 目录内使用——
 * 目录外一律走 dataSourceRepo 的函数,不要让 SQL 字符串散出去。
 */
export interface AppDb {
  raw: RawDb;
  close(): void;
}

export function openAppDb(path: string): AppDb {
  mkdirSync(dirname(path), { recursive: true });
  const raw = new Database(path);
  raw.pragma("journal_mode = WAL");
  // better-sqlite3 默认不开外键,不开则 ON DELETE CASCADE 静默失效。
  raw.pragma("foreign_keys = ON");
  return { raw, close: () => raw.close() };
}
```

- [ ] **Step 4: 写 `appDb/migrations.ts`**

```ts
import type { AppDb } from "./index";

export interface Migration {
  id: number;
  name: string;
  /** 在同一个事务内被调用;抛错则整批回滚。 */
  up(db: AppDb): void;
}

const M1 = `
CREATE TABLE data_sources (
  id               TEXT PRIMARY KEY,
  name             TEXT NOT NULL UNIQUE,
  kind             TEXT NOT NULL,
  config_cipher    BLOB NOT NULL,
  config_iv        BLOB NOT NULL,
  config_tag       BLOB NOT NULL,
  owner            TEXT NOT NULL DEFAULT 'local',
  write_probe      TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  last_check_at    TEXT,
  last_check_ok    INTEGER,
  last_check_error TEXT
);
`;

const M2 = `
CREATE TABLE schema_cache (
  data_source_id TEXT PRIMARY KEY REFERENCES data_sources(id) ON DELETE CASCADE,
  schema_json    TEXT NOT NULL,
  fetched_at     TEXT NOT NULL
);
`;

/** 只许往末尾追加。改动已发布的条目会让老库与新库结构不一致。 */
export const MIGRATIONS: Migration[] = [
  { id: 1, name: "data_sources", up: db => db.raw.exec(M1) },
  { id: 2, name: "schema_cache", up: db => db.raw.exec(M2) },
];

/** 返回本次实际应用的迁移 id。整批在一个事务里,任一条失败全部回滚。 */
export function runMigrations(db: AppDb, migrations: Migration[] = MIGRATIONS): number[] {
  db.raw.exec(`CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
  )`);
  const done = new Set(
    (db.raw.prepare("SELECT id FROM schema_migrations").all() as { id: number }[]).map(r => r.id),
  );
  const pending = migrations.filter(m => !done.has(m.id)).sort((a, b) => a.id - b.id);
  if (!pending.length) return [];

  const record = db.raw.prepare(
    "INSERT INTO schema_migrations (id, name, applied_at) VALUES (?, ?, ?)",
  );
  const applyAll = db.raw.transaction((list: Migration[]) => {
    for (const m of list) {
      try {
        m.up(db);
      } catch (e) {
        throw new Error(`迁移 ${m.id}(${m.name})失败: ${(e as Error).message}`);
      }
      record.run(m.id, m.name, new Date().toISOString());
    }
  });
  applyAll(pending);
  return pending.map(m => m.id);
}
```

注意「整批回滚」的测试断言连 `schema_migrations` 都不该留下:`CREATE TABLE IF NOT EXISTS` 在事务**外**执行,所以失败后这张表会存在——所以测试里断言的是**首次**运行失败的场景,此时 `openAppDb` 是新库、`CREATE TABLE IF NOT EXISTS` 已建表。**把测试里那条断言改成检查表是空的**:

```ts
    expect(db.raw.prepare("SELECT COUNT(*) AS n FROM schema_migrations").get()).toEqual({ n: 0 });
```

替换掉 `expect(tableNames(db)).not.toContain("schema_migrations");` 这一行。这是实现驱动出来的修正:版本表本身不是迁移的产物,它先于迁移存在。

- [ ] **Step 5: 给 `config.ts` 加 `appDbPath`**

Modify `apps/backend/src/config.ts`,在 `dbPath` 下面加一行:

```ts
  appDbPath: process.env.APP_DB_PATH ?? "./data/app.db",
```

- [ ] **Step 6: 运行测试确认通过**

Run: `npx vitest --root apps/backend run tests/appDb.migrations.test.ts`
Expected: PASS,7 个测试。

- [ ] **Step 7: 跑全量后端测试确认没打破 P1**

Run: `npx vitest --root apps/backend run`
Expected: PASS,171 + 7 = 178 个测试。

- [ ] **Step 8: 提交**

```bash
git add apps/backend/src/appDb apps/backend/src/config.ts apps/backend/tests/appDb.migrations.test.ts
git commit -m "feat(backend): app.db connection and versioned migration framework"
```

---

### Task 2: 凭据加密(AES-256-GCM)与密钥加载

数据库连接参数(含密码)不能明文落库。用 `node:crypto` 的 AES-256-GCM,零新依赖。威胁模型见 spec 第 2 节:防的是 `app.db` 被误提交/误拷走,防不住能读本机文件系统的人。

**Files:**
- Create: `apps/backend/src/appDb/secrets.ts`
- Modify: `apps/backend/src/config.ts`(加 `appKeyPath`)
- Modify: `.gitignore`(补 `*.key`)
- Test: `apps/backend/tests/appDb.secrets.test.ts`

**Interfaces:**
- Consumes: 无
- Produces:
  - `interface Sealed { cipher: Buffer; iv: Buffer; tag: Buffer }`
  - `class DecryptError extends Error` —— 解密/认证失败的专用类型,Task 3 与 P2a-2 的路由据此映射成 `DECRYPT_ERROR`
  - `function encryptJson(value: unknown, key: Buffer): Sealed`
  - `function decryptJson<T>(sealed: Sealed, key: Buffer): T` —— 失败抛 `DecryptError`
  - `function loadKey(keyPath?: string): Buffer` —— 默认读 `config.appKeyPath`
  - `config.appKeyPath: string`

- [ ] **Step 1: 写失败的测试**

Create `apps/backend/tests/appDb.secrets.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdirSync, rmSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { encryptJson, decryptJson, loadKey, DecryptError } from "../src/appDb/secrets";

const tmpDir = join(process.cwd(), ".tmp-test");
const keyPath = join(tmpDir, "app.key");
const key = randomBytes(32);

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  delete process.env.APP_KEY;
});
afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  delete process.env.APP_KEY;
});

const secret = { host: "10.0.0.5", port: 3306, user: "bi_ro", password: "p@ss w0rd 中文" };

describe("加解密往返", () => {
  it("解出来和存进去的一模一样", () => {
    expect(decryptJson(encryptJson(secret, key), key)).toEqual(secret);
  });

  it("密文里不含明文密码", () => {
    const { cipher } = encryptJson(secret, key);
    expect(cipher.toString("utf8")).not.toContain("p@ss");
    expect(cipher.toString("latin1")).not.toContain("p@ss");
  });

  it("同一明文两次加密的密文不同(IV 随机)", () => {
    const a = encryptJson(secret, key);
    const b = encryptJson(secret, key);
    expect(a.iv.equals(b.iv)).toBe(false);
    expect(a.cipher.equals(b.cipher)).toBe(false);
  });
});

describe("完整性校验", () => {
  const flip = (b: Buffer): Buffer => {
    const c = Buffer.from(b);
    c[0] = c[0] ^ 0xff;
    return c;
  };

  it("篡改密文则解密失败", () => {
    const s = encryptJson(secret, key);
    expect(() => decryptJson({ ...s, cipher: flip(s.cipher) }, key)).toThrow(DecryptError);
  });
  it("篡改 IV 则解密失败", () => {
    const s = encryptJson(secret, key);
    expect(() => decryptJson({ ...s, iv: flip(s.iv) }, key)).toThrow(DecryptError);
  });
  it("篡改认证标签则解密失败", () => {
    const s = encryptJson(secret, key);
    expect(() => decryptJson({ ...s, tag: flip(s.tag) }, key)).toThrow(DecryptError);
  });
  it("换一把钥匙解不开", () => {
    const s = encryptJson(secret, key);
    expect(() => decryptJson(s, randomBytes(32))).toThrow(DecryptError);
  });
  it("错误消息是可读中文,不泄露密文", () => {
    const s = encryptJson(secret, key);
    expect(() => decryptJson(s, randomBytes(32))).toThrow(/凭据无法解密/);
  });
});

describe("loadKey", () => {
  it("APP_KEY 优先,不落文件", () => {
    const raw = randomBytes(32);
    process.env.APP_KEY = raw.toString("base64");
    expect(loadKey(keyPath).equals(raw)).toBe(true);
    expect(existsSync(keyPath)).toBe(false);
  });

  it("APP_KEY 长度不对时报可读错误", () => {
    process.env.APP_KEY = Buffer.from("太短").toString("base64");
    expect(() => loadKey(keyPath)).toThrow(/APP_KEY 必须是 32 字节/);
  });

  it("没有 APP_KEY 时生成密钥文件", () => {
    const k = loadKey(keyPath);
    expect(k).toHaveLength(32);
    expect(readFileSync(keyPath)).toHaveLength(32);
  });

  it("第二次调用复用同一个密钥文件", () => {
    expect(loadKey(keyPath).equals(loadKey(keyPath))).toBe(true);
  });

  it("密钥文件长度不对时报可读错误,不静默重建", () => {
    loadKey(keyPath);
    rmSync(keyPath);
    mkdirSync(tmpDir, { recursive: true });
    require("node:fs").writeFileSync(keyPath, randomBytes(7));
    expect(() => loadKey(keyPath)).toThrow(/密钥文件.*32 字节/);
  });
});
```

最后一个测试里的 `require` 在 ESM 下不可用,**改成在文件顶部一并引入 `writeFileSync`**:把 `import { mkdirSync, rmSync, existsSync, readFileSync } from "node:fs";` 改成 `import { mkdirSync, rmSync, existsSync, readFileSync, writeFileSync } from "node:fs";`,那一行写成 `writeFileSync(keyPath, randomBytes(7));`。

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest --root apps/backend run tests/appDb.secrets.test.ts`
Expected: FAIL,无法解析 `../src/appDb/secrets`。

- [ ] **Step 3: 写 `appDb/secrets.ts`**

```ts
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, chmodSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { config } from "../config";

const ALGO = "aes-256-gcm";
const IV_BYTES = 12;   // GCM 的标准 IV 长度
const KEY_BYTES = 32;  // AES-256

export interface Sealed { cipher: Buffer; iv: Buffer; tag: Buffer }

/** 解密或认证失败。上层据此映射成 DECRYPT_ERROR,不要用裸 Error。 */
export class DecryptError extends Error {
  constructor(message = "凭据无法解密,请重新填写连接信息") { super(message); this.name = "DecryptError"; }
}

export function encryptJson(value: unknown, key: Buffer): Sealed {
  const iv = randomBytes(IV_BYTES);
  const c = createCipheriv(ALGO, key, iv);
  const cipher = Buffer.concat([c.update(JSON.stringify(value), "utf8"), c.final()]);
  return { cipher, iv, tag: c.getAuthTag() };
}

export function decryptJson<T>(sealed: Sealed, key: Buffer): T {
  try {
    const d = createDecipheriv(ALGO, key, sealed.iv);
    d.setAuthTag(sealed.tag);
    const plain = Buffer.concat([d.update(sealed.cipher), d.final()]).toString("utf8");
    return JSON.parse(plain) as T;
  } catch {
    // 不把原始错误或密文带出去。
    throw new DecryptError();
  }
}

/**
 * 密钥来源:APP_KEY(32 字节 base64)优先,否则读/建密钥文件。
 * 长度不对一律报错,绝不静默重新生成——那会把「换了钥匙」伪装成「数据损坏」。
 */
export function loadKey(keyPath: string = config.appKeyPath): Buffer {
  const fromEnv = process.env.APP_KEY;
  if (fromEnv) {
    const k = Buffer.from(fromEnv, "base64");
    if (k.length !== KEY_BYTES) {
      throw new Error(`APP_KEY 必须是 32 字节的 base64,当前解出 ${k.length} 字节`);
    }
    return k;
  }
  if (existsSync(keyPath)) {
    const k = readFileSync(keyPath);
    if (k.length !== KEY_BYTES) {
      throw new Error(`密钥文件 ${keyPath} 应为 32 字节,实际 ${k.length} 字节;请恢复备份或删除后重新配置数据源`);
    }
    return k;
  }
  mkdirSync(dirname(keyPath), { recursive: true });
  const k = randomBytes(KEY_BYTES);
  writeFileSync(keyPath, k);
  // Windows 上 mode 位不由 NTFS ACL 采纳,这行等于无操作,不视为失败。
  try { chmodSync(keyPath, 0o600); } catch { /* 平台不支持,忽略 */ }
  return k;
}
```

- [ ] **Step 4: 给 `config.ts` 加 `appKeyPath`**

```ts
  appKeyPath: process.env.APP_KEY_PATH ?? "./data/app.key",
```

- [ ] **Step 5: 给 `.gitignore` 补一条**

现有规则里的 `data/` 与 `*.db` 已覆盖 `data/app.db` 与 `data/app.key`。补 `*.key` 是第二道保险:万一密钥被挪到别的目录,`data/` 就不管了,而密钥和密文一起进 git 等于没加密。在 `*.db-wal` 后面加一行:

```
*.key
```

- [ ] **Step 6: 运行测试确认通过**

Run: `npx vitest --root apps/backend run tests/appDb.secrets.test.ts`
Expected: PASS,13 个测试。

- [ ] **Step 7: 提交**

```bash
git add apps/backend/src/appDb/secrets.ts apps/backend/src/config.ts .gitignore apps/backend/tests/appDb.secrets.test.ts
git commit -m "feat(backend): AES-256-GCM credential sealing with generated local key"
```

---

### Task 3: 数据源领域类型与仓储

唯一碰 `data_sources` / `schema_cache` 的 SQL 的地方。目录外一律调这些函数。

**关键设计**:`DataSourceRecord.config` 的类型是 `DsConfig | null`,`null` 配 `configError: true` 表示**解密失败**。不为此另建一个类型——单一类型强迫调用方处理这个状态,而 spec 第 2 节要求解密失败不能让服务起不来。

**Files:**
- Modify: `packages/shared/src/types.ts`(追加三个前后端共用的契约类型)
- Create: `apps/backend/src/datasources/types.ts`(只放后端自己的东西)
- Create: `apps/backend/src/appDb/dataSourceRepo.ts`
- Test: `apps/backend/tests/dataSourceRepo.test.ts`

**Interfaces:**
- Consumes: `AppDb`、`runMigrations`(Task 1);`encryptJson`、`decryptJson`、`DecryptError`(Task 2);`TableSchema`(`@chatbi/shared`)
- Produces —— `packages/shared/src/types.ts`(前后端共用,因为 P2a-2 的前端表单要构造 `DsConfig` 发给后端):
  - `type DataSourceKind = "sqlite" | "mysql" | "postgres"`
  - `type WritePrivilege = "readonly" | "writable" | "unknown"`
  - `type DsConfig = { kind: "sqlite"; path: string } | { kind: "mysql"; host: string; port: number; database: string; user: string; password: string; ssl: boolean } | { kind: "postgres"; host: string; port: number; database: string; user: string; password: string; ssl: boolean; schema?: string }`
- Produces —— `apps/backend/src/datasources/types.ts`(只有后端用得到的):
  - `interface DataSourceRecord { id: string; name: string; kind: DataSourceKind; owner: string; config: DsConfig | null; configError: boolean; writePrivilege: WritePrivilege | null; createdAt: string; updatedAt: string; lastCheckAt: string | null; lastCheckOk: boolean | null; lastCheckError: string | null }`
  - `function targetLabel(config: DsConfig): string` —— 脱敏摘要,**永不含密码**
  - 为了让本计划后续任务的导入路径统一,这个文件**再 re-export 一次**上面三个共用类型:`export type { DataSourceKind, WritePrivilege, DsConfig } from "@chatbi/shared";`
- Produces —— `appDb/dataSourceRepo.ts`:
  - `class DuplicateNameError extends Error`
  - `createDataSource(db, key, input: { name: string; config: DsConfig; writePrivilege?: WritePrivilege }): DataSourceRecord`
  - `updateDataSource(db, key, id: string, patch: { name?: string; config?: DsConfig }): DataSourceRecord | null`
  - `getDataSource(db, key, id: string): DataSourceRecord | null`
  - `listDataSources(db, key): DataSourceRecord[]`
  - `deleteDataSource(db, id: string): boolean`
  - `recordCheck(db, id: string, r: { ok: boolean; error?: string; writePrivilege?: WritePrivilege }): void`
  - `putSchemaCache(db, id: string, schema: TableSchema[]): void`
  - `getSchemaCache(db, id: string): { schema: TableSchema[]; fetchedAt: string } | null`

  (`db: AppDb`、`key: Buffer` 是前两个参数,下同。)

- [ ] **Step 1: 写失败的测试**

Create `apps/backend/tests/dataSourceRepo.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { openAppDb, type AppDb } from "../src/appDb/index";
import { runMigrations } from "../src/appDb/migrations";
import {
  createDataSource, updateDataSource, getDataSource, listDataSources, deleteDataSource,
  recordCheck, putSchemaCache, getSchemaCache, DuplicateNameError,
} from "../src/appDb/dataSourceRepo";
import { targetLabel, type DsConfig } from "../src/datasources/types";
import type { TableSchema } from "@chatbi/shared";

const tmpDir = join(process.cwd(), ".tmp-test");
const key = randomBytes(32);
let db: AppDb;

const mysqlCfg: DsConfig = {
  kind: "mysql", host: "10.0.0.5", port: 3306, database: "sales",
  user: "bi_ro", password: "s3cret", ssl: false,
};

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  db = openAppDb(join(tmpDir, "app.db"));
  runMigrations(db);
});
afterEach(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

describe("targetLabel", () => {
  it("给出可读摘要且不含密码", () => {
    const label = targetLabel(mysqlCfg);
    expect(label).toBe("mysql://bi_ro@10.0.0.5:3306/sales");
    expect(label).not.toContain("s3cret");
  });
  it("sqlite 用路径", () => {
    expect(targetLabel({ kind: "sqlite", path: "./data/chatbi.db" })).toBe("./data/chatbi.db");
  });
});

describe("createDataSource", () => {
  it("存进去再读出来,config 已解密", () => {
    const created = createDataSource(db, key, { name: "销售库", config: mysqlCfg });
    expect(created.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(getDataSource(db, key, created.id)!.config).toEqual(mysqlCfg);
  });
  it("密码不以明文存在库里", () => {
    createDataSource(db, key, { name: "销售库", config: mysqlCfg });
    const row = db.raw.prepare("SELECT config_cipher FROM data_sources").get() as { config_cipher: Buffer };
    expect(row.config_cipher.toString("latin1")).not.toContain("s3cret");
  });
  it("同名冲突抛 DuplicateNameError", () => {
    createDataSource(db, key, { name: "重名", config: mysqlCfg });
    expect(() => createDataSource(db, key, { name: "重名", config: mysqlCfg }))
      .toThrow(DuplicateNameError);
  });
  it("owner 默认 local,writePrivilege 默认为 null", () => {
    const r = createDataSource(db, key, { name: "x", config: mysqlCfg });
    expect(r.owner).toBe("local");
    expect(r.writePrivilege).toBeNull();
  });
});

describe("updateDataSource", () => {
  it("只改名字时保留原 config", () => {
    const c = createDataSource(db, key, { name: "旧名", config: mysqlCfg });
    const u = updateDataSource(db, key, c.id, { name: "新名" })!;
    expect(u.name).toBe("新名");
    expect(u.config).toEqual(mysqlCfg);
  });
  it("换 config 时重新加密", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    const next: DsConfig = { ...mysqlCfg, password: "另一个密码" };
    expect(updateDataSource(db, key, c.id, { config: next })!.config).toEqual(next);
  });
  it("updatedAt 会变", async () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    await new Promise(r => setTimeout(r, 5));
    expect(updateDataSource(db, key, c.id, { name: "y" })!.updatedAt).not.toBe(c.updatedAt);
  });
  it("id 不存在返回 null", () => {
    expect(updateDataSource(db, key, "nope", { name: "y" })).toBeNull();
  });
});

describe("解密失败", () => {
  it("换了钥匙则 config 为 null 且 configError 为真,不抛错", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    const other = randomBytes(32);
    const r = getDataSource(db, other, c.id)!;
    expect(r.config).toBeNull();
    expect(r.configError).toBe(true);
    expect(r.name).toBe("x");   // 名字与 id 仍然可用
  });
  it("列表里坏的和好的共存", () => {
    createDataSource(db, key, { name: "好的", config: mysqlCfg });
    const list = listDataSources(db, randomBytes(32));
    expect(list).toHaveLength(1);
    expect(list[0].configError).toBe(true);
  });
});

describe("recordCheck", () => {
  it("写入检查结果与写权限", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    recordCheck(db, c.id, { ok: true, writePrivilege: "writable" });
    const r = getDataSource(db, key, c.id)!;
    expect(r.lastCheckOk).toBe(true);
    expect(r.writePrivilege).toBe("writable");
    expect(r.lastCheckAt).toBeTruthy();
    expect(r.lastCheckError).toBeNull();
  });
  it("失败时记下原因,并清掉上一次的成功标记", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    recordCheck(db, c.id, { ok: true, writePrivilege: "readonly" });
    recordCheck(db, c.id, { ok: false, error: "连不上" });
    const r = getDataSource(db, key, c.id)!;
    expect(r.lastCheckOk).toBe(false);
    expect(r.lastCheckError).toBe("连不上");
  });
});

describe("schema 缓存", () => {
  const schema: TableSchema[] = [{
    tableName: "orders",
    columns: [{ name: "id", type: "int", notNull: true, pk: true }],
    foreignKeys: [],
  }];

  it("写入后能读回,带时间戳", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    putSchemaCache(db, c.id, schema);
    const got = getSchemaCache(db, c.id)!;
    expect(got.schema).toEqual(schema);
    expect(got.fetchedAt).toBeTruthy();
  });
  it("再写一次是覆盖而不是报主键冲突", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    putSchemaCache(db, c.id, schema);
    putSchemaCache(db, c.id, []);
    expect(getSchemaCache(db, c.id)!.schema).toEqual([]);
  });
  it("没缓存返回 null", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    expect(getSchemaCache(db, c.id)).toBeNull();
  });
});

describe("deleteDataSource", () => {
  it("删掉后连缓存一起没了", () => {
    const c = createDataSource(db, key, { name: "x", config: mysqlCfg });
    putSchemaCache(db, c.id, []);
    expect(deleteDataSource(db, c.id)).toBe(true);
    expect(getDataSource(db, key, c.id)).toBeNull();
    expect(getSchemaCache(db, c.id)).toBeNull();
  });
  it("删不存在的返回 false", () => {
    expect(deleteDataSource(db, "nope")).toBe(false);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest --root apps/backend run tests/dataSourceRepo.test.ts`
Expected: FAIL,无法解析 `../src/datasources/types`。

- [ ] **Step 3a: 往 `packages/shared/src/types.ts` 末尾追加三个共用类型**

```ts
export type DataSourceKind = "sqlite" | "mysql" | "postgres";

export type WritePrivilege = "readonly" | "writable" | "unknown";

/**
 * 数据源连接参数。前端表单构造它、后端加密存它,所以放在共享契约里。
 * ssl 只有开关:自定义 CA 与客户端证书不在 P2a 范围。
 */
export type DsConfig =
  | { kind: "sqlite"; path: string }
  | { kind: "mysql"; host: string; port: number; database: string; user: string; password: string; ssl: boolean }
  | { kind: "postgres"; host: string; port: number; database: string; user: string; password: string; ssl: boolean; schema?: string };
```

- [ ] **Step 3b: 写 `datasources/types.ts`**

```ts
import type { DataSourceKind, DsConfig, WritePrivilege } from "@chatbi/shared";

// 让本目录下的导入路径统一,不必到处区分「这个类型在 shared 还是在这里」。
export type { DataSourceKind, DsConfig, WritePrivilege } from "@chatbi/shared";

export interface DataSourceRecord {
  id: string;
  name: string;
  kind: DataSourceKind;
  owner: string;
  /** null 表示解密失败,此时 configError 为 true。 */
  config: DsConfig | null;
  configError: boolean;
  writePrivilege: WritePrivilege | null;
  createdAt: string;
  updatedAt: string;
  lastCheckAt: string | null;
  lastCheckOk: boolean | null;
  lastCheckError: string | null;
}

/** 给人看的脱敏摘要。永远不含密码——这个函数是密码不外泄的关键一环。 */
export function targetLabel(config: DsConfig): string {
  if (config.kind === "sqlite") return config.path;
  return `${config.kind}://${config.user}@${config.host}:${config.port}/${config.database}`;
}
```

- [ ] **Step 4: 写 `appDb/dataSourceRepo.ts`**

```ts
import { randomUUID } from "node:crypto";
import type { TableSchema } from "@chatbi/shared";
import type { AppDb } from "./index";
import { encryptJson, decryptJson, DecryptError } from "./secrets";
import type { DataSourceKind, DataSourceRecord, DsConfig, WritePrivilege } from "../datasources/types";

export class DuplicateNameError extends Error {
  constructor(name: string) { super(`已有同名数据源:${name}`); this.name = "DuplicateNameError"; }
}

interface RawRow {
  id: string; name: string; kind: string; owner: string;
  config_cipher: Buffer; config_iv: Buffer; config_tag: Buffer;
  write_probe: string | null;
  created_at: string; updated_at: string;
  last_check_at: string | null; last_check_ok: number | null; last_check_error: string | null;
}

const COLUMNS = `id, name, kind, owner, config_cipher, config_iv, config_tag, write_probe,
  created_at, updated_at, last_check_at, last_check_ok, last_check_error`;

function toRecord(row: RawRow, key: Buffer): DataSourceRecord {
  let config: DsConfig | null = null;
  let configError = false;
  try {
    config = decryptJson<DsConfig>(
      { cipher: row.config_cipher, iv: row.config_iv, tag: row.config_tag }, key,
    );
  } catch (e) {
    if (!(e instanceof DecryptError)) throw e;
    configError = true;   // 不抛:名字与 id 仍然有用,界面要能显示「需重新配置」
  }
  return {
    id: row.id, name: row.name, kind: row.kind as DataSourceKind, owner: row.owner,
    config, configError,
    writePrivilege: (row.write_probe as WritePrivilege | null) ?? null,
    createdAt: row.created_at, updatedAt: row.updated_at,
    lastCheckAt: row.last_check_at,
    lastCheckOk: row.last_check_ok === null ? null : row.last_check_ok === 1,
    lastCheckError: row.last_check_error,
  };
}

export function createDataSource(
  db: AppDb, key: Buffer,
  input: { name: string; config: DsConfig; writePrivilege?: WritePrivilege },
): DataSourceRecord {
  const sealed = encryptJson(input.config, key);
  const now = new Date().toISOString();
  const id = randomUUID();
  try {
    db.raw.prepare(
      `INSERT INTO data_sources
         (id, name, kind, config_cipher, config_iv, config_tag, write_probe, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).run(id, input.name, input.config.kind, sealed.cipher, sealed.iv, sealed.tag,
      input.writePrivilege ?? null, now, now);
  } catch (e) {
    if (/UNIQUE constraint failed: data_sources\.name/i.test((e as Error).message)) {
      throw new DuplicateNameError(input.name);
    }
    throw e;
  }
  return getDataSource(db, key, id)!;
}

export function getDataSource(db: AppDb, key: Buffer, id: string): DataSourceRecord | null {
  const row = db.raw.prepare(`SELECT ${COLUMNS} FROM data_sources WHERE id = ?`).get(id) as RawRow | undefined;
  return row ? toRecord(row, key) : null;
}

export function listDataSources(db: AppDb, key: Buffer): DataSourceRecord[] {
  const rows = db.raw.prepare(`SELECT ${COLUMNS} FROM data_sources ORDER BY created_at`).all() as RawRow[];
  return rows.map(r => toRecord(r, key));
}

export function updateDataSource(
  db: AppDb, key: Buffer, id: string, patch: { name?: string; config?: DsConfig },
): DataSourceRecord | null {
  const current = getDataSource(db, key, id);
  if (!current) return null;
  const now = new Date().toISOString();
  try {
    if (patch.config) {
      const sealed = encryptJson(patch.config, key);
      db.raw.prepare(
        `UPDATE data_sources SET name = ?, kind = ?, config_cipher = ?, config_iv = ?,
           config_tag = ?, updated_at = ? WHERE id = ?`,
      ).run(patch.name ?? current.name, patch.config.kind,
        sealed.cipher, sealed.iv, sealed.tag, now, id);
    } else {
      db.raw.prepare("UPDATE data_sources SET name = ?, updated_at = ? WHERE id = ?")
        .run(patch.name ?? current.name, now, id);
    }
  } catch (e) {
    if (/UNIQUE constraint failed: data_sources\.name/i.test((e as Error).message)) {
      throw new DuplicateNameError(patch.name!);
    }
    throw e;
  }
  return getDataSource(db, key, id);
}

export function deleteDataSource(db: AppDb, id: string): boolean {
  // schema_cache 靠 ON DELETE CASCADE 跟着走(openAppDb 已开 foreign_keys)。
  return db.raw.prepare("DELETE FROM data_sources WHERE id = ?").run(id).changes > 0;
}

export function recordCheck(
  db: AppDb, id: string, r: { ok: boolean; error?: string; writePrivilege?: WritePrivilege },
): void {
  db.raw.prepare(
    `UPDATE data_sources
        SET last_check_at = ?, last_check_ok = ?, last_check_error = ?,
            write_probe = COALESCE(?, write_probe)
      WHERE id = ?`,
  ).run(new Date().toISOString(), r.ok ? 1 : 0, r.error ?? null, r.writePrivilege ?? null, id);
}

export function putSchemaCache(db: AppDb, id: string, schema: TableSchema[]): void {
  db.raw.prepare(
    `INSERT INTO schema_cache (data_source_id, schema_json, fetched_at) VALUES (?, ?, ?)
     ON CONFLICT(data_source_id) DO UPDATE SET schema_json = excluded.schema_json,
       fetched_at = excluded.fetched_at`,
  ).run(id, JSON.stringify(schema), new Date().toISOString());
}

export function getSchemaCache(
  db: AppDb, id: string,
): { schema: TableSchema[]; fetchedAt: string } | null {
  const row = db.raw.prepare(
    "SELECT schema_json, fetched_at FROM schema_cache WHERE data_source_id = ?",
  ).get(id) as { schema_json: string; fetched_at: string } | undefined;
  return row ? { schema: JSON.parse(row.schema_json) as TableSchema[], fetchedAt: row.fetched_at } : null;
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest --root apps/backend run tests/dataSourceRepo.test.ts`
Expected: PASS,17 个测试。

- [ ] **Step 6: 跑全量后端测试**

Run: `npx vitest --root apps/backend run`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add packages/shared/src/types.ts apps/backend/src/datasources/types.ts apps/backend/src/appDb/dataSourceRepo.ts apps/backend/tests/dataSourceRepo.test.ts
git commit -m "feat(shared,backend): data source contract types and app.db repository"
```

---

### Task 4: 驱动接口、方言层与错误映射

三个纯文件:接口(无运行时代码)、三个方言常量、原生错误 → `DsErrorCode` 的纯函数。**不需要任何数据库就能全部测完**,是 CI 的主体。

**Files:**
- Modify: `packages/shared/src/types.ts`(追加 `DsErrorCode` —— P2a-2 的前端要按它渲染错误,和 `DsConfig` 一样属于前后端共用契约)
- Create: `apps/backend/src/datasources/driver.ts`
- Create: `apps/backend/src/datasources/dialect.ts`
- Create: `apps/backend/src/datasources/errors.ts`
- Test: `apps/backend/tests/dialect.test.ts`
- Test: `apps/backend/tests/dsErrors.test.ts`

**Interfaces:**
- Consumes: `DataSourceKind`、`WritePrivilege`(Task 3);`Row`、`TableSchema`(`@chatbi/shared`)
- Produces —— `packages/shared/src/types.ts`:
  - `type DsErrorCode = "CONNECTION_ERROR" | "AUTH_ERROR" | "DB_NOT_FOUND" | "NOT_FOUND" | "TIMEOUT" | "SQL_ERROR" | "SCHEMA_STALE" | "PERMISSION_ERROR" | "DECRYPT_ERROR" | "UNKNOWN"` —— `DB_NOT_FOUND` 是**目标库**不存在,`NOT_FOUND` 是**我们自己的数据源记录**不存在(Task 8 的 registry 与 P2a-2 的路由都要用),两个不能合并
- Produces —— `errors.ts`(re-export `DsErrorCode`,外加):
  - `class DsError extends Error { readonly code: DsErrorCode; readonly details?: string }`
  - `function mapMysqlError(e: unknown): DsError`
  - `function mapPgError(e: unknown): DsError`
  - `function mapSqliteError(e: unknown): DsError`
  - `function isRetryable(code: DsErrorCode): boolean` —— 只有 `SQL_ERROR` 与 `SCHEMA_STALE` 为真;P2a-2 的 `chatService` 用它决定是否重试
- Produces —— `dialect.ts`:
  - `interface Dialect { kind: DataSourceKind; quoteIdent(name: string): string; sqlParserDialect: "sqlite" | "mysql" | "postgresql"; promptNotes: string }`
  - `const SQLITE_DIALECT`、`MYSQL_DIALECT`、`POSTGRES_DIALECT`
  - `function dialectFor(kind: DataSourceKind): Dialect`
- Produces —— `driver.ts`:
  - `interface QueryResult { rows: Row[]; truncated: boolean }`
  - `type TestResult = { ok: true; writePrivilege: WritePrivilege } | { ok: false; code: DsErrorCode; message: string; details?: string }`
  - `interface Driver { readonly kind; readonly dialect; testConnection(): Promise<TestResult>; introspect(): Promise<TableSchema[]>; runQuery(sql: string, limit: number, timeoutMs: number): Promise<QueryResult>; probeWritePrivilege(): Promise<WritePrivilege>; close(): Promise<void> }`

- [ ] **Step 1: 写方言测试**

Create `apps/backend/tests/dialect.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { dialectFor, SQLITE_DIALECT, MYSQL_DIALECT, POSTGRES_DIALECT } from "../src/datasources/dialect";

describe("quoteIdent", () => {
  it("sqlite 与 postgres 用双引号", () => {
    expect(SQLITE_DIALECT.quoteIdent("order date")).toBe('"order date"');
    expect(POSTGRES_DIALECT.quoteIdent("order date")).toBe('"order date"');
  });
  it("mysql 用反引号", () => {
    expect(MYSQL_DIALECT.quoteIdent("order date")).toBe("`order date`");
  });
  it("转义标识符里的引号,防止拼接被截断", () => {
    expect(POSTGRES_DIALECT.quoteIdent('a"b')).toBe('"a""b"');
    expect(MYSQL_DIALECT.quoteIdent("a`b")).toBe("`a``b`");
  });
});

describe("sqlParserDialect", () => {
  it("三种源各自对应 node-sql-parser 的方言名", () => {
    expect(SQLITE_DIALECT.sqlParserDialect).toBe("sqlite");
    expect(MYSQL_DIALECT.sqlParserDialect).toBe("mysql");
    expect(POSTGRES_DIALECT.sqlParserDialect).toBe("postgresql");
  });
});

describe("promptNotes", () => {
  it("各自举出本方言的时间截断函数", () => {
    expect(SQLITE_DIALECT.promptNotes).toContain("strftime");
    expect(MYSQL_DIALECT.promptNotes).toContain("DATE_FORMAT");
    expect(POSTGRES_DIALECT.promptNotes).toContain("date_trunc");
  });
  it("三段提示互不相同且都非空", () => {
    const all = [SQLITE_DIALECT, MYSQL_DIALECT, POSTGRES_DIALECT].map(d => d.promptNotes);
    expect(new Set(all).size).toBe(3);
    for (const n of all) expect(n.trim().length).toBeGreaterThan(0);
  });
  it("不含别的方言的函数名,避免误导模型", () => {
    expect(MYSQL_DIALECT.promptNotes).not.toContain("strftime");
    expect(POSTGRES_DIALECT.promptNotes).not.toContain("DATE_FORMAT");
  });
});

describe("dialectFor", () => {
  it("按 kind 取到对应方言", () => {
    expect(dialectFor("sqlite")).toBe(SQLITE_DIALECT);
    expect(dialectFor("mysql")).toBe(MYSQL_DIALECT);
    expect(dialectFor("postgres")).toBe(POSTGRES_DIALECT);
  });
});
```

- [ ] **Step 2: 写错误映射测试**

Create `apps/backend/tests/dsErrors.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { mapMysqlError, mapPgError, mapSqliteError, isRetryable, DsError } from "../src/datasources/errors";

const mysqlErr = (code: string, message = "boom") => Object.assign(new Error(message), { code });
const pgErr = (code: string, message = "boom") => Object.assign(new Error(message), { code });

describe("mapMysqlError", () => {
  const cases: [string, string][] = [
    ["ECONNREFUSED", "CONNECTION_ERROR"],
    ["ENOTFOUND", "CONNECTION_ERROR"],
    ["ETIMEDOUT", "CONNECTION_ERROR"],
    ["ER_ACCESS_DENIED_ERROR", "AUTH_ERROR"],
    ["ER_BAD_DB_ERROR", "DB_NOT_FOUND"],
    ["ER_QUERY_TIMEOUT", "TIMEOUT"],
    ["ER_NO_SUCH_TABLE", "SCHEMA_STALE"],
    ["ER_BAD_FIELD_ERROR", "SCHEMA_STALE"],
    ["ER_PARSE_ERROR", "SQL_ERROR"],
    ["ER_TABLEACCESS_DENIED_ERROR", "PERMISSION_ERROR"],
  ];
  for (const [code, expected] of cases) {
    it(`${code} → ${expected}`, () => {
      expect(mapMysqlError(mysqlErr(code)).code).toBe(expected);
    });
  }
  it("未知错误码归入 UNKNOWN 并保留原文", () => {
    const e = mapMysqlError(mysqlErr("ER_SOMETHING_NEW", "原始英文消息"));
    expect(e.code).toBe("UNKNOWN");
    expect(e.details).toContain("原始英文消息");
  });
  it("消息是可读中文,不是原始错误码", () => {
    const e = mapMysqlError(mysqlErr("ECONNREFUSED"));
    expect(e.message).toMatch(/无法连接/);
    expect(e.message).not.toContain("ECONNREFUSED");
  });
});

describe("mapPgError", () => {
  const cases: [string, string][] = [
    ["28P01", "AUTH_ERROR"],
    ["28000", "AUTH_ERROR"],
    ["3D000", "DB_NOT_FOUND"],
    ["57014", "TIMEOUT"],
    ["42P01", "SCHEMA_STALE"],
    ["42703", "SCHEMA_STALE"],
    ["42601", "SQL_ERROR"],
    ["42501", "PERMISSION_ERROR"],
    ["25006", "PERMISSION_ERROR"],
  ];
  for (const [code, expected] of cases) {
    it(`SQLSTATE ${code} → ${expected}`, () => {
      expect(mapPgError(pgErr(code)).code).toBe(expected);
    });
  }
  it("网络层错误没有 SQLSTATE,按连接错误处理", () => {
    expect(mapPgError(pgErr("ECONNREFUSED")).code).toBe("CONNECTION_ERROR");
  });
  it("只读事务拒绝写入时给出解释性消息", () => {
    expect(mapPgError(pgErr("25006")).message).toMatch(/只读/);
  });
});

describe("mapSqliteError", () => {
  it("打不开文件 → DB_NOT_FOUND", () => {
    expect(mapSqliteError(mysqlErr("SQLITE_CANTOPEN")).code).toBe("DB_NOT_FOUND");
  });
  it("只读连接拒绝写 → PERMISSION_ERROR", () => {
    expect(mapSqliteError(mysqlErr("SQLITE_READONLY")).code).toBe("PERMISSION_ERROR");
  });
  it("表不存在 → SCHEMA_STALE", () => {
    expect(mapSqliteError(mysqlErr("SQLITE_ERROR", "no such table: orders")).code).toBe("SCHEMA_STALE");
  });
  it("列不存在 → SCHEMA_STALE", () => {
    expect(mapSqliteError(mysqlErr("SQLITE_ERROR", "no such column: amt")).code).toBe("SCHEMA_STALE");
  });
  it("其它语法错 → SQL_ERROR", () => {
    expect(mapSqliteError(mysqlErr("SQLITE_ERROR", 'near "FROM": syntax error')).code).toBe("SQL_ERROR");
  });
  it("wrapTimeout 抛的超时 → TIMEOUT", () => {
    expect(mapSqliteError(new Error("query timeout")).code).toBe("TIMEOUT");
  });
  it("已经是 DsError 时原样返回,不二次包装", () => {
    const original = new DsError("TIMEOUT", "超时了");
    expect(mapSqliteError(original)).toBe(original);
  });
});

describe("isRetryable", () => {
  it("SQL 相关的错误值得把原因喂回模型重试一轮", () => {
    expect(isRetryable("SQL_ERROR")).toBe(true);
    expect(isRetryable("SCHEMA_STALE")).toBe(true);
  });
  it("连接、认证、超时、权限、解密都不该重试", () => {
    for (const c of ["CONNECTION_ERROR", "AUTH_ERROR", "DB_NOT_FOUND", "NOT_FOUND", "TIMEOUT",
      "PERMISSION_ERROR", "DECRYPT_ERROR", "UNKNOWN"] as const) {
      expect(isRetryable(c)).toBe(false);
    }
  });
});
```

- [ ] **Step 3: 运行两个测试确认失败**

Run: `npx vitest --root apps/backend run tests/dialect.test.ts tests/dsErrors.test.ts`
Expected: FAIL,两个模块都解析不到。

- [ ] **Step 4a: 往 `packages/shared/src/types.ts` 末尾追加 `DsErrorCode`**

```ts
/** 数据源相关的错误分类。前端按它决定要不要提示「刷新结构」「重新配置凭据」等。 */
export type DsErrorCode =
  | "CONNECTION_ERROR"
  | "AUTH_ERROR"
  | "DB_NOT_FOUND"     // 目标库/文件不存在
  | "NOT_FOUND"        // 我们自己的数据源记录不存在
  | "TIMEOUT"
  | "SQL_ERROR"
  | "SCHEMA_STALE"     // SQL_ERROR 的一种:表或列不存在,提示用户刷新结构
  | "PERMISSION_ERROR"
  | "DECRYPT_ERROR"
  | "UNKNOWN";
```

- [ ] **Step 4b: 写 `datasources/errors.ts`**

```ts
import type { DsErrorCode } from "@chatbi/shared";

// 与 DsConfig 同理:类型定义在 shared,本目录 re-export 一次,免得导入路径两套。
export type { DsErrorCode } from "@chatbi/shared";

export class DsError extends Error {
  constructor(readonly code: DsErrorCode, message: string, readonly details?: string) {
    super(message);
    this.name = "DsError";
  }
}

/** 只有与 SQL 内容相关的错误值得把原因喂回模型重试;连不上库重试只是多等一个超时。 */
export function isRetryable(code: DsErrorCode): boolean {
  return code === "SQL_ERROR" || code === "SCHEMA_STALE";
}

const NET_CODES = new Set([
  "ECONNREFUSED", "ENOTFOUND", "ETIMEDOUT", "EHOSTUNREACH", "ENETUNREACH", "ECONNRESET", "EPIPE",
]);

const MESSAGES: Record<DsErrorCode, string> = {
  CONNECTION_ERROR: "无法连接到数据库,请检查地址、端口与网络",
  AUTH_ERROR: "认证失败,请检查用户名与密码",
  DB_NOT_FOUND: "数据库或文件不存在,请检查库名/路径",
  NOT_FOUND: "数据源不存在,可能已被删除",
  TIMEOUT: "查询超时,请缩小查询范围或调高 QUERY_TIMEOUT_MS",
  SQL_ERROR: "SQL 执行失败",
  SCHEMA_STALE: "表或列不存在;表结构可能已变更,试试刷新结构",
  PERMISSION_ERROR: "当前账号权限不足",
  DECRYPT_ERROR: "凭据无法解密,请重新填写连接信息",
  UNKNOWN: "数据库返回了未预期的错误",
};

function build(code: DsErrorCode, e: unknown): DsError {
  const raw = e instanceof Error ? e.message : String(e);
  return new DsError(code, MESSAGES[code], raw);
}

const codeOf = (e: unknown): string =>
  typeof (e as { code?: unknown })?.code === "string" ? (e as { code: string }).code : "";

const MYSQL_MAP: Record<string, DsErrorCode> = {
  ER_ACCESS_DENIED_ERROR: "AUTH_ERROR",
  ER_DBACCESS_DENIED_ERROR: "AUTH_ERROR",
  ER_BAD_DB_ERROR: "DB_NOT_FOUND",
  ER_QUERY_TIMEOUT: "TIMEOUT",
  PROTOCOL_SEQUENCE_TIMEOUT: "TIMEOUT",
  ER_NO_SUCH_TABLE: "SCHEMA_STALE",
  ER_BAD_FIELD_ERROR: "SCHEMA_STALE",
  ER_PARSE_ERROR: "SQL_ERROR",
  ER_TABLEACCESS_DENIED_ERROR: "PERMISSION_ERROR",
  ER_COLUMNACCESS_DENIED_ERROR: "PERMISSION_ERROR",
  ER_SPECIFIC_ACCESS_DENIED_ERROR: "PERMISSION_ERROR",
  ER_CANT_UPDATE_WITH_READLOCK: "PERMISSION_ERROR",
};

export function mapMysqlError(e: unknown): DsError {
  if (e instanceof DsError) return e;
  const code = codeOf(e);
  if (NET_CODES.has(code)) return build("CONNECTION_ERROR", e);
  const mapped = MYSQL_MAP[code];
  if (mapped) return build(mapped, e);
  if (/query timeout/i.test((e as Error)?.message ?? "")) return build("TIMEOUT", e);
  return build("UNKNOWN", e);
}

const PG_MAP: Record<string, DsErrorCode> = {
  "28P01": "AUTH_ERROR",
  "28000": "AUTH_ERROR",
  "3D000": "DB_NOT_FOUND",
  "57014": "TIMEOUT",       // query_canceled,statement_timeout 生效时就是这个
  "42P01": "SCHEMA_STALE",  // undefined_table
  "42703": "SCHEMA_STALE",  // undefined_column
  "42601": "SQL_ERROR",     // syntax_error
  "42883": "SQL_ERROR",     // undefined_function
  "42804": "SQL_ERROR",     // datatype_mismatch
  "42501": "PERMISSION_ERROR",
  "25006": "PERMISSION_ERROR",  // read_only_sql_transaction
};

export function mapPgError(e: unknown): DsError {
  if (e instanceof DsError) return e;
  const code = codeOf(e);
  if (NET_CODES.has(code)) return build("CONNECTION_ERROR", e);
  const mapped = PG_MAP[code];
  if (mapped) {
    if (mapped === "PERMISSION_ERROR" && code === "25006") {
      return new DsError("PERMISSION_ERROR", "该连接是只读事务,拒绝写入操作",
        e instanceof Error ? e.message : String(e));
    }
    return build(mapped, e);
  }
  if (/query timeout/i.test((e as Error)?.message ?? "")) return build("TIMEOUT", e);
  return build("UNKNOWN", e);
}

export function mapSqliteError(e: unknown): DsError {
  if (e instanceof DsError) return e;
  const code = codeOf(e);
  const msg = (e as Error)?.message ?? "";
  if (/query timeout/i.test(msg)) return build("TIMEOUT", e);
  if (code === "SQLITE_CANTOPEN") return build("DB_NOT_FOUND", e);
  if (code.startsWith("SQLITE_READONLY")) return build("PERMISSION_ERROR", e);
  if (/no such (table|column)/i.test(msg)) return build("SCHEMA_STALE", e);
  if (code.startsWith("SQLITE_")) return build("SQL_ERROR", e);
  return build("UNKNOWN", e);
}
```

- [ ] **Step 5: 写 `datasources/dialect.ts`**

```ts
import type { DataSourceKind } from "./types";

export interface Dialect {
  kind: DataSourceKind;
  quoteIdent(name: string): string;
  /** node-sql-parser 的 database 选项;方言不对会把合法 SQL 判成解析失败。 */
  sqlParserDialect: "sqlite" | "mysql" | "postgresql";
  /** 注入 LLM 提示词,告诉它本次要写哪种方言。 */
  promptNotes: string;
}

const dq = (name: string): string => `"${name.replace(/"/g, '""')}"`;
const bq = (name: string): string => `\`${name.replace(/`/g, "``")}\``;

export const SQLITE_DIALECT: Dialect = {
  kind: "sqlite",
  quoteIdent: dq,
  sqlParserDialect: "sqlite",
  promptNotes: `本次目标数据库是 SQLite。
- 按月/按日截断时间用 strftime,例如 strftime('%Y-%m', order_date)。
- 标识符用双引号,例如 "order date"。
- 日期是文本,比较时用 'YYYY-MM-DD' 格式的字符串。`,
};

export const MYSQL_DIALECT: Dialect = {
  kind: "mysql",
  quoteIdent: bq,
  sqlParserDialect: "mysql",
  promptNotes: `本次目标数据库是 MySQL。
- 按月截断时间用 DATE_FORMAT(order_date, '%Y-%m');按周用 DATE_FORMAT(order_date, '%x-W%v')。
- 标识符用反引号,例如 \`order date\`。
- 不要使用 SQLite 或 PostgreSQL 特有的函数。`,
};

export const POSTGRES_DIALECT: Dialect = {
  kind: "postgres",
  quoteIdent: dq,
  sqlParserDialect: "postgresql",
  promptNotes: `本次目标数据库是 PostgreSQL。
- 按月截断时间用 to_char(date_trunc('month', order_date), 'YYYY-MM')。
- 标识符用双引号,例如 "order date";未加引号的标识符会被折成小写。
- 整数相除要显式转换,例如 SUM(a)::numeric / SUM(b)。`,
};

export function dialectFor(kind: DataSourceKind): Dialect {
  switch (kind) {
    case "sqlite": return SQLITE_DIALECT;
    case "mysql": return MYSQL_DIALECT;
    case "postgres": return POSTGRES_DIALECT;
  }
}
```

- [ ] **Step 6: 写 `datasources/driver.ts`**

```ts
import type { Row, TableSchema } from "@chatbi/shared";
import type { DataSourceKind, WritePrivilege } from "./types";
import type { Dialect } from "./dialect";
import type { DsErrorCode } from "./errors";

export interface QueryResult { rows: Row[]; truncated: boolean }

export type TestResult =
  | { ok: true; writePrivilege: WritePrivilege }
  | { ok: false; code: DsErrorCode; message: string; details?: string };

/**
 * 数据源驱动。只有这五个方法——每加一个都要在三个实现里各写一遍,
 * 宁可让上层多写一点组合逻辑。所有失败一律抛 DsError。
 */
export interface Driver {
  readonly kind: DataSourceKind;
  readonly dialect: Dialect;
  /** 连一次并顺带探写权限。调用方直接用返回的 writePrivilege,不要再单独探一次。 */
  testConnection(): Promise<TestResult>;
  introspect(): Promise<TableSchema[]>;
  /** 调用方应已用 enforceLimit(sql, limit + 1) 注入上限;实现负责切回 limit 行并报告是否多出来过。 */
  runQuery(sql: string, limit: number, timeoutMs: number): Promise<QueryResult>;
  probeWritePrivilege(): Promise<WritePrivilege>;
  close(): Promise<void>;
}
```

- [ ] **Step 7: 运行测试确认通过**

Run: `npx vitest --root apps/backend run tests/dialect.test.ts tests/dsErrors.test.ts`
Expected: PASS,方言 10 个 + 错误映射 29 个。

- [ ] **Step 8: 提交**

```bash
git add packages/shared/src/types.ts apps/backend/src/datasources apps/backend/tests/dialect.test.ts apps/backend/tests/dsErrors.test.ts
git commit -m "feat(shared,backend): driver contract, dialect table and native error mapping"
```

---

### Task 5: 驱动契约测试骨架 + SQLite 驱动

一套断言跑三个 driver。先建骨架并让 SQLite 通过——SQLite 无条件跑,是 CI 里唯一能保证执行的那一份。

**两处必须诚实标注的能力差异**(不能让「跳过」看起来像「通过」):

1. **SQLite 的超时无法在进程内强制**。`better-sqlite3` 是同步执行,长查询把事件循环堵住,`wrapTimeout` 的 `setTimeout` 根本轮不到执行;它也不暴露 `sqlite3_interrupt`。所以骨架用 `timeoutEnforcement: "server" | "none"` 声明,`"none"` 时**跳过并打印说明**。
2. **MySQL 的会话只读可被显式事务绕过**,`writeRejection: "engine" | "expected-weak"`,弱的那档改为断言 `probeWritePrivilege()` 至少能报出 `writable`。

**Files:**
- Create: `apps/backend/src/datasources/drivers/contract.ts`
- Create: `apps/backend/src/datasources/drivers/sqlite.ts`
- Test: `apps/backend/tests/drivers.sqlite.test.ts`

**Interfaces:**
- Consumes: `Driver`、`QueryResult`、`TestResult`(Task 4);`DsError`、`mapSqliteError`(Task 4);`DsConfig`(Task 3);`DbClient`(现有 `src/dbClient.ts`);`enforceLimit`、`wrapTimeout`(现有 `src/sqlGuard.ts`)
- Produces:
  - `interface ContractHooks { setup(): Promise<{ driver: Driver; cleanup: () => Promise<void> }>; sql: { monthlyTotals: string; manyRows: string; insert: string; slow: string; badTable: string }; writeRejection: "engine" | "expected-weak"; timeoutEnforcement: "server" | "none" }`
  - `function runDriverContract(name: string, hooks: ContractHooks): void` —— 内部自建 `describe`/`it`
  - `function createSqliteDriver(config: Extract<DsConfig, { kind: "sqlite" }>): Driver`

**固定夹具(三个 driver 必须建出同样的东西,列类型可各自不同):**

| 表 | 列 | 数据 |
|---|---|---|
| `contract_customers` | `customer_id` 主键、`region` NOT NULL | `(1,'华东')`、`(2,'华南')` |
| `contract_orders` | `order_id` 主键、`customer_id` 外键→`contract_customers.customer_id`、`order_date`、`amount` | 6 行:`2024-01-05/1/100`、`2024-01-20/2/200`、`2024-02-03/1/300`、`2024-02-14/2/400`、`2024-03-08/1/500`、`2024-03-22/2/600` |

按月汇总的期望结果固定为 `[["2024-01",300],["2024-02",700],["2024-03",1100]]`。

- [ ] **Step 1: 写契约骨架 `drivers/contract.ts`**

```ts
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import type { Driver } from "../driver";
import { DsError } from "../errors";

export interface ContractHooks {
  /** 建夹具表并灌数据,返回可用的 driver 与清理函数。 */
  setup(): Promise<{ driver: Driver; cleanup: () => Promise<void> }>;
  sql: {
    /** 按月汇总,应得 [["2024-01",300],["2024-02",700],["2024-03",1100]] */
    monthlyTotals: string;
    /** 返回全部 6 行订单 */
    manyRows: string;
    /** 一条写语句 */
    insert: string;
    /** 一条必然超过 200ms 的查询 */
    slow: string;
    /** 查一张不存在的表 */
    badTable: string;
  };
  /** engine = 引擎硬拒;expected-weak = 引擎拒不住(MySQL),改为断言能探出写权限 */
  writeRejection: "engine" | "expected-weak";
  /** server = 服务端能掐;none = 进程内无法强制(SQLite 同步执行) */
  timeoutEnforcement: "server" | "none";
}

export function runDriverContract(name: string, hooks: ContractHooks): void {
  describe(`${name} 驱动契约`, () => {
    let driver: Driver;
    let cleanup: () => Promise<void>;

    beforeAll(async () => { ({ driver, cleanup } = await hooks.setup()); }, 30_000);
    afterAll(async () => { await cleanup?.(); });

    it("testConnection 成功并给出写权限判断", async () => {
      const r = await driver.testConnection();
      expect(r.ok).toBe(true);
      if (r.ok) expect(["readonly", "writable", "unknown"]).toContain(r.writePrivilege);
    });

    it("introspect 找到两张夹具表", async () => {
      const names = (await driver.introspect()).map(t => t.tableName);
      expect(names).toEqual(expect.arrayContaining(["contract_customers", "contract_orders"]));
    });

    it("introspect 给出列名、主键与非空标记", async () => {
      const orders = (await driver.introspect()).find(t => t.tableName === "contract_orders")!;
      expect(orders.columns.map(c => c.name).sort())
        .toEqual(["amount", "customer_id", "order_date", "order_id"]);
      expect(orders.columns.find(c => c.name === "order_id")!.pk).toBe(true);
      const customers = (await driver.introspect()).find(t => t.tableName === "contract_customers")!;
      expect(customers.columns.find(c => c.name === "region")!.notNull).toBe(true);
    });

    it("introspect 给出外键指向", async () => {
      const orders = (await driver.introspect()).find(t => t.tableName === "contract_orders")!;
      expect(orders.foreignKeys).toEqual(expect.arrayContaining([
        { column: "customer_id", refTable: "contract_customers", refColumn: "customer_id" },
      ]));
    });

    it("按月汇总的结果三种源一致", async () => {
      const { rows } = await driver.runQuery(hooks.sql.monthlyTotals, 100, 5000);
      const pairs = rows.map(r => [String(Object.values(r)[0]), Number(Object.values(r)[1])]);
      expect(pairs).toEqual([["2024-01", 300], ["2024-02", 700], ["2024-03", 1100]]);
    });

    it("超过上限时切到上限并标记 truncated", async () => {
      const r = await driver.runQuery(hooks.sql.manyRows, 3, 5000);
      expect(r.rows).toHaveLength(3);
      expect(r.truncated).toBe(true);
    });

    it("行数不足上限时不误报截断", async () => {
      const r = await driver.runQuery(hooks.sql.manyRows, 100, 5000);
      expect(r.rows).toHaveLength(6);
      expect(r.truncated).toBe(false);
    });

    it("查不存在的表报 SCHEMA_STALE", async () => {
      await expect(driver.runQuery(hooks.sql.badTable, 10, 5000)).rejects.toMatchObject({
        code: "SCHEMA_STALE",
      });
    });

    it("抛出的一律是 DsError 而不是原生错误", async () => {
      await expect(driver.runQuery(hooks.sql.badTable, 10, 5000)).rejects.toBeInstanceOf(DsError);
    });

    if (hooks.writeRejection === "engine") {
      it("写操作被引擎拒绝", async () => {
        await expect(driver.runQuery(hooks.sql.insert, 10, 5000)).rejects.toBeInstanceOf(DsError);
      });
    } else {
      it("引擎拦不住写(已知弱点),但能探出账号有写权限", async () => {
        expect(await driver.probeWritePrivilege()).toBe("writable");
      });
    }

    if (hooks.timeoutEnforcement === "server") {
      it("超时由服务端掐断", async () => {
        await expect(driver.runQuery(hooks.sql.slow, 10, 200)).rejects.toMatchObject({
          code: "TIMEOUT",
        });
      }, 20_000);
    } else {
      it.skip(`超时无法在进程内强制(${name} 同步执行),已知限制`, () => {
        // 占位:保留一个可见的 skip,让「跳过」出现在测试报告里而不是消失。
      });
    }
  });
}
```

- [ ] **Step 2: 写 SQLite 驱动 `drivers/sqlite.ts`**

```ts
import type { TableSchema } from "@chatbi/shared";
import { DbClient } from "../../dbClient";
import { wrapTimeout } from "../../sqlGuard";
import type { Driver, QueryResult, TestResult } from "../driver";
import { SQLITE_DIALECT } from "../dialect";
import { mapSqliteError } from "../errors";
import type { DsConfig, WritePrivilege } from "../types";

type SqliteConfig = Extract<DsConfig, { kind: "sqlite" }>;

/**
 * SQLite 驱动:只读打开文件,写操作由引擎硬拒——这是三种源里最强的只读保证。
 * 超时只有 wrapTimeout 兜底:better-sqlite3 同步执行,长查询会堵住事件循环,
 * 进程内无法真正掐断(不暴露 sqlite3_interrupt)。契约测试里以 timeoutEnforcement: "none" 标注。
 */
export function createSqliteDriver(config: SqliteConfig): Driver {
  let client: DbClient | null = null;
  const open = (): DbClient => {
    if (!client) {
      try {
        client = new DbClient(config.path, { readonly: true });
      } catch (e) {
        throw mapSqliteError(e);
      }
    }
    return client;
  };

  return {
    kind: "sqlite",
    dialect: SQLITE_DIALECT,

    async testConnection(): Promise<TestResult> {
      try {
        open().getSchema();
        return { ok: true, writePrivilege: "readonly" };
      } catch (e) {
        const err = mapSqliteError(e);
        return { ok: false, code: err.code, message: err.message, details: err.details };
      }
    },

    async introspect(): Promise<TableSchema[]> {
      try {
        return open().getSchema().filter(t => !t.tableName.startsWith("sqlite_"));
      } catch (e) {
        throw mapSqliteError(e);
      }
    },

    async runQuery(sql: string, limit: number, timeoutMs: number): Promise<QueryResult> {
      try {
        return await wrapTimeout(
          timeoutMs,
          Promise.resolve().then(() => open().runQuery(sql, limit)),
        );
      } catch (e) {
        throw mapSqliteError(e);
      }
    },

    async probeWritePrivilege(): Promise<WritePrivilege> {
      // 只读连接,恒定只读。
      return "readonly";
    },

    async close(): Promise<void> {
      client?.close();
      client = null;
    },
  };
}
```

- [ ] **Step 3: 写 SQLite 契约测试**

Create `apps/backend/tests/drivers.sqlite.test.ts`:

```ts
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { DbClient } from "../src/dbClient";
import { createSqliteDriver } from "../src/datasources/drivers/sqlite";
import { runDriverContract } from "../src/datasources/drivers/contract";

const tmpDir = join(process.cwd(), ".tmp-test-sqlite");
const dbPath = join(tmpDir, "contract.db");

const FIXTURE = `
CREATE TABLE contract_customers (
  customer_id INTEGER PRIMARY KEY, region TEXT NOT NULL
);
CREATE TABLE contract_orders (
  order_id INTEGER PRIMARY KEY, customer_id INTEGER,
  order_date TEXT, amount REAL,
  FOREIGN KEY (customer_id) REFERENCES contract_customers(customer_id)
);
INSERT INTO contract_customers VALUES (1,'华东'),(2,'华南');
INSERT INTO contract_orders VALUES
 (1,1,'2024-01-05',100),(2,2,'2024-01-20',200),(3,1,'2024-02-03',300),
 (4,2,'2024-02-14',400),(5,1,'2024-03-08',500),(6,2,'2024-03-22',600);
`;

runDriverContract("SQLite", {
  async setup() {
    rmSync(tmpDir, { recursive: true, force: true });
    mkdirSync(tmpDir, { recursive: true });
    const writable = new DbClient(dbPath);
    writable.execRaw(FIXTURE);
    writable.close();
    const driver = createSqliteDriver({ kind: "sqlite", path: dbPath });
    return {
      driver,
      cleanup: async () => {
        await driver.close();
        rmSync(tmpDir, { recursive: true, force: true });
      },
    };
  },
  sql: {
    monthlyTotals: `SELECT strftime('%Y-%m', order_date) AS m, SUM(amount) AS total
                    FROM contract_orders GROUP BY m ORDER BY m`,
    manyRows: "SELECT order_id, amount FROM contract_orders ORDER BY order_id LIMIT 7",
    insert: "INSERT INTO contract_customers VALUES (9,'华北')",
    slow: `WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 20000000)
           SELECT COUNT(*) AS n FROM c`,
    badTable: "SELECT * FROM contract_no_such_table",
  },
  writeRejection: "engine",
  timeoutEnforcement: "none",
});
```

`manyRows` 用 `LIMIT 7` 是因为调用方本该先跑 `enforceLimit(sql, limit + 1)`;契约测试直接把探针上限写进 SQL,验证 driver 的切片与 `truncated` 逻辑。

- [ ] **Step 4: 运行测试**

Run: `npx vitest --root apps/backend run tests/drivers.sqlite.test.ts`
Expected: PASS 10 个 + SKIP 1 个(超时那条,报告里应看得见 `↓ 超时无法在进程内强制`)。

- [ ] **Step 5: 跑全量后端测试**

Run: `npx vitest --root apps/backend run`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add apps/backend/src/datasources/drivers apps/backend/tests/drivers.sqlite.test.ts
git commit -m "feat(backend): driver contract suite and read-only SQLite driver"
```

---

### Task 6: MySQL 驱动

**Files:**
- Create: `apps/backend/src/datasources/drivers/mysql.ts`
- Modify: `apps/backend/package.json`(加 `mysql2`)
- Test: `apps/backend/tests/drivers.mysql.test.ts`(env 门控的契约测试)
- Test: `apps/backend/tests/mysqlGrants.test.ts`(不需要数据库)

**Interfaces:**
- Consumes: `Driver`、`QueryResult`、`TestResult`(Task 4);`MYSQL_DIALECT`、`mapMysqlError`、`DsError`(Task 4);`DsConfig`、`WritePrivilege`(Task 3);`runDriverContract`(Task 5)
- Produces:
  - `function createMysqlDriver(config: Extract<DsConfig, { kind: "mysql" }>): Driver`
  - `function parseMysqlGrants(lines: string[]): WritePrivilege` —— 纯函数,单独测

**三个必须做对的细节:**

1. **类型回传**:mysql2 默认把 `DECIMAL` 给成字符串、`DATE`/`DATETIME` 给成 JS `Date` 对象。两者都会破坏图表推导(`Row` 只接受 `string | number | null`)。连接时开 `decimalNumbers: true`(DECIMAL 转 number)与 `dateStrings: true`(日期转字符串,与 SQLite 的文本日期一致)。精度取舍写进注释:BI 场景要的是可画的数,不是分币级精度。
2. **超时下推**:每次查询前 `SET SESSION max_execution_time = ?`(毫秒,只作用于 SELECT,正合我们的用途),外面再套 `wrapTimeout(timeoutMs + 500)` 兜底——**客户端的超时必须比服务端的大**,否则客户端先跳、服务端的取消永远不会触发。
3. **只读**:连接建立后 `SET SESSION TRANSACTION READ ONLY`。这一档拦不住显式 `START TRANSACTION`,所以契约里 `writeRejection: "expected-weak"`,真正的防线是只读账号 + `sqlGuard`。

- [ ] **Step 1: 装依赖**

```bash
npm install mysql2 --workspace=apps/backend
```

- [ ] **Step 2: 写 grants 解析的失败测试**

Create `apps/backend/tests/mysqlGrants.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { parseMysqlGrants } from "../src/datasources/drivers/mysql";

describe("parseMysqlGrants", () => {
  it("只有 SELECT 与 USAGE 时判为只读", () => {
    expect(parseMysqlGrants([
      "GRANT USAGE ON *.* TO `bi_ro`@`%`",
      "GRANT SELECT ON `sales`.* TO `bi_ro`@`%`",
    ])).toBe("readonly");
  });

  it("有 INSERT 时判为可写", () => {
    expect(parseMysqlGrants([
      "GRANT SELECT, INSERT ON `sales`.* TO `app`@`%`",
    ])).toBe("writable");
  });

  it("ALL PRIVILEGES 判为可写", () => {
    expect(parseMysqlGrants(["GRANT ALL PRIVILEGES ON *.* TO `root`@`localhost`"])).toBe("writable");
  });

  it("只看 GRANT 与 ON 之间的权限段,不被库名误导", () => {
    expect(parseMysqlGrants([
      "GRANT SELECT ON `insert_logs`.* TO `bi_ro`@`%`",
    ])).toBe("readonly");
  });

  it("认不出格式时返回 unknown,不谎称安全", () => {
    expect(parseMysqlGrants(["这不是一条 grant"])).toBe("unknown");
    expect(parseMysqlGrants([])).toBe("unknown");
  });

  it("多条里只要有一条可写就判可写", () => {
    expect(parseMysqlGrants([
      "GRANT SELECT ON `a`.* TO `u`@`%`",
      "GRANT DELETE ON `b`.* TO `u`@`%`",
    ])).toBe("writable");
  });
});
```

- [ ] **Step 3: 运行确认失败**

Run: `npx vitest --root apps/backend run tests/mysqlGrants.test.ts`
Expected: FAIL,解析不到模块。

- [ ] **Step 4: 写 `drivers/mysql.ts`**

```ts
import mysql from "mysql2/promise";
import type { TableSchema } from "@chatbi/shared";
import { wrapTimeout } from "../../sqlGuard";
import type { Driver, QueryResult, TestResult } from "../driver";
import { MYSQL_DIALECT } from "../dialect";
import { mapMysqlError } from "../errors";
import type { DsConfig, WritePrivilege } from "../types";

type MysqlConfig = Extract<DsConfig, { kind: "mysql" }>;

const WRITE_PRIVS = /\b(ALL PRIVILEGES|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|SUPER|FILE|INDEX|REFERENCES|TRIGGER|LOCK TABLES)\b/i;

/**
 * 只看 `GRANT <权限段> ON ...` 里的权限段,避免被 `insert_logs` 这种库名骗到。
 * 认不出格式返回 unknown——宁可显示「权限未知」也不谎称只读。
 */
export function parseMysqlGrants(lines: string[]): WritePrivilege {
  let sawAny = false;
  for (const line of lines) {
    const m = /^\s*GRANT\s+([\s\S]*?)\s+ON\s+/i.exec(line);
    if (!m) continue;
    sawAny = true;
    if (WRITE_PRIVS.test(m[1])) return "writable";
  }
  return sawAny ? "readonly" : "unknown";
}

export function createMysqlDriver(config: MysqlConfig): Driver {
  let conn: mysql.Connection | null = null;
  let appliedTimeout = -1;

  async function connect(): Promise<mysql.Connection> {
    if (conn) return conn;
    try {
      conn = await mysql.createConnection({
        host: config.host, port: config.port, database: config.database,
        user: config.user, password: config.password,
        ssl: config.ssl ? {} : undefined,
        // DECIMAL 默认给字符串、日期默认给 Date 对象,都会破坏图表推导。
        // BI 要的是可画的数与统一的日期文本,精度上的取舍是有意的。
        decimalNumbers: true,
        dateStrings: true,
        supportBigNumbers: true,
        multipleStatements: false,
      });
      // 会话级只读。拦不住显式 START TRANSACTION,真正的防线是只读账号 + sqlGuard。
      await conn.query("SET SESSION TRANSACTION READ ONLY");
      return conn;
    } catch (e) {
      conn = null;
      throw mapMysqlError(e);
    }
  }

  async function applyTimeout(c: mysql.Connection, timeoutMs: number): Promise<void> {
    if (appliedTimeout === timeoutMs) return;
    // max_execution_time 只作用于 SELECT,正合我们的用途。
    await c.query(`SET SESSION max_execution_time = ${Number(timeoutMs)}`);
    appliedTimeout = timeoutMs;
  }

  return {
    kind: "mysql",
    dialect: MYSQL_DIALECT,

    async testConnection(): Promise<TestResult> {
      try {
        const c = await connect();
        await c.query("SELECT 1");
        return { ok: true, writePrivilege: await this.probeWritePrivilege() };
      } catch (e) {
        const err = mapMysqlError(e);
        return { ok: false, code: err.code, message: err.message, details: err.details };
      }
    },

    async introspect(): Promise<TableSchema[]> {
      try {
        const c = await connect();
        const [cols] = await c.query(
          `SELECT TABLE_NAME AS t, COLUMN_NAME AS c, COLUMN_TYPE AS ty,
                  IS_NULLABLE AS nullable, COLUMN_KEY AS ck
             FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = ?
            ORDER BY TABLE_NAME, ORDINAL_POSITION`,
          [config.database],
        ) as [Record<string, string>[], unknown];
        const [fks] = await c.query(
          `SELECT TABLE_NAME AS t, COLUMN_NAME AS c,
                  REFERENCED_TABLE_NAME AS rt, REFERENCED_COLUMN_NAME AS rc
             FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = ? AND REFERENCED_TABLE_NAME IS NOT NULL`,
          [config.database],
        ) as [Record<string, string>[], unknown];

        const byTable = new Map<string, TableSchema>();
        for (const r of cols) {
          if (!byTable.has(r.t)) byTable.set(r.t, { tableName: r.t, columns: [], foreignKeys: [] });
          byTable.get(r.t)!.columns.push({
            name: r.c, type: r.ty,
            notNull: r.nullable === "NO",
            pk: r.ck === "PRI",
          });
        }
        for (const r of fks) {
          byTable.get(r.t)?.foreignKeys.push({ column: r.c, refTable: r.rt, refColumn: r.rc });
        }
        return [...byTable.values()];
      } catch (e) {
        throw mapMysqlError(e);
      }
    },

    async runQuery(sql: string, limit: number, timeoutMs: number): Promise<QueryResult> {
      try {
        const c = await connect();
        await applyTimeout(c, timeoutMs);
        // 客户端兜底必须比服务端宽,否则服务端的取消永远来不及触发。
        const [rows] = await wrapTimeout(
          timeoutMs + 500,
          c.query({ sql, timeout: timeoutMs + 400 }) as Promise<[Record<string, never>[], unknown]>,
        );
        const all = rows as unknown as QueryResult["rows"];
        return { rows: all.slice(0, limit), truncated: all.length > limit };
      } catch (e) {
        throw mapMysqlError(e);
      }
    },

    async probeWritePrivilege(): Promise<WritePrivilege> {
      try {
        const c = await connect();
        const [rows] = await c.query("SHOW GRANTS FOR CURRENT_USER()") as [Record<string, string>[], unknown];
        return parseMysqlGrants(rows.map(r => String(Object.values(r)[0] ?? "")));
      } catch {
        return "unknown";   // 探测失败不影响可用性
      }
    },

    async close(): Promise<void> {
      await conn?.end().catch(() => { /* 已断开 */ });
      conn = null;
      appliedTimeout = -1;
    },
  };
}
```

- [ ] **Step 5: 运行 grants 测试确认通过**

Run: `npx vitest --root apps/backend run tests/mysqlGrants.test.ts`
Expected: PASS,6 个测试。

- [ ] **Step 6: 写 env 门控的契约测试**

Create `apps/backend/tests/drivers.mysql.test.ts`:

```ts
import { describe, it } from "vitest";
import mysql from "mysql2/promise";
import { createMysqlDriver } from "../src/datasources/drivers/mysql";
import { runDriverContract } from "../src/datasources/drivers/contract";
import type { DsConfig } from "../src/datasources/types";

const FIXTURE = [
  "DROP TABLE IF EXISTS contract_orders",
  "DROP TABLE IF EXISTS contract_customers",
  `CREATE TABLE contract_customers (
     customer_id INT PRIMARY KEY, region VARCHAR(32) NOT NULL
   )`,
  `CREATE TABLE contract_orders (
     order_id INT PRIMARY KEY, customer_id INT,
     order_date DATE, amount DECIMAL(12,2),
     FOREIGN KEY (customer_id) REFERENCES contract_customers(customer_id)
   )`,
  "INSERT INTO contract_customers VALUES (1,'华东'),(2,'华南')",
  `INSERT INTO contract_orders VALUES
     (1,1,'2024-01-05',100),(2,2,'2024-01-20',200),(3,1,'2024-02-03',300),
     (4,2,'2024-02-14',400),(5,1,'2024-03-08',500),(6,2,'2024-03-22',600)`,
];

const raw = process.env.TEST_MYSQL_URL;

if (!raw) {
  // 必须有可见的跳过:静默 skip 会让「全绿」变成假信号。
  console.log("跳过 MySQL 驱动契约测试:未设置 TEST_MYSQL_URL(例:mysql://user:pw@127.0.0.1:3306/chatbi_test)");
  describe("MySQL 驱动契约", () => {
    it.skip("未设置 TEST_MYSQL_URL,跳过", () => { /* 见上面的控制台提示 */ });
  });
} else {
  const u = new URL(raw);
  const config: Extract<DsConfig, { kind: "mysql" }> = {
    kind: "mysql",
    host: u.hostname,
    port: Number(u.port || 3306),
    database: u.pathname.replace(/^\//, ""),
    user: decodeURIComponent(u.username),
    password: decodeURIComponent(u.password),
    ssl: u.searchParams.get("ssl") === "true",
  };

  runDriverContract("MySQL", {
    async setup() {
      const admin = await mysql.createConnection({
        host: config.host, port: config.port, database: config.database,
        user: config.user, password: config.password, multipleStatements: false,
      });
      for (const stmt of FIXTURE) await admin.query(stmt);
      await admin.end();
      const driver = createMysqlDriver(config);
      return {
        driver,
        cleanup: async () => {
          await driver.close();
          const c = await mysql.createConnection({
            host: config.host, port: config.port, database: config.database,
            user: config.user, password: config.password,
          });
          await c.query("DROP TABLE IF EXISTS contract_orders");
          await c.query("DROP TABLE IF EXISTS contract_customers");
          await c.end();
        },
      };
    },
    sql: {
      monthlyTotals: `SELECT DATE_FORMAT(order_date, '%Y-%m') AS m, SUM(amount) AS total
                      FROM contract_orders GROUP BY m ORDER BY m`,
      manyRows: "SELECT order_id, amount FROM contract_orders ORDER BY order_id LIMIT 7",
      insert: "INSERT INTO contract_customers VALUES (9,'华北')",
      slow: "SELECT COUNT(*) AS n FROM contract_orders a, contract_orders b, contract_orders c, contract_orders d, contract_orders e, contract_orders f, contract_orders g, contract_orders h",
      badTable: "SELECT * FROM contract_no_such_table",
    },
    // 建夹具需要写权限,所以这个账号必然是 writable —— 正好验证探测能报出来。
    writeRejection: "expected-weak",
    timeoutEnforcement: "server",
  });
}
```

夹具是用**同一个账号**建的,所以测试账号必然有写权限,`expected-weak` 那条断言 `probeWritePrivilege() === "writable"` 自然成立。真实使用时应配只读账号——那时界面上不会有黄色警告。

- [ ] **Step 7: 运行契约测试(有库时)**

Run: `TEST_MYSQL_URL=mysql://root:pw@127.0.0.1:3306/chatbi_test npx vitest --root apps/backend run tests/drivers.mysql.test.ts`
Expected: PASS,11 个测试。没有 MySQL 时运行同一条命令(不带变量),Expected: 1 个 skip + 控制台出现跳过提示。

- [ ] **Step 8: 提交**

```bash
git add apps/backend/src/datasources/drivers/mysql.ts apps/backend/package.json package-lock.json apps/backend/tests/drivers.mysql.test.ts apps/backend/tests/mysqlGrants.test.ts
git commit -m "feat(backend): MySQL driver with session read-only and server-side timeout"
```

---

### Task 7: PostgreSQL 驱动

三个 driver 里最长的一个:要处理 schema 过滤、只读事务、类型解析覆盖。

**Files:**
- Create: `apps/backend/src/datasources/drivers/postgres.ts`
- Modify: `apps/backend/package.json`(加 `pg`、`@types/pg`)
- Test: `apps/backend/tests/drivers.postgres.test.ts`(env 门控)

**Interfaces:**
- Consumes: 同 Task 6,外加 `POSTGRES_DIALECT`、`mapPgError`
- Produces: `function createPgDriver(config: Extract<DsConfig, { kind: "postgres" }>): Driver`

**四个必须做对的细节:**

1. **`pg` 是 CJS**:写 `import pg from "pg"; const { Client } = pg;`。写成具名导入在 vitest 里能过、真实启动会抛 `SyntaxError`——`node-sql-parser` 已经踩过一次(见 `sqlGuard.ts` 顶部注释)。
2. **类型解析要覆盖**:`pg` 默认把 `numeric` 与 `int8` 给成**字符串**,把 `date`/`timestamp` 给成 JS `Date`。前者让数值列变文本、后者让日期列变对象,两样都会破坏图表推导。用 Client 的 `types.getTypeParser` **按连接覆盖**,不用 `pg.types.setTypeParser`(那是进程全局的,会污染别的连接)。
3. **只读事务**:每次查询包进 `BEGIN READ ONLY` / `COMMIT`,里面 `SET LOCAL statement_timeout`。这是三种源里除 SQLite 之外唯一**服务端硬拒写**的手段。出错必须 `ROLLBACK`,否则连接卡在失败事务里,后续查询全报 `25P02`。
4. **schema 过滤**:PG 多 schema 是常态,`information_schema` 查询必须按 `config.schema ?? "public"` 过滤,否则会把系统表全抓进 prompt。

- [ ] **Step 1: 装依赖**

```bash
npm install pg --workspace=apps/backend
npm install -D @types/pg --workspace=apps/backend
```

- [ ] **Step 2: 写 `drivers/postgres.ts`**

```ts
// pg 是 CJS:必须默认导入再取属性,具名导入在真实启动时抛 SyntaxError。
import pg from "pg";
const { Client } = pg;
import type { TableSchema } from "@chatbi/shared";
import { wrapTimeout } from "../../sqlGuard";
import type { Driver, QueryResult, TestResult } from "../driver";
import { POSTGRES_DIALECT } from "../dialect";
import { mapPgError } from "../errors";
import type { DsConfig, WritePrivilege } from "../types";

type PgConfig = Extract<DsConfig, { kind: "postgres" }>;

/**
 * 按连接覆盖类型解析:numeric/int8 默认给字符串、date/timestamp 默认给 Date 对象,
 * 都会破坏图表推导。不用 pg.types.setTypeParser——那是进程全局的。
 */
const OVERRIDES: Record<number, (v: string) => unknown> = {
  20: v => Number(v),     // int8
  1700: v => Number(v),   // numeric
  1082: v => v,           // date      → 原样文本
  1114: v => v,           // timestamp → 原样文本
  1184: v => v,           // timestamptz
};
const typeConfig = {
  getTypeParser: ((oid: number, format?: unknown) =>
    OVERRIDES[oid] ?? (pg.types.getTypeParser as (o: number, f?: unknown) => unknown)(oid, format)
  ) as never,
};

const COLUMNS_SQL = `
SELECT c.table_name AS t, c.column_name AS col, c.data_type AS ty,
       c.is_nullable AS nullable,
       (pk.column_name IS NOT NULL) AS is_pk
  FROM information_schema.columns c
  LEFT JOIN (
    SELECT kcu.table_name, kcu.column_name
      FROM information_schema.table_constraints tc
      JOIN information_schema.key_column_usage kcu
        ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
     WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = $1
  ) pk ON pk.table_name = c.table_name AND pk.column_name = c.column_name
 WHERE c.table_schema = $1
 ORDER BY c.table_name, c.ordinal_position`;

const FK_SQL = `
SELECT tc.table_name AS t, kcu.column_name AS col,
       ccu.table_name AS rt, ccu.column_name AS rc
  FROM information_schema.table_constraints tc
  JOIN information_schema.key_column_usage kcu
    ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
  JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
 WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = $1`;

const PRIV_SQL = `
SELECT current_setting('is_superuser') = 'on' AS is_super,
       has_schema_privilege(current_user, $1, 'CREATE') AS can_create,
       EXISTS (
         SELECT 1 FROM information_schema.table_privileges
          WHERE grantee = current_user AND table_schema = $1
            AND privilege_type IN ('INSERT','UPDATE','DELETE')
       ) AS can_write`;

export function createPgDriver(config: PgConfig): Driver {
  const schema = config.schema ?? "public";
  let client: pg.Client | null = null;

  async function connect(): Promise<pg.Client> {
    if (client) return client;
    const c = new Client({
      host: config.host, port: config.port, database: config.database,
      user: config.user, password: config.password,
      ssl: config.ssl ? { rejectUnauthorized: true } : false,
      types: typeConfig,
    });
    try {
      await c.connect();
      client = c;
      return c;
    } catch (e) {
      await c.end().catch(() => { /* 连都没连上 */ });
      throw mapPgError(e);
    }
  }

  return {
    kind: "postgres",
    dialect: POSTGRES_DIALECT,

    async testConnection(): Promise<TestResult> {
      try {
        const c = await connect();
        await c.query("SELECT 1");
        return { ok: true, writePrivilege: await this.probeWritePrivilege() };
      } catch (e) {
        const err = mapPgError(e);
        return { ok: false, code: err.code, message: err.message, details: err.details };
      }
    },

    async introspect(): Promise<TableSchema[]> {
      try {
        const c = await connect();
        const cols = await c.query(COLUMNS_SQL, [schema]);
        const fks = await c.query(FK_SQL, [schema]);
        const byTable = new Map<string, TableSchema>();
        for (const r of cols.rows as Record<string, string | boolean>[]) {
          const t = String(r.t);
          if (!byTable.has(t)) byTable.set(t, { tableName: t, columns: [], foreignKeys: [] });
          byTable.get(t)!.columns.push({
            name: String(r.col), type: String(r.ty),
            notNull: r.nullable === "NO",
            pk: r.is_pk === true,
          });
        }
        for (const r of fks.rows as Record<string, string>[]) {
          byTable.get(r.t)?.foreignKeys.push({ column: r.col, refTable: r.rt, refColumn: r.rc });
        }
        return [...byTable.values()];
      } catch (e) {
        throw mapPgError(e);
      }
    },

    async runQuery(sql: string, limit: number, timeoutMs: number): Promise<QueryResult> {
      const c = await connect();
      try {
        // 只读事务:PG 服务端硬拒写入,是这三种源里最强的一档。
        await c.query("BEGIN READ ONLY");
        await c.query(`SET LOCAL statement_timeout = ${Number(timeoutMs)}`);
        // 客户端兜底比服务端宽,否则服务端的取消来不及触发。
        const res = await wrapTimeout(timeoutMs + 500, c.query(sql));
        await c.query("COMMIT");
        const all = res.rows as unknown as QueryResult["rows"];
        return { rows: all.slice(0, limit), truncated: all.length > limit };
      } catch (e) {
        // 不 ROLLBACK 会让连接卡在失败事务里,之后每条查询都报 25P02。
        await c.query("ROLLBACK").catch(() => { /* 连接可能已断 */ });
        throw mapPgError(e);
      }
    },

    async probeWritePrivilege(): Promise<WritePrivilege> {
      try {
        const c = await connect();
        const r = await c.query(PRIV_SQL, [schema]);
        const row = r.rows[0] as { is_super: boolean; can_create: boolean; can_write: boolean };
        return row.is_super || row.can_create || row.can_write ? "writable" : "readonly";
      } catch {
        return "unknown";
      }
    },

    async close(): Promise<void> {
      await client?.end().catch(() => { /* 已断开 */ });
      client = null;
    },
  };
}
```

- [ ] **Step 3: 写 env 门控的契约测试**

Create `apps/backend/tests/drivers.postgres.test.ts`:

```ts
import { describe, it } from "vitest";
import pg from "pg";
const { Client } = pg;
import { createPgDriver } from "../src/datasources/drivers/postgres";
import { runDriverContract } from "../src/datasources/drivers/contract";
import type { DsConfig } from "../src/datasources/types";

const FIXTURE = [
  "DROP TABLE IF EXISTS contract_orders",
  "DROP TABLE IF EXISTS contract_customers",
  `CREATE TABLE contract_customers (
     customer_id INTEGER PRIMARY KEY, region VARCHAR(32) NOT NULL
   )`,
  `CREATE TABLE contract_orders (
     order_id INTEGER PRIMARY KEY,
     customer_id INTEGER REFERENCES contract_customers(customer_id),
     order_date DATE, amount NUMERIC(12,2)
   )`,
  "INSERT INTO contract_customers VALUES (1,'华东'),(2,'华南')",
  `INSERT INTO contract_orders VALUES
     (1,1,'2024-01-05',100),(2,2,'2024-01-20',200),(3,1,'2024-02-03',300),
     (4,2,'2024-02-14',400),(5,1,'2024-03-08',500),(6,2,'2024-03-22',600)`,
];

const raw = process.env.TEST_PG_URL;

if (!raw) {
  console.log("跳过 PostgreSQL 驱动契约测试:未设置 TEST_PG_URL(例:postgres://user:pw@127.0.0.1:5432/chatbi_test)");
  describe("PostgreSQL 驱动契约", () => {
    it.skip("未设置 TEST_PG_URL,跳过", () => { /* 见上面的控制台提示 */ });
  });
} else {
  const u = new URL(raw);
  const config: Extract<DsConfig, { kind: "postgres" }> = {
    kind: "postgres",
    host: u.hostname,
    port: Number(u.port || 5432),
    database: u.pathname.replace(/^\//, ""),
    user: decodeURIComponent(u.username),
    password: decodeURIComponent(u.password),
    ssl: u.searchParams.get("ssl") === "true",
  };

  const admin = async (): Promise<pg.Client> => {
    const c = new Client({
      host: config.host, port: config.port, database: config.database,
      user: config.user, password: config.password,
      ssl: config.ssl ? { rejectUnauthorized: true } : false,
    });
    await c.connect();
    return c;
  };

  runDriverContract("PostgreSQL", {
    async setup() {
      const c = await admin();
      for (const stmt of FIXTURE) await c.query(stmt);
      await c.end();
      const driver = createPgDriver(config);
      return {
        driver,
        cleanup: async () => {
          await driver.close();
          const d = await admin();
          await d.query("DROP TABLE IF EXISTS contract_orders");
          await d.query("DROP TABLE IF EXISTS contract_customers");
          await d.end();
        },
      };
    },
    sql: {
      monthlyTotals: `SELECT to_char(date_trunc('month', order_date), 'YYYY-MM') AS m,
                             SUM(amount) AS total
                        FROM contract_orders GROUP BY 1 ORDER BY 1`,
      manyRows: "SELECT order_id, amount FROM contract_orders ORDER BY order_id LIMIT 7",
      insert: "INSERT INTO contract_customers VALUES (9,'华北')",
      // 不用 pg_sleep:它在我们的方言禁用词表里,拿它做夹具会造成「测试用的正是被禁的东西」的错觉。
      slow: "SELECT COUNT(*) AS n FROM generate_series(1, 300000000)",
      badTable: "SELECT * FROM contract_no_such_table",
    },
    // 只读事务让引擎真的拒写。
    writeRejection: "engine",
    timeoutEnforcement: "server",
  });
}
```

- [ ] **Step 4: 运行契约测试**

Run: `TEST_PG_URL=postgres://postgres:pw@127.0.0.1:5432/chatbi_test npx vitest --root apps/backend run tests/drivers.postgres.test.ts`
Expected: PASS,11 个测试。其中「写操作被引擎拒绝」应因 `25006` 而失败于服务端,`mapPgError` 把它映射成 `PERMISSION_ERROR`。

不带变量运行时:1 个 skip + 控制台跳过提示。

- [ ] **Step 5: 跑全量后端测试**

Run: `npx vitest --root apps/backend run`
Expected: PASS(MySQL/PG 各 1 skip)。

- [ ] **Step 6: 提交**

```bash
git add apps/backend/src/datasources/drivers/postgres.ts apps/backend/package.json package-lock.json apps/backend/tests/drivers.postgres.test.ts
git commit -m "feat(backend): PostgreSQL driver with read-only transactions and statement_timeout"
```

---

### Task 8: 驱动工厂与 registry

单用户,**不做连接池**:按 `dataSourceId` 缓存活的 `Driver`,懒建,编辑/删除时关闭,进程退出时全关。schema 的读缓存逻辑也归它——「缓存缺失时 introspect 一次并写回」是每个调用方都需要的,不能散落。

**Files:**
- Create: `apps/backend/src/datasources/drivers/index.ts`
- Create: `apps/backend/src/datasources/registry.ts`
- Test: `apps/backend/tests/registry.test.ts`

**Interfaces:**
- Consumes: `AppDb`(Task 1);`getDataSource`、`putSchemaCache`、`getSchemaCache`(Task 3);`Driver`(Task 4);`DsError`(Task 4,含新增的 `NOT_FOUND`);三个 `create*Driver`(Task 5–7)
- Produces:
  - `function createDriverFor(config: DsConfig): Driver`
  - `interface DataSourceRegistry { get(id: string): Promise<Driver>; schemaFor(id: string): Promise<TableSchema[]>; refreshSchema(id: string): Promise<{ schema: TableSchema[]; fetchedAt: string }>; invalidate(id: string): Promise<void>; closeAll(): Promise<void> }`
  - `function createRegistry(deps: { db: AppDb; key: Buffer; createDriver?: (config: DsConfig) => Driver }): DataSourceRegistry`

- [ ] **Step 1: 写失败的测试**

Create `apps/backend/tests/registry.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import type { TableSchema } from "@chatbi/shared";
import { openAppDb, type AppDb } from "../src/appDb/index";
import { runMigrations } from "../src/appDb/migrations";
import { createDataSource, getSchemaCache } from "../src/appDb/dataSourceRepo";
import { createRegistry } from "../src/datasources/registry";
import { SQLITE_DIALECT } from "../src/datasources/dialect";
import type { Driver } from "../src/datasources/driver";
import type { DsConfig } from "../src/datasources/types";

const tmpDir = join(process.cwd(), ".tmp-test");
const key = randomBytes(32);
const cfg: DsConfig = { kind: "sqlite", path: "./whatever.db" };
const schema: TableSchema[] = [{
  tableName: "t", columns: [{ name: "a", type: "INTEGER", notNull: false, pk: false }], foreignKeys: [],
}];

let db: AppDb;

function fakeDriver(): Driver & { closed: number; introspects: number } {
  const d = {
    kind: "sqlite" as const, dialect: SQLITE_DIALECT,
    closed: 0, introspects: 0,
    testConnection: async () => ({ ok: true as const, writePrivilege: "readonly" as const }),
    introspect: async () => { d.introspects++; return schema; },
    runQuery: async () => ({ rows: [], truncated: false }),
    probeWritePrivilege: async () => "readonly" as const,
    close: async () => { d.closed++; },
  };
  return d;
}

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  db = openAppDb(join(tmpDir, "app.db"));
  runMigrations(db);
});
afterEach(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

describe("get", () => {
  it("懒建:第一次才造 driver,第二次复用同一个实例", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const create = vi.fn(() => fakeDriver());
    const reg = createRegistry({ db, key, createDriver: create });
    expect(create).not.toHaveBeenCalled();
    const a = await reg.get(rec.id);
    const b = await reg.get(rec.id);
    expect(a).toBe(b);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("id 不存在时报 NOT_FOUND", async () => {
    const reg = createRegistry({ db, key, createDriver: () => fakeDriver() });
    await expect(reg.get("nope")).rejects.toMatchObject({ code: "NOT_FOUND" });
  });

  it("解密失败时报 DECRYPT_ERROR,且不去建连接", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const create = vi.fn(() => fakeDriver());
    const reg = createRegistry({ db, key: randomBytes(32), createDriver: create });
    await expect(reg.get(rec.id)).rejects.toMatchObject({ code: "DECRYPT_ERROR" });
    expect(create).not.toHaveBeenCalled();
  });
});

describe("invalidate", () => {
  it("关掉旧连接,下次重建", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const made: ReturnType<typeof fakeDriver>[] = [];
    const reg = createRegistry({
      db, key,
      createDriver: () => { const d = fakeDriver(); made.push(d); return d; },
    });
    await reg.get(rec.id);
    await reg.invalidate(rec.id);
    expect(made[0].closed).toBe(1);
    await reg.get(rec.id);
    expect(made).toHaveLength(2);
  });

  it("对没建过连接的 id 是安全的空操作", async () => {
    const reg = createRegistry({ db, key, createDriver: () => fakeDriver() });
    await expect(reg.invalidate("nope")).resolves.toBeUndefined();
  });
});

describe("schemaFor", () => {
  it("缓存缺失时 introspect 一次并写回缓存", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const d = fakeDriver();
    const reg = createRegistry({ db, key, createDriver: () => d });
    expect(await reg.schemaFor(rec.id)).toEqual(schema);
    expect(d.introspects).toBe(1);
    expect(getSchemaCache(db, rec.id)!.schema).toEqual(schema);
  });

  it("缓存命中时不再打库", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const d = fakeDriver();
    const reg = createRegistry({ db, key, createDriver: () => d });
    await reg.schemaFor(rec.id);
    await reg.schemaFor(rec.id);
    expect(d.introspects).toBe(1);
  });
});

describe("refreshSchema", () => {
  it("无论有没有缓存都重新抓,并覆盖缓存", async () => {
    const rec = createDataSource(db, key, { name: "x", config: cfg });
    const d = fakeDriver();
    const reg = createRegistry({ db, key, createDriver: () => d });
    await reg.schemaFor(rec.id);
    const r = await reg.refreshSchema(rec.id);
    expect(d.introspects).toBe(2);
    expect(r.schema).toEqual(schema);
    expect(r.fetchedAt).toBeTruthy();
  });
});

describe("closeAll", () => {
  it("关闭所有活连接", async () => {
    const a = createDataSource(db, key, { name: "a", config: cfg });
    const b = createDataSource(db, key, { name: "b", config: cfg });
    const made: ReturnType<typeof fakeDriver>[] = [];
    const reg = createRegistry({
      db, key, createDriver: () => { const d = fakeDriver(); made.push(d); return d; },
    });
    await reg.get(a.id);
    await reg.get(b.id);
    await reg.closeAll();
    expect(made.map(d => d.closed)).toEqual([1, 1]);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest --root apps/backend run tests/registry.test.ts`
Expected: FAIL,解析不到 `../src/datasources/registry`。

- [ ] **Step 3: 写 `drivers/index.ts`**

```ts
import type { Driver } from "../driver";
import type { DsConfig } from "../types";
import { createSqliteDriver } from "./sqlite";
import { createMysqlDriver } from "./mysql";
import { createPgDriver } from "./postgres";

export function createDriverFor(config: DsConfig): Driver {
  switch (config.kind) {
    case "sqlite": return createSqliteDriver(config);
    case "mysql": return createMysqlDriver(config);
    case "postgres": return createPgDriver(config);
  }
}
```

- [ ] **Step 4: 写 `datasources/registry.ts`**

```ts
import type { TableSchema } from "@chatbi/shared";
import type { AppDb } from "../appDb/index";
import { getDataSource, getSchemaCache, putSchemaCache } from "../appDb/dataSourceRepo";
import type { Driver } from "./driver";
import { DsError } from "./errors";
import type { DsConfig } from "./types";
import { createDriverFor } from "./drivers/index";

export interface DataSourceRegistry {
  get(id: string): Promise<Driver>;
  /** 读缓存;缺失时 introspect 一次并写回。 */
  schemaFor(id: string): Promise<TableSchema[]>;
  /** 无条件重抓并覆盖缓存。 */
  refreshSchema(id: string): Promise<{ schema: TableSchema[]; fetchedAt: string }>;
  /** 数据源被编辑或删除后调用:关掉旧连接,免得继续用旧凭据。 */
  invalidate(id: string): Promise<void>;
  closeAll(): Promise<void>;
}

export function createRegistry(deps: {
  db: AppDb;
  key: Buffer;
  createDriver?: (config: DsConfig) => Driver;
}): DataSourceRegistry {
  const make = deps.createDriver ?? createDriverFor;
  // 单用户,不做连接池:一个数据源一个长连接,复用成本远低于每次重连的延迟。
  const live = new Map<string, Driver>();

  async function get(id: string): Promise<Driver> {
    const cached = live.get(id);
    if (cached) return cached;
    const rec = getDataSource(deps.db, deps.key, id);
    if (!rec) throw new DsError("NOT_FOUND", `数据源不存在:${id}`);
    if (!rec.config) throw new DsError("DECRYPT_ERROR", "凭据无法解密,请重新填写连接信息");
    const driver = make(rec.config);
    live.set(id, driver);
    return driver;
  }

  return {
    get,

    async schemaFor(id) {
      const cached = getSchemaCache(deps.db, id);
      if (cached) return cached.schema;
      const schema = await (await get(id)).introspect();
      putSchemaCache(deps.db, id, schema);
      return schema;
    },

    async refreshSchema(id) {
      const schema = await (await get(id)).introspect();
      putSchemaCache(deps.db, id, schema);
      return { schema, fetchedAt: getSchemaCache(deps.db, id)!.fetchedAt };
    },

    async invalidate(id) {
      const driver = live.get(id);
      if (!driver) return;
      live.delete(id);
      await driver.close().catch(() => { /* 已断开 */ });
    },

    async closeAll() {
      const all = [...live.values()];
      live.clear();
      await Promise.all(all.map(d => d.close().catch(() => { /* 已断开 */ })));
    },
  };
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest --root apps/backend run tests/registry.test.ts`
Expected: PASS,10 个测试。

- [ ] **Step 6: 提交**

```bash
git add apps/backend/src/datasources/registry.ts apps/backend/src/datasources/drivers/index.ts apps/backend/tests/registry.test.ts
git commit -m "feat(backend): data source registry with lazy connections and schema cache"
```

---

### Task 9: 内置示例源与启动顺序

**与 spec 的一处细化**:spec 第 1 节把「插入内置示例源」放在迁移 3 号里。这里改成独立的 `ensureBuiltinDataSource()`,原因是插入前必须**加密** config,而加密要密钥——把密钥穿进迁移 API 会让每条纯 DDL 迁移都背上一个用不着的参数。这个函数幂等,效果一样。

**幂等规则**:只在 `data_sources` **完全为空**时插入。用户删掉示例源之后,只要还有别的数据源,重启不会把它招回来;若删光了则会重新出现——空状态下给一个能问的源比让界面空着更好。

**Files:**
- Create: `apps/backend/src/appDb/bootstrap.ts`
- Modify: `apps/backend/src/server.ts`
- Test: `apps/backend/tests/bootstrap.test.ts`

**Interfaces:**
- Consumes: `openAppDb`(Task 1);`runMigrations`(Task 1);`loadKey`(Task 2);`createDataSource`、`listDataSources`(Task 3);`createRegistry`(Task 8);现有 `migrate`、`DbClient`
- Produces:
  - `function ensureBuiltinDataSource(db: AppDb, key: Buffer, opts: { path: string; name?: string }): DataSourceRecord | null` —— 插入了返回记录,已有数据源则返回 `null`
  - `function bootstrapApp(paths?: { dbPath?: string; appDbPath?: string; appKeyPath?: string }): { appDb: AppDb; registry: DataSourceRegistry; key: Buffer }` —— 从 `server.ts` 导出,**不监听端口**,可测
  - `startServer()` 行为不变地继续可用

**启动顺序(顺序不能颠倒)**:

1. 示例业务库迁移(可写 `DbClient` 跑现有 `migrate`,然后关闭)—— 保证 `chatbi.db` 存在,否则内置源的只读连接打不开。
2. `loadKey()` —— 缺失时生成 `data/app.key`。
3. `openAppDb()` + `runMigrations()` —— 建我们自己的表。
4. `ensureBuiltinDataSource()` —— 要用第 2 步的密钥,指向第 1 步的文件。
5. `createRegistry()` —— 不建任何连接。
6. 挂路由、注册退出钩子、`listen`。

- [ ] **Step 1: 写失败的测试**

Create `apps/backend/tests/bootstrap.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdirSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { openAppDb, type AppDb } from "../src/appDb/index";
import { runMigrations } from "../src/appDb/migrations";
import { createDataSource, listDataSources } from "../src/appDb/dataSourceRepo";
import { ensureBuiltinDataSource } from "../src/appDb/bootstrap";
import { bootstrapApp } from "../src/server";

const tmpDir = join(process.cwd(), ".tmp-test-boot");
const key = randomBytes(32);
let db: AppDb;

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  db = openAppDb(join(tmpDir, "app.db"));
  runMigrations(db);
});
afterEach(() => { db.close(); rmSync(tmpDir, { recursive: true, force: true }); });

describe("ensureBuiltinDataSource", () => {
  it("空库时插入一条 sqlite 示例源,config 指向给定路径", () => {
    const r = ensureBuiltinDataSource(db, key, { path: "./data/chatbi.db" })!;
    expect(r.kind).toBe("sqlite");
    expect(r.name).toBe("示例订单库");
    expect(r.config).toEqual({ kind: "sqlite", path: "./data/chatbi.db" });
  });

  it("内置源的 config 也是加密的,不给它开后门", () => {
    ensureBuiltinDataSource(db, key, { path: "./data/chatbi.db" });
    const row = db.raw.prepare("SELECT config_cipher FROM data_sources").get() as { config_cipher: Buffer };
    expect(row.config_cipher.toString("latin1")).not.toContain("chatbi.db");
  });

  it("已经有数据源时什么也不做", () => {
    createDataSource(db, key, { name: "我的库", config: { kind: "sqlite", path: "./x.db" } });
    expect(ensureBuiltinDataSource(db, key, { path: "./data/chatbi.db" })).toBeNull();
    expect(listDataSources(db, key)).toHaveLength(1);
  });

  it("连续调用两次只插一条", () => {
    ensureBuiltinDataSource(db, key, { path: "./data/chatbi.db" });
    ensureBuiltinDataSource(db, key, { path: "./data/chatbi.db" });
    expect(listDataSources(db, key)).toHaveLength(1);
  });
});

describe("bootstrapApp", () => {
  const paths = {
    dbPath: join(tmpDir, "biz.db"),
    appDbPath: join(tmpDir, "app2.db"),
    appKeyPath: join(tmpDir, "app2.key"),
  };

  it("按顺序建出业务库、密钥、元数据库与内置源", () => {
    const app = bootstrapApp(paths);
    try {
      expect(existsSync(paths.dbPath)).toBe(true);      // 第 1 步:示例业务库
      expect(existsSync(paths.appKeyPath)).toBe(true);   // 第 2 步:密钥
      expect(existsSync(paths.appDbPath)).toBe(true);    // 第 3 步:元数据库
      const list = listDataSources(app.appDb, app.key);  // 第 4 步:内置源
      expect(list).toHaveLength(1);
      expect(list[0].config).toEqual({ kind: "sqlite", path: paths.dbPath });
    } finally {
      app.appDb.close();
    }
  });

  it("第二次启动不重复插入,也不重新生成密钥", () => {
    const first = bootstrapApp(paths);
    const firstKey = Buffer.from(first.key);
    first.appDb.close();
    const second = bootstrapApp(paths);
    try {
      expect(second.key.equals(firstKey)).toBe(true);
      expect(listDataSources(second.appDb, second.key)).toHaveLength(1);
    } finally {
      second.appDb.close();
    }
  });

  it("registry 建好但不预热任何连接", async () => {
    const app = bootstrapApp(paths);
    try {
      // 内置源指向刚建好的业务库,取一次应当成功。
      const id = listDataSources(app.appDb, app.key)[0].id;
      const driver = await app.registry.get(id);
      expect(driver.kind).toBe("sqlite");
      await app.registry.closeAll();
    } finally {
      app.appDb.close();
    }
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest --root apps/backend run tests/bootstrap.test.ts`
Expected: FAIL,解析不到 `../src/appDb/bootstrap`。

- [ ] **Step 3: 写 `appDb/bootstrap.ts`**

```ts
import type { AppDb } from "./index";
import { createDataSource, listDataSources } from "./dataSourceRepo";
import type { DataSourceRecord } from "../datasources/types";

const BUILTIN_NAME = "示例订单库";

/**
 * 首次启动时给一个能立刻提问的源,保住「开箱即跑」。
 * 只在完全没有数据源时插入:用户删掉它之后,只要还有别的源,重启不会招它回来。
 */
export function ensureBuiltinDataSource(
  db: AppDb, key: Buffer, opts: { path: string; name?: string },
): DataSourceRecord | null {
  if (listDataSources(db, key).length > 0) return null;
  return createDataSource(db, key, {
    name: opts.name ?? BUILTIN_NAME,
    config: { kind: "sqlite", path: opts.path },
    writePrivilege: "readonly",
  });
}
```

- [ ] **Step 4: 改 `server.ts`**

整体替换 `startServer` 之前的部分,加入 `bootstrapApp`:

```ts
import express from "express";
import { realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { DbClient } from "./dbClient";
import { LlmClient } from "./llmClient";
import { migrate } from "./migrate";
import { createChatRouter } from "./routes/chat";
import { config } from "./config";
import { openAppDb, type AppDb } from "./appDb/index";
import { runMigrations } from "./appDb/migrations";
import { loadKey } from "./appDb/secrets";
import { ensureBuiltinDataSource } from "./appDb/bootstrap";
import { createRegistry, type DataSourceRegistry } from "./datasources/registry";

/**
 * 启动期的准备工作,不监听端口——所以可以在测试里直接调。
 * 顺序有依赖:业务库要先存在(内置源指向它),密钥要先有(内置源的 config 要加密)。
 */
export function bootstrapApp(paths: {
  dbPath?: string; appDbPath?: string; appKeyPath?: string;
} = {}): { appDb: AppDb; registry: DataSourceRegistry; key: Buffer } {
  const dbPath = paths.dbPath ?? config.dbPath;

  // 1. 示例业务库:先用可写连接建表灌数据,关掉后只读连接才打得开。
  const writable = new DbClient(dbPath);
  try {
    migrate(writable);
  } finally {
    writable.close();
  }

  // 2. 密钥。3. 元数据库与迁移。4. 内置示例源。
  const key = loadKey(paths.appKeyPath ?? config.appKeyPath);
  const appDb = openAppDb(paths.appDbPath ?? config.appDbPath);
  runMigrations(appDb);
  ensureBuiltinDataSource(appDb, key, { path: dbPath });

  // 5. registry:不建任何连接。
  const registry = createRegistry({ db: appDb, key });
  return { appDb, registry, key };
}

export function startServer() {
  let app: { appDb: AppDb; registry: DataSourceRegistry; key: Buffer };
  try {
    app = bootstrapApp();
  } catch (e) {
    console.error("启动准备失败:", (e as Error).message);
    process.exit(1);
  }

  // P2a-2 会把 chat 的 deps 换成按 dataSourceId 取 driver;
  // 现在先保持 P1 的行为不变,避免这一步就改动问答链路。
  const db = new DbClient(config.dbPath, { readonly: true });
  try { db.getSchema(); } catch (e) { console.error("schema self-check failed:", e); process.exit(1); }

  const deps = {
    db: {
      getSchema: () => db.getSchema(),
      runQuery: (sql: string, limit: number) => db.runQuery(sql, limit),
    },
    llm: new LlmClient(),
  };
  const server = express();
  server.use(express.json());
  server.use("/api/chat", createChatRouter(deps));

  const shutdown = async (): Promise<void> => {
    await app.registry.closeAll();
    app.appDb.close();
    db.close();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  server.listen(config.port, "localhost", () => console.log(`backend on http://localhost:${config.port}`));
}
```

`isMainModule()` 与文件末尾的 `if (isMainModule()) startServer();` 原样保留。

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest --root apps/backend run tests/bootstrap.test.ts`
Expected: PASS,7 个测试。

- [ ] **Step 6: 跑全量后端测试**

Run: `npx vitest --root apps/backend run`
Expected: PASS。P1 的 171 个测试一个不少。

- [ ] **Step 7: 真启动一次确认没有 ESM 崩溃**

自动化测试走 Vite 的模块解析,掩盖不了 `pg` 这类 CJS 依赖的具名导入问题——必须真跑一次。

Run: `npm run dev --workspace=apps/backend`
Expected: 打印 `backend on http://localhost:5174`,不抛 `SyntaxError`;`apps/backend/data/` 下出现 `app.db` 与 `app.key`。按 Ctrl+C 应当干净退出。

- [ ] **Step 8: 提交**

```bash
git add apps/backend/src/appDb/bootstrap.ts apps/backend/src/server.ts apps/backend/tests/bootstrap.test.ts
git commit -m "feat(backend): bootstrap order, builtin sample data source and shutdown hooks"
```

---

## 本计划完成时的状态

**能做到:**
- `app.db` 里存着加密的数据源记录与 schema 缓存,删数据源时缓存跟着走。
- 三个 driver 都通过同一套契约测试;SQLite 无条件跑,MySQL/PG 由 `TEST_MYSQL_URL` / `TEST_PG_URL` 门控且跳过时会打印原因。
- registry 能按 id 懒建连接、读写 schema 缓存、编辑后失效、退出时全关。
- 后端真启动一次不崩,`data/` 下出现 `app.db` 与 `app.key`。

**还做不到(P2a-2 的事):**
- 界面上看不到任何数据源——没有 API、没有页面。
- 提问仍然只查内置 `chatbi.db`:`POST /api/chat` 还没有 `dataSourceId`,`chatService` 还在用旧的同步 deps。
- `sqlGuard` 仍然硬编码 sqlite 方言,`columnTypes` 还不认识 MySQL/PG 的类型名。

**给 P2a-2 的交接清单(签名照抄,不要重新发明):**

| 要用的东西 | 从哪来 |
|---|---|
| `bootstrapApp(paths?)` → `{ appDb, registry, key }` | `src/server.ts` |
| `registry.get(id)` / `schemaFor(id)` / `refreshSchema(id)` / `invalidate(id)` / `closeAll()` | `src/datasources/registry.ts` |
| `Driver.runQuery(sql, limit, timeoutMs)` —— **异步** | `src/datasources/driver.ts` |
| `dialectFor(kind)` → `{ quoteIdent, sqlParserDialect, promptNotes }` | `src/datasources/dialect.ts` |
| `DsError` / `DsErrorCode` / `isRetryable(code)` | `src/datasources/errors.ts` |
| `createDataSource` / `updateDataSource` / `getDataSource` / `listDataSources` / `deleteDataSource` / `recordCheck` / `getSchemaCache` | `src/appDb/dataSourceRepo.ts` |
| `targetLabel(config)`、`DsConfig`、`DataSourceRecord`、`WritePrivilege` | `src/datasources/types.ts` |
| `DuplicateNameError`(映射成 HTTP 409) | `src/appDb/dataSourceRepo.ts` |

## 自查记录

- **`DsErrorCode` 加了 `NOT_FOUND`**:Task 8 的 registry 需要区分「我们的数据源记录不存在」与「目标库不存在(`DB_NOT_FOUND`)」。Task 4 的类型定义、`MESSAGES` 表与 `isRetryable` 测试列表都已同步。
- **`Migration.up(db)` 取代 spec 里的 `{ sql }`**:Task 9 的内置源要加密后插入,纯 SQL 做不到。
- **内置源改用 `ensureBuiltinDataSource()` 而非迁移 3 号**:同上,避免把密钥参数穿进每条迁移。
- **SQLite 的超时无法在进程内强制**:已在契约骨架里用 `timeoutEnforcement: "none"` 显式声明并保留一个可见的 skip,不假装通过。

## 实施期的偏差记录(2026-07-31 执行时补)

- **临时目录不能共用 `.tmp-test`**:`Global Constraints` 里的约定与既有 `tests/dbClient.test.ts` 撞车,vitest 并行跑文件时两边的 `rmSync` 互删,现象是随机的 8 个 `SQLITE_CANTOPEN`。改成每个测试文件一个目录:`.tmp-test-appdb` / `.tmp-test-secrets` / `.tmp-test-repo` / `.tmp-test-registry`(Task 5、9 本来就已经是独立目录)。
- **Task 1 的回滚断言正则写错**:`/迁移 999 .*boom/` 要求 id 后有空格,而实现给的消息是 `迁移 999(boom)失败: ...`。按实现改测试为 `/迁移 999.*boom/`——消息格式是有意的,带括号更易读。
- **契约里那条「写操作被引擎拒绝」对 SQLite 是空转**:裸 `INSERT` 在 `DbClient.runQuery` 的「不返回行的语句」检查处就被挡下,压根没到引擎,所以只证明了「抛的是 DsError」。已在 `tests/drivers.sqlite.test.ts` 补一个 `INSERT ... RETURNING`(返回行的写语句)用例,它真的走到引擎并得到 `PERMISSION_ERROR`,只读连接的硬拒才算被验证。
- **MySQL / PostgreSQL 契约测试未真跑过**:本机 3306 / 5432 都没有监听,两个文件按设计跳过并打印了原因。三个 driver 里只有 SQLite 的契约有实测证据;MySQL/PG 目前只有类型检查 + `parseMysqlGrants` 纯函数测试 + ESM 导入实测。要真验收必须起库后带 `TEST_MYSQL_URL` / `TEST_PG_URL` 重跑。
- **`pg`/`mysql2` 的 ESM 导入已用 tsx 单独实测**(不只靠 vitest):两个 `create*Driver` 都能在真实 Node ESM 下构造出来,没有 `SyntaxError`。
- **Ctrl+C 的干净退出无法在本机自动验证**:Windows 没有真信号,`SIGINT`/`SIGTERM` 只在真实控制台 Ctrl+C 时才会触发 Node 的模拟。已确认真启动不崩、`data/` 下生成 `app.db` 与 `app.key`、进程可被终止;退出钩子本身留待人工 Ctrl+C 验收。
