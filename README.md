# Review Agent

面向团队的自主代码审阅助手。v1 只接收本地 Git diff 和明确指定的最小上下文，输出中文建议性报告；不会上传完整仓库、集成 GitHub 或阻断合并。

## 目录

- `apps/api`：FastAPI 审阅 API 与 OpenAPI 契约。
- `apps/cli`：跨平台 Python CLI，负责本地忽略规则与脱敏。
- `apps/web`：Next.js 仪表盘骨架。
- `docs`：架构和架构决策记录。
- `infra`：本地 PostgreSQL 与 Redis Compose 配置。

## 本地运行

安装 Python 工具 `uv` 和 Node.js 依赖后，运行：

```sh
docker compose -f infra/docker-compose.yml up -d
uv run --directory apps/api uvicorn review_agent_api.main:app --app-dir src --reload
npm install
npm --workspace @review-agent/web run dev
```

完整质量检查：

```sh
npm run format:check
npm run typecheck
npm test
npm run build
```
