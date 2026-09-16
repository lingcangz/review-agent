# 更新记录

## 2026-09-16（上下文范围与远端历史）

- 将审查上下文请求升级为结构化 `path`、`start_line`、`end_line`，单段最多 500 行；CLI 仅读取并回传服务获准的确切范围，且继续执行忽略路径、仓库边界、二进制和密钥脱敏检查。
- 新增 Alembic 迁移 `20260916_0004`：保存上下文行范围，并允许同一审查中的同一路径保存多个不同范围。
- 新增组织隔离的 `GET /v1/reviews?limit=&cursor=` 历史摘要接口；CLI `history` 默认使用远端结果并在不可用时回退到本机历史。
- 重新生成 `apps/api/openapi.json` 与 Web API TypeScript 类型。
- 验证：`npm run format:check`、`npm run typecheck`、`npm test`（Web 3、API 11、CLI 14）与 `npm run build` 均通过；`git diff --check` 无输出。
- 已知限制：迁移前处于 `needs_context` 状态的旧任务没有历史行范围，升级后会安全地转换为请求该文件的第 1–500 行；如仍需更多内容，worker 会发起新的受限请求。

## 2026-09-16

- 实现 CLI `init`、`login`、`review` 与 `history`：配置和本地任务历史均在仓库外保存；`review` 从 `--base` 收集 diff、文件清单，默认自动确认 `y`，`--confirm` 可要求人工确认。
- 增加 Git 路径规范化、`.review-agentignore` 校验、二进制拒绝和密钥脱敏；上下文请求只回传服务明确请求的、受限且脱敏的文本路径，显式 `--context` 支持 `路径@起始行-结束行`。
- 增加本地变更 Python 文件的 AST、Ruff 与 Bandit 高置信分析，结果只在本机显示，不会发送给 API。
- 验证：`uv run --directory apps/cli ruff format --check .`、`uv run --directory apps/cli ruff check .`、`uv run --directory apps/cli mypy src`、`uv run --directory apps/cli pytest` 均通过（13 个测试）；`git diff --check` 无输出。

- 2026-09-15：将 API 与 CLI 的解释器约束收紧为 Python 3.12（`>=3.12,<3.13`），并将 Starlette 约束在 v1 以前、AnyIO 限制为 `<4.15`；未受约束的 Starlette 1.6 会要求 `httpx2`，而 AnyIO 4.15 的 blocking portal 在当前环境无法返回，二者会使最小 ASGI 请求测试挂起。重建受支持环境后将复跑完整检查。
- 2026-09-15：在 Python 3.12.14 的本机执行环境中完成验证：`npm run format:check`、`npm run typecheck`、`npm test`（Web 3、API 9、CLI 3）与 `npm run build` 均通过；`git diff --check` 无输出。受限沙箱会阻止事件循环的本地跨线程通信，因此 HTTP 测试须在本机执行环境中运行。

## 2026-09-15

- 建立组织、成员邀请、邮箱会话、CLI PAT、审查任务、规则与上下文回传 API。
- 使用 SQLAlchemy 2 持久化模型和 Alembic 初始迁移；所有组织资源查询均由已认证主体的组织标识限定。
- 补充鉴权、跨组织拒绝、迁移与请求校验测试，并重新生成 OpenAPI/前端类型。
- 增加原始 diff/上下文的 30 天清理命令 `review-agent-purge-raw-content`；部署应每日调度该命令。
- 接入 Mailpit 本地 SMTP 收件箱、Redis/arq 审查 worker 和 OpenAI Responses API 结构化输出；worker 使用 `store=false`、再次脱敏并验证发现锚定改动行。
- 新增 worker 持久化集成测试，验证结构化结果仅保存已锚定的发现并将任务标记为完成。
- worker 现读取 `OPENAI_BASE_URL`，并通过 `python-dotenv` 安全加载未提交 `.env`；示例文件已移除真实密钥。
- 本地 `.env` 已保持 Git 忽略，并将权限收紧为仅当前用户可读写（`600`）。
- 完成邮箱魔术链接的 Web 验证页和请求页；令牌绑定组织，验证页手动确认后才交换会话，并补充受限 CORS 与迁移。
- 登录成功后清除浏览器地址栏中的一次性令牌查询参数，避免令牌遗留在浏览历史中。
- 忽略本地 SQLite 回退数据库文件，避免开发数据误提交；生产仍以 PostgreSQL 为唯一事实来源。
- 新增 Web 组织创建引导页，并将邮箱登录的浏览器会话改为 HttpOnly Cookie；Cookie 鉴权、凭据 CORS 和组织 ID 预填均有测试覆盖。

验证：`npm run format:check`、`npm run typecheck`、`npm test` 和 `npm run build` 均已通过；本地 PostgreSQL 已成功升级至最新 Alembic 迁移，Mailpit SMTP 投递已验证。
