# Data Agent

**企业级智能数据分析平台** - 基于大语言模型 + 代码沙箱的自然语言数据处理解决方案

通过对话式交互，让业务人员也能完成专业的数据清洗、统计分析、可视化报告等工作。

---

## ✨ 核心能力

### 📊 数据分析
| 能力 | 说明 |
|------|------|
| **数据探索** | 自动识别数据结构、字段类型、缺失值分布、数据质量评估 |
| **描述性统计** | 均值、中位数、标准差、分位数、分布分析 |
| **相关性分析** | Pearson/Spearman 相关系数、热力图可视化 |
| **回归分析** | 线性回归、多元回归、逻辑回归 |
| **假设检验** | t 检验、卡方检验、ANOVA 方差分析 |

### 🔧 数据处理
| 能力 | 说明 |
|------|------|
| **数据清洗** | 缺失值处理、异常值检测、重复数据去除、格式标准化 |
| **数据转换** | 透视表、数据聚合、分组统计、时间序列处理 |
| **多源整合** | 跨文件关联、多表合并、VLOOKUP 逻辑、字段映射 |
| **数据库操作** | SQL 查询生成、数据提取、ETL 流程 |

### 📈 高级分析
| 能力 | 说明 |
|------|------|
| **聚类分析** | K-Means、层次聚类、DBSCAN |
| **分类预测** | 决策树、随机森林、XGBoost |
| **时间序列** | 趋势分解、季节性分析、ARIMA 预测 |
| **因果分析** | 归因分析、连环替代法、杜邦分析、贡献度分析 |
| **异常检测** | 统计异常、时序异常、离群点检测 |

### � 可视化与报告
| 能力 | 说明 |
|------|------|
| **图表生成** | 折线图、柱状图、饼图、散点图、热力图、桑基图、漏斗图 |
| **交互式报告** | HTML 报告、Chart.js 可视化、TailwindCSS 美化 |
| **自动化报告** | 周报/月报模板、管理层摘要、详细分析报告 |
| **Office 导出** | Excel 多 Sheet 输出、Word 文档、PPT 演示文稿 |

---

## �️ 技术架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           用户浏览器 (Web UI)                            │
│         对话交互 · 文件上传 · 任务预览确认 · 结果展示与下载               │
└─────────────────────────────────────────────────────────────────────────┘
                                      │ HTTP/SSE
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        FastAPI 后端服务 (:8090)                          │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────┐ ┌──────────────────┐  │
│  │ 会话管理    │ │ 文件服务     │ │ 任务调度    │ │ 流式响应 (SSE)   │  │
│  │ /sessions   │ │ /files       │ │ /conversation│ │ 实时输出推送     │  │
│  └─────────────┘ └──────────────┘ └─────────────┘ └──────────────────┘  │
│                                      │                                   │
│  ┌───────────────────────────────────┴─────────────────────────────┐    │
│  │                 AgentService (ReAct Agent)                       │    │
│  │  · AgentScope 智能体框架        · 多轮对话状态管理               │    │
│  │  · DeepSeek/GPT 大模型接入      · 计划笔记本 (Plan Notebook)     │    │
│  │  · 工具自动调用 (Function Call) · 中断恢复机制                   │    │
│  └──────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
          │                        │                          │
          ▼                        ▼                          ▼
┌──────────────────┐  ┌────────────────────┐  ┌────────────────────────────┐
│   PostgreSQL     │  │      Redis         │  │     Celery Worker          │
│  · 会话持久化    │  │  · 任务状态缓存    │  │  · 异步任务执行            │
│  · 消息历史存储  │  │  · 中断信号传递    │  │  · 任务超时管理            │
│  · Agent 状态    │  │  · 预览确认状态    │  │  · 自动继续机制            │
└──────────────────┘  └────────────────────┘  └────────────────────────────┘
                                                              │
┌─────────────────────────────────────────────────────────────┴───────────┐
│                   AgentScope Runtime Sandbox Server                      │
│                           (代码沙箱 :10000)                              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  DataAnalysisSandbox (自定义沙箱扩展)                             │   │
│  │  · run_kuncode    → 委派 KunCode AI 执行数据分析任务              │   │
│  │  · run_ipython    → 直接执行 Python 代码                          │   │
│  │  · run_shell      → 执行 Shell 命令                               │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                    │                                     │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              隔离 Docker 容器 (数据分析运行时)                     │   │
│  │  预装: pandas · numpy · matplotlib · seaborn · scikit-learn      │   │
│  │        scipy · statsmodels · openpyxl · xlrd · plotly            │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                    │                                     │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    SKILL 技能包 (可扩展分析能力)                   │   │
│  │  · 连环替代法   · 异常检测     · 聚类分析    · 相关性分析         │   │
│  │  · 贡献度分析   · 决策树规则   · 漏斗分析    · AB 对比分析        │   │
│  │  · Chart.js 图表生成  · Excel/Word/PPT 导出                       │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │ MCP Protocol
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     MCP Knowledge Server (:8765)                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  search_knowledge(query, category, top_k)                         │   │
│  │  类别: 计算公式 | 概念定义 | 分析方法 | 报告模板                   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                    │                                     │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │           Milvus 向量数据库 + Embedding 模型                      │   │
│  │           企业知识库 · 业务公式 · 分析模板                        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🎯 技术亮点

### 双 Agent 协作架构
| Agent | 角色 | 职责 |
|-------|------|------|
| **DataPM** | 数据产品经理 | 需求理解、计划制定、任务拆解、质量把控 |
| **DataAnalyst** | 数据分析师 | 代码实现、数据处理、报告生成、结果输出 |

### Human-in-the-Loop (HITL)
- **计划预览**：复杂任务自动生成分析计划，用户可编辑确认
- **任务预览**：代码执行前展示任务描述，支持修改后执行
- **中断恢复**：支持随时中断任务，保留已完成的中间结果

### 安全沙箱执行
- **Docker 隔离**：代码在独立容器中执行，保护主机安全
- **资源限制**：CPU、内存、执行时间限制
- **权限控制**：禁止危险操作 (rm -rf、系统修改等)

### 可扩展 SKILL 体系
- **插件化设计**：分析算法封装为独立 SKILL，即插即用
- **知识沉淀**：业务公式、分析模板、最佳实践可配置化
- **MCP 集成**：通过 Model Context Protocol 接入企业知识库

---

## 📁 支持的数据格式

| 类型 | 格式 |
|------|------|
| **表格数据** | Excel (.xlsx, .xls)、CSV、TSV、Parquet |
| **文本数据** | JSON、XML、TXT、Markdown |
| **数据库** | MySQL、PostgreSQL、SQLite、通过代码连接更多 |

---

## 🚀 快速开始

### 环境要求
- Python 3.12+
- Docker（代码沙箱环境）
- PostgreSQL、Redis

### 安装部署

```bash
# 0. 安装docker和必须的镜像和容器

## redis
docker pull redis:7-alpine

docker run -d \
  --name data_analysis_redis \
  --restart always \
  -p 6380:6379 \
  -v data_analysis_redis_data:/data \
  -e REDIS_PASSWORD=password \
  redis:7-alpine \
  redis-server --requirepass password --appendonly yes


## pgsql
docker pull postgres:16

docker run -d \
  --name data_analysis_postgres \
  --restart always \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=data_analysis \
  -v data_analysis_pgdata:/var/lib/postgresql/data \
  -p 5488:5432 \
  --restart unless-stopped \
  postgres:16


## 安装 Milvus：
wget https://github.com/milvus-io/milvus/releases/download/v2.6.9/milvus-standalone-docker-compose.yml -O docker-compose.yml

wget https://raw.githubusercontent.com/milvus-io/milvus/master/configs/milvus.yaml -O milvus.yaml

### 编辑 milvus.yaml，找到 common.security 部分，修改为：
common:
  security:
    authorizationEnabled: true  # 将 false 改为 true

### 修改 docker-compose.yml，在 standalone 服务中添加卷映射：
volumes:
  - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/milvus:/var/lib/milvus
  - ./milvus.yaml:/milvus/configs/milvus.yaml  # 添加这一行

### 启动
sudo docker compose up -d

### 停止
sudo docker compose down


# 1. 安装依赖
uv sync


# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填写数据库、API Key 等配置


# 3. 构建沙箱镜像（首次部署）
cd sandbox_image

runtime-sandbox-builder data_analysis \
    --dockerfile_path Dockerfile \
    --extension ../data_analysis_sandbox.py

## 编辑 sanbox.env中的redis和API Key
vim sandbox.env


# 4. 启动沙箱服务
./start_sandbox_server.sh start


# 5. 启动主服务
./start.sh start


# 6. 构建向量数据库集合：
python scripts/rebuild_milvus_from_postgres.py
```

访问 **http://localhost:8090** 开始使用

### 服务管理

```bash
./start.sh start    # 启动所有服务 (API + Celery + MCP)
./start.sh stop     # 停止服务
./start.sh restart  # 重启服务
./start.sh status   # 查看状态
```

---

## 📖 使用示例

**数据探索**
> "帮我看看这个 Excel 文件的数据结构，有哪些字段，数据质量怎么样"

**统计分析**
> "计算各产品线的销售额均值、中位数，并按地区分组统计"

**可视化**
> "画一个折线图展示过去12个月的销售趋势，按产品类型分组"

**数据处理**
> "把这两个表按客户ID关联，合并成一个完整的客户订单表"

**高级分析**
> "用连环替代法分析本月销售额下降的原因，分解价格、销量、结构因素的贡献"

**报告生成**
> "生成一份本周销售数据的分析报告，包含趋势图表和异常点标注"

---

## 📂 目录结构

```
├── app/                         # 后端服务
│   ├── api/                     # API 路由 (会话、文件、对话、计划等)
│   ├── services/                # 业务逻辑 (AgentService、文件服务等)
│   ├── models/                  # 数据模型 (Tortoise ORM)
│   └── repositories/            # 数据访问层
├── frontend/                    # Web 前端
│   ├── index.html               # 主页面
│   ├── js/app.js                # 前端逻辑
│   └── css/style.css            # 样式
├── mcp_knowledge_server/        # MCP 知识库服务
├── sandbox_image/               # 沙箱 Docker 镜像配置
├── system_prompt.md             # DataPM 系统提示词
├── analyst_prompt.md            # DataAnalyst 系统提示词
├── data_analysis_sandbox.py     # 自定义沙箱扩展
└── start.sh                     # 服务管理脚本
```

---

## 🔧 配置说明

| 文件 | 说明 |
|------|------|
| `.env` | 环境变量 (数据库、API Key、模型配置等) |
| `sandbox.env` | 沙箱服务配置 |

---

## 🛠️ 技术栈

| 组件 | 技术选型 |
|------|----------|
| **后端框架** | FastAPI + Celery |
| **智能体框架** | AgentScope (ReAct Agent) |
| **大模型** | DeepSeek / GPT-4 / Claude (可配置) |
| **数据库** | PostgreSQL + Redis |
| **向量数据库** | Milvus |
| **代码沙箱** | AgentScope Runtime + Docker |
| **前端** | 原生 JS + Prism.js + SheetJS |

---

## 📜 License

MIT License