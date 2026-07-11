# DataAgent 项目缺陷整改指导方案

> 编制日期：2026-07-11  
> 当前工作分支：`feat/backend-misc`  
> 适用范围：Windows 本地运行、Docker 依赖服务、FastAPI 后端、Agent/KunCode 调用链、终端交互、React 前端重构分支

## 1. 文档目标

本方案用于指导后续整改，不直接替代需求设计或提交记录。它覆盖当前代码审查、Git 历史核对和在线回归中已经确认的缺陷，并区分以下三类状态：

- **已修复但未提交**：当前工作区已经修改并通过回归，合并前仍需形成独立提交。
- **当前仍存在**：在 `feat/backend-misc` 中仍可复现或可由代码直接确认。
- **前端分支问题**：只存在于 `feat/frontend-vue-refactor`，当前运行版本并未加载这些代码。

目标不是一次性重写全部系统，而是先建立唯一可运行基线，再逐步收敛调用协议、部署方式、安全和测试。

## 2. 当前基线结论

### 2.1 实际运行前端

当前 `feat/backend-misc` 的 `app/main.py` 直接提供以下静态资源：

- `frontend/index.html`
- `frontend/css/style.css`
- `frontend/js/api.js`
- `frontend/js/app.js`

因此当前浏览器实际加载的是原生 HTML/CSS/JavaScript，而不是 React 重构版。

### 2.2 React 重构并未丢失

React/TypeScript 重构位于独立分支 `feat/frontend-vue-refactor`：

- `2fbebf9`：新增 React、TypeScript、Vite、Zustand 和组件化前端。
- `d053d3e`：继续修改 `FilesPanel`、`PlanPanel`、`TerminalPanel` 和会话 Store。

该分支虽然名为 `vue-refactor`，实际技术栈是 React。它没有合并到当前后端分支，所以当前运行时不可见。两个分支从 `f24a843` 分叉，并同时修改了 `app/main.py`、`conversation.py`、`files.py`、`config.py`、`agent_service.py` 和 `tasks.py`，不能直接无审查合并。

### 2.3 已验证的在线基线

- `8090` 主服务和 `10001` 沙箱服务可访问。
- PostgreSQL、带认证 Redis、Milvus RPC 可用。
- Mimo 可以驱动 KunCode 完成连续调用。
- 同一会话连续两次 KunCode 调用均能结束、清除任务状态并在刷新后恢复终端历史。
- Milvus 容器仍被 Docker 标记为 `unhealthy`，但 RPC、数据库和集合访问正常，说明容器健康检查和实际可用性判断不一致。

## 3. 缺陷总表

| 编号 | 严重度 | 状态 | 缺陷 | 主要影响 |
|---|---|---|---|---|
| D-01 | P0 | 当前仍存在 | 后端分支和 React 前端分支长期分叉 | 前端重构实际未上线，继续两边修改会扩大冲突 |
| D-02 | P0 | 已修复未提交 | Windows 本地任务重复初始化并关闭全局 ORM/AgentService | 第一轮成功后第二轮出现 `pool is closing` 或 500 |
| D-03 | P0 | 已修复未提交 | API 返回的任务 ID 与本地执行器内部任务 ID 不一致 | 前端订阅错误 Redis Stream，表现为永久等待 |
| D-04 | P0 | 已修复未提交 | 直连 KunCode 分支提前返回且不持久化消息 | 刷新后命令和结果丢失，终端状态无法恢复 |
| D-05 | P0 | 当前仍存在 | `/conversation/stream/{task_id}` 没有任务所有权校验 | 知道 task ID 即可读取其他任务输出 |
| D-06 | P0 | 当前仍存在 | 静态前端直接将 `marked.parse()` 结果写入 `innerHTML` | 模型输出或知识内容可形成存储型/反射型 XSS |
| D-07 | P1 | 当前仍存在 | KunCode、沙箱和内置工具没有统一结构化事件协议 | 前端只能依赖文本和正则判断内部工具、成功或失败 |
| D-08 | P1 | 已部分修复 | 简单问题可暴露过多 shell/IPython/检查类工具 | 一个简单任务可能产生大量无价值 shell 调用 |
| D-09 | P1 | 当前仍存在 | `_should_direct_run_kuncode` 只检查消息是否包含 `kuncode` | 讨论 KunCode、报错咨询等消息也会被误判为直接执行 |
| D-10 | P1 | 已部分修复 | 前端完成态依赖最后一次 `tool_result` 或流结束兜底 | 断线、错误和重连时仍缺少严格状态机 |
| D-11 | P1 | 前端分支问题 | React 前端未进入当前分支，Vite 代理仍指向 `8000` | 开发环境无法正确访问实际 `8090` 后端 |
| D-12 | P1 | 前端分支问题 | `FilesPanel`、`PlanPanel` 存在 Hook lint 规则问题 | `npm run lint` 失败，异步加载可能产生陈旧状态 |
| D-13 | P1 | 前端分支问题 | React 终端通过正则猜测 KunCode 内部调用 | 工具数量、名称和状态可能误识别，无法保证准确展示 |
| D-14 | P1 | 当前仍存在 | Windows 没有原生启动/停止脚本 | Bash 的 `nohup`、`kill`、PID 文件流程无法可靠管理 Windows 服务 |
| D-15 | P1 | 当前仍存在 | PostgreSQL、Redis、Milvus、沙箱和主服务启动方式分散 | 环境容易出现只启动 Docker 但 8090/10001 未启动的情况 |
| D-16 | P1 | 当前仍存在 | `/health` 只检查 AgentService 的 `_started` | PostgreSQL、Redis、Milvus、Embedding、沙箱不可用时仍可能返回健康 |
| D-17 | P1 | 当前仍存在 | Milvus 数据库/集合需要手工执行重建脚本 | Docker 重建后知识库可能不存在，功能静默降级 |
| D-18 | P1 | 当前仍存在 | Embedding 服务 `9997` 没有随项目启动，也没有明确降级状态 | 知识库新增和向量重建会在运行期失败 |
| D-19 | P1 | 当前仍存在 | 会话清理只删除沙箱绑定，不主动销毁沙箱容器和实际文件 | Docker 中持续积累 `data-sandbox-*` 容器和磁盘数据 |
| D-20 | P1 | 当前仍存在 | 数据库初始化修改 Tortoise 私有字段并执行 `generate_schemas` | 生命周期脆弱，无法替代正式迁移，升级 ORM 风险高 |
| D-21 | P1 | 当前仍存在 | Mimo 仍收到不支持的 `temperature` 参数 | 日志持续警告，配置看似生效但实际被忽略 |
| D-22 | P1 | 当前仍存在 | Mimo 能调用 KunCode，但对短指令存在扩展解释 | `9*9` 可能生成乘法表，结果准确性依赖提示词约束 |
| D-23 | P1 | 当前仍存在 | SSE 传输的是累计完整输出而非增量事件 | 长输出带来重复带宽、重复 DOM 更新和 Redis Stream 膨胀 |
| D-24 | P1 | 当前仍存在 | KunCode 存在 300/1800/7200 秒多层超时 | 用户看到的卡住时间不确定，取消时不易保证子进程完全退出 |
| D-25 | P1 | 当前仍存在 | CORS 使用 `*` 且允许凭据，JWT 有弱默认密钥 | 非纯本地部署时存在明显安全配置风险 |
| D-26 | P1 | 前端分支问题 | SSE token 和文件 token 倾向通过 URL 查询参数传递 | token 可能进入浏览器历史、代理日志和 Referer |
| D-27 | P1 | 前端分支问题 | 文件预览包含远程 PDF worker 和未净化 HTML | 离线不可用，并可能引入供应链或 HTML 注入风险 |
| D-28 | P2 | 当前仍存在 | 静态 `app.js` 和 `style.css` 都是超大单文件 | 状态、渲染和 API 行为耦合，修改容易产生回归 |
| D-29 | P2 | 当前仍存在 | 缺少正式后端、前端和端到端测试套件 | 当前修复主要依赖人工回归，无法阻止再次引入卡死问题 |
| D-30 | P2 | 当前仍存在 | Windows 重定向日志出现中文乱码 | 故障排查困难，无法稳定搜索关键日志 |
| D-31 | P2 | 当前仍存在 | Pydantic、Redis `close()`、`datetime.utcnow()` 存在弃用警告 | 依赖升级后会成为错误或产生维护噪音 |
| D-32 | P2 | 当前仍存在 | README、脚本默认端口和远程地址曾长期漂移 | 新环境容易连接错误服务或错误端口 |
| D-33 | P2 | 当前仍存在 | 启动脚本用固定 `sleep 2/3` 判断成功 | 实际主服务可能需要约 40 秒，容易误报启动失败或成功 |

## 4. 推荐目标架构

### 4.1 分支和前端选择

建议将 React 重构版作为最终前端，不再同时维护 4900 行静态 `app.js` 和 React 两套实现。

推荐步骤：

1. 在提交当前后端修复后，从 `feat/backend-misc` 新建 `integration/react-terminal`。
2. 只迁移 `2fbebf9` 和 `d053d3e` 中的 `frontend/` 内容，不先接受它们对后端文件的修改。
3. 以当前后端 API 为基线，逐项修正 React API Client 和 Store。
4. React 通过 lint、build 和端到端测试后，再删除静态前端。
5. 将分支重命名为准确的 React 名称，避免继续使用 `vue-refactor`。

不建议直接执行无审查的分支 merge，因为双方都改动了任务生命周期和沙箱接口，直接合并可能重新引入已修复的数据库连接问题。

### 4.2 统一任务事件协议

后端、Redis、历史记录和前端统一使用一个事件模型：

```json
{
  "event_id": "evt_uuid",
  "task_id": "task_uuid",
  "session_id": "session_uuid",
  "call_id": "call_uuid",
  "parent_call_id": null,
  "source": "kuncode",
  "tool_name": "run_kuncode",
  "phase": "started",
  "status": "running",
  "input": {"prompt": "..."},
  "output_delta": "",
  "error": null,
  "started_at": "2026-07-11T00:00:00Z",
  "finished_at": null
}
```

`phase` 只允许以下值：

- `started`
- `progress`
- `completed`
- `failed`
- `cancelled`

KunCode 内部工具必须通过 `parent_call_id` 关联到外层 `run_kuncode`。前端不再用正则从普通文本猜测 `bash/read/write`，也不再通过是否包含 `[ERROR]` 判断失败。

### 4.3 前端工具状态机

每个工具调用按 `call_id` 保存独立状态：

```text
idle -> running -> completed
               -> failed
               -> cancelled
```

约束：

- `tool_result` 只能更新相同 `call_id` 的记录。
- 收到任务级 `end` 时，只能把仍为 `running` 的调用标记为 `failed/cancelled`，不能默认成功。
- 历史恢复和实时流必须使用同一个 reducer。
- 刷新后展示结果应由持久化事件重放得到，而不是写死“完成”。
- 终端只追加 `output_delta`，历史数据库只保存最终聚合结果或分段事件，不重复保存累计快照。

## 5. 分阶段整改计划

## 阶段 0：固化当前修复基线

### 修改内容

1. 将当前工作区按功能拆分提交：
   - Windows 任务生命周期和任务 ID。
   - KunCode 直连历史持久化。
   - shell/IPython 工具默认关闭。
   - 静态前端终端完成态。
   - 文档和端口配置。
2. 为以下回归场景增加最小自动化测试：
   - 普通问题后继续发送第二个问题。
   - 同一会话连续两次 KunCode。
   - 失败、空输出和中断路径均产生配对的调用结果。
3. 记录当前 API 响应样例，作为 React 整合时的契约基线。

### 涉及文件

- `app/tasks.py`
- `app/api/conversation.py`
- `app/services/agent_service.py`
- `frontend/js/app.js`
- `frontend/css/style.css`
- `system_prompt.md`

### 验收标准

- 连续 20 次同会话请求没有 `pool is closing`。
- API 返回 task ID、Redis stream key 和前端订阅 task ID 完全一致。
- 每个 `plugin_call` 恰好有一个同 `call_id` 的 `plugin_call_output`。
- 刷新后终端没有永久 `running`。

## 阶段 1：整合 React 前端

### 修改内容

1. 从 React 分支迁移 `frontend/src`、构建配置和依赖文件。
2. 修改 `vite.config.ts`：开发代理从 `http://localhost:8000` 改为 `http://localhost:8090`，或读取 `VITE_API_PROXY_TARGET`。
3. 保留当前分支中 `app/main.py` 的后端生命周期修改，只引入 React `dist` 的静态服务逻辑。
4. 启动时若 `frontend/dist/index.html` 不存在，应明确报错或提示先执行构建，不应返回空白页。
5. React 验收通过后删除旧 `frontend/js`、`frontend/css` 和旧入口 HTML。
6. 核对 `html-editor.html` 是否仍是业务功能；如需要，应迁移成 React 路由，不能在删除静态前端时静默丢失。

### FilesPanel 整改

- 不要用 `setTimeout(..., 0)` 绕过 Hook 规则。
- 将目录请求封装为 `useWorkspaceFiles(sessionId, path)`，用 `AbortController` 取消旧请求。
- 会话切换时以 `sessionId + path` 作为请求键，避免旧请求覆盖新会话状态。
- PDF worker 随前端构建产物本地发布，不依赖 unpkg CDN。
- Word/HTML 预览必须经过 DOMPurify；优先在隔离 iframe 中使用严格 CSP。
- 下载和图片预览通过带 `Authorization` 的 fetch 获取 Blob，再创建临时 Object URL；禁止把 JWT 放进 URL。
- 组件卸载时释放 Object URL、PDF worker 和渲染任务。

### PlanPanel 整改

- 使用 `usePlan(sessionId)` 管理加载、错误、刷新和取消。
- 不在 effect 中同步重置多个本地状态；会话键变化时由请求状态自然切换。
- 子任务改用稳定 `subtask_id`，不要使用数组 index 作为更新和删除标识。
- 编辑操作加入禁用态、错误提示和乐观更新回滚。

### TerminalPanel 整改

- 删除文本正则推断内部工具的主路径。
- 用统一事件 reducer 同时处理实时流和历史消息。
- 同一 `call_id` 的增量输出只追加一次。
- 明确展示 `running/completed/failed/cancelled`，任务结束不等于工具成功。

### 验收标准

```bash
cd frontend
npm ci
npm run lint
npm run build
```

- 三条命令全部退出码为 0。
- FastAPI 加载的是 `frontend/dist/index.html`。
- 浏览器 Network 中不再请求旧 `/js/app.js`。
- 登录、会话、文件、计划、终端、管理页功能全部通过。

## 阶段 2：重构任务流和 KunCode 事件

### 修改内容

1. 在 `sandbox_image/routers/kuncode_stream.py` 输出结构化 SSE，而不是只输出字符串。
2. 如果 KunCode 提供 JSON/JSONL 事件模式，直接透传并校验；如果不提供，只将内容标记为 `log`，不要伪造内部工具调用。
3. `data_analysis_sandbox.py` 保留增量事件，不在每个 chunk 上构造累计全文。
4. `agent_service.py` 将工具事件写入 Redis Stream，并在结束时聚合一次最终历史。
5. 使用 `Last-Event-ID` 或显式 cursor 支持断线续传，避免每次从 Redis ID `0` 全量重放。
6. 每个 task 建立 `user_id/session_id/task_id` 所有权记录。
7. SSE 读取前验证当前用户确实拥有该 task。
8. 将直接运行触发条件改为显式字段，例如 `execution_mode="kuncode"`，不要从自然语言中搜索关键字。
9. 错误状态使用结构化 `error_code`，不再依赖输出中是否存在 `[ERROR]`。

### 超时和取消

统一定义：

- 连接超时：10 秒。
- 首字节超时：60 秒，可配置。
- 空闲输出超时：300 秒，可配置。
- 总执行超时：1800 秒，可配置。
- 前端每 15 秒收到心跳。

取消任务时必须：

1. 写入 `cancel_requested`。
2. 终止 KunCode 子进程及其子进程树。
3. 写入 `cancelled` 结果并持久化。
4. 清除 session task key。
5. 释放沙箱连接。

### 验收标准

- 简单算术只显示一个外层 KunCode 调用，不出现 9 个无意义 shell 调用。
- 复杂任务可准确显示 KunCode 内部工具的开始、结束和失败。
- 断网后重连不会重复命令或丢失输出。
- 中断后 5 秒内不再存在对应 KunCode 子进程。

## 阶段 3：统一 Windows 和 Docker 运行方式

### 修改内容

1. 增加根目录 `compose.yaml`，统一管理：
   - PostgreSQL
   - Redis
   - Milvus、etcd、MinIO
   - 可选 Embedding 服务
   - Sandbox Manager
2. 主 FastAPI 可继续宿主机运行，但必须由统一脚本管理；也可增加 Docker profile。
3. 新增原生 `scripts/start.ps1`：
   - `up`、`down`、`restart`、`status`、`logs`。
   - 使用绝对项目路径和 `.venv\Scripts\python.exe`。
   - 设置 `DEBUG=release`、`PYTHONUTF8=1` 和 UTF-8 日志环境。
   - 精确记录监听进程 PID，不记录临时 launcher PID。
4. 删除固定 `sleep 3` 判定，改为最多 90 秒轮询 `/ready`。
5. `start.sh` 和 `start.ps1` 调用同一套 Python 健康检查逻辑，避免两个脚本继续漂移。

### 健康检查

提供两个端点：

- `/live`：进程存活即可返回 200。
- `/ready`：PostgreSQL、Redis、Sandbox 必须正常；Milvus/Embedding 根据知识库是否启用决定 required 或 degraded。

返回示例：

```json
{
  "status": "degraded",
  "dependencies": {
    "postgres": "ok",
    "redis": "ok",
    "sandbox": "ok",
    "milvus": "ok",
    "embedding": "disabled"
  }
}
```

### Milvus 和知识库

- 修正 `milvus/docker-compose.yml` 的健康检查，使其与当前镜像实际端点一致。
- 应用启动时执行幂等 bootstrap：创建数据库和集合，但不删除现有数据。
- Embedding 未配置时，在管理界面明确显示“知识库写入不可用”，而不是运行到请求时才报错。
- 清理重建脚本中的 `100.100.*` 远程默认地址，所有脚本统一读取 `Settings`。

### 沙箱资源回收

`SessionCleanupService.cleanup_session()` 需要补充：

- 调用 Sandbox Manager 销毁绑定的容器。
- 删除会话挂载目录和上传文件，或按保留策略移入回收站。
- 清理失败时记录可重试任务，不能只删除绑定后遗留孤儿容器。
- 增加定时 reconciler：对比数据库绑定和 Docker 容器，清理无主 `data-sandbox-*`。

### 验收标准

- 一台新 Windows 机器只需 `.\scripts\start.ps1 up` 即可启动全部必需服务。
- `status` 同时显示进程、端口和依赖健康，不只判断 PID。
- 删除会话后对应沙箱容器和文件按策略消失。
- Docker 重启后知识库数据库和集合自动恢复可用。

## 阶段 4：安全和数据层整改

### 安全项

- `/conversation/stream/{task_id}`、任务状态、interrupt 接口全部验证会话所有权。
- 使用 fetch streaming 携带 Authorization，或改用 SameSite/HttpOnly Cookie；禁止查询参数 token。
- JWT 默认密钥在非开发环境必须导致启动失败。
- CORS origins 从环境变量白名单读取；本地默认只允许 `localhost/127.0.0.1`。
- 所有 Markdown/HTML 渲染使用 DOMPurify 白名单。
- 文件下载验证路径解析结果仍在会话 workspace 内，禁止目录穿越。
- 管理接口继续要求 `is_admin`，并增加操作审计日志。

### 数据库项

- 删除 `connections._connections`、`connections._inited` 等私有字段修改。
- 应用生命周期只初始化和关闭 ORM 一次。
- 使用 Aerich migration 管理表结构，不在生产启动时调用 `generate_schemas`。
- KunCode 的用户消息、调用和结果在一个事务中写入；失败时保证不会留下孤立调用。

### 验收标准

- 用户 A 无法读取、终止或下载用户 B 的任务和文件。
- 输入 `<img src=x onerror=alert(1)>` 不会执行脚本。
- 生产配置使用默认 JWT 密钥时应用拒绝启动。
- 数据库升级可通过 migration 前进和回滚。

## 阶段 5：模型适配、日志和质量门禁

### Mimo 适配

- 为各 provider 建立能力表：`temperature`、thinking、tool calls、parallel calls、JSON mode、最大上下文。
- Mimo 不支持的参数不要传给 `OpenAIChatModel`，消除“参数被忽略”警告。
- 对“只返回最终数字”等严格任务使用固定执行模板，不依赖模型自行理解输出格式。
- 将模型能力问题和代码错误分开记录：HTTP/API 错误、格式错误、工具协议错误、结果质量错误使用不同 error code。

### 日志和可观测性

- 全链路记录 `request_id/task_id/session_id/call_id/sandbox_id`。
- Windows 文件日志明确使用 UTF-8。
- Redis 使用 `aclose()`，时间使用 timezone-aware UTC。
- 记录关键耗时：模型首 token、KunCode 首输出、总执行、持久化和前端完成。
- 对超时、孤立调用、无主沙箱和重复工具调用增加指标。

### 测试和 CI

后端至少覆盖：

- 任务 ID 一致性。
- Windows 共享资源生命周期。
- tool call/result 配对和重排。
- SSE 所有权和断线续传。
- 超时、中断、空输出、模型错误。
- Milvus bootstrap 和 Embedding 降级。

前端至少覆盖：

- reducer 的全部工具状态迁移。
- 重连去重和历史恢复。
- FilesPanel 会话切换竞态。
- PlanPanel 增删改失败回滚。
- Markdown XSS 清洗。

端到端固定场景：

1. 登录并创建会话。
2. 普通问答不调用 shell。
3. 同一会话连续两次 KunCode。
4. 刷新后两次调用仍显示完成和正确输出。
5. 长任务中断后前端、Redis 和子进程全部结束。
6. 删除会话后沙箱资源回收。
7. 知识库新增、检索和 Docker 重启恢复。

CI 必须执行：

```bash
python -m pytest
python -m compileall app
cd frontend && npm ci && npm run lint && npm run build
```

并执行至少一组 Playwright 桌面和移动端回归。

## 6. 推荐提交顺序

建议每项单独提交，便于回滚：

1. `fix(tasks): preserve shared resources and task ids on Windows`
2. `fix(kuncode): persist direct invocation history`
3. `fix(terminal): finalize sandbox tool states`
4. `chore(prompt): remove obsolete shell tool guidance`
5. `feat(frontend): integrate React application on backend baseline`
6. `refactor(events): introduce structured task and tool events`
7. `feat(runtime): add Windows service manager and unified compose`
8. `fix(security): authorize streams and sanitize rendered content`
9. `refactor(database): replace runtime schema generation with migrations`
10. `test(e2e): cover consecutive KunCode and reconnect workflows`

每个提交都应保持可启动，不要在同一提交中同时合并前端、重写事件协议和修改部署方式。

## 7. 最终发布门槛

满足以下条件后才建议合并到 `main`：

- [ ] 当前未提交修复已拆分提交并通过回归。
- [ ] 只保留一套正式前端，浏览器不再加载旧静态 JS。
- [ ] `npm run lint`、`npm run build`、后端测试全部通过。
- [ ] 普通问题不会产生无意义 shell 调用。
- [ ] 连续 KunCode、刷新、重连、中断均无永久 running。
- [ ] 工具调用和结果使用结构化事件并严格配对。
- [ ] SSE、文件和会话操作全部验证所有权。
- [ ] Markdown/HTML 渲染经过安全清洗。
- [ ] Windows 可通过一个 PowerShell 命令启动和停止完整环境。
- [ ] `/ready` 能准确反映 PostgreSQL、Redis、Sandbox、Milvus 和 Embedding 状态。
- [ ] Milvus 不再出现“RPC 可用但 Docker unhealthy”的冲突状态。
- [ ] 删除会话会回收沙箱容器和文件。
- [ ] 日志为 UTF-8，且可按 task/session/call 追踪完整链路。
- [ ] 不再存在 Pydantic、Redis close、UTC 时间和模型参数弃用警告。

## 8. 实施原则

1. **先固化后端修复，再整合前端**，防止分支合并覆盖已验证逻辑。
2. **先定义事件协议，再美化终端**，否则前端只能继续猜测状态。
3. **运行状态必须来自后端事实**，不能由 CSS 动画或流结束兜底推断成功。
4. **本地运行也按安全边界设计**，避免未来 Docker/服务器部署时重新补授权。
5. **每个阶段都必须可回滚和可在线验证**，不接受跨多个核心模块的一次性大合并。
