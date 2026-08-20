# Chat-BI V2-1 · P3a 四张表、guard 与 `/sql/validate` 设计

**上游 spec**：`2026-08-11-chatbi-v2-1-design.md`（§2.4 端点表、§2.5 数据模型、§2.6 错误码、§4.3 四道闸、§4.6 审计、§5.1 测试策略、§6 预留接口）。本份只展开 P3 的第一段，不改上游的任何其他结论。

**一句话**：把「哪些 SQL 允许执行」这条红线做成一个可单独验收的纯逻辑模块，并把 P3 后续三段要写的四张表建好。

## 0. P3 的四段划分与本份的位置

P3（可控链路）按上游 spec 的内容盘出来包含：四张表 · guard（AST 校验 / LIMIT 注入 / `PolicyResolver`）· `LLMProvider` 三实现 · `ContextProvider` 与列示例值 · 问答流 SSE · 执行器 · 执行流 SSE 与取消 · `chart_spec` · `/sql/validate` · 四个历史与回放 REST · `export.csv` · F-401 下钻 · append-only 审计。这明显超过 P2 任何一段（P2a 3234 行 / P2b 3250 行 / P2c 2431 行计划），塞进一份 spec 会得到一份没法验收的东西。**切成四段，每段自己就是能跑通、能验收的软件**：

| 段 | 内容 | 外部依赖 | 独立验收点 |
|---|---|---|---|
| **P3a（本份）** | 四张表 + migration 0005 · `run_events` append-only 仓储 · **guard** · `POST /sql/validate` | 无 | 闸 2、闸 3 完整可测；`/sql/validate` 可用。不碰 LLM、不碰 SSE |
| P3b | 执行器 · 执行流 SSE · `DELETE` 取消 · 结果预览落库 · `chart_spec` | 真库（`demo_sales` 已有） | **不需要 LLM**——run 由测试直接造。真执行、真取消、真超时、落审计 |
| P3c | `LLMProvider`（ollama / openai_compatible / fake）· `ContextProvider` · 列示例值 · 管线 · 问答流 SSE | Ollama（已就绪） | 完整问答链路 |
| P3d | 历史与回放四个 REST · `export.csv` · F-401 下钻 | P3a/P3b 的表 | F-304 回放 |

**P3b 不依赖 P3c**，这是这个切法的关键：执行流由用户的批准动作开启、输入是编辑器里的 SQL，run 可以在测试里直接造。于是「真执行 + 真取消」这段最危险的代码能在 LLM 完全不参与的情况下验完。

### 0.1 本份做什么、不做什么

**做**：闸 2（AST 校验）· 闸 3（LIMIT 注入）· `PolicyResolver` 注入点 · `GuardVerdict` · `POST /sql/validate` · migration 0005 四张表 + 模型 · `run_events` 的 append-only 仓储。

**不做，且各有归属**：执行器与两条 SSE（P3b/P3c）· `runs`/`conversations`/`run_result_previews` 三张表的仓储（跟着各自消费方走）· `chart_spec`（P3b）· 闸 1 与闸 4（闸 1 是 P2b 的 `/test`，已完成；闸 4 语句超时与真取消在 P3b 的执行器）。

### 0.2 一条已定的跨段决定，记在这里免得丢

**LLM 超时拆成「首 token 超时」+「总时长上限」两个，不是上游 spec §4.5 写的单一 30s。** 依据是本机实测（Ollama 原生 0.32.7 + `qwen3:8b`，CPU 推理）：

| 指标 | 实测 |
|---|---|
| 冷启动（含模型加载） | 36s |
| 热启动首 token | 5.8s |
| 吞吐 | 4.1 tok/s |
| 60 token 的 SQL 总时长 | 20.3s |

单一 30s 总时长超时在本机根本不可用：冷启动就撞破，200 token 的输出要约 50s。而 §2.2 的 `draft.delta` 本来就是流式的——真正要防的是「卡住不出 token」，不是「总时长长」。**这条在 P3c 落实，届时要同步改上游 spec §4.5 的措辞。** 本份不实现任何 LLM 代码，记在这里只是为了不丢。



## 1. 闸 2（AST 校验）是三道检查，不是一道

上游 spec §4.3 写的是「sqlglot 解析后只放行 `SELECT` 与 `WITH`，禁多语句、禁 DDL/DML/`COPY`/`GRANT` 等一切非查询语句」。**照字面实现会留两个能真正写库的缺口**——下面三道检查里，第 2、3 道是实测出来的，不是推演。

实测环境：`sqlglot 30.17.0`。

### 1.1 第一道：根节点白名单 + 单语句

```python
statements = sqlglot.parse(sql, dialect=dialect)   # 返回 list
if len(statements) != 1:            -> MULTIPLE_STATEMENTS
if not isinstance(root, exp.Select | exp.Union | exp.With):  -> WRITE_BLOCKED
```

`parse()` 而不是 `parse_one()`：多语句必须**能被看见然后拒绝**，而 `parse_one()` 在多语句上的行为是只给第一条，等于静默丢掉后面那条。实测 `select 1; select 2` → `parse()` 返回 2 条、根都是 `Select`。

放行集合里有 `exp.Union`：`select a from t union select b from u` 的根是 Union 而不是 Select，漏了它会把一条合法查询判成写操作。

### 1.2 第二道：整树扫描写节点

**实测**：

| SQL | 根节点 | 树内写节点 |
|---|---|---|
| `with x as (select 1 a) select * from x` | `Select` | — |
| `with x as (insert into t values (1) returning *) select * from x` | **`Select`** | `Insert` |

两者的**根节点完全相同**。Postgres 的 data-modifying CTE 在语法上就是一个带 `With` 的 `Select`，第一道检查无法区分它们。所以必须遍历整棵树：

```python
WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
               exp.Alter, exp.TruncateTable, exp.Grant, exp.Merge, exp.Copy)
if any(isinstance(node, WRITE_NODES) for node in root.walk()):  -> WRITE_BLOCKED
```

`exp.Merge` 与 `exp.Copy` 一起收：`MERGE` 是写，`COPY` 上游 spec §4.3 点名要禁（它能读写文件系统）。

### 1.3 第三道：`into` arg 检查

**实测**（三个方言逐一确认）：

| SQL | 根节点 | 树内写节点 | `args["into"]` |
|---|---|---|---|
| `select * into new_t from t` | `Select` | **空** | **非 None** |

`SELECT INTO` 在 Postgres 里**会建一张新表**，在三个方言下 sqlglot 都把它解析成 `Select` + `into` arg。前两道检查**全部放行它**——根是 Select、树内没有任何写节点类。这是本份设计里最重要的一个发现：

```python
if root.args.get("into") is not None:  -> WRITE_BLOCKED
```

顺带确认了两条不必额外处理的：`create table x as select * from t` 的根是 `Create`（第一道拦住）；MySQL 的 `select … into outfile '/tmp/x.csv'` 在 sqlglot 里直接 `ParseError`（判成 `SQL_PARSE_ERROR` 拒绝，拒绝比放行安全）。

### 1.4 为什么这三道要分开写而不是合成一个函数

它们**失败模式不同、被绕过的方式也不同**，合成一坨会让「哪一道漏了」无法定位。更要紧的是测试：三道各自有专属的绕过样本，反向验证要能证明「删掉第 2 道 → 只有 CTE 那条转红」「删掉第 3 道 → 只有 `SELECT INTO` 那条转红」，两者不能互相兜住。合成一个函数后这种证明做不出来。

### 1.5 解析失败即拒绝，不做兜底

上游 spec §4.3 明写「解析失败即拒绝，不做『看起来像 SELECT 就放过』的兜底」。`sqlglot.errors.ParseError` → `SQL_PARSE_ERROR`。

注释夹带（`/* */ drop table t`）、大小写变形、空白变形全部由 AST 天然处理——**这正是用 AST 而不是正则的理由**，不需要额外代码，但需要测试钉住（§8）。



## 2. 闸 3（LIMIT 注入）：`limit` arg 有三种形态

上游 spec §4.3：「强制注入 LIMIT（默认 1000，可配）。已有 LIMIT 且更小则保留原值。」

**实测发现的坑**：`tree.args["limit"]` 不只装 `exp.Limit`。三种 SQL 都把东西放进同一个 arg：

| SQL | `args` 里的键 | 节点类型 |
|---|---|---|
| `select * from t limit 5` | `limit` | `exp.Limit` |
| `select * from t fetch first 5 rows only` | **`limit`** | `exp.Fetch` |
| `select * from t limit 3 by x`（ClickHouse） | **`limit`** | 带 `BY` 的 `Limit` |

只认 `exp.Limit` 并从它读数值，另两种会因为「读不出数值」而被当成**没有 LIMIT**，然后 `tree.limit(1000)` 把它们整个替换掉。实测输出：

```
输入  select * from t fetch first 5 rows only
输出  SELECT * FROM t LIMIT 1000        ← FETCH FIRST 5 被静默抹掉了
输入  select * from t limit 3 by x      （clickhouse）
输出  SELECT * FROM t LIMIT 1000        ← LIMIT BY 语义被整个丢掉
```

这不是安全问题（1000 仍是上限），但**用户明确写的「只要 5 行」被无声改成 1000 行**，而 `effective_sql` 会回显这个结果，用户只会以为后端算错了。

### 2.1 处理规则

| 现有形态 | 处理 | 理由 |
|---|---|---|
| 无 | 注入 `LIMIT <max>` | spec §4.3 |
| `LIMIT n`，`n ≤ max` | 原样保留 | spec §4.3「更小则保留原值」 |
| `LIMIT n`，`n > max` | 改成 `LIMIT <max>` | 收紧 |
| `FETCH FIRST n ROWS ONLY`，`n ≤ max` | **原样保留**，不改写成 `LIMIT` | 它已经是一个不超上限的行数限制，改写只会让 `effective_sql` 与用户写的对不上 |
| `FETCH FIRST n ROWS ONLY`，`n > max` | 换成 `LIMIT <max>` | 收紧 |
| `LIMIT n BY x` | **原样保留 + warning** | 见 §2.2 |
| `LIMIT` 的值不是字面量（表达式/参数） | 换成 `LIMIT <max>` | 无法静态判断它是否 ≤ max，收紧是安全的方向 |

`OFFSET` 单独一个 arg（实测 `select * from t offset 10` 只有 `offset`），与本节无关，不动它。

### 2.2 `LIMIT n BY x` 保留原样，是有意的取舍

ClickHouse 的 `LIMIT n BY x` 语义是「每个 `x` 取 n 行」，**总行数无上界**。理想做法是再加一个总 `LIMIT`，但实测 sqlglot 对同一条语句上两个 LIMIT 直接报错：

```
select * from t limit 3 by x limit 5000
  -> ParseError: Found multiple 'LIMIT' clauses. Line 1, Col: 34.
```

所以没有「不改变语义又能加总上限」的写法。**这不留缺口**：P2b 的驱动层取 `max_rows + 1` 行后 `truncate()`，返回行数在驱动那一层是硬保证的（那也是 `truncated` 标记的来源）。闸 3 注入 LIMIT 的额外价值是**减少库侧扫描量**，对这个边缘语法放弃该优化、换取不篡改用户语义，是可接受的。

verdict 里带一条 warning 说明「这条语句的库侧行数未受限，返回结果仍会被截断到 <max> 行」——让它可见，而不是悄悄放过。

### 2.3 注入结果就是 `effective_sql`

`root.sql(dialect=dialect)` 的输出即 `effective_sql`，上游 spec §2.3 要求它必须回显（可审计的前提）。

**它与用户输入几乎总是不同**，即使一个字都没改：sqlglot 会规范化关键字大小写、引号、空白、括号。所以**任何「比较字符串判断有没有被改」的做法都会误报**——`limit_applied` 必须是一个独立的布尔字段（§4）。

### 2.4 `max_rows` 从哪来

`Settings.max_result_rows`（默认 1000，P1 已有）。**guard 的函数签名显式接收它，不自己读 `get_settings()`**——与 P2b 驱动的 `execute()` 同一条约定：安全红线代码不要隐式全局依赖，否则测试要靠改环境变量才能测边界值。



## 3. `GuardVerdict` 与错误码

```python
@dataclass(frozen=True)
class GuardVerdict:
    ok: bool
    effective_sql: str | None   # ok=False 时为 None——被拒的语句没有「实际会跑的版本」
    code: str | None            # ok=True 时为 None
    reason: str | None          # 给用户看的中文短句，ok=True 时为 None
    limit_applied: bool         # 注入或收紧了行数上限
    warnings: tuple[str, ...]   # 不阻止执行，但用户该知道
```

frozen dataclass 而不是 Pydantic 模型：guard 是领域层，它的输出要能脱离 HTTP 用（P3b 的执行器直接消费它）。HTTP 响应模型在 `api/` 那一层单独声明，从这个对象转过去。

### 3.1 三个错误码：两个首次落地，一个新增

上游 spec §2.6 已经**定义**了 `WRITE_BLOCKED` 与 `SQL_PARSE_ERROR`，但它们在代码里还不存在（`errors.py` 现在只有 P1/P2 的那几个）——本份是它们首次落地。真正**新增**的只有一个：

```python
MULTIPLE_STATEMENTS = ("MULTIPLE_STATEMENTS", "一次只能执行一条语句", 400)
```

上游 §2.6 把多语句归在 `WRITE_BLOCKED`（「AST 命中写操作/DDL/多语句」）。**分开是因为它们的用户动作不同**：`WRITE_BLOCKED` 要用户改掉写操作，多语句要用户删掉分号后面的部分。合成一个码会让前端只能给一句笼统的话。这是对上游 §2.6 的一处细化，要回填。

`SQL_PARSE_ERROR` 的 `reason` **可以带 sqlglot 报的位置信息**（行列号），这不违反 §4.4：那是用户自己刚写的 SQL，不是库结构。上游 §2.6 的前端表现也明写「内联说明 + 报错位置」。

`WRITE_BLOCKED` 的 `reason` **说清是哪一类写操作**（「语句包含 INSERT」/「`SELECT INTO` 会创建表」），同理——用户自己写的东西，告诉他比让他猜好。**但不包含表名与列名**：那部分可能来自被污染的 LLM 输出或库结构。

### 3.2 三个码都是 400，不是 403

被拒的原因是「这条语句不允许执行」，不是「你没权限」。403 会让前端把它渲染成权限问题，而用户改一下 SQL 就能过。`PERMISSION_DENIED`(403) 留给真正的授权失败（无 `can_query`），那在 `require_datasource` 里，不在 guard。



## 4. `POST /api/datasources/{id}/sql/validate`

上游 spec §2.4 写的路径是 `POST /api/sql/validate`。**本份改挂到数据源下**，因为 dialect 由 `datasource.kind` 决定——同一条 SQL 在 postgres 与 clickhouse 下解析结果不同（`LIMIT 3 BY x` 在前者是 `ParseError`，在后者合法）。一个不带数据源的 `/api/sql/validate` 没法选方言，只能猜。这是对上游 §2.4 的一处偏离，要回填。

顺带的好处是权限自动对齐：吃 `require_datasource`，与 `/test`、`/schema`、`/grants` 一致——「数据源不存在 → 404 / 无 `can_query` 授权 → 403」不用重写。

```
POST /api/datasources/{datasource_id}/sql/validate
请求  {"sql": "select * from demo_sales.orders"}

200   {"ok": true, "code": null, "reason": null,
       "effective_sql": "SELECT * FROM demo_sales.orders LIMIT 1000",
       "limit_applied": true, "warnings": []}

200   {"ok": false, "code": "WRITE_BLOCKED", "reason": "语句包含 INSERT",
       "effective_sql": null, "limit_applied": false, "warnings": []}

401 / 403 / 404   {"code": ..., "message": ...}
```

### 4.1 判定失败也返回 200

**`ok=false` 在响应体里，不是 HTTP 错误码。** 编辑器停止输入 300ms 后就调一次（上游 §2.4），用 4xx 表达「你这条 SQL 有写操作」会让前端把**正常的输入过程**当成错误流——用户打字打到一半必然产生大量语法不完整的中间态，每一个都返回 4xx 会污染监控、也会让前端的错误处理逻辑无法区分「真的出错了」和「用户还在打字」。

401/403/404 仍然是真的 HTTP 错误：那些是「你不该问这个问题」，与「你问的语句不合格」是两回事。

### 4.2 `limit_applied` 为什么必须是独立字段

见 §2.3：sqlglot 会重写整条语句，前端拿 `effective_sql` 与用户输入比字符串**必然误报**（大小写、引号、空白全变）。给一个布尔字段，前端就能准确地在 `LIMIT 5000` 旁边显示「实际会跑 1000 行」。

这也是这个端点返回 `effective_sql` 的全部理由：F-301「每一句 SQL 看得见」如果只在点了运行之后才成立，那用户是在**提交之后**才知道服务端改了什么。输入时就看见，是这条产品红线的完整形态。

### 4.3 它是无状态的，不建 run

不写库、不产生 `run`、不记 `run_events`。理由：它每 300ms 就可能被调一次，为每次按键建审计记录会把 `run_events` 变成击键日志，而 F-304 要审计的是**执行**，不是编辑过程。真正的执行审计在 P3b 的执行流里。



## 5. 四张表（migration 0005）与 append-only

照上游 spec §2.5 建，只有两处补充：

```sql
conversations(id uuid pk, user_id uuid fk, datasource_id uuid fk, title text, created_at)

runs(id uuid pk, conversation_id uuid fk, user_id uuid fk, datasource_id uuid fk,
     question text, chips jsonb,
     generated_sql text,   -- LLM 原始生成版（F-302 AC2 左侧）
     final_sql text,       -- 用户批准的版本（右侧）
     effective_sql text,   -- 注入 LIMIT/策略后实际下发
     status text check (status in
       ('drafted','blocked','running','succeeded','failed','cancelled')),
     error_code text, row_count int, duration_ms int,
     llm_provider text, llm_model text,
     parent_run_id uuid fk,   -- 下钻链路（F-401）
     created_at timestamptz, executed_at timestamptz)

run_events(id bigserial pk, run_id uuid fk, seq int, step text, status text,
           duration_ms int, detail jsonb, at timestamptz,
           unique (run_id, seq))

run_result_previews(run_id uuid pk fk, columns jsonb, rows jsonb, truncated bool)
```

### 5.1 外键的删除行为

| 外键 | 行为 | 理由 |
|---|---|---|
| `conversations.user_id` → users | `RESTRICT` | 与 `datasources.created_by` 一致：会话是审计对象 |
| `conversations.datasource_id` → datasources | `RESTRICT` | 删数据源不该静默销毁历史问答记录。要删得先处理历史——这是有意的摩擦 |
| `runs.conversation_id` → conversations | `CASCADE` | run 脱离会话没有意义 |
| `runs.user_id` / `runs.datasource_id` | `RESTRICT` | 同上，审计对象 |
| `runs.parent_run_id` → runs | `SET NULL` | 删掉父 run 不该连带删掉下钻出来的子 run；断掉链接即可。因此这一列可空 |
| `run_events.run_id` → runs | `CASCADE` | 事件流脱离 run 没有意义 |
| `run_result_previews.run_id` → runs | `CASCADE` | 同上 |

`runs.datasource_id` 用 `RESTRICT` 与 P2c 的 `schema_cache`/`column_notes` 用 `CASCADE` **是有意的不同**：缓存与注释是可重建的派生数据，run 是不可重建的审计记录。

### 5.2 `run_events` 的 append-only 怎么落实

上游 spec §2.5 与 §4.6 都写了「append-only：仓储层只暴露 `append` 与 `list`，没有 UPDATE/DELETE 路径」。本份的落实方式：

- `runs/repository.py` 里**只有** `append_event()` 与 `list_events()` 两个函数。没有 `update_event`、没有 `delete_event`。
- `seq` 由调用方给（执行流按事件顺序递增），`unique (run_id, seq)` 由 DB 保证不重复——**这条约束是 append-only 的真正守卫**：即使有人绕过仓储直接写，重放一个已用过的 seq 也会被 DB 拒绝。
- **不加数据库层的 REVOKE/触发器**。理由：应用账号是同一个，它必须能 INSERT；用触发器禁 UPDATE 会让 migration 的 downgrade 变复杂，而收益只是防住「有人故意绕过仓储层」——那种人也能改触发器。约束写在仓储的形状里 + 一条测试钉住「模块里没有 update/delete 函数」，是这个规模下正确的成本。

`detail jsonb` **不存结果行内容**（上游 §4.6：「不记录结果行内容到日志，只记行数」）。这一条在 P3b 写入事件时才有实际约束力，本份只在 `append_event()` 的文档字符串里写明。

### 5.3 本份只做 `run_events` 的仓储

其余三张表在 P3a **只有表和模型，没有仓储**。这与 P2c1「表先建、仓储跟着消费方」是同一个安排：migration 的正确性能单独验完（up/down 双向 + 外键行为），而 `runs` 的写路径要等 P3b/P3c 才知道确切形状。

例外是 `run_events`：它的 append-only 性质是 F-304 的核心，且**与消费方无关**——不管谁来写事件，都不该有 UPDATE 路径。在这里定下并钉住，比等到 P3b 再补更可靠。



## 6. `PolicyResolver` 注入点

上游 spec §6 要求留这个接口，§4.2 要求「行级/列级**只在执行器留注入点**，`PolicyResolver` 恒返回空策略」。

```python
@dataclass(frozen=True)
class Policy:
    """V2-1 恒为空。V2-2 的语义层策略往这里填。"""
    row_filters: tuple[str, ...] = ()    # 要 AND 进 WHERE 的条件表达式
    denied_columns: frozenset[str] = frozenset()


class PolicyResolver(Protocol):
    def resolve(self, *, user_id: uuid.UUID, datasource_id: uuid.UUID) -> Policy: ...


class EmptyPolicyResolver:
    """V2-1 唯一实现：恒返回空策略。"""
    def resolve(self, *, user_id, datasource_id) -> Policy:
        return Policy()
```

### 6.1 guard 现在就接收 `Policy` 参数，但不实现应用逻辑

`validate()` 的签名里有 `policy: Policy`，函数体里**只有一条**：`if policy.row_filters or policy.denied_columns: raise NotImplementedError`。

这看起来奇怪，理由是明确的：**V2-2 要改的是这一个函数，而不是它的所有调用方**。如果 V2-1 的签名里没有 policy，那 V2-2 落地行列级权限时要改 guard、改执行器、改两条 SSE 的调用点——而 spec §4.2 承诺的是「改动限于 `PolicyResolver` 实现与语义层新表，执行器与其余模块不动」。让参数现在就在位，那句承诺才成立。

`NotImplementedError` 而不是静默忽略：一个非空 policy 被无声丢掉，等于行列级权限**看起来生效了实际没有**——那是最坏的安全失败。V2-1 里这条分支不可能被触发（只有 `EmptyPolicyResolver`），但它是 V2-2 实施者的护栏。

### 6.2 `PolicyResolver` 做成 FastAPI 依赖

与 P2b 的 `driver_for`、P1 的 `get_identity_provider` 同形，理由也一样：**可测**。P3b 的执行器测试要能塞一个返回非空策略的假 resolver 来验证 §6.1 那条 `NotImplementedError` 真的会抛。P1 遗留 2 就是反例（当初不是依赖，测试里换不掉，拖到 P2a 才补）。



## 7. 文件落点与模块边界

### 7.1 新建

| 文件 | 职责 | 规模约束 |
|---|---|---|
| `guard/validator.py` | 三道检查 + LIMIT 注入。纯函数，不 import fastapi / sqlalchemy | **≤200 行**（上游 spec §1.4 点名的安全红线之一） |
| `guard/policy.py` | `Policy` · `PolicyResolver` 协议 · `EmptyPolicyResolver` | 小 |
| `guard/schemas.py` | `GuardVerdict` | 小 |
| `guard/deps.py` | `policy_resolver_for`（FastAPI 依赖） | 小 |
| `api/sql_router.py` | `POST /{id}/sql/validate` | 小 |
| `migrations/versions/0005_runs.py` | 四张表 | — |
| `runs/repository.py` | `append_event()` / `list_events()`，**没有别的** | 小 |

### 7.2 修改

| 文件 | 改动 |
|---|---|
| `db/models.py` | 加 `Conversation` / `Run` / `RunEvent` / `RunResultPreview` 四个模型 |
| `errors.py` | 加 `MULTIPLE_STATEMENTS`（`WRITE_BLOCKED` / `SQL_PARSE_ERROR` 也在本份首次落地） |
| `datasources/schemas.py` 或新建 `guard/schemas.py` | `SqlValidateRequest` / `SqlValidateResponse` |
| `api/routers.py` | `ALL_ROUTERS` 加 `sql_router` |
| `tests/test_migrations.py` | `TABLES` 加四张 |
| `pyproject.toml` | 加 `sqlglot`（唯一新依赖） |

### 7.3 为什么 guard 是一个独立顶层包而不是塞进 `datasources/`

guard 的输入是「一条 SQL + 方言 + 上限 + 策略」，**它不认识数据源模型、不认识仓储、不发任何查询**。放进 `datasources/` 会让人以为它需要数据源对象，从而在将来给它传 ORM 对象——那会让它变得不可脱离库测试，而它是安全红线，必须能穷举边界。

`api/sql_router.py` 是唯一同时认识 `Datasource` 与 guard 的地方：它从 `datasource.kind` 取方言、从 `Settings` 取上限、从依赖取 policy，然后调纯函数。

### 7.4 `runs/` 也是独立顶层包

与 `datasources/` 平级。它现在只有一个 `repository.py`，P3b/P3c/P3d 会往里加。**不放进 `db/`**：`db` 是叶子模块（上游 spec §1.3 规则 4），只有模型与会话，不含业务查询。

### 7.5 唯一的新依赖

`sqlglot`（实测 30.17.0）。它是纯 Python、无编译依赖、无传递依赖，装在哪都一样。**不锁死小版本**（`sqlglot>=30`）但要在实施期记下实测版本——AST 节点类名与 arg 名是它的内部结构，跨大版本可能变，而本份的三道检查全部依赖这些名字（`exp.Insert`、`args["into"]`、`args["limit"]`）。§8 的测试就是这个风险的守卫：升级后跑一遍就知道有没有变。



## 8. 测试策略

上游 spec §5.1 点名 guard 是两个要「穷举边界」的模块之一（另一个是执行器，在 P3b）。所以它的测试是**清单式**的，不是「按测试价值挑几条」。

### 8.1 闸 2 的拒绝清单（每条一个用例）

| 类别 | 样本 |
|---|---|
| 裸写操作 | `insert` · `update` · `delete` · `drop table` · `create table` · `alter table` · `truncate` · `grant` · `merge` · `copy` |
| 多语句 | `select 1; select 2` · `select 1;` （尾随分号**必须放行**——它是单语句） |
| data-modifying CTE | `with x as (insert … returning *) select * from x` |
| `SELECT INTO` | `select * into new_t from t`，三个方言各一条 |
| 注释夹带 | `select 1 /* */; drop table t` · `select 1 -- \n; drop table t` |
| 大小写与空白变形 | `InSeRt InTo t …` · 语句前后大量空白与换行 |
| 解析失败 | `select from where` · `select * from t limit 3 by x limit 5`（后者在 clickhouse 下是真实的 ParseError） |

「尾随分号必须放行」这条容易漏：`select 1;` 在 `parse()` 下是 **1** 条语句，把它判成多语句会让大量正常输入被拒。

### 8.2 闸 2 的放行清单

`select` · `with … select` · `union` / `union all` · 子查询 · `join` · 窗口函数 · `select` 里带字符串字面量 `'insert into'`（**字面量不是节点**，AST 天然不会误判，但要有测试证明——这是「用 AST 而不是正则」的直接收益，正则实现必然在这条上误报）。

### 8.3 闸 3 的清单

§2.1 那张表的每一行一个用例，三个方言各跑一遍能跑的部分。特别要有：

- `FETCH FIRST 5 ROWS ONLY` → `effective_sql` **仍含 `FETCH FIRST 5`**，`limit_applied=False`
- `FETCH FIRST 5000 ROWS ONLY` → 换成 `LIMIT 1000`，`limit_applied=True`
- `LIMIT 3 BY x`（clickhouse）→ 原样保留，`limit_applied=False`，**warnings 非空**
- `LIMIT 1000`（正好等于上限）→ 原样保留，`limit_applied=False`。边界值必须单独测：`<` 与 `<=` 写错在这里才看得出来
- 子查询里的 `LIMIT 5` 不被动，外层照样注入

### 8.4 反向验证（每条都要写明「哪些转红、哪些必须保持绿」）

1. **删掉整树扫描（第 2 道）** → data-modifying CTE 那条转红，其余全部保持绿。这证明只有那一条在守这个缺口。
2. **删掉 `into` 检查（第 3 道）** → `SELECT INTO` 三条转红，data-modifying CTE 那条**保持绿**。第 1、2 条互为对照：证明两道检查各守一个缺口，谁都兜不住谁。
3. **把 `parse()` 换成 `parse_one()`** → 多语句那条转红（它只会看到第一条 `select 1` 并放行）。
4. **`limit` 的读取只认 `exp.Limit`** → `FETCH FIRST 5` 与 `LIMIT 3 BY x` 两条转红，`LIMIT 5` 那条保持绿。
5. **上限比较从 `<=` 改成 `<`** → `LIMIT 1000` 那条边界用例转红，其余全绿。
6. **`Policy` 非空时不抛 `NotImplementedError` 而是忽略** → §6.1 那条测试转红。这一条守的是 V2-2 的安全，现在就要有。

### 8.5 不做的测试

不测 sqlglot 自身的解析正确性（那是它的测试）。本份测的是**我们的三道检查在它的输出上是否做对判断**——所以每个用例都断言 `GuardVerdict` 的字段，不断言 AST 结构。

`/sql/validate` 的端点测试只覆盖编排（鉴权 404/403/401、`ok=false` 仍返回 200、响应字段完整），**不重复 guard 的清单**——那些在领域层已经测过，在 HTTP 层再跑一遍只是让同一件事慢十倍。



## 9. 与上游 spec 的偏离，以及要回填的东西

### 9.1 有意偏离（三处）

| 上游原文 | 本份的做法 | 理由 |
|---|---|---|
| §2.4 `POST /api/sql/validate` | 改挂到 `POST /api/datasources/{id}/sql/validate` | dialect 由 `kind` 决定，不带数据源没法选方言（§4）；顺带让权限与 `/test`、`/schema` 自动一致 |
| §2.6 多语句归在 `WRITE_BLOCKED` | 单独一个 `MULTIPLE_STATEMENTS` | 用户动作不同：一个要改写操作，一个要删分号后的部分（§3.1） |
| §4.3「只放行 `SELECT` 与 `WITH`」 | 三道检查，另加整树扫描与 `into` 检查 | 照字面实现留两个能真正写库的缺口，两者都是实测确认的（§1.2、§1.3） |

前两条要回填进上游 spec。第三条不是冲突而是补充，但**上游 §4.3 闸 2 那段应该加一句**「白名单只看根节点是不够的」，否则下一个读 spec 的人会以为一道就够。

### 9.2 已知的松散端与取舍

- **`LIMIT n BY x` 不注入总上限**（§2.2）。缺口由驱动层的 `truncate()` 兜住，verdict 带 warning。
- **`Policy` 非空即 `NotImplementedError`**（§6.1）。V2-1 不可能触发，它是 V2-2 的护栏。
- **`sqlglot` 的节点类名与 arg 名是内部结构**，跨大版本可能变。不锁小版本，靠 §8 的测试在升级时暴露。实施期要记下实测版本号。
- **`/sql/validate` 不建 run、不记事件**（§4.3）。所以「用户在编辑器里试了 10 版才通过」这件事不可审计。这是有意的：F-304 审计的是执行，不是编辑过程。
- **guard 不做表名白名单校验**。上游 §4.5 的「表名/schema 名过 `schema_cache` 白名单」是 **prompt 注入**的防线（防被污染的元数据把指令注进 prompt），不是 SQL 执行的防线，消费方是 P3c 的 prompt 构建。`known_identifiers()` 在 P2c 已就位。这两件事容易混，混了会在 guard 里加一个既拦不住注入、又会误拒合法 SQL（用户完全可以查一张不在缓存里的新表）的检查。
- **本份没有生产调用方的东西**：`run_events` 仓储（消费方 P3b）、`PolicyResolver`（P3b）、四张表里的三张。与 P2a 的 `read_password`、P2b 的 `execute()`、P2c 的 `known_identifiers()` 同形，是分段交付的常态，别当成死代码。



## 10. 交接清单（P3b / P3c / P3d 要消费的签名）

```python
# guard（chatbi.guard）
validate_sql(sql: str, *, dialect: str, max_rows: int,
             policy: Policy) -> GuardVerdict
#   纯函数。dialect 是 sqlglot 的方言名，由调用方从 datasource.kind 映射
#   （postgres / mysql / clickhouse 三者同名，但映射要显式写出来，别假设永远相同）
GuardVerdict(ok, effective_sql, code, reason, limit_applied, warnings)
Policy(row_filters, denied_columns)          # V2-1 恒为空
PolicyResolver.resolve(*, user_id, datasource_id) -> Policy
EmptyPolicyResolver                          # V2-1 唯一实现
policy_resolver_for()                        # FastAPI 依赖，可被 override

# 审计（chatbi.runs.repository）
append_event(session, *, run_id, seq: int, step: str, status: str,
             duration_ms: int | None, detail: dict | None) -> RunEvent
list_events(session, run_id) -> list[RunEvent]
#   **没有 update / delete**。detail 里不放结果行内容（上游 §4.6）

# 模型（chatbi.db.models）
Conversation / Run / RunEvent / RunResultPreview

# 错误码（chatbi.errors）
WRITE_BLOCKED(400) / SQL_PARSE_ERROR(400) / MULTIPLE_STATEMENTS(400)

# 端点
POST /api/datasources/{id}/sql/validate -> 200（ok 在体内）| 401 | 403 | 404
```

**P3b 执行器**
- 执行前调 `validate_sql()`，把 `verdict.effective_sql` 交给驱动，把 `verdict` 的 `code`/`reason` 用于 `validate` SSE 事件（上游 §2.3）。**不要再写一条校验路径**——闸 2、闸 3 只有这一个实现。
- `run.effective_sql` 存 `verdict.effective_sql`，`run.final_sql` 存用户提交的原文。两者不同是正常的（§2.3）。
- `validate` 判定为 `ok=false` 时 run 置 `blocked`（上游 §2.3），流即结束。
- 事件用 `append_event()`，`seq` 从 1 递增。`unique (run_id, seq)` 会在重放同一个 seq 时拒绝——那说明执行流的序号管理有 bug，不要靠 catch 掉它来"修复"。
- `QUERY_TIMEOUT` / `QUERY_CANCELLED` 两个错误码由 P3b 新增（本份只有 guard 的三个）。

**P3c 问答流**
- `run.generated_sql` 是 LLM 原始输出，**不经过 guard**（它可能是废的，那正是 `blocked` 状态要表达的）。guard 只在执行流上跑。
- LLM 超时按 §0.2 拆两个，并同步改上游 spec §4.5。
- 表名白名单用 P2c 的 `known_identifiers()`，那是 prompt 防线，与 guard 无关（§9.2）。

**P3d 回放**
- `list_events()` 已就位。`run_events` 的 `seq` 是回放顺序的唯一依据，别按 `at` 排序（同毫秒内的事件顺序不确定）。



## 11. 自查记录

**上游 spec 覆盖核对（本份负责的部分）**

| 上游条目 | 落在哪 |
|---|---|
| §4.3 闸 2「AST 校验，只放行 SELECT 与 WITH，禁多语句/DDL/DML/COPY/GRANT」 | §1 三道检查 |
| §4.3 闸 2「用 AST 而不是正则」「解析失败即拒绝，不兜底」 | §1.5 + §8.2 的字面量用例 |
| §4.3 闸 3「强制注入 LIMIT，已有且更小则保留」 | §2 |
| §4.3「写操作永久禁用，不做二次确认」 | §1 全部拒绝，没有任何放行开关 |
| §2.4 `POST /api/sql/validate` | §4（路径有一处有意偏离） |
| §2.5 四张表 | §5 |
| §2.5 + §4.6 `run_events` append-only | §5.2 |
| §2.6 `WRITE_BLOCKED` / `SQL_PARSE_ERROR` | §3.1（另加 `MULTIPLE_STATEMENTS`） |
| §4.2「行列级只在执行器留注入点，`PolicyResolver` 恒返回空策略」 | §6 |
| §6 预留接口表里的 `PolicyResolver` | §6 |
| §1.4「`guard/validator.py` 保持 200 行以内」 | §7.1 |
| §5.1「guard 与执行器穷举边界」 | §8 清单式测试 |
| §4.6「不记录结果行内容，只记行数」 | §5.2 末（约束力在 P3b） |

**不在本份的上游条目**：§2.2 问答流（P3c）· §2.3 执行流与取消（P3b）· §4.3 闸 1（P2b 已完成）与闸 4（P3b）· §4.5 LLM 边界（P3c，§0.2 记了超时那条决定）· §2.4 的其余 REST（P3d）。

**歧义检查**：「多语句」明确为 `parse()` 返回 >1 条，尾随分号不算（§8.1）。「已有 LIMIT 且更小则保留」明确为 `<=`（边界值 `LIMIT 1000` 有专门用例）。「LIMIT」明确为 `limit` arg 的三种形态（§2）。`/sql/validate` 的失败明确为「200 + 体内 ok=false」，与 401/403/404 分开（§4.1）。

**写作过程中的回改三处**

1. **闸 2 从一道变三道**。初稿照上游 §4.3 只写了根节点白名单。写到「怎么测」时想到 data-modifying CTE，跑 sqlglot 一验——根节点确实是 `Select`，与正常 CTE 无法区分。接着顺手试了 `SELECT INTO`，发现它连整树扫描都躲得过（树内写节点为空）。**两道都是实测出来的，不是从文档推的**，所以 §1.2、§1.3 里直接放了实测表格。
2. **`FETCH FIRST` 的判断改过一次**。第一次实测的读取代码把 `args["limit"]` 的非 `exp.Limit` 值 `repr()` 成字符串 `'None'`，于是打印出「现有 limit=None」，我一度以为 `FETCH FIRST` 不在 `limit` arg 里。补验 arg 键才发现它**在**，只是节点类型是 `exp.Fetch`。§2 的表格是修正后的。这个教训值得记：**用 `repr()` 兜住未知类型会把「类型不对」伪装成「值为 None」。**
3. **`/sql/validate` 的路径改到数据源下**。初稿照上游写 `/api/sql/validate`，写 §8 的三方言用例时才意识到没有 `datasource_id` 就选不了方言，而 `LIMIT 3 BY x` 在 postgres 下是 ParseError、在 clickhouse 下合法——同一条 SQL 两种判定，方言不是可选参数。

**规模自查**：`guard/validator.py` 要在 200 行内装三道检查 + LIMIT 注入的七种形态。估算：三道检查约 40 行（含常量表），LIMIT 处理约 60 行，`GuardVerdict` 组装约 20 行，文档字符串与注释约 60 行——**接近上限但不超**。若实施时超了，正确的拆法是把 LIMIT 处理搬到 `guard/limits.py`，**不是**删注释：那些注释记的是实测结论，删掉下一个人就会把 `into` 检查当成多余的。

