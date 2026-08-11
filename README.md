# Chat-BI

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2-D71F00)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama-000000?logo=ollama&logoColor=white)
![pytest](https://img.shields.io/badge/tested_with-pytest-0A9EDC?logo=pytest&logoColor=white)

面向数据分析师/工程师的 AI 副驾：每一句由 LLM 生成的 SQL 都**看得见**（草稿与最终版可 diff）、**改得了**（结果落地前可在编辑器里改）、**存得下**（人在回路批准后执行，全链路日志可回放）。多用户、行列级权限、Postgres / MySQL / ClickHouse 三类数据源接入。

v1（本机单用户离线问数工具，TypeScript 全栈）已作废并从工作树删除，可从本次重写提交的父节点恢复；v2 起后端换栈为 Python + FastAPI，产品定位换为面向分析师的 AI 副驾。

## 路线图

三段拆分，每段各走一轮 spec → plan → 实施（详见 `docs/superpowers/specs/2026-08-11-chatbi-v2-1-design.md`）：

| 段 | 范围 | 退出标准 | 状态 |
|---|---|---|---|
| **V2-1** | 基座（认证/多用户/数据源/应用库）+ 可控链路（生成→可见→可编辑→批准→执行→日志/回放）+ 结果展示（表格 ⇄ 图表 + 下钻） | 四个核心功能端到端可用；三类数据源对真库跑通；粗粒度权限可用 | **进行中（P1：后端基座骨架）** |
| V2-2 | 语义层（物理/业务/指标/治理四层）+ 行列级权限策略与编辑 UI + pgvector 语义检索 | 指标口径统一；行列级隔离可验证 | 未开始 |
| V2-3 | 资产沉淀、feedback 学习、洞察文本、导出到 Notebook | 资产可复用；纠正一次后同类提问命中修正 | 未开始 |

## 本地运行

后端在 `apps/api`，需要 Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)。

### 1. 准备 Postgres

二选一：

- **原生 Postgres**（推荐用于本地开发）：确保本机 5432 端口有 Postgres，用户 `chatbi` / 密码 `chatbi`，并已建好 `chatbi`、`chatbi_test` 两个数据库。
- **Docker Compose**：`docker compose -f docker/compose.yml up -d` 会拉起 `app-postgres`（宿主端口映射到 **5433**，避免与原生 Postgres 冲突）与 `ollama` 两个服务；连接字符串里的端口相应改成 5433。

### 2. 装依赖并起服务

```bash
cd apps/api
uv sync
export CHATBI_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi
export CHATBI_SECRET_KEY=dev-only-not-for-production
uv run uvicorn chatbi.main:app --reload
```

启动后 `GET http://localhost:8000/health` 应返回 `{"status": "ok"}`。

## 测试

```bash
cd apps/api
export TEST_DATABASE_URL=postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi_test
export CHATBI_SECRET_KEY=dev-only-not-for-production
uv run pytest
```

当前阶段（P1）只有 `/health` 的骨架测试，不依赖数据库；后续任务引入数据库相关测试后需要 `TEST_DATABASE_URL` 指向的 `chatbi_test` 库可写。

## 结构

```
apps/api            Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic
docker/compose.yml   app-postgres（宿主 5433）· ollama（11434），P1 阶段只写不跑
docs/                产品与技术设计文档
docs/superpowers/    spec 与实施计划（SDD 流程产物）
```
