# 模型 API 审计与费用保护实施计划

## 目标

为 DataAgent 建立可追溯的模型 API 调用链，覆盖后端直连模型、Docker 沙箱中的 KunCode 调用，以及统一网关转发的真实外部请求。

系统最终应能够回答：

- 哪个任务、会话、沙箱和容器触发了请求；
- 请求使用了哪个 Provider 和模型；
- 实际发往上游的模型是否与项目配置一致；
- 请求何时开始、何时结束、是否重试、是否超时或取消；
- 请求来自哪个容器、User-Agent 和网关入口；
- 消耗了多少 Token；
- 2026 年 7 月 22 日和 2026 年 9 月 24 日的异常调用是否来自 DataAgent。

审计日志用于追踪来源，费用限制用于防止异常扣费。两者需要同时建设。

## 关键设计原则

1. 后端日志记录“项目准备发起的请求”。
2. 沙箱日志记录“哪个任务启动了 KunCode”。
3. 审计网关记录“实际发往模型供应商的请求”。
4. 只记录必要的请求元数据，不记录 API Key 明文、Authorization、完整 Prompt、Cookie 或用户文件内容。
5. 所有时间统一保存为 UTC ISO 8601 格式，并保留请求的本地时区信息用于排查。
6. 使用 trace_id 串联后端、任务、沙箱、KunCode 和网关日志。
7. 重试记录为同一个逻辑请求下的多个实际尝试，不能把重试误计为多个用户任务。
8. X-Device-Fingerprint、X-OS-Version 和 User-Agent 属于网关鉴权、路由和设备上下文信息，应作为审计字段保存，但不能代替真实出口审计。

## 当前项目中的接入位置

后端直接模型调用重点接入：

- app/services/model_factory.py
- RetryingStreamingModel
- AgentScope 模型创建、流式响应、异常和重试处理位置

沙箱调用链重点接入：

- data_analysis_sandbox.py
- app/services/sandbox_injection.py
- sandbox_image/routers/kuncode_stream.py
- sandbox_image/kuncode.json
- Docker Compose 或沙箱启动配置中的环境变量和网络设置

KunCode 在容器内执行，宿主后端只能直接观察沙箱任务的开始和结束。因此，仅在 model_factory.py 或宿主日志中记录，不能百分之百证明容器已经向 Mimo 发出了 HTTP 请求。

## 第一阶段：建立统一请求审计模块

新增统一模块，例如：

~~~text
app/observability/model_audit.py
~~~

日志采用 JSON Lines 格式，默认写入：

~~~text
logs/model-audit/requests.log
~~~

建议配置：

~~~text
MODEL_AUDIT_ENABLED=true
MODEL_AUDIT_LOG_PATH=/var/log/dataagent/model-audit/requests.log
MODEL_AUDIT_RETENTION_DAYS=90
~~~

每次请求至少生成以下事件：

~~~text
request_started
request_finished
request_failed
request_cancelled
~~~

建议字段：

~~~json
{
  "event": "request_finished",
  "request_id": "req_xxx",
  "trace_id": "trace_xxx",
  "parent_task_id": "task_xxx",
  "session_id": "session_xxx",
  "source": "backend|sandbox|kuncode|gateway",
  "entrypoint": "conversation_async|run_kuncode",
  "provider": "mimo",
  "requested_model": "mimo-v2.5-pro",
  "actual_model": "mimo-v2.5-pro",
  "base_url_host": "api.xiaomimimo.com",
  "request_type": "chat_completion",
  "stream": true,
  "attempt": 1,
  "http_status": 200,
  "started_at": "2026-09-24T12:00:00Z",
  "finished_at": "2026-09-24T12:00:08Z",
  "latency_ms": 8000,
  "prompt_tokens": 1000,
  "completion_tokens": 5000,
  "total_tokens": 6000,
  "result": "success",
  "error_type": null,
  "user_agent": "dataagent-sandbox/1.x",
  "device_type": "docker",
  "os_version": "linux-container",
  "api_key_fingerprint": "sha256:xxxx"
}
~~~

必须脱敏：

- API Key 只保存 SHA-256 指纹或末四位；
- 删除 Authorization、Cookie 和其他认证 Header；
- 不保存完整 Prompt、工具输入、上传文件和模型响应正文；
- 记录错误类型和摘要时避免把请求头或密钥写入异常文本。

日志应使用 UTF-8、按天或按大小轮转，并通过 Docker volume 持久化，避免容器删除后审计记录丢失。

## 第二阶段：接入后端模型调用

在 app/services/model_factory.py 和 RetryingStreamingModel 周围加入审计包装层。

需要覆盖：

- 请求开始、成功、失败、超时和取消；
- HTTP 或 SDK 异常；
- 流式响应正常结束和中途断开；
- 后端关闭时的任务取消；
- 每一次重试。

请求标识规则：

~~~text
request_id：一次逻辑模型请求
attempt：该逻辑请求的第几次实际 HTTP 尝试
trace_id：贯穿整个用户任务和沙箱调用链
~~~

成功响应中的 Token 用量优先取供应商返回值；供应商没有返回时，再使用项目已有的 Token 估算值，并标记 usage_source=estimated。

对于流式请求，只有收到结束标记并成功解析响应时才记为 success。连接中途断开时记为 partial 或 failed，并保存已经收到的 Token 数量（如果可获得）。

## 第三阶段：建立后端到沙箱的关联链

向沙箱环境注入以下上下文：

~~~text
DATAAGENT_TRACE_ID
DATAAGENT_TASK_ID
DATAAGENT_SESSION_ID
DATAAGENT_SANDBOX_ID
DATAAGENT_AUDIT_SOURCE=sandbox
~~~

宿主侧记录：

~~~text
sandbox_started
kuncode_started
kuncode_finished
kuncode_failed
kuncode_cancelled
~~~

每条沙箱记录需要包含 trace_id、task_id、session_id、sandbox_id、容器 ID、KunCode 使用的模型配置、启动和结束时间、退出码以及超时或异常原因。

这一层用于回答“哪个 DataAgent 任务启动了 KunCode”。它本身不能保证 KunCode 真的访问了上游 API，因此必须继续接入出口层。

## 第四阶段：增加统一模型审计网关

新增内部服务：

~~~text
model-audit-gateway
~~~

调用路径：

~~~text
DataAgent 后端 ─────┐
                    ├──> model-audit-gateway ───> Mimo 或其他模型 API
Docker KunCode ─────┘
~~~

配置示意：

~~~text
MIMO_BASE_URL=http://model-audit-gateway:8080/v1
MIMO_UPSTREAM_BASE_URL=https://api.xiaomimimo.com/v1
~~~

网关需要：

- 接收后端和沙箱请求；
- 记录真实请求时间、来源容器 IP、User-Agent、X-Device-Fingerprint 和 X-OS-Version；
- 从请求体解析实际 model；
- 记录上游 HTTP 状态码和响应耗时；
- 解析上游 Token 用量；
- 支持 SSE 流式转发；
- 转发取消和超时；
- 移除或遮蔽敏感 Header；
- 将请求转发到真实模型供应商。

网关每条记录至少应包含：

~~~text
trace_id
request_id
source_ip
container_id
user_agent
requested_model
upstream_model
upstream_status
upstream_latency
token_usage
~~~

如果上游网关要求特定 Header，可以统一注入：

~~~text
User-Agent: dataagent-sandbox/<version>
X-Device-Fingerprint: dataagent-instance-<hash>
X-OS-Version: linux-container
~~~

这些 Header 应使用明确的项目和实例标识，不应伪造真实硬件信息，也不应写入 API Key。

网关是确认真实外部 API 请求的最强证据。它可以识别：

- 项目配置为 mimo-v2.5-pro，实际请求却是 mimo-v2.6-pro-ultraspeed；
- 请求来自未知容器或未知 User-Agent；
- 请求不带合法的 DataAgent trace_id；
- 同一 API Key 指纹出现在多个设备或出口；
- 请求在前端关闭后仍由后台任务继续发出。

## 第五阶段：模型白名单和费用保护

审计功能只能记录，不能阻止异常扣费，因此要增加调用保护。

默认配置建议：

~~~text
ALLOWED_MODEL_PROVIDERS=deepseek
ALLOWED_KUNCODE_MODELS=deepseek/deepseek-v4-flash
DISABLE_MIMO=true
~~~

重新启用 Mimo 时增加：

- Provider 和模型白名单；
- 单任务、单会话、单用户每日 Token 上限；
- 最大并发请求数；
- 单请求最大执行时间；
- 重试次数上限；
- 单日预算阈值；
- 超限自动熔断；
- 服务关闭时取消全部后台模型任务。

模型调用前执行准入检查：

~~~text
provider 是否允许
model 是否允许
当前任务 Token 预算是否足够
当前用户额度是否足够
当前并发数是否超过限制
~~~

超过限制时在发出 HTTP 请求前直接拒绝，避免请求产生费用后才发现超限。

## 第六阶段：查询和管理接口

新增受保护的管理接口：

~~~text
GET /api/admin/model-audits
~~~

支持按 start_time、end_time、provider、model、source、session_id、task_id、request_id 和 result 筛选。

必须支持以下排查查询：

~~~text
查询 2026-07-22 的所有 Mimo 请求
查询 2026-09-24 的所有模型请求
查询实际模型为 mimo-v2.6-pro-ultraspeed 的请求
查询所有来自 sandbox 或 kuncode 的请求
查询 requested_model 与 actual_model 不一致的请求
查询没有 trace_id 的外部模型请求
~~~

接口必须进行管理员鉴权，并继续隐藏 API Key、Prompt、Cookie 和完整响应内容。

## 第七阶段：测试和验收

### 后端直接调用

- 生成 request_started 和 request_finished；
- 记录 Provider、模型、状态码、耗时和 Token；
- 失败请求有错误类型；
- 重试有独立 attempt；
- API Key 和 Prompt 不出现在日志中。

### Docker KunCode 调用

- 宿主任务、沙箱、KunCode 和网关拥有同一个 trace_id；
- 可以查到容器 ID；
- KunCode 正常结束、异常退出、超时和取消均有记录；
- 能区分宿主后端调用和沙箱调用。

### 流式和取消

- SSE 正常结束记录为 success；
- 中途断开记录为 partial 或 failed；
- 前端关闭后仍在执行的后台任务仍能留下完整审计记录；
- 应用关闭时后台任务收到取消并记录 request_cancelled。

### 模型一致性

- 项目配置模型、沙箱模型、网关实际模型分别记录；
- 若出现 mimo-v2.6-pro-ultraspeed，可以明确显示它是在哪一层首次出现；
- 发现未知模型时触发告警或直接拒绝请求。

### 费用保护

- 超过 Token、并发或预算限制时，请求不会发往上游；
- Mimo 被禁用时，所有 Mimo 请求在本地被拒绝；
- 重试次数受控；
- 服务关闭后不会遗留未注册的后台模型任务。

## 推荐实施顺序

### P0：立即保护

- 吊销并替换已暴露的 Mimo API Key；
- 默认禁用 Mimo；
- 增加 Provider 和模型白名单；
- 限制重试、并发和单任务 Token。

### P1：快速建立可追溯性

- 实现统一 JSONL 审计模块；
- 接入后端模型工厂；
- 接入重试、流式、取消和异常；
- 增加 request_id 和 trace_id；
- 配置日志轮转和 Docker volume。

### P2：覆盖沙箱

- 注入任务、会话、沙箱和容器上下文；
- 记录 KunCode 生命周期；
- 串联宿主日志和沙箱日志。

### P3：确认真实外部请求

- 部署模型审计网关；
- 让后端和沙箱统一经过网关；
- 支持 Mimo 的流式转发；
- 记录实际模型、源 IP、User-Agent、Token 和状态码。

### P4：管理和长期治理

- 增加管理查询接口；
- 增加未知模型、未知出口和预算超限告警；
- 定期归档或删除过期审计日志；
- 将关键审计摘要写入数据库，保留 JSONL 作为原始流水。

## 最终验收标准

完成后，系统必须能够通过一个 trace_id 从用户任务追踪到：

~~~text
用户请求
  -> 后端任务
  -> 模型准入检查
  -> 沙箱或后端模型调用
  -> KunCode 执行
  -> 审计网关
  -> 上游模型 API
  -> Token、状态和费用相关摘要
~~~

并且能够明确回答：

> 2026 年 9 月 24 日的 Mimo 调用是否由当前 DataAgent、某个旧容器、某个未知本地进程，还是其他远程客户端产生。

## 当前实施状态（2026-10-08）

本计划的实施结果分为“已完成”“部分完成”和“尚未完成”。本节记录当前代码真实状态，避免把宿主侧记录误认为模型供应商出口记录。

### 已完成

- 已建立统一 JSONL 模型审计模块，记录请求开始、成功、失败、部分失败和取消事件。
- 已接入后端 AgentScope 模型调用，覆盖流式请求、异常、重试、取消、请求 ID、尝试次数、Token 用量和 API Key 脱敏。
- 已加入 Provider、模型、Mimo 开关、单请求 Token、用户每日 Token 和并发准入控制。
- 已加入 JSONL 日轮转、保留期限清理和管理员查询接口 GET /api/admin/model-audits。
- 已完成管理员鉴权、查询条件转发和前端审计列表页面。
- 已向 KunCode 请求传递 trace、任务、会话和沙箱上下文，并记录 KunCode 开始、完成、失败、取消和模型准入拒绝事件。
- 已统一主模型、上下文压缩模型和沙箱模型的 Mimo 配置，当前模型为 mimo-v2.6-pro。
- 已减少沙箱模型配置重复：宿主侧同步/异步沙箱共用运行环境生成逻辑，空的沙箱模型配置会从当前 Provider 和模型名称派生。
- 已更新 KunCode 镜像默认配置、运行时配置和模型白名单，并通过配置版本使旧配置容器失效。
- 已通过 Python 编译检查、后端审计/任务回归测试、前端 lint/build、差异空白检查和 Mimo 实际接口验证。

### 部分完成

- 当前审计可以证明后端或沙箱准备调用的模型，以及 KunCode 的生命周期；但 actual_model 对宿主和沙箱调用主要来自 SDK 响应或请求配置。
- 当前审计记录了模型主机、耗时和 Token；没有统一拿到每次上游 HTTP 状态码、源 IP、容器 ID、User-Agent、X-Device-Fingerprint 和 X-OS-Version。
- trace 已在后端任务、模型调用和 KunCode 请求之间传递，但还没有经过统一出口网关，因此无法用一个 trace 完整关联到供应商收到的真实 HTTP 请求。
- 重试、并发和 Token 限制已实现；预算金额、价格表、费用累计、预算熔断和告警尚未形成完整闭环。
- 审计日志写入本地 JSONL 并支持轮转；尚未通过 Docker volume 或数据库保存关键审计摘要，也没有集中式多实例查询存储。
- 每日用户 Token 统计当前保存在进程内存中，服务重启或多进程部署时不能作为可靠的全局额度账本。

### 尚未完成

- 尚未实现 model-audit-gateway，后端和 KunCode 仍可直接访问 Mimo，因此没有真实出口层审计。
- 尚未实现网关的 SSE 转发、上游响应状态记录、实际模型解析、来源容器信息采集和上游取消/超时转发。
- 尚未实现未知模型、未知出口、模型不一致、预算超限和异常调用的告警通知。
- 尚未把关键审计摘要写入 PostgreSQL，也没有提供按 trace 聚合展示“用户请求 → 后端任务 → 沙箱 → KunCode → 上游 API”的完整视图。
- 尚未完成针对真实 Docker KunCode 的端到端验收，包括容器 ID、真实上游请求、超时、取消、服务关闭和旧容器复用场景。
- 计划中的“吊销并替换已暴露 API Key”需要在 Mimo 控制台执行，代码仓库无法替代这项外部操作；当前密钥仍应按已暴露密钥处理。
- 计划建议的默认禁用 Mimo 未采用，因为当前用户明确要求启用 Mimo；现状是通过白名单和准入限制 Mimo，而不是默认关闭。

### 后续优先级

1. 先吊销并替换当前 API Key，并确认旧 Key 已失效。
2. 增加或部署统一模型审计网关，让后端和沙箱只访问网关地址。
3. 将每日额度和费用统计迁移到 Redis/PostgreSQL，并补充预算熔断和告警。
4. 完成真实 Docker、SSE、取消、超时和服务关闭场景的端到端验收。
5. 将关键审计摘要按 trace 聚合到管理后台，并补充未知模型和未知出口查询。
