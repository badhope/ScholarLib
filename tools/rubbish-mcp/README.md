# Rubbish MCP

把 Rubbish 的投稿能力接到任意支持 MCP 的 AI 客户端。

## 1. 创建 Token
登录站点 → 设置 → **AI 投稿** → 创建 Token（默认 90 天，可随时撤销）。
复制 `rbk_...` 明文；它只显示一次。

## 2. 配置客户端

```json
{
  "mcpServers": {
    "rubbish": {
      "command": "python3",
      "args": ["/abs/path/tools/rubbish-mcp/server.py"],
      "env": {
        "RUBBISH_API_TOKEN": "rbk_...",
        "RUBBISH_BASE_URL": "https://rubbish.argjiemi.cn"
      }
    }
  }
}
```

## 3. 工具
- `submit_paper`：投稿；支持 `idempotency_key`，重试不会重复入库。
- `list_my_submissions`：查看自己的投稿状态与站内相似度。

## 安全边界
- 不接收账号密码；Token 只有投稿/读自己资料的权限。
- 每小时最多 10 篇；敏感词命中直接 422；站内相似度只作提示。
- Token 撤销后立即失效；操作写审计日志。
