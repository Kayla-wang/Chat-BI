# Chat-BI

![TypeScript](https://img.shields.io/badge/TypeScript-5.4-3178C6?logo=typescript&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Vite](https://img.shields.io/badge/Vite-5-646CFF?logo=vite&logoColor=white)
![Express](https://img.shields.io/badge/Express-4-000000?logo=express&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-better--sqlite3-003B57?logo=sqlite&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama-000000?logo=ollama&logoColor=white)
![ECharts](https://img.shields.io/badge/Charts-ECharts_5-AA344D)
![Vitest](https://img.shields.io/badge/tested_with-Vitest-6E9F18?logo=vitest&logoColor=white)

本地运行的对话式 BI:自然语言提问 → 本地 Ollama 生成只读 SQL → 查询 SQLite → 返回 ECharts 图表。数据不出本机,SQL 经白名单校验。TypeScript 全栈 monorepo(Express + SSE / React + Vite)。

- **完全离线**:LLM 跑在本地 Ollama,数据留在本地 SQLite,不需要任何云端 API key。
- **只读兜底**:生成的 SQL 必须是 `SELECT` / `WITH ... SELECT`,禁堆叠查询、禁注释、禁写入与 DDL 关键词,自动注入 `LIMIT` 并加查询超时;执行走只读连接。
- **自动纠错**:JSON 解析失败、SQL 校验不通过或执行报错时,带着错误原因重试一轮再放弃。
- **图表先落地,洞察后写**:结果与图表一次性下发立刻渲染,洞察文本由第二轮 LLM 真流式逐字写出;第二轮失败只降级洞察,不影响图表。
- **开箱即跑**:首次启动自动建表并灌入示例订单数据,不用自备数据源;界面跟随系统深浅色。

## 运行

需要 Node 20+(`better-sqlite3` 12 的下限,本机 v24)与本地 Ollama。

1. 拉模型:`ollama pull qwen3:8b`。Windows 下装完 Ollama 服务已随托盘常驻 11434,不用手动 `ollama serve`
2. `npm install`
3. 后端:`npm run dev --workspace=apps/backend`(http://localhost:5174)
4. 前端:`npm run dev --workspace=apps/frontend`(http://localhost:5173)

模型默认值是 `llama3.1`,但验收问题全是中文,换 `qwen3:8b` 一类中文更强的模型出 SQL 更稳,用 `OLLAMA_MODEL` 指定。

第一轮 LLM(出 SQL)不可缺:Ollama 不可用时整轮直接返回 `error`,图表出不来;只有第二轮洞察会降级(见验收清单第 8 条)。

`DB_PATH` 默认是相对路径,后端必须以 `apps/backend` 为工作目录启动 —— 上面的 `--workspace=` 命令即可;从仓库根直接 `tsx apps/backend/src/server.ts` 会在根目录另建一个空库重新灌数据。根目录的 `npm run dev` 用 `&` 同时起两个进程,只在 bash 下有效,PowerShell/cmd 请开两个终端。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `PORT` | `5174` | 后端监听端口;前端用 `BACKEND_PORT`(回落到 `PORT`)决定 `/api` 代理指向 |
| `DB_PATH` | `./data/chatbi.db` | SQLite 示例库路径(首次启动自动建表 + 灌示例数据) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama 服务地址 |
| `OLLAMA_MODEL` | `llama3.1` | 使用的模型 |
| `QUERY_TIMEOUT_MS` | `5000` | 单次查询超时 |
| `ROW_LIMIT` | `1000` | 返回行数上限(自动注入 `LIMIT`) |
| `INSIGHT_TIMEOUT_MS` | `8000` | 洞察生成(第二轮 LLM)超时,超时降级为模板文本 |

配置直接读 `process.env`,没有接 dotenv —— `.env` 文件不会被加载,临时覆盖写在命令前:

```bash
OLLAMA_MODEL=qwen3:8b INSIGHT_TIMEOUT_MS=30000 npm run dev --workspace=apps/backend
```

纯 CPU 推理时第二轮洞察几乎必然撞上 `INSIGHT_TIMEOUT_MS` 降级成模板文本,先调到 30000 以上再判断洞察功能是否正常。

后端端口被占用时(常见于本机同时跑别的 Vite 项目)换一个,两个进程用同一个变量即可:

```bash
PORT=5175 npm run dev --workspace=apps/backend
PORT=5175 npm run dev --workspace=apps/frontend   # vite 只读它来定代理目标,自身仍是 5173
```

前端 dev server 端口固定 5173,若被占用 Vite 会自动往上找(5174、5175……),看它启动时打印的地址。

## 结构

```
apps/backend      Express + SSE:promptBuilder → sqlGuard → dbClient → chartSpec/facts → insightWriter
apps/frontend     React + Vite:AppShell / ChatWindow / ResultCard(图表·表格·SQL)/ InsightPanel
packages/shared   契约与纯函数:types(ChartSpec、StreamEvent)、format、renderer(ChartSpec → ECharts option)、facts
docs/superpowers  设计 spec 与实施计划
```

一次问答的事件流:`result`(图表 + 表格 + SQL 一次下发)→ `insightFacts`(后端纯函数算出的事实)→ `insightDelta` × N(第二轮 LLM 逐字)→ `done`;任一步出错发 `error`。图表以 `ChartSpec` 为单一来源,ECharts option 只在 `packages/shared/src/renderer.ts` 生成一处。

## 测试

```bash
npm test                               # 全仓 26 文件 / 267 测试(复用各工作区自己的配置)
npx vitest --root apps/backend run     # 后端 171
npx vitest --root apps/frontend run    # 前端 67
npx vitest --root packages/shared run  # 共享 29
```

测试不需要 Ollama,也不需要真实网络:`fetch` 与 llm 依赖都是注入的桩。

Windows 下偶发 `No test suite found in file ...`(文件被收集到但报 0 个测试):vitest 1.6 worker 收集阶段的 flake,与并发/机器负载相关 —— 观测到的失败都发生在有其它进程同时跑 vitest 的时候,且失败那次 collect 耗时是正常值的两倍以上。不是代码问题,单独重跑一次即可,尽量别让两个 vitest 进程并行。

## 手动验收清单

发版前依次问,人工确认图表类型、数据与洞察:

1. 「按月统计订单金额」→ 折线图,x 轴按月排序,洞察提到趋势百分比
2. 「各产品类别销售额占比」→ 饼图,洞察提到头部占比
3. 「各地区订单总额对比」→ 柱状图
4. 「按月看各区域销售额」→ 多条折线,图例是区域名
5. 「各区域各类别销售额占比结构」→ 百分比堆叠柱状图,y 轴 0–100%
6. 三轮下钻:「按月统计订单金额」→「只看华东区」→「按周看」,每轮图表都正确变化
7. 「查询 1999 年的订单」→ 空表格 + 洞察「没有符合条件的记录」
8. 关掉 Ollama 后再问一次 → 图表仍渲染,洞察降级为模板文本(验证第二轮失败不影响第一轮)
9. 任意一轮展开「查看 SQL」与「计算依据」,核对 SQL 与洞察里的数字一致

## 界面

- 设计 tokens 集中在 `apps/frontend/src/theme/tokens.css`,组件通过 CSS 变量取色,不写颜色字面量。
- 深浅色跟随系统 `prefers-color-scheme`,不提供手动开关。
- 图表调色板取 Okabe-Ito 色觉友好色系派生(`theme/chartPalette.ts`),浅色深色各一套 8 色。
- 涨跌不用颜色表达——中式涨红跌绿与国际涨绿跌红相反,统一用文字说明,避免误读。
- 数字统一 `tabular-nums` 等宽对齐(表格、坐标轴、洞察)。

## 已知限制

- SQL 校验以只读数据库连接为根本防线;AST 校验(`node-sql-parser`,sqlite 方言)解析失败时回退到加固正则。实测示例库的全部验收查询(含 `strftime`、多表 JOIN + GROUP BY、`LIKE` 过滤)均走 AST 路径,未触发正则回退。
- 洞察文本由 LLM 措辞,数字由后端纯函数计算。若怀疑措辞与数字不符,展开「计算依据」核对。
- `seriesBy` 取值超过 12 个(`SERIES_BY_MAX`)时自动退化为单系列,并在图表下方标注。
- 第一轮 LLM 调用没有超时保护(`llmClient` 是裸 `fetch`),模型很慢时 SSE 会一直挂着、既不出图也不报错。只有第二轮洞察有 `INSIGHT_TIMEOUT_MS`;`QUERY_TIMEOUT_MS` 只管 SQLite 执行,与 LLM 无关。
- `npm run build` 只产出前端静态文件,后端只挂了 `/api/chat`、不托管它们,离开 Vite dev server 需要自己加静态服务或反向代理。
