# MCP 密钥引用

MCP 配置保存在 PostgreSQL，不能保存 API Key、密码或生产连接串。敏感值必须使用：

```text
{{secret:NAME}}
```

例如高德远程 MCP 的 URL 应保存为：

```text
https://mcp.amap.com/mcp?key={{secret:AMAP_MCP_KEY}}
```

在本机 `.env` 设置真实值，并将该名称加入白名单：

```dotenv
MCP_SECRET_REFERENCE_ALLOWLIST=AMAP_MCP_KEY
AMAP_MCP_KEY=replace-with-your-web-service-key
```

运行时仅 `SandboxInjectionService` 在写入沙箱临时
`/root/.config/kuncode/kuncode.json` 时解析引用。缺少或未白名单的引用会让
该 MCP 注入失败，不会保留旧配置。不要把真实值写入后台表单、源码或日志。
