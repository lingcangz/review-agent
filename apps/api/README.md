# Review Agent API

本地开发：

```sh
uv run alembic upgrade head
uv run uvicorn review_agent_api.main:app --reload --app-dir src
uv run review-agent-worker
```

服务只接收 Git diff 和调用方明确提供的、按路径限定的上下文；不会接收完整仓库压缩包。

公开 OpenAPI 包含组织创建、邀请码、邮箱会话、CLI Personal Access Token、审查任务、上下文回传和审查规则接口。
除创建组织、接受邀请和邮箱登录外，接口要求 `Authorization: Bearer <token>`。服务始终从该凭据推导组织范围，
跨组织资源统一返回 404，避免泄露对象是否存在。

执行 `uv run python scripts/export_openapi.py` 后，通过根目录 `npm run generate:api` 生成 Web 类型。

部署环境应每天运行 `uv run review-agent-purge-raw-content`。该任务删除过期的按需上下文并清空超过 30 天的
diff，同时保留审查任务和审计元数据。

本地执行 `docker compose -f ../../infra/docker-compose.yml up -d` 后，邮件登录链接会投递到 Mailpit：
`http://localhost:8025`。worker 从 Redis 领取任务，调用 OpenAI Responses API（`store=false`），并将经
Pydantic 校验且锚定至改动行的发现持久化。不要在日志、任务参数或异常中输出 diff、上下文或令牌。

API 和 worker 会从当前目录或父目录的未提交 `.env` 加载环境变量。第三方 OpenAI 兼容网关应设置
`OPENAI_BASE_URL`；`OPENAI_API_KEY` 必须只保存在该文件或部署密钥管理器中。

邮箱登录请求必须包含组织 ID。邮件链接绑定该组织，Web 的 `/auth/verify` 页面要求用户手动确认后才交换
一次性令牌；API 将会话写入 HttpOnly Cookie。开发 Web 地址通过 `CORS_ORIGINS` 配置，默认是
`http://localhost:3000`。
