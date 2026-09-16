# Review Agent CLI

跨平台 Python 客户端。它只从指定的 Git base 收集 diff，绝不会上传完整仓库、二进制文件、`.review-agentignore` 匹配文件或本地工具分析结果。

```sh
review-agent init --api-url http://localhost:8000
review-agent login --email you@example.com --organization <组织 ID>
review-agent review --base origin/main
review-agent history
```

提交前会展示文件清单与脱敏提示，并默认自动确认 `y`；需要人工确认时使用 `--confirm`（`--yes` 保留为兼容选项）。令牌也可通过 `REVIEW_AGENT_TOKEN` 或 `--token` 提供；CLI 不会输出令牌。`init`、`login`、`history` 使用当前用户配置目录（或 `REVIEW_AGENT_CONFIG`），不会写入被审查仓库。

每次审查只对变更且仍存在的 `.py` 文件执行 AST、Ruff 和 Bandit。仅显示 AST 语法错误、Ruff 高置信未定义名称/解析错误以及 Bandit 高严重度且高置信的问题；本地检查结果不会发送给 API。服务要求上下文时，CLI 仅回传其请求的、路径受限、指定行范围且脱敏后的文本文件。`history` 登录后读取组织隔离的远端摘要；网络不可用时回退到本机记录，`--local` 可强制本机模式。
