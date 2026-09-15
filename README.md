# Review Agent

y
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
uv run --directory apps/api alembic upgrade head
uv run --directory apps/api uvicorn review_agent_api.main:app --app-dir src --reload
uv run --directory apps/api review-agent-worker
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

## 鉴权与组织 API

先通过 `POST /v1/organizations` 创建组织和管理员邮箱，再调用 `POST /v1/auth/email-login` 与
`POST /v1/auth/email-login/verify` 获取会话 Bearer Token。管理员可创建邀请码和审查规则；成员可创建
一次性展示的 CLI PAT（`POST /v1/auth/personal-access-tokens`）。所有审查、规则与上下文请求均从 Bearer
Token 推导组织，客户端不能指定组织标识。

开发环境的登录邮件会投递到本地 Mailpit 收件箱；生产环境须设置 `APP_ENV=production` 并配置真实 SMTP 服务。
打开邮件内的链接后，在 Web 验证页手动确认即可完成登录。
首次使用可访问 `/onboarding` 创建组织；完成后页面会把组织 ID 带入登录页。

## 本地异步审查

Compose 会启动 Redis 和 Mailpit。登录邮件可在 `http://localhost:8025` 查看；API 通过本地 SMTP
`localhost:2525` 投递。设置 `OPENAI_API_KEY`（以及可选的 `OPENAI_MODEL`）后，另开一个终端运行
`uv run --directory apps/api review-agent-worker`。提交审查后，worker 仅向 OpenAI 发送脱敏的 diff、
明确提供的上下文和本组织已启用规则，并以结构化中文结果更新任务。
