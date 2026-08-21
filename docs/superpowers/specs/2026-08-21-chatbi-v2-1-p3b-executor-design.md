# Chat-BI V2-1 · P3b 执行器、执行流 SSE 与真取消 设计

**上游 spec**：`2026-08-11-chatbi-v2-1-design.md`（§2.3 执行流、§2.6 错误码、§3.5 结果与图表、§4.3 四道闸、§4.6 审计、§5.1 测试策略、§6 预留接口）。**P3a 设计**：`2026-08-20-chatbi-v2-1-p3a-guard-design.md`（guard 与四张表已就位）。

**一句话**：把一条已被 guard 批准的 SQL 真的跑起来、把过程流式吐给前端、并且在用户放弃时**真的掐掉库侧的查询**——而不是只关掉流。

## 0. 范围与前置

P3 分四段（划分见 P3a 设计 §0）。本份是第二段。

**做**：执行器（`asyncio.to_thread` 包驱动 + 真取消）· `POST /api/runs/{run_id}/execute`（SSE）· `DELETE /api/runs/{run_id}/execute` · 进程内的运行注册表 · `chart_spec` 规则推断 · 结果预览落库 · `runs` 与 `run_result_previews` 的仓储。

**不做，且各有归属**：

| 推后的东西 | 去哪 | 理由 |
|---|---|---|
| `POST /api/ask` 问答流、`LLMProvider`、`ContextProvider`、列示例值 | P3c | 本段**不需要 LLM**，见下 |
| `runs` 的创建路径、`conversations` 的仓储 | P3c | run 由问答流创建；本段只**消费**已存在的 run |
| 历史与回放 REST、`export.csv`、F-401 下钻 | P3d | |
| 闸 2 与闸 3 | **P3a 已完成** | 本段调 `validate_sql()`，不再写第二条校验路径 |

### 0.1 为什么本段不依赖 P3c

执行流的输入是**编辑器里的 SQL**（上游 spec §2.3：「请求体 `{sql}`——编辑器当前内容，不是草稿」），run 只需要**已存在**。测试里直接造一条 `status='drafted'` 的 run 即可，不需要任何 LLM 参与。

这让「真执行 + 真取消」——本段最危险的代码——能在 LLM 完全不参与的情况下验完，只需要已有的 `demo_sales`（P2b 建的，在应用库里，不需要 Docker）。

### 0.2 前置状态

- P3a 的 `validate_sql()` / `GuardVerdict` / `Policy` / `policy_resolver_for` 已就位。
- 四张表（`conversations` / `runs` / `run_events` / `run_result_previews`）已建，`run_events` 的 append-only 仓储（`append_event` / `list_events`）已就位。
- P2b 的 `Driver.execute(info, sql, *, timeout_seconds, max_rows, on_start)` 与 `Driver.cancel(info, handle)` 已就位并对真 Postgres 验过（含库侧超时与真取消）。`connection_info()` / `driver_for` 也在。
- 起点：**310 passed / 28 skipped**。

### 0.3 不新增依赖

SSE 用手写的 `StreamingResponse` + `media_type="text/event-stream"`。**实测确认不需要 `sse-starlette`**：`TestClient.stream()` 能读到事件行，`Request.is_disconnected()` 可用（虽然在 TestClient 下恒 False，见 §11.3）。少一个依赖，且 SSE 的格式（`event:` / `data:` / 空行）足够简单，自己拼比引一个包更容易看清发出去的到底是什么。



## 1. 取消：三件事，缺一不可

上游 spec §2.3 写的是「cancel asyncio task **并**调驱动的取消能力」。那个「并」不是补充说明，而是**技术上必须**——下面是实测依据。

### 1.1 `asyncio.to_thread` 的 task 被 cancel 后，线程继续跑到底

```python
task = asyncio.create_task(asyncio.to_thread(blocking, 2.0))   # 线程里 time.sleep(2)
await asyncio.sleep(0.2)
task.cancel()
# -> asyncio 侧立刻抛 CancelledError
# -> 但 2 秒后 finished == [2.0]：**线程根本没被中断，还把活干完了**
```

Python 没有安全地从外部中断线程的机制，`to_thread` 也不提供。所以：

- **只 `task.cancel()`** = 关掉 SSE 流，而那条查询**继续在用户的生产库上跑到底**。这正是上游 spec §2.3 说「只关流不取消后端查询是错的：私有化部署里一条跑飞的查询能拖垮用户的生产库」的技术根源。
- **只 `driver.cancel()`** = 库侧掐掉查询，驱动抛 `QueryCancelled`，线程结束，流也随之结束。功能正确，只是流要多等一个往返。

### 1.2 所以 `cancel_run()` 做三件事

```python
def cancel_run(run_id) -> bool:      # 返回是否真的取消了一个正在跑的 run
    1. driver.cancel(info, handle)   # 另开连接掐掉库侧查询（P2b 已实现三个驱动）
    2. task.cancel()                 # 让 SSE 流停止等待，不必等驱动抛异常回来
    3. run.status = 'cancelled'; append_event(...); **显式 commit**（见 §2）
```

顺序是有意的：**先掐库侧，再关流**。反过来的话，`task.cancel()` 之后生成器可能已经退出，而退出路径上如果没有兜住 `CancelledError` 就走不到第 1 步——查询就漏了。

### 1.3 `cancel_run()` 是唯一的取消入口

上游 spec §2.3 有**两个**触发器：客户端断开、`DELETE /api/runs/{run_id}/execute`。两者都只调 `cancel_run()`，自己不做任何取消动作。

这样切是为了**可测**：`cancel_run()` 本身能被直接调用测试（造一个 run + 一个假 handle，断言驱动的 `cancel` 被调、状态与事件落库），而两个触发器各自只需验「它确实调了那个函数」。§11.3 会说明为什么这一点特别重要——其中一个触发器**无法**用现有测试设施验。

### 1.4 进程内注册表

`DELETE` 是**另一个 HTTP 请求**，它必须能找到正在跑的那条查询的 `QueryHandle`。所以需要一张表：

```python
# execution/registry.py
_RUNNING: dict[uuid.UUID, RunningQuery] = {}     # run_id -> (handle, task, info, driver)
register(run_id, ...) / get(run_id) / unregister(run_id)
```

`QueryHandle` 从 P2b 的 `on_start` 回调拿——它在**语句真正下发之前**被调用（P2b 的协议明写「这是取消能力的唯一入口」），所以注册表在那个回调里写。

**一个模块级 dict 成立的唯一前提是单进程部署。** 上游 spec §7.2 明确不做连接池、不做多进程扩展（单机私有化部署），所以这是当前架构下正确的成本。但它是一条**真实的架构约束**，不是实现细节：将来上多 worker（`uvicorn --workers N`）时，`DELETE` 会有 (N-1)/N 的概率打到没有那条 run 的进程上，取消静默失效。这一条要写进部署文档，且**必须在注册表模块的文件头写明**，否则下一个人加 `--workers` 时不会想到这里。

`unregister` 必须在 `finally` 里：查询正常结束、失败、被取消都要清掉，否则注册表会泄漏 handle，而一个陈旧的 handle 会让后续的 `cancel` 掐掉**别人的**查询（backend pid 会被复用）。



## 2. 执行流必须显式 commit，不能依赖 `get_db`

**这是本份最容易踩且最隐蔽的一条。**

### 2.1 实测：流中途出错时 `get_db` 会回滚

`get_db` 的形状是「`yield` 之后 `commit()`，异常时 `rollback()`」（P1 就是这样，且它对普通端点是对的）。而 SSE 的生成器在**依赖清理之前**被消费，所以：

| 情形 | `get_db` 走哪条 | 后果 |
|---|---|---|
| 执行成功、流正常耗尽 | `COMMIT` | 审计记录在 |
| 生成器中途抛异常 | **`ROLLBACK`** | **执行期间写的所有事件全部丢失** |

实测输出（一个最小复现）：

```
正常结束:        ['open', '写入一条事件（未 commit）', 'COMMIT', 'close']
生成器中途抛异常: ['open', '写入一条事件（未 commit）', 'ROLLBACK (RuntimeError)', 'close']
```

（顺带确认了一件好事：session 在生成器执行期间**是活的**，提交与关闭都发生在生成器耗尽之后。所以 `Depends(get_db)` 在 SSE 里可用，不需要在生成器里自己开 session。）

### 2.2 为什么这个失败模式特别危险

**它只影响失败路径。** 开发时跑一条成功的查询，审计记录齐全、一切正常；只有当执行失败、超时、或被取消时，`run_events` 才是空的、`runs.status` 才还停在 `running`。

而上游 spec §4.6 要审计的正是 who / when / 状态 / **错误码**，F-304 的「全链路可审计」对失败的执行同样成立——**被取消和失败的执行恰恰是最需要审计的那些**。

### 2.3 落实

每写完一批状态变更 + 事件就 `session.commit()`。具体是四个提交点：

1. `validate` 判定之后（含 `ok=false` 时 run 置 `blocked`）
2. `execute.started` 之后（run 置 `running`、`final_sql` 与 `effective_sql` 落库、`executed_at` 写入）
3. 结果拿到之后（run 置 `succeeded`、`row_count` / `duration_ms`、结果预览落库）
4. 任一失败路径上（run 置 `failed` / `cancelled` + `error_code`）

**这条要有专门的测试**：让驱动抛异常，然后**在另一个 session 里**查 `run_events` 与 `runs.status`——必须看到两条事件与 `status='failed'`。

用同一个 session 查会因为 identity map 而假绿（P2c1 与 p3a2 各踩过一次同形的坑：验 DB 侧的事实不能用可能命中 identity map 的读取）。所以那条测试要么 `expire_all()`，要么另开一个 engine/session。

### 2.4 一个连带结论：`get_db` 不动

不改 `get_db` 去适配 SSE。它对普通端点的语义（请求成功即提交、异常即回滚）是对的，为 SSE 改掉会影响所有既有端点。SSE 这一条路径自己负责提交时机——**这是流式端点与请求/响应端点的真实差异，不是可以抽象掉的重复**。



## 3. 闸 4 的超时只靠库侧，不加 asyncio 层兜底

上游 spec §4.3 闸 4：「语句超时 + 真取消（默认 60s，可配）。超时与客户端断开都要调驱动的取消能力。」

**不在执行器里加 `asyncio.wait_for`。** 理由与 §1.1 同源：`wait_for` 超时后 cancel 的是 to_thread task，而**线程不会停**——加了之后的行为是「流提前结束、查询继续跑」，那正是闸 4 要防的事。一层停不住东西的超时比没有超时更糟，因为它让人以为有保护。

超时由**驱动的库侧机制**负责，P2b 三个驱动都已实现：

| 驱动 | 机制 | 状态 |
|---|---|---|
| Postgres | `select set_config('statement_timeout', …)` | 已对真库验过（含真取消） |
| MySQL | `MAX_EXECUTION_TIME` hint | 按契约写完，等 P2b Task 7 门禁 |
| ClickHouse | `max_execution_time` setting | 同上 |

超时表现为驱动抛 `QueryTimeout`，执行流把它映射成 `QUERY_TIMEOUT`（§7.3）。

**库侧超时失效是驱动层的 bug，该在驱动层修。** 契约测里 `test_execute_raises_query_timeout` 就是它的守卫（P2b 已有，对 Postgres 真跑过）。在执行器里盖一层假兜底会让那个 bug 变得不可见。

**一处诚实的局限**：如果驱动卡在**连接阶段**（P2b 的 `_CONNECT_TIMEOUT_SECONDS = 10`），那 10 秒既不受闸 4 的 60s 管、也不产生 `QueryHandle`（还没下发语句），所以那 10 秒内 `DELETE` 取消不了任何东西——`cancel_run()` 会返回 `False`（注册表里没有这条 run）。这是可接受的：10 秒有上限、且没有查询真的在跑，没有「拖垮生产库」的风险。但 `DELETE` 在这个窗口里返回什么要定清楚（§7.4）。



## 4. SSE 生成器里的并发边界

执行流是 `async def` 生成器。FastAPI 对 `async def` 路由**不**用 threadpool，所以生成器直接跑在事件循环上——里面每一个同步调用都会阻塞循环。

| 调用 | 怎么办 | 理由 |
|---|---|---|
| `driver.execute()` / `driver.cancel()` | **必须 `asyncio.to_thread`** | 可能几十秒。阻塞循环会让同一个进程里所有其他请求（含 `DELETE` 取消！）全部卡死——那会让取消功能在最需要它的时候不可用 |
| `session.add/flush/commit`、`append_event`、仓储读写 | **直接调，不 to_thread** | 见下 |
| `validate_sql()` | 直接调 | 纯 CPU，sqlglot 解析一条语句是微秒级 |

**DB 写不 to_thread 的理由不是「快」，是「安全」**：SQLAlchemy 的 `Session` **不是线程安全的**，把它扔进 `to_thread` 意味着同一个 session 被事件循环线程与工作线程交替使用，那是一个真实的正确性风险（静默的数据错乱，不是异常）。而收益是本机 Postgres 单行写入的亚毫秒阻塞——在单机私有化部署的并发量下不可观察。

**用一个真实的风险换一个不可观察的收益，是错的方向。**

`DELETE` 端点里的 `driver.cancel()` 同样要 `to_thread`：它要另开一条连接，慢的话会把取消请求自己卡住。



## 5. 一个 run 恰好执行一次

`runs` 表里 `final_sql` / `effective_sql` / `row_count` / `duration_ms` / `executed_at` / `error_code` 都是**单列**——一个 run 只装得下一次执行。所以：

**已经离开 `drafted` 的 run 再 POST execute → `409 RUN_NOT_EXECUTABLE`。**

```
drafted  ──POST execute──> running ──┬─> succeeded
   │                                  ├─> failed
   │                                  ├─> cancelled
   └──validate 不通过───> blocked     
```

`drafted` 是唯一可执行的状态。`running` / `succeeded` / `failed` / `cancelled` / `blocked` 一律 409。

三个收益：

1. **审计记录不可改写**（F-304）。上一次执行的 SQL 与行数不会被静默覆盖。
2. **双击运行按钮的防护是免费的**——第二次请求打在 `running` 上，409。不需要前端做防抖，也不需要额外的锁。
3. **状态机只有一个方向**，回放/重跑不需要考虑「run 被跑了三次，哪次是哪次」。

代价：「改了 SQL 再跑」必须**建新 run**。那属于 P3c（问答流创建 run）与 P4（前端在重跑时发起新的 ask 或新 run），本段不做。上游 spec §3.5 的回放说「运行按钮文案变『重跑』」——那是「装回工作区 + 重新走一遍流程」，与「重复执行同一个 run」不是一回事。

**`blocked` 也不允许重试**，尽管它没有真的执行过。理由：`blocked` 说明用户提交的 SQL 被 guard 拒了，而改完 SQL 再提交是一次**新的**批准动作（F-303 的闸门），应该留下新的痕迹。让它可重试等于允许「同一个 run 上反复试探 guard」而只留最后一次的记录。

### 5.1 并发保护靠 DB 而不是靠检查

`drafted → running` 的转换用**带条件的 UPDATE**，不是「先 SELECT 判断状态再 UPDATE」：

```sql
update runs set status = 'running', ... where id = :id and status = 'drafted'
```

`rowcount == 0` 即表示「它已经不是 drafted 了」→ 409。check-then-update 在两个并发请求下会双双通过检查（P2a 的仓储也是因为同一个理由用 `insert + IntegrityError` 而不是 check-then-insert）。



## 6. 授权：新依赖 `require_run`

路径参数是 `run_id`，而既有的 `require_datasource` 是按 `datasource_id` 取的，所以需要一个新依赖。

**执行一个 run 需要三条同时成立**：

| 条件 | 为什么 | 不满足时 |
|---|---|---|
| 是这个 run 的所有者（`run.user_id == current_user.id`） | 提交的是「我的编辑器内容」，结果写进「我的 run」。别人代跑我的 run 会让 `runs.user_id` 与实际执行者不一致，而那一列是审计的主体（spec §4.6 的 who） | 404 |
| 对 `run.datasource_id` 有 `can_query` | 授权可能在 run 创建**之后**被撤销。不重新检查等于给了一条绕过 `datasource_grants` 的路 | 403 |
| 角色不是 `viewer` | 上游 spec §4.2 明写「viewer 只看历史，**不能执行**」 | 403 |

第三条**不被第二条覆盖**——一个 viewer 完全可以有 `can_query` 授权（grants 表不区分角色）。漏了它，viewer 就能执行查询。

### 6.1 不存在的 run 与别人的 run 都是 404

不是 403。理由与 P2a 的数据源可见性一致：**用 403 区分「不存在」与「存在但不属于你」会泄露「这个 id 存在」这个事实**，而 run id 是 uuid、可枚举性低但没必要主动确认。

这与 `require_datasource` 的做法**有意不同**（那里存在但无权限是 403）：数据源是**共享资源**，一个 analyst 知道「有这么个数据源但我没被授权」是合理的、也是他去找管理员要授权的前提。run 是**私有资源**，不存在这个诉求。

### 6.2 `GET`/`DELETE` 的授权与 `POST` 相同

`DELETE /api/runs/{run_id}/execute` 吃同一个 `require_run`——取消别人的查询和执行别人的 run 一样不该允许。**admin 也不例外**：他要停掉一条跑飞的查询，正确的路径是去数据库侧 kill，而不是在应用里给自己开一个能操作别人 run 的后门。这一条要写明，否则「admin 应该能管一切」的直觉会让它在某次评审里被"修复"。



## 7. 执行流的事件序列

### 7.1 SSE 格式

```
event: validate
data: {"ok": true}

```
每个事件三部分：`event: <名字>` 行、`data: <紧凑 JSON>` 行、一个空行。`media_type="text/event-stream"`。

**`data` 恒为一行 JSON**，不做多行 `data:`：SSE 允许多行，但那需要接收端拼接，而我们的载荷都是小 JSON。一行的代价是长 SQL 会让那一行很长，可接受。

### 7.2 成功路径的完整序列

| # | 事件 | 载荷 | 同时做的事 |
|---|---|---|---|
| 1 | `validate` | `{ok: true}` | `append_event(seq=1, step="validate", status="ok")` + **commit** |
| 2 | `log` | `{step: "validate", status: "ok", duration_ms}` | 上一条 `run_event` 的实时投影，见 §7.5 |
| 3 | `execute.started` | `{dialect, effective_sql}` | run → `running`，`final_sql` / `effective_sql` / `executed_at` 落库 + **commit**；注册表登记 |
| 4 | `ping` | `{}` | 每 15s 一次，直到结果回来（见 §7.6） |
| 5 | `result` | `{columns, rows, row_count, truncated}` | `run_result_previews` 落库（≤100 行） |
| 6 | `chart_spec` | `{type, x, y, reason}` | 纯函数推断（§8） |
| 7 | `log` | `{step: "execute", status: "ok", duration_ms}` | `append_event(seq=2, step="execute")` |
| 8 | `log` | `{step: "render", status: "ok", duration_ms}` | `append_event(seq=3, step="render")` |
| 9 | `done` | `{status: "succeeded", duration_ms, row_count}` | run → `succeeded` + `row_count` / `duration_ms` + **commit** |

`understand` 与 `generate` 两个 step（上游 spec §2.3 的 `step` 枚举里有）属于问答流，**本段不产生**。

### 7.3 失败路径

| 触发 | 事件 | run 状态 | 错误码 |
|---|---|---|---|
| guard 判定 `ok=false` | `validate{ok:false, code, reason}` → `done` | `blocked` | guard 给的（`WRITE_BLOCKED` / `SQL_PARSE_ERROR` / `MULTIPLE_STATEMENTS`） |
| 连不上 | `error` → `done` | `failed` | `CONNECTION_ERROR` |
| 库侧超时 | `error` → `done` | `failed` | `QUERY_TIMEOUT` |
| 被取消 | `error` → `done` | `cancelled` | `QUERY_CANCELLED` |
| 库拒绝执行（语法/权限/表不存在） | `error` → `done` | `failed` | `QUERY_FAILED` |

**`validate` 不通过时不发 `error`**，只发 `validate{ok:false}` 然后 `done`——上游 spec §2.3 明写「`ok=false` 时流即结束」。判定失败不是异常，它是这条流的一个正常出口（与 P3a 的 `/sql/validate` 返回 200 同一个道理）。

**每条流都以 `done` 结尾**，包括失败。前端只需要一个终止信号，不用分别处理「收到 error 就不会再有 done 了」这种分支。

### 7.4 五个错误码：三个首次落地，两个新增

```python
QUERY_TIMEOUT = ("QUERY_TIMEOUT", "查询超时，请缩小时间范围或增加过滤条件", 504)
QUERY_CANCELLED = ("QUERY_CANCELLED", "查询已取消", 499)
QUERY_FAILED = ("QUERY_FAILED", "数据库拒绝执行该查询", 400)
RUN_NOT_EXECUTABLE = ("RUN_NOT_EXECUTABLE", "该查询已执行过或正在执行", 409)
RUN_NOT_FOUND = ("RUN_NOT_FOUND", "查询记录不存在", 404)
```

上游 spec §2.6 已列 `QUERY_TIMEOUT` / `QUERY_CANCELLED` / `RUN_NOT_FOUND` 三个（本段首次落地），`QUERY_FAILED` 与 `RUN_NOT_EXECUTABLE` 是新增，要回填。

`QUERY_FAILED` 的 message 里**带库的原始错误文本**——这是 P2b 的 `QueryFailed` 刻意保留原文的原因（「分析师要靠它改 SQL」）。它与 §4.4 的「错误消息不含结构信息」**不冲突**：那条针对的是连接类错误（可能含地址端口），而这里的原文是用户自己写的 SQL 在库上的报错，正是他需要看到的。**这处张力要写明**，否则某次安全评审会把它抹掉。

`499` 不是标准 HTTP 状态码（nginx 的扩展），但这两个码只出现在 SSE 的 `error` 事件载荷里，**不作为 HTTP 状态返回**——流已经是 200 了。状态码那一栏在这里只用于 `ApiError` 元组的形状一致，以及万一将来有非 SSE 的调用方。

### 7.5 `log` 事件与 `run_events` 是同一件事的两面

上游 spec §2.3 的 `log` 载荷是 `{step, status, duration_ms, detail?}`——**与 `run_events` 表的列完全一致**。所以 `log` 事件就是一条 `run_event` 的实时投影：

```python
def emit_event(...):        # 一次调用做两件事
    event = append_event(session, run_id=..., seq=next_seq(), step=..., ...)
    session.commit()
    return sse("log", {"step": ..., "status": ..., "duration_ms": ...})
```

**一个写入点、一个格式**。分开写会让「日志 Tab 看到的」与「回放看到的」有可能不一致，而上游 spec §3.5 说日志 Tab 就是「按 `run_events` 的 step 逐行渲染」——它们本来就该是同一份数据。

`detail` **不放结果行内容**（spec §4.6），只放 `row_count` 之类的标量。

### 7.6 `ping` 的实现

每 15s 发一次 `{}`，直到结果回来。实现是 `asyncio.wait([execute_task], timeout=15)` 的循环——**不是**一个独立的心跳协程：独立协程需要额外的同步来保证「结果回来后不再发 ping」，而 `wait` 的超时循环天然做到这一点。

上游 spec §2.3 明写「驱动普遍不提供进度，**不假装有进度条**」——所以 `ping` 的载荷是空的 `{}`，不带任何百分比或「已扫描 N 行」。那些数字驱动给不出来，编出来就是骗人。



## 8. `chart_spec` 规则推断

上游 spec §3.5 已经给了规则：「1 维度 + 1 度量 → 柱状；含时间维度 → 折线；2 度量 → 散点；单值 → 大数字卡」。本节只把它落成确定的判定顺序并补齐 spec 没覆盖的边界。

### 8.1 判定顺序（自上而下，第一个命中即返回）

| # | 条件 | `type` | `reason` |
|---|---|---|---|
| 1 | 0 行 | `table` | 没有数据可画 |
| 2 | 1 行 1 列且是数值 | `metric` | 单值 → 大数字卡 |
| 3 | 有时间列 且 ≥1 度量 | `line` | 含时间维度 → 折线 |
| 4 | 恰好 1 个非数值列 + 恰好 1 个数值列 | `bar` | 1 维度 + 1 度量 |
| 5 | 0 个非数值列 + 恰好 2 个数值列 | `scatter` | 2 度量 |
| 6 | 其余 | `table` | 兜底 |

**时间优先于度量个数**（规则 3 在 4、5 之前）：1 时间列 + 2 度量 → 折线（两条线），而不是散点。理由是 spec §3.5 把「含时间维度」写成独立一条，且时间序列画散点几乎总是错的。

**「度量」= `ColumnSchema.is_numeric`**，那是 P2b 的驱动给的（`QueryResult.columns`），不在这里重新猜类型。这也是 p3a1 那个 `regtype` vs `format_type` 的坑为什么重要——`is_numeric` 错了，选图就跟着错，而且不报错。

**「时间列」的判定**：`data_type` 归一化后（小写）含 `date` / `time` / `timestamp`。这是字符串匹配，不够严谨（一个叫 `timezone_name` 的文本列会被误判为时间），但：
- 驱动没有 `is_temporal` 标记，加一个要改 P2b 的协议与三个驱动；
- 误判的后果是「图表类型选错了」，而 spec §3.5 明写「用户可手动改类型与字段（F-402 AC2）」——有出口。

**取舍写明**：如果 V2-3 换 LLM 选图（spec §6 说直接替换该函数），这个字符串匹配就一起消失了；在那之前它是一个有已知误判、有用户出口、且不影响正确性的启发式。**不为它加协议字段。**

### 8.2 `x` 与 `y` 怎么填

- `line` / `bar`：`x` = 那个维度列名（时间列优先），`y` = 全部数值列名。
- `scatter`：`x` = 第一个数值列，`y` = `[第二个数值列]`。
- `metric`：`x = None`，`y = [那一列]`。
- `table`：`x = None`，`y = []`。

### 8.3 纯函数，不设接口

`infer_chart_spec(columns: tuple[ColumnSchema, ...], row_count: int) -> ChartSpec`。

上游 spec §6 明写「`ChartSpec` 不设接口——V2-1 的规则推断是纯函数，V2-3 要换成 LLM 选图时直接替换该函数，加一层抽象是过早的」。照办：一个函数、一个 frozen dataclass，不要 `ChartInferrer` 协议。

**输入只有列信息与行数，不含结果行**。选图不需要看数据本身，而不把行传进去就使这个函数天然不可能把结果行写进日志（spec §4.6）。



## 9. 结果预览落库

上游 spec §2.5：`run_result_previews(run_id pk, columns jsonb, rows jsonb, truncated bool)`，注释是「只存前 100 行摘要，不存全量快照；回放时重跑取全量」。

### 9.1 100 行是预览的上限，与闸 3 的 1000 行是两回事

| 上限 | 值 | 谁定 | 作用 |
|---|---|---|---|
| 闸 3 的 `max_rows` | `Settings.max_result_rows`（默认 1000） | guard 注入 LIMIT + 驱动 `truncate()` | 限制**从库里取回**多少行 |
| 预览上限 | **100**（`Settings.preview_rows`，新增） | 本段 | 限制**存进 `run_result_previews` 与发给前端**多少行 |

所以一次执行可能取回 1000 行、预览只存/发前 100 行，而 `row_count` 报的是取回的行数（1000），`truncated` 报的是**驱动那一层是否发生了截断**（即库里其实有 >1000 行）。

**三个数不能混**。`result` 事件的 `row_count` 与 `truncated` 直接来自 `QueryResult`（驱动给的），`rows` 是 `result.rows[:100]`。前端据 §3.5 显示「已显示前 100 行，共 N 行」，那个 N 就是 `row_count`。

**这处很容易写错成「`truncated` 表示前端只看到 100 行」**，那会让一次返回 50 行的查询也显示「已截断」。要有测试钉住：取回 200 行（<1000，`truncated=False`）时，`rows` 长度是 100 而 `truncated` 仍是 `False`。

### 9.2 JSON 序列化

`rows` 是 `tuple[tuple[Any, ...], ...]`，里面可能有 `datetime` / `Decimal` / `date` / `bytes`——`json.dumps` 不认它们，而 JSONB 列要的是可序列化的值。

统一转换：`datetime`/`date` → ISO 字符串，`Decimal` → `float`，`bytes` → base64 字符串，其余原样。

**`Decimal → float` 会丢精度**，这是有意的：预览是给人看的（和画图用的），而 JSON 没有十进制类型；前端拿到字符串又得自己解析。全量导出（P3d 的 `export.csv`）走**重跑 + 流式写出**，不经过这个转换，所以精度在需要它的路径上是完整的。这条要写明——否则有人会为了「精度」把它改成字符串，然后前端的图表就画不出来了。

### 9.3 `columns` 存什么

`[{name, type, is_numeric}]`——与 `result` 事件的 `columns` 同形（上游 spec §2.3 的载荷定义）。**不存 `is_nullable` 与 `comment`**：预览是结果的摘要，不是 schema 元数据，那些在 `/schema` 端点（P2c）。



## 10. 文件落点与模块边界

### 10.1 新建

| 文件 | 职责 | 规模 |
|---|---|---|
| `execution/executor.py` | `execute_approved(...)`：`to_thread` 包驱动 + 注册表登记 + 异常翻译。**安全红线，≤200 行**（spec §1.4 点名） | ≤200 |
| `execution/registry.py` | 进程内 `run_id → RunningQuery` + `cancel_run()` | 小 |
| `execution/charts.py` | `infer_chart_spec()` 纯函数 + `ChartSpec` | 小 |
| `execution/preview.py` | `QueryResult` → 可存 JSONB 的 `columns`/`rows`（含类型转换） | 小 |
| `execution/sse.py` | `sse(event, data) -> bytes` 一个函数 | 极小 |
| `runs/repository.py`（**改**） | 加 `get_run` / `mark_running` / `mark_finished` / `save_preview` | — |
| `api/run_router.py` | `POST` / `DELETE /api/runs/{run_id}/execute` | — |
| `runs/deps.py` | `require_run` | 小 |

### 10.2 为什么 `execution/` 是独立顶层包

它是**唯一**同时认识 guard、驱动、与 run 状态的地方。放进 `runs/`（那是持久化）或 `api/`（那是 HTTP 编排）都会让「执行」这件事没有自己的家。

`executor.py` 与 `guard/validator.py` 是 spec §1.4 点名的**两个**安全红线文件，都要 ≤200 行、只做一件事。所以注册表、图表推断、预览转换、SSE 格式化各自分文件——它们都不是执行本身。

### 10.3 依赖方向

```
api/run_router.py  ──> execution/*  ──> datasources/{connection,deps,drivers}
       │                    │      ──> guard/validator
       │                    └────── > runs/repository
       └──> runs/deps ──> runs/repository
```

`execution/` **不 import fastapi**（除了它不需要——`Request.is_disconnected()` 在 router 里读，取消的触发在 router，`cancel_run()` 只收 run_id）。这让执行器与注册表能脱离 HTTP 测。

`registry.py` 的文件头必须写明「单进程前提」（§1.4）。

### 10.4 `runs/repository.py` 加的四个函数与 append-only 不冲突

`run_events` 仍然只有 `append_event` / `list_events`。新增的四个动的是 `runs` 与 `run_result_previews` 两张表——**它们不是 append-only 的**（run 的状态本来就要从 `drafted` 变到终态）。

p3a2 那条扫模块导出名的测试（禁 `update`/`delete` 字样）**要相应调整**：它守的是「`run_events` 没有 update 路径」，而 `mark_running` / `mark_finished` 是 `runs` 的更新。改成显式的白名单式断言（列出允许的函数名）而不是关键词黑名单——黑名单会因为一个叫 `update_run_status` 的合法函数而误报，而那时最省事的"修复"是删掉这条测试。



## 11. 测试策略

上游 spec §5.1 点名执行器是要「穷举边界」的两个模块之一（另一个是 guard，P3a 已做）。

### 11.1 三层

| 层 | 用什么 | 覆盖 |
|---|---|---|
| 纯函数 | 无夹具 | `infer_chart_spec` 的六条判定分支 · `preview` 的类型转换 · `sse()` 的格式 |
| 领域层 | `db_session` + 假驱动 | `execute_approved` 的成功/超时/取消/失败四条路径 · `cancel_run()` · 状态机与 409 · **失败路径的审计落库**（§2.3） |
| 端点层 | `TestClient.stream()` + 假驱动 | 事件序列、鉴权、`DELETE` 触发取消 |
| **真库** | `demo_sales` + 真 Postgres 驱动 | 一条真查询跑通 · **真超时** · **真取消**（`DELETE` 触发） |

真库那一层是本段的**退出标准**：spec §4.3 闸 4 的「真取消」不能只用假驱动验——假驱动的 `cancel` 是一个被记录的调用，而真取消要证明**库侧的查询真的死了**。

### 11.2 真库测试怎么写

`demo_sales` 在应用库里，所以不需要 Docker。用 `pg_sleep(30)` 造一条慢查询（P2b 的契约测夹具已有同样的手法）：

1. **真超时**：`timeout_seconds=2` + `select pg_sleep(30)` → 2 秒后拿到 `QUERY_TIMEOUT`，且**总耗时 < 5 秒**（断言这一点才能证明是库侧超时生效，而不是等 30 秒跑完）。
2. **真取消**：起执行流 → 拿到 `execute.started` 后调 `DELETE` → 断言流以 `QUERY_CANCELLED` 结束，**并且在另一条连接上查 `pg_stat_activity` 确认那个 backend 已经不在跑那条语句了**。

第 2 条的后半句是关键。只断言「流结束了」证明不了取消——`task.cancel()` 单独就能让流结束，而查询还在跑（§1.1）。**必须去库里看。**

### 11.3 「客户端断开」这条触发器无法自动化测

**实测**：`TestClient` 下 `Request.is_disconnected()` **恒为 `False`**。客户端只读 3 行就退出 `stream` 上下文，服务端仍把 50 次循环全跑完：

```
服务端 tick 了 50 次（共 50 次机会）
is_disconnected 在第 None 次循环变 True
```

TestClient 走 ASGI 的内存传输，客户端提前退出不产生 `http.disconnect` 消息。所以：

- **`cancel_run()` 本身**：领域层测试全覆盖（造 run + 假 handle，断言驱动 `cancel` 被调、状态与事件落库）。
- **`DELETE` 触发器**：端点测试 + 真库测试都覆盖。
- **断开触发器**：**不在回归套件内**。用一次 `uvicorn` + 客户端中断的真跑验证，结果写进实施偏差。

这个分工是「拆解 + 一次真跑」的取舍：把取消动作抽成 `cancel_run()` 之后，未覆盖的只剩「`is_disconnected()` 变 True 时会调它」这一行代码，而它的两个组成部分（检测、动作）各自都被验过。**如实标注它不在回归套件内**，不假装覆盖了。

引入一个起 uvicorn 子进程的夹具能覆盖它，但那个夹具（端口分配、进程生命周期、Windows 上的信号语义）比它守的那一行代码脆得多，会成为一个长期的 flaky 来源。

### 11.4 假驱动的形状

只实现 `execute` 与 `cancel`（本段唯一调的两个）。缺 `probe` / `reflect` 是**故意**的——执行流若调了它不该调的方法会以 `AttributeError` 暴露（与 P2b `/test`、P2c `/schema` 的假驱动同形）。

假驱动要能演四种行为：正常返回、抛 `QueryTimeout`、抛 `QueryFailed`、以及**阻塞直到被 cancel**（用一个 `threading.Event` 等待，`cancel()` 里 set 它然后抛 `QueryCancelled`）。第四种是取消路径的关键——它必须真的在线程里阻塞，否则测不到「to_thread 还没返回时 DELETE 进来了」这个时序。

### 11.5 反向验证要覆盖的

1. **去掉 `driver.cancel()` 只留 `task.cancel()`** → 真库取消测试的「`pg_stat_activity` 里没有那条语句」转红，而「流以 `QUERY_CANCELLED` 结束」**保持绿**。这一对是本段最重要的反向验证：它证明了 §1.1 那个实测结论落进了测试。
2. **把四个 `commit()` 去掉，改回依赖 `get_db`** → §2.3 那条「失败路径的审计落库」转红，而成功路径的全部测试**保持绿**。
3. **`mark_running` 改成 check-then-update** → 并发 409 那条转红（若测得到）；至少要能证明带条件的 UPDATE 的 `rowcount` 分支被走到。
4. **`chart_spec` 的时间优先规则去掉**（把规则 3 挪到 4、5 之后）→ 「1 时间 + 2 度量 → line」转红，其余五条分支保持绿。
5. **预览的 `rows[:100]` 改成 `rows`** → §9.1 那条「200 行时 rows 是 100 而 truncated 仍 False」转红。
6. **`unregister` 从 `finally` 里挪到成功路径上** → 失败/取消后注册表泄漏，要有一条测试断言「执行结束后注册表为空」（三种终态各一次）。



## 12. 与上游 spec 的偏离，以及要回填的东西

### 12.1 有意偏离与补充（四处）

| 上游原文 | 本份的做法 | 理由 |
|---|---|---|
| §2.6 错误码表 | 新增 `QUERY_FAILED` 与 `RUN_NOT_EXECUTABLE` | 前者是「库拒绝执行」（与超时/取消/连不上都不同，且要带库的原文）；后者是 §5 的一次性语义 |
| §2.3 未定义 run 的幂等性 | **恰好执行一次**，非 `drafted` 一律 409 | §5：`runs` 的结果字段是单列，多次执行会改写审计记录 |
| §2.3 未定义执行的授权 | 所有者 + `can_query` + 非 viewer，且不存在与非本人都是 404 | §6 |
| §2.5 `run_result_previews` 的「前 100 行」 | 100 成为 `Settings.preview_rows` | 与闸 3 的 `max_result_rows` 是两个不同的上限（§9.1），配置项分开才说得清 |

**要回填进上游 spec**：§2.6 加两个错误码；§2.3 补一句 run 的一次性语义与执行授权；§2.5 的 `run_result_previews` 注释里点明「100 与闸 3 的 1000 是两个上限」。

### 12.2 已知的松散端与取舍

- **注册表是进程内的**（§1.4）。多 worker 部署下取消会静默失效。写进部署文档 + 注册表模块的文件头。
- **闸 4 不加 asyncio 层兜底**（§3）。库侧超时失效时没有第二道防线——那是有意的，因为第二道防线停不住线程。
- **连接阶段的 10 秒窗口内取消不了任何东西**（§3 末）。有上限、无查询在跑，可接受。
- **`chart_spec` 的时间列判定是字符串匹配**（§8.1），已知会误判 `timezone_name` 这类列名。有用户出口（可手动改图型），不为它改 P2b 的驱动协议。
- **预览的 `Decimal → float` 丢精度**（§9.2）。全量导出走重跑，精度在需要它的路径上完整。
- **「客户端断开」触发器不在回归套件内**（§11.3）。
- **`ping` 的载荷是空的**，不假装有进度（上游 spec §2.3 明写）。
- **本段结束时 `runs` 仍然没有创建路径**——run 由 P3c 的问答流创建，本段的测试自己造 run。所以 P3b 交付后**这条链路还不能从界面走通**，要等 P3c。这是分段交付的常态（与 P2b 的 `execute()` 没有生产调用方同形），但它意味着 P3b 的验收只能靠测试与真库跑，没有「点一下看看」的路径。



## 13. 交接清单（P3c / P3d 要消费的签名）

```python
# 执行（chatbi.execution）
executor.execute_approved(driver, info: ConnectionInfo, *, run_id, effective_sql: str,
                          timeout_seconds: int, max_rows: int) -> QueryResult
#   内部：to_thread 包 driver.execute()，on_start 回调里登记注册表，finally 里 unregister。
#   抛 QueryTimeout / QueryCancelled / QueryFailed / ConnectionFailed（P2b 的四个）

registry.cancel_run(run_id) -> bool          # 唯一的取消入口。返回是否真取消了
registry.is_running(run_id) -> bool

charts.infer_chart_spec(columns, row_count) -> ChartSpec    # 纯函数
ChartSpec(type, x: str | None, y: tuple[str, ...], reason: str)

preview.to_preview(result: QueryResult, *, limit: int) -> tuple[list, list, bool]
#   -> (columns_json, rows_json, truncated)。rows 截到 limit；truncated 来自
#      QueryResult（**驱动那一层是否截断**），不是「预览是否截断」

# 持久化（chatbi.runs.repository）
get_run(session, run_id) -> Run | None
mark_running(session, run_id, *, final_sql, effective_sql) -> bool
#   带条件的 UPDATE（where status='drafted'）。返回 False 即「它已不是 drafted」-> 409
mark_finished(session, run_id, *, status, row_count=None, duration_ms=None,
              error_code=None) -> None
save_preview(session, run_id, *, columns, rows, truncated) -> RunResultPreview
append_event / list_events                   # P3a 已有，仍然只有这两个

# 依赖（chatbi.runs.deps）
require_run(run_id, db, user) -> Run         # 所有者 + can_query + 非 viewer，否则 404/403

# 端点
POST   /api/runs/{run_id}/execute  -> 200 SSE | 401 | 403 | 404 | 409
DELETE /api/runs/{run_id}/execute  -> 204 | 401 | 403 | 404
```

**P3c 问答流**
- 建 run 时 `status='drafted'`、写 `question` / `chips` / `generated_sql` / `llm_provider` / `llm_model`。**`final_sql` 与 `effective_sql` 留空**——那两列由本段的执行流写。
- `run.generated_sql` **不经过 guard**（P3a 已写明）。guard 只在执行流上跑。
- 事件的 `seq`：问答流用 1..N（`understand` / `generate`），**执行流从 `max(seq)+1` 续**。所以 `emit_event` 要先查当前最大 seq 而不是从 1 硬起——本段的实现要按这个写，即使本段测试里 run 都是干净的。**这一条最容易在 P3c 接上时才炸**（`unique (run_id, seq)` 会拒绝重复的 1）。
- 「改了 SQL 重跑」= 建**新** run（§5）。要不要给它设 `parent_run_id` 由 P3c/P4 定——F-401 的下钻用的是同一列，混用会让「下钻链」与「重跑链」分不开，建议**重跑不设**。

**P3d 回放**
- `list_events()` 给回放的时间线，**按 seq 排序**（P3a 已实现）。
- `run_result_previews` 里的 `columns`/`rows` 是已经转换过的 JSON（§9.2 丢了 Decimal 精度）。回放展示用它；`export.csv` **重跑取全量**，别从预览里导。
- `runs.status` 的六个值都可能出现在历史列表里，`blocked` 与 `cancelled` 也要有对应的界面呈现。



## 14. 自查记录

**上游 spec 覆盖核对（本份负责的部分）**

| 上游条目 | 落在哪 |
|---|---|
| §2.3 请求体 `{sql}` 是编辑器内容，记为 `final_sql` | §7.2 第 3 行 |
| §2.3 八个事件（`validate`/`execute.started`/`ping`/`result`/`chart_spec`/`log`/`error`/`done`） | §7.2、§7.3 |
| §2.3「`ok=false` 时流即结束，run 置 `blocked`」 | §7.3 |
| §2.3「`effective_sql` 必须回显（可审计的前提）」 | §7.2 第 3 行的 `execute.started` |
| §2.3「每 15s 心跳，不假装有进度条」 | §7.6 |
| §2.3「客户端断开或 DELETE → cancel task **并**调驱动取消」 | §1（实测证明「并」是必须的） |
| §2.3「只关流不取消后端查询是错的」 | §1.1 + §11.2 的真库取消测试 |
| §2.5 `run_result_previews` 只存前 100 行 | §9 |
| §2.6 `QUERY_TIMEOUT` / `QUERY_CANCELLED` / `RUN_NOT_FOUND` | §7.4（首次落地，另新增两个） |
| §3.5 图表规则（柱状/折线/散点/大数字卡） | §8.1 |
| §3.5「只渲染前 100 行，超出显示共 N 行」 | §9.1 的三个数 |
| §4.3 闸 4 语句超时 + 真取消 | §3 + §1 |
| §4.6 审计 who/when/状态/错误码 · 不记结果行内容 | §2.3 四个提交点 · §7.5 的 `detail` 约束 · §8.3 的输入不含行 |
| §5.1 执行器穷举边界 | §11 |
| §6「`ChartSpec` 不设接口」 | §8.3 |

**不在本份的上游条目**：§2.2 问答流 · §4.5 LLM 边界 · §2.4 的历史/回放 REST · §4.3 闸 1（P2b 已完成）与闸 2/3（P3a 已完成）。

**歧义检查**：「100 行」与「1000 行」明确为两个上限、两个配置项（§9.1）。「`truncated`」明确为「驱动那一层是否截断」而非「预览是否截断」。「取消」明确为三件事且顺序固定（§1.2）。「一个 run 执行几次」明确为恰好一次（§5）。`log` 事件与 `run_events` 明确为同一份数据的两面（§7.5）。

**写作过程中的回改四处**

1. **§2 整节是写到「测试策略」时才补的**。初稿的执行流依赖 `get_db` 自动提交，写 §11 的「失败路径审计」用例时才想到「那条路径上 session 会被回滚吗」，跑了一个最小复现——**会**。这条如果漏掉，成功路径的测试全绿而失败路径的审计是空的，是本份最隐蔽的一个坑。
2. **§3 从「加 `asyncio.wait_for` 兜底」改成「不加」**。初稿写了兜底，写 §1.1 的实测结论时发现两者矛盾：既然 cancel 停不住线程，那 `wait_for` 超时后的行为就是「流结束、查询继续跑」——正是闸 4 要防的。删掉比留着诚实。
3. **§7.5 是发现 `log` 载荷与 `run_events` 列完全一致之后加的**。初稿把两者当成两件事（SSE 事件 vs 持久化），比对上游 spec §2.3 的载荷定义与 §2.5 的表定义才发现它们同形，而 §3.5 说日志 Tab 就是渲染 `run_events`——本来就该是一份数据。
4. **§13 里「执行流的 seq 从 `max(seq)+1` 续」是写交接清单时才想到的**。本段的测试里 run 都是干净的（没有问答流的事件），所以从 1 起也全绿；接上 P3c 之后 `unique (run_id, seq)` 会拒绝重复的 1，而那时报错出现在执行流里、看起来像本段的 bug。**这类「本段测不出、下段才炸」的耦合要在交接清单里点名**，P2c 的 `known_identifiers` 与 P2b 的 `execute()` 都是同一类。

**规模自查**：`executor.py` 要在 200 行内装 `to_thread` 调用 + 注册表登记 + 四类异常翻译 + `on_start` 回调。估算 60 行代码 + 60 行注释，宽裕。真正的风险在 `api/run_router.py`——SSE 生成器 + 事件序列 + 四个提交点 + 异常映射容易膨胀。spec §1.4 没点名它，但如果超过 250 行，应该把「事件序列的编排」抽成 `execution/stream.py`（生成器）而 router 只做鉴权与响应包装。**这一条留给实施期判断**，写计划时按不抽来估。

