# Review Agent CLI

跨平台 Python 客户端。示例：

```sh
review-agent review --diff-file change.diff --context src/service.py --token rap_...
```

它会先读取当前目录的 `.review-agentignore`，拒绝忽略路径，并在发送前脱敏常见密钥模式。
令牌也可通过 `REVIEW_AGENT_TOKEN` 环境变量提供；CLI 不会输出令牌。
