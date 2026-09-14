# Review Agent API

本地开发：`uv run uvicorn review_agent_api.main:app --reload --app-dir src`。

服务只接收 Git diff 和调用方明确提供的、按路径限定的上下文；不会接收完整仓库压缩包。
