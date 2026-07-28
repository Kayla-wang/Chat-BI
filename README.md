# Chat-BI

本地运行的对话式 BI 工具:自然语言提问 → 本地 Ollama 生成只读 SQL → 查询内置 SQLite 示例库 → 返回 ECharts option → 前端渲染图表/表格。

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

## 测试

```bash
npx vitest --root apps/backend run     # 后端
npx vitest --root apps/frontend run    # 前端
npx vitest --root packages/shared run  # 共享类型
```

## 手动验收清单

发版前依次问,人工确认图表类型与数据:

1. "按月统计订单金额" → 期望折线图(line)
2. "各产品类别销售额占比" → 期望饼图(pie)
3. "各地区订单总额对比" → 期望柱状图(bar)
4. "查询 1999 年的订单" → 期望空结果 + 提示无记录
