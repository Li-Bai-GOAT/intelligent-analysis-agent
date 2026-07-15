# DataAgent 协作指南

本文件适用于仓库根目录及其所有子目录。其他大模型或自动化代理开始工作前，应先阅读本文件，再阅读与任务直接相关的代码。若本文件与用户当前明确要求冲突，以用户当前要求为准；若文档与代码冲突，以当前代码和可重复验证结果为准。

## 1. 固定项目背景

- 项目名称：DataAgent，企业级数据分析智能体。
- 当前主运行环境：Windows 本地宿主机 + Docker Desktop，不是服务器部署，也不是全量 Docker 化部署。
- 当前有效前端：`frontend/src/` 下的 React 单页应用。FastAPI 从 `frontend/dist/` 提供生产静态文件。
- 核心角色：DataPM 产品经理 Agent 负责理解需求、规划和调度；KunCode 在隔离沙箱中执行代码、Shell 和文件生成任务。
- 对话页负责展示用户/Agent 对话、计划、终端事件和执行状态；实际生成文件通过右侧“文件”页浏览、预览和下载，不应把终端当作文件交付入口。
- 管理后台仅面向管理员，当前包含总览、知识库、系统提示词、Agent、Skill 和 MCP 管理。
- 默认管理员账号只用于本地联调。不要把账号、密码、Token 或 API Key 写入源码、文档、日志或提交信息。
- 当前 Git 主线是 `main`。不要自行恢复已删除的旧功能分支，也不要重新引入旧静态前端。

## 2. 当前架构与请求流程

### 2.1 运行拓扑

```text
Browser / React
    |
    | HTTP + SSE, /api/*
    v
FastAPI :8090
    |-- PostgreSQL :5488   业务数据、用户、会话、配置、文件元数据
    |-- Redis :6380        任务流、HITL、活动任务和运行时状态
    |-- Sandbox Manager :10001
    |       `-- AgentScope Runtime Docker sandbox
    |               |-- /workspace
    |               `-- KunCode CLI + tools/skills/MCP
    |-- Milvus :19530      知识向量索引
    `-- Ollama :9997       qwen3-embedding:0.6b
```

### 2.2 对话与任务流

1. 前端登录后保存 JWT，并先创建或选择会话。
2. `POST /api/conversation/chat` 用于直接 SSE 对话；`POST /api/conversation/async` 用于可恢复长任务。
3. Windows 下异步任务使用 FastAPI 进程内任务执行器；非 Windows 路径才使用 Celery。
4. Redis Stream 保存可重放任务事件，`GET /api/conversation/stream/{task_id}` 负责续接。
5. `execution_mode=auto` 由 DataPM 决定是否调用工具；`execution_mode=kuncode` 明确要求直接调用 KunCode。
6. 沙箱与会话绑定，宿主机 `sessions_mount_dir/` 持久化容器 `/workspace`。
7. KunCode 完成后，后端从输出中提取相对工作区文件路径，通过 `generated_files` 事件通知前端刷新文件页。

### 2.3 事件协议

后端和前端共同依赖 `frontend/src/types/index.ts` 中的事件契约。修改任务流时必须同步检查 `app/services/agent_service.py`、`app/tasks.py`、`app/api/conversation.py` 和 `frontend/src/stores/session.ts`。

- 常用事件类型：`text`、`thinking`、`tool_call`、`tool_result`、`status`、`plan`、`kuncode_preview`、`plan_preview`、`user_input_required`、`context_update`、`interrupted`、`error`、`end`。
- 同一次工具调用的 `tool_call` 与 `tool_result` 必须使用相同且稳定的 `tool_id`。
- 可恢复事件应保留 `event_id`、`task_id`、`session_id`。
- 工具状态使用 `phase` 和 `execution_status`；完成、失败、中断都必须进入终态，不能让前端永久显示 `running`。
- 每条任务路径最终必须发送 `end`，错误路径先发送 `error`，再完成状态清理。
- `generated_files` 使用相对 `/workspace` 的路径；不要把容器绝对路径作为最终用户交付方式。

## 3. 数据所有权

- PostgreSQL 是业务数据事实来源：用户、会话、消息、知识条目、系统提示词、Agent、Skill/MCP 元数据、文件和沙箱绑定均以它为准。
- Milvus 是可重建的派生索引，不是知识正文主存储。知识 CRUD 先写 PostgreSQL，再同步向量。
- Redis 是运行时和任务状态存储，不应成为长期业务数据唯一来源。
- `user_uploads/`、`sessions_mount_dir/` 和 Docker Volumes 是本地运行数据，不属于源码。
- 系统提示词默认值来自 `system_prompt.md`，数据库中的 `system_prompts` 记录优先。
- Agent、Skill、MCP 先在 PostgreSQL/仓库目录管理，再由 `SandboxInjectionService` 注入运行中的沙箱容器。

## 4. 技术栈

### 4.1 后端

- Python 3.12+
- FastAPI + Uvicorn
- AgentScope 1.0.11、AgentScope Runtime 1.0.5
- Tortoise ORM + asyncpg，Aerich 预留数据库迁移能力
- Redis asyncio client；Celery 仅用于非 Windows 异步执行路径
- Pydantic Settings 管理 `.env`
- PyMilvus 管理向量集合
- httpx 处理模型、沙箱和 Embedding HTTP/SSE 请求
- JWT + bcrypt 认证
- 模型适配：DeepSeek、MiniMax、OpenAI、Anthropic、Mimo

### 4.2 前端

- React 19 + TypeScript 6
- Vite 8
- Zustand 状态管理
- Tailwind CSS 4
- Lucide React 图标
- React Markdown + remark-gfm
- pdf.js、Mammoth、SheetJS、PptxJS、JSZip 用于文件预览与处理

### 4.3 沙箱与基础设施

- Docker Desktop
- AgentScope Runtime Sandbox Manager
- PostgreSQL 16、Redis 7
- Milvus standalone 2.5.13 + etcd + MinIO
- Ollama + `qwen3-embedding:0.6b`，1024 维向量
- KunCode CLI 运行在沙箱容器内，默认模型为 `mimo/mimo-v2.5-pro`

## 5. 关键目录和职责

| 路径 | 职责 |
| --- | --- |
| `app/main.py` | FastAPI 生命周期、健康检查、API 注册、React 静态文件服务 |
| `app/config.py` | 所有环境变量定义和默认配置 |
| `app/api/` | HTTP/SSE API；路由统一挂载到 `/api` |
| `app/models/` | Tortoise ORM 数据模型 |
| `app/repositories/` | PostgreSQL 数据访问层 |
| `app/services/agent_service.py` | DataPM、工具注册、KunCode 调用和事件生成核心 |
| `app/services/model_factory.py` | 多模型供应商适配 |
| `app/services/sandbox_injection.py` | Agent/Skill/MCP/KunCode 配置注入容器 |
| `app/tasks.py` | Windows 本地任务与非 Windows Celery 任务 |
| `app/services/milvus_bootstrap.py` | Milvus 数据库、集合、维度和索引初始化 |
| `app/utils/milvus_client.py` | Embedding 调用和 Milvus CRUD/检索 |
| `frontend/src/stores/` | JWT、会话、SSE 任务和 UI 状态 |
| `frontend/src/components/` | 对话、布局、文件/计划/终端面板 |
| `frontend/src/admin/` | 管理后台页面和类型 |
| `data_analysis_sandbox.py` | 自定义同步/异步沙箱类型与工具代理 |
| `sandbox_proxy_extension.py` | Sandbox Manager 到容器 FastAPI/SSE 的代理 |
| `sandbox_image/` | 沙箱镜像、KunCode 配置及流式路由 |
| `sandbox_skills/` | 注入沙箱的内置技能和资源 |
| `scripts/start.ps1` | Windows 主服务、沙箱和本地 Ollama 生命周期 |
| `milvus/docker-compose.yml` | Milvus、etcd、MinIO |
| `embedding/docker-compose.yml` | GPU Ollama Embedding 服务 |
| `tests/test_task_regressions.py` | 当前后端关键任务回归测试 |

## 6. 配置与运行接口

### 6.1 端口

| 服务 | 宿主机端口 | 检查方式 |
| --- | ---: | --- |
| FastAPI + 生产前端 | 8090 | `GET /live`、`GET /ready` |
| Vite 开发服务器 | 5173 | 仅 `npm run dev` 时使用 |
| Sandbox Manager | 10001 | `GET /docs` |
| PostgreSQL | 5488 | 主服务 `/ready` 执行 `SELECT 1` |
| Redis | 6380 | 主服务 `/ready` 执行 `PING` |
| Milvus | 19530 | PyMilvus 连接 |
| Milvus HTTP health | 9091 | `GET /healthz` |
| Ollama OpenAI-compatible API | 9997 | `GET /v1/models` |

`scripts/start.ps1 -Action status` 对 PostgreSQL、Redis、Milvus 只显示端口监听状态，因此可能显示 `health=n/a`。真实依赖状态以 `http://127.0.0.1:8090/ready` 为准。

### 6.2 环境变量

- 本地机密放在 `.env`，模板放在 `.env.example`。
- `sandbox.env` 是 Sandbox Manager 配置。将它视为敏感配置，不要在输出中打印其值。
- 不要在代码里硬编码 API Key、JWT Secret、数据库密码或 Sandbox Bearer Token。
- Windows 启动脚本为主进程设置 `DEBUG=release` 和 `PYTHONUTF8=1`。
- 当前 Embedding 契约：模型 `qwen3-embedding:0.6b`、维度 `1024`、OpenAI-compatible `/v1/embeddings`。
- 当前 Mimo Base URL：`https://api.xiaomimimo.com/v1`。密钥只能从环境变量读取。

### 6.3 硬件要求

- Docker Desktop 必须可访问 Linux 容器和 Docker API。
- Ollama Compose 当前请求 NVIDIA GPU；本机目标环境为 8 GB 级独显，0.6B Embedding 模型适合常驻。
- 若 GPU Compose 不可用，`scripts/start.ps1` 可识别仓库上级目录的 `.runtime/ollama/bin/ollama.exe` 作为 Windows 原生回退，但 `.runtime/` 不属于仓库。
- 不要在未验证显存和向量维度迁移前替换更大的 Embedding 模型。

## 7. 启动命令

所有 Windows 命令默认从仓库根目录执行：

```powershell
cd E:\Full_Stack_Challenge\dataagent
```

### 7.1 首次安装

```powershell
uv sync
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
```

首次构建沙箱镜像：

```powershell
.\.venv\Scripts\runtime-sandbox-builder.exe data_analysis `
  --dockerfile_path .\sandbox_image\Dockerfile `
  --extension .\data_analysis_sandbox.py
```

首次启动 Ollama 后拉取模型：

```powershell
docker compose -f .\embedding\docker-compose.yml up -d
docker exec dataagent-ollama ollama pull qwen3-embedding:0.6b
```

### 7.2 日常快捷启动

先启动 Docker Desktop，然后执行：

```powershell
docker start data_analysis_postgres data_analysis_redis
docker compose -f .\milvus\docker-compose.yml up -d
docker compose -f .\embedding\docker-compose.yml up -d
.\scripts\start.ps1 -Action up
```

访问 `http://127.0.0.1:8090`。

### 7.3 状态、日志、重启和停止

```powershell
.\scripts\start.ps1 -Action status
.\scripts\start.ps1 -Action logs -Service main
.\scripts\start.ps1 -Action logs -Service sandbox
.\scripts\start.ps1 -Action restart
.\scripts\start.ps1 -Action down
```

`down` 只停止脚本管理的主服务、Sandbox Manager 和原生 Ollama，不删除 Docker 容器、镜像或数据卷。

### 7.4 前端开发模式

后端保持在 8090，然后执行：

```powershell
cd frontend
npm.cmd run dev
```

Vite 将 `/api` 和 `/ready` 代理到 8090。生产模式修改前端后必须重新执行 `npm.cmd run build`，否则 FastAPI 仍会提供旧的 `frontend/dist`。

## 8. 测试与验收命令

### 8.1 后端回归

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_task_regressions -v
```

### 8.2 前端质量门禁

```powershell
cd frontend
npm.cmd run lint
npm.cmd run build
```

PowerShell 可能禁止执行 `npm.ps1`，因此 Windows 下优先使用 `npm.cmd`。Vite 的大 chunk 警告当前不是构建失败，但新增大型依赖时应考虑懒加载。

### 8.3 运行时验收

```powershell
Invoke-RestMethod http://127.0.0.1:8090/ready | ConvertTo-Json -Depth 4
Invoke-WebRequest http://127.0.0.1:9091/healthz
Invoke-RestMethod http://127.0.0.1:9997/v1/models
```

涉及对话、KunCode、文件或管理后台的修改，不能只做单元测试；至少完成登录、会话创建、真实接口调用和最终状态检查。测试产生的知识条目、会话或文件应在验证后清理。

## 9. 编码规范

### 9.1 通用规则

- 以现有模块边界为准，保持修改聚焦，不做无关重构。
- 文本文件统一使用 UTF-8。Windows PowerShell 默认代码页可能把正确 UTF-8 显示成乱码；不要仅凭 `Get-Content` 的显示重写文件，优先使用 `Get-Content -Encoding utf8` 或检查真实 API 响应。
- 不要用字符串前缀判断路径归属；使用 `os.path.commonpath`、`Path.resolve().relative_to()` 等结构化路径检查。
- 日志不得包含密码、Token、API Key、完整授权头或用户敏感文件内容。
- 新行为必须有与风险相匹配的测试；修复任务流时优先补充 `tests/test_task_regressions.py`。

### 9.2 Python

- 使用 Python 3.12 类型语法，保持异步 API、服务和仓储调用链为 `async/await`。
- API 层负责认证、权限和请求/响应；Service 层负责业务编排；Repository 层负责数据库操作。
- 对会话、文件、任务流接口必须验证当前用户所有权；管理接口使用 `get_admin_user`。
- 不要在异步请求路径中加入阻塞等待。确需调用同步 Milvus/Docker SDK 时使用现有线程边界或 `asyncio.to_thread`。
- Windows 主进程使用 `AgentService.get_instance()` 共享生命周期资源；非 Windows Celery 任务使用独立实例并负责清理。不要混用，否则会关闭主进程数据库或 Redis 连接。
- 开发环境允许 `DB_AUTO_CREATE_SCHEMA=true`；生产环境必须通过迁移管理结构，不允许自动建表。

### 9.3 React/TypeScript

- TypeScript 严格模式开启，避免 `any`，共享契约放在 `frontend/src/types/` 或 `frontend/src/admin/types.ts`。
- 服务端状态和 SSE 逻辑集中在 Zustand store/API client，不要让多个组件各自实现任务状态机。
- 工具调用更新必须按 `tool_id` 原位合并，不能为流式参数重复创建终端条目。
- 使用现有 Button、Modal、Tabs、Notice 等组件和 Lucide 图标，保持当前紧凑、工作型管理界面。
- 文件预览和下载必须经过认证 API；不要重新开放无需认证的 raw workspace 路由。
- 不要创建新的旧式静态 `frontend/js`、`frontend/css` 或独立 HTML 管理页。

## 10. 修改前后的检查清单

修改前：

1. 执行 `git status --short`，保留用户已有未提交改动。
2. 阅读直接调用方和被调用方，特别是事件协议、权限和生命周期代码。
3. 确认运行方式是 Windows 宿主进程还是 Docker 容器，不要混淆路径和端口。

修改后：

1. 执行相关单元测试、前端 lint/build 和 `git diff --check`。
2. 前端修改后重新生成 `frontend/dist` 供本地验证，但不要提交 dist。
3. 后端运行代码修改后重启 `scripts/start.ps1` 管理的服务。
4. 检查 `/ready`，并验证任务结束后终端不再 `running`、加载状态不再转圈。
5. 涉及文件生成时，确认对话给出明确完成答复和相对文件路径，右侧文件页能看到并打开实际文件。

## 11. 禁止修改或破坏的内容

除非用户明确授权并说明迁移/备份方案，否则禁止：

- 修改、提交或输出 `.env`、真实 API Key、JWT Secret、数据库密码和 Sandbox Bearer Token。
- 删除或重建 PostgreSQL、Redis、Milvus、Ollama 的数据卷。
- 删除 `user_uploads/`、`sessions_mount_dir/`、知识库或用户会话数据。
- 清理或改动同一 Docker Desktop 中的 Dify 项目容器、镜像、网络和卷。
- 对不属于 DataAgent 的 Docker 资源执行批量 prune、删除或重建。
- 将 Milvus 维度从 1024 改为其他值，或替换 Embedding 模型后直接复用非空集合。必须先设计重建和数据回填流程。
- 绕过 JWT、管理员权限、会话所有权或工作区路径检查。
- 让宿主机直接执行模型生成的 Shell/Python；用户代码和 KunCode 必须在沙箱容器内运行。
- 仅凭 PID 文件强制结束进程；必须核验进程名称和命令行，防止 PID 被 Windows 系统进程复用。
- 恢复已废弃的旧静态前端，或让 FastAPI 再次加载 `frontend/js/app.js` 一类旧文件。
- 提交 `.venv/`、`node_modules/`、`frontend/dist/`、日志、PID、用户文件、会话挂载目录、模型文件或 Docker 数据。
- 回退、覆盖或格式化用户未提交且与当前任务无关的修改。

## 12. 已知边界与判断原则

- `README.md` 同时保留了部分 Linux/历史部署说明；Windows 当前权威启动入口是 `scripts/start.ps1` 和本文件的命令。
- Milvus 与 Embedding 对基础对话不是硬阻塞依赖，故 `/ready` 可能在它们 degraded 时仍返回主服务可用；知识库功能则不可视为正常。
- 管理后台已经重构，但用户管理、审计日志、提示词版本历史和回滚仍不是完整功能，不要在未检查代码前假定存在。
- 当前没有独立前端测试套件，前端最低验证是 lint、TypeScript/Vite build 和真实浏览器流程。
- KunCode 输出可能长时间流式返回。超时、错误和非零退出必须明确转为失败事件，不能以“接口仍连接”代表成功。
- 若文档、注释出现乱码，先区分终端代码页、源码编码和数据库历史数据；不要批量转码整个仓库。

## 13. 常见任务定位

| 任务 | 首先检查 |
| --- | --- |
| 对话卡住或状态不结束 | `agent_service.py`、`tasks.py`、`conversation.py`、`session.ts` |
| KunCode 无输出/调用失败 | `data_analysis_sandbox.py`、`kuncode_stream.py`、`sandbox_proxy_extension.py`、沙箱日志 |
| 终端重复命令或一直 running | 事件 `tool_id`、`phase`、`execution_status` 和 `TerminalPanel.tsx` |
| 生成文件未显示 | `generated_files`、`FilesPanel.tsx`、sandbox binding 和 workspace API |
| 管理后台接口问题 | `frontend/src/admin/`、`frontend/src/api/admin.ts`、`app/api/sandbox.py` |
| 提示词乱码 | `system_prompt.md`、`app/api/system_prompt.py`、数据库 `system_prompts` 记录 |
| 知识库 degraded | `/ready`、Ollama `/v1/models`、Milvus health、集合维度 |
| 启动/停止异常 | `scripts/start.ps1`、`.pids/`、`logs/*.err.log`，先核验真实监听进程 |

完成工作时，应向用户说明修改文件、真实验证结果、未运行的测试和仍存在的风险；不要把“端口已监听”表述为“完整功能已通过”。
