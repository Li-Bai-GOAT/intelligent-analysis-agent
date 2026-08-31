# DataAgent 项目目录地图

本页按目录说明当前项目的职责、数据边界与日常使用方式。代码、运行时数据和历史产物刻意分开，方便定位问题，也避免将本地数据误提交到仓库。

## 顶层分区

```text
dataagent/
├── app/                    后端业务与 API
├── frontend/               React 前端
├── sandbox_image/          Docker 沙箱镜像
├── sandbox_skills/         可注入的分析技能
├── scripts/                运维与数据维护脚本
├── tests/                  自动化回归测试
├── mcp_knowledge_server/   MCP 知识库服务
├── milvus/、embedding/     向量检索与 Embedding 基础设施
├── docs/                   可追踪的项目文档
├── artifacts/              验收证据与历史归档
└── logs/、user_uploads/、sessions_mount_dir/  本地运行时数据
```

## 源代码与服务目录

| 目录 | 职责 | 常用入口 |
| --- | --- | --- |
| `app/` | FastAPI 后端、领域模型、数据访问、Agent 编排与任务执行。 | `app/main.py`、`app/services/agent_service.py`、`app/tasks.py` |
| `app/api/` | 认证、会话、对话、文件、计划、知识库、系统提示词和沙箱管理 API。 | 路由统一挂载于 `/api`。 |
| `app/models/` | Tortoise ORM 模型。 | 用户、会话、消息、知识、文件、沙箱配置等。 |
| `app/repositories/` | PostgreSQL 数据访问层。 | 业务数据的读写边界。 |
| `app/services/` | DataPM、模型适配、沙箱注入、清理与业务编排。 | 不在 API 层堆叠业务逻辑。 |
| `frontend/` | React 19 + TypeScript + Vite 前端工程。 | `frontend/src/App.tsx`、`npm.cmd run dev`。 |
| `frontend/src/admin/` | 管理后台。 | 知识库、提示词、Agent、Skill、MCP 管理页面。 |
| `frontend/src/components/` | 认证、聊天、布局及计划/文件/终端面板。 | UI 组件与交互展示。 |
| `frontend/src/stores/` | Zustand 状态管理。 | JWT、会话、SSE 任务和 UI 状态。 |
| `frontend/src/types/` | 前端领域类型与 SSE 事件契约。 | 修改任务流前应优先核对。 |
| `mcp_knowledge_server/` | 面向知识库检索的 MCP 服务。 | 作为可扩展工具接入点。 |

## 执行环境与基础设施

| 目录 | 职责 | 说明 |
| --- | --- | --- |
| `sandbox_image/` | 数据分析 Docker 镜像和容器内运行配置。 | 用户任务与 KunCode 在此隔离环境执行。 |
| `sandbox_skills/` | 内置 Skill、参考资料、模板与资源。 | Markdown 多为运行时 Skill 说明，不属于项目决策文档。 |
| `scripts/` | Windows 启动、数据初始化、同步与修复脚本。 | 日常服务生命周期入口是 `scripts/start.ps1`。 |
| `milvus/` | Milvus、etcd、MinIO 的 Docker Compose 配置。 | 向量索引是可重建的派生数据。 |
| `embedding/` | Embedding 服务的容器配置。 | 与本地 Ollama 回退方式共同支持向量化。 |

## 文档、测试与交付物

| 目录 | 职责 | 维护规则 |
| --- | --- | --- |
| `docs/` | 规划、整改、验收和项目结构文档。 | 从 [docs/README.md](README.md) 开始查找。 |
| `docs/plans/` | 尚待执行或作为历史参考的改造方案。 | 实施前必须以当前代码和验证结果核实。 |
| `docs/reports/` | 已完成的验证报告。 | 记录范围、结果与未覆盖项。 |
| `artifacts/` | E2E 输出、审查证据和历史归档。 | 与相关输入/输出放在一起，见 [artifacts/README.md](../artifacts/README.md)。 |
| `tests/` | 后端回归测试。 | 任务流改动优先补充 `test_task_regressions.py`。 |

## 本地运行时目录

| 目录 | 内容 | Git 状态 |
| --- | --- | --- |
| `logs/` | 当前服务日志和 `legacy/` 下的历史日志。 | 忽略，不提交。 |
| `user_uploads/` | 用户上传文件。 | 忽略，不提交或清空。 |
| `sessions_mount_dir/` | 会话绑定的容器工作区持久化数据。 | 忽略，不提交或清空。 |
| `.pids/` | `start.ps1` 管理的进程 PID 文件。 | 忽略。 |
| `.venv/`、`__pycache__/`、`.pytest_cache/` | 本地 Python 环境与缓存。 | 可再生成，不提交。 |

## 根目录关键文件

| 文件 | 用途 |
| --- | --- |
| `README.md` | 项目主体介绍、架构、主流程、运行与验证入口。 |
| `AGENTS.md` | 当前运行架构、端口、数据边界和开发约束的权威基线。 |
| `system_prompt.md` | DataPM 默认系统提示词；数据库记录可覆盖默认值。 |
| `pyproject.toml`、`uv.lock` | Python 依赖与锁定版本。 |
| `.env.example` | 可提交的环境变量模板。 |
| `.env`、`sandbox.env` | 仅本地使用的敏感配置，不得提交或输出；模板分别为 `.env.example`、`sandbox.env.example`。 |
| `data_analysis_sandbox.py`、`sandbox_proxy_extension.py` | 自定义沙箱和流式代理扩展。 |
| `start.sh`、`start_sandbox_server.sh` | 历史 Linux 启动入口；当前 Windows 主线以 `scripts/start.ps1` 为准。 |

## 导航建议

1. 想理解产品和架构：先读根目录 [README](../README.md)。
2. 想修改任务流：查看 `app/services/agent_service.py`、`app/tasks.py`、`app/api/conversation.py`、`frontend/src/stores/session.ts` 和 `frontend/src/types/index.ts`。
3. 想修改文件交付：查看 `app/api/files.py`、前端文件面板和会话绑定逻辑。
4. 想调整沙箱能力：查看 `sandbox_image/`、`data_analysis_sandbox.py`、`sandbox_skills/` 和管理后台的注入接口。
5. 想排查本地问题：先执行 `scripts/start.ps1 -Action status`，再读取 `logs/`，不要将用户数据或运行时目录当作源代码修改。
