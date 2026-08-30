# DataAgent 核心浏览器 E2E 验收报告

> 状态：已验证
>
> 核验日期：2026-08-30
>
> 对应路线图：P0 原第 4 项“核心浏览器 E2E”

## 结论

前端已建立 Playwright/Chromium E2E 套件。9 项可重复的浏览器契约测试全部通过，另有 3 项连接真实 `http://127.0.0.1:8090`、PostgreSQL 和实际模型链路的在线冒烟全部通过。在线验证使用一次性普通用户与管理员；测试会话通过正式 API 删除，临时账号已从数据库清理。

## 覆盖矩阵

| 场景 | 自动化证据 | 结果 |
| --- | --- | --- |
| 登录、创建会话、发送简单问题 | Chromium UI；在线服务实际回答 `E2E_OK` | 通过 |
| 成功 | SSE `text/end` 后输入恢复可发送 | 通过 |
| 失败 | SSE `error` 投影为明确 `[ERROR]` 终态 | 通过 |
| 中断 | 浏览器点击“中断”，调用正式 interrupt API，进入 `[CANCELLED]` | 通过 |
| 计划确认 | 恢复计划可见，并提交 plan preview 确认协议 | 通过 |
| KunCode 确认 | KunCode 预览内容可编辑并提交确认协议 | 通过 |
| SSE 断线重连 | 首次流意外结束；第二次携带 `Last-Event-ID: 1-0` 并完成 | 通过 |
| 文件交付 | `generated_files` 自动切换文件页；Markdown 可预览和下载 | 通过 |
| 普通用户权限 | 共享配置只读、写控件隐藏、真实 PUT 返回 403 | 通过 |
| 管理员权限 | 系统提示词、知识、Skill、MCP 写控件可见 | 通过 |

## 运行方式

从 `frontend/` 执行：

```powershell
npm.cmd run test:e2e
```

真实服务冒烟需要先启动 DataAgent，并仅通过环境变量提供专用验收账号：

```powershell
$env:E2E_USERNAME = '<普通用户>'
$env:E2E_PASSWORD = '<普通用户密码>'
$env:E2E_ADMIN_USERNAME = '<管理员>'
$env:E2E_ADMIN_PASSWORD = '<管理员密码>'
$env:E2E_BASE_URL = 'http://127.0.0.1:8090'
npm.cmd run test:e2e:live
```

在线简单问题用例会准确记录并删除自己创建的会话。账号生命周期由本地验收脚本或 CI fixture 管理，凭据不得写入仓库。

## 同步修复

自动化首次覆盖中断时发现，原“暂停”按钮只关闭前端 SSE，不会调用后端中断接口。现已改为调用 `/api/conversation/session/{session_id}/interrupt`；后端确认后即使 `interrupted` 流事件与断流发生竞态，前端也会可靠进入取消终态。会话切换继续只断开当前浏览器订阅，不会误取消后台任务。

## 本轮命令结果

- `npm.cmd run lint`：通过。
- `npm.cmd run build`：通过；保留既有约 1.94 MB 大 chunk 警告。
- `npm.cmd run test:e2e`：9/9 通过。
- `npm.cmd run test:e2e:live`：3/3 通过。
- `python -m unittest tests.test_task_regressions -v`：52/52 通过。
- `/ready`：PostgreSQL、Redis、Sandbox、Milvus、Embedding 全部 `ok`。

## 剩余边界

- 核心 P0 浏览器覆盖已完成；计划面板专项仍可补充两个会话快速切换时的迟到响应隔离用例。
- KunCode 复杂任务的真实失败后自动修复、长时间依赖下载视觉阶段仍属于运行时专项的增强验收，不影响本套件作为日常浏览器门禁。
