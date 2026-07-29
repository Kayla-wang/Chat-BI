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
- **只读兜底**:生成的 SQL 必须是 `SELECT` / `WITH ... SELECT`,禁堆叠查询、禁写入与 DDL 关键词,自动注入 `LIMIT` 并加查询超时。
- **自动纠错**:JSON 解析失败、SQL 校验不通过或执行报错时,带着错误原因重试一轮再放弃。
- **图表先落地,洞察后写**:结果与图表一次性下发立刻渲染,洞察文本由第二轮 LLM 真流式逐字写出;第二轮失败只降级洞察,不影响图表。
- **开箱即跑**:首次启动自动建表并灌入示例订单数据,不用自备数据源。

## 运行

1. 启动 Ollama 并拉模型:`ollama serve` + `ollama pull llama3.1`(或设置 `OLLAMA_MODEL`)
2. `npm install`
3. 后端:`npm run dev --workspace=apps/backend`(默认 http://localhost:5174)
4. 前端:`npm run dev --workspace=apps/frontend`(http://localhost:5173)

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DB_PATH` | `./data/chatbi.db` | SQLite 示例库路径(首次启动自动建表 + 灌示例数据) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama 服务地址 |
| `OLLAMA_MODEL` | `llama3.1` | 使用的模型 |
| `QUERY_TIMEOUT_MS` | `5000` | 单次查询超时 |
| `ROW_LIMIT` | `1000` | 返回行数上限(自动注入 `LIMIT`) |
| `INSIGHT_TIMEOUT_MS` | `8000` | 洞察生成(第二轮 LLM)超时,超时降级为模板文本 |

## 测试

```bash
npx vitest --root apps/backend run     # 后端
npx vitest --root apps/frontend run    # 前端
npx vitest --root packages/shared run  # 共享类型
```

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

## 已知限制

- SQL 校验以只读数据库连接为根本防线;AST 校验(`node-sql-parser`,sqlite 方言)解析失败时回退到加固正则。实测示例库的全部验收查询(含 `strftime`、多表 JOIN + GROUP BY、`LIKE` 过滤)均走 AST 路径,未触发正则回退。
- 洞察文本由 LLM 措辞,数字由后端纯函数计算。若怀疑措辞与数字不符,展开「计算依据」核对。
- `seriesBy` 取值超过 12 个时自动退化为单系列,并在图表下方标注。
