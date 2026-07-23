# 单轮对话聚合与 KunCode 结束态修复计划

> 状态：已执行（2026-07-23）  
> 编制日期：2026-07-23  
> 适用范围：Auto / KunCode 对话、实时流、历史回放、终端执行状态  
> 目标：一个用户问题在聊天区最终只对应一个可折叠的思考区域和一个最终回答；KunCode 在成功、失败、中断或连接异常后均不再保持转圈状态。

## 1. 问题描述

当前界面存在两类相互关联但需要分别修复的问题：

1. 最近一次 Auto 对话不断出现新的“思考过程”和计划工具条目，长时间没有最终回答。
2. 历史对话中，同一个用户问题会回放出多条“思考过程”、计划工具和多段回答。
3. `run_kuncode` 在任务已经结束或流已经异常断开后，仍可能保持 `RUNNING` 或转圈状态。

期望效果接近 ChatGPT：

- 用户发送一个问题后，聊天区只创建一个稳定的 assistant 回合。
- 该回合最多展示一个默认折叠的“思考过程”。流式 reasoning 只更新这个区域，不新增气泡。
- 计划管理、子任务状态、KunCode 调用等内部工具事件不作为聊天消息逐条展示。
- 回合完成时只显示一个最终回答；执行细节继续在右侧计划、终端和文件面板查看。
- KunCode 无论成功、失败、中断还是连接丢失，都必须进入明确终态。

## 2. 已确认的现状与根因

### 2.1 历史消息没有“用户回合”聚合层

`frontend/src/stores/session.ts` 的 `selectSession` 将数据库记录逐条转换为前端消息：

- 每条 `reasoning` 都被转换成独立 assistant 消息。
- 每条普通 assistant `message` 也被转换成独立消息。
- `plugin_call` 只尝试挂到它前面的 assistant 消息上。

数据库中保存的是 AgentScope 的原始执行轨迹，而不是最终聊天视图。实查最近的代表性记录可以看到同一用户输入之后依次保存了多组：

```text
reasoning
preview_plan / create_plan
reasoning
update_subtask_state
reasoning
run_kuncode
reasoning
finish_subtask
...
final message
```

因此历史页按原始记录直接渲染时，必然产生多个机器人头像、多个思考块和多个工具条目。这一现象在本次结束态补偿修改之前保存的历史数据中也存在，说明它不是由补偿函数单独引入的。

### 2.2 实时消息按“最后一条 assistant”猜测归属

当前 `handleStreamData` 没有稳定的回合标识：

- `thinking` 只会更新最后一条已经存在的 assistant 消息；当它紧跟用户消息到达时，不会主动创建 assistant 占位消息。
- `text`、`tool_call` 同样依赖最后一条消息的角色决定覆盖还是新增。
- 页面刷新、切换会话、断点续传后，实时事件会与从数据库重建的多条 assistant 消息混合。

这会造成实时页面与历史页面的显示结构不一致，也无法保证“一问一答”。

### 2.3 内部计划工具仍进入聊天区

`MessageBubble.tsx` 目前只隐藏了部分工具名。以下计划内部工具仍可能被当成聊天工具卡展示：

- `preview_plan`
- `update_subtask_state`
- `finish_subtask`
- `finish_plan`

上次隐藏 `run_kuncode` 后，执行过程本身不再显示，但上述计划事件和多段 reasoning 仍然可见，反而使页面看起来像“只会反复思考、没有执行”。

### 2.4 工具终态协议不完整

当前结束态存在以下不一致：

- `AgentService.write_task_stream` 默认把 `tool_result` 映射为 `phase=progress`、`execution_status=running`，与“已有工具结果”语义冲突。
- `TerminalPanel` 只依据 `tool.result` 是否为 `undefined` 判断运行状态，没有优先使用后端的 `execution_status`。
- SSE 重试全部失败时，客户端只执行 `onDone(error)`，没有保证用同一收尾函数关闭未决工具。
- 历史加载使用 `toolResults.get(toolId) || ''`，没有真实结果时也会得到空字符串，终端可能把未完成调用误判成成功。
- 当前 `_build_terminal_tool_results` 在整轮结束时为所有未配对工具生成“已结束”结果。它能停止转圈，但在拿不到真实工具结果时直接标记 `completed`，可能掩盖失败或丢失事件。

### 2.5 最近一次请求同时存在过度规划

实查最近未完成回合的持久化轨迹，DataPM 将单个文档讲解请求拆成多个子任务并连续调用多次 KunCode，最后停在一个尚无配对输出和最终回答的 `run_kuncode`。这说明：

- 页面重复显示首先来自消息投影错误；
- 等待时间过长还来自 DataPM 对单文件讲解任务的复杂度判断偏重；
- 最后一项 KunCode 调用没有形成完整的调用—结果—结束事件闭环。

`system_prompt.md` 已有“简单任务无需计划”的原则，但当前活动提示词优先来自数据库，因此只修改仓库默认文件并不能保证运行实例立即生效。

## 3. 修改原则

1. 保留数据库中的原始 AgentScope 消息，避免迁移或破坏模型上下文。
2. 在前端增加统一的“聊天视图投影”，把原始执行轨迹聚合为用户可读回合。
3. 计划和工具执行详情仍保留在计划/终端面板，不丢失诊断能力。
4. 工具状态必须来源于明确事件，不能用空字符串冒充成功。
5. 成功、失败、中断、超时和网络断开必须共用一套幂等收尾逻辑。
6. 修改聚焦消息聚合和生命周期，不重构 AgentScope 存储结构。

## 4. 拟实施方案

### 阶段 A：建立单轮聊天视图模型

在前端增加纯函数形式的消息投影层，例如 `conversationProjection.ts`：

1. 以每条 user 消息作为新回合边界。
2. 将下一条 user 消息之前的所有 assistant `reasoning`、普通文本和工具调用归入同一个 assistant 回合。
3. reasoning 采用增量去重后聚合到唯一 `thinking` 字段；同一内容的累计流片段不重复追加。
4. 普通 assistant 文本只保留本回合最后一个有效交付文本作为最终回答；工具执行前的过渡文本不额外生成气泡。
5. 工具调用按稳定 `tool_id` 合并并保留在回合对象中，供终端面板消费，但不在聊天区直接展示。
6. 兼容没有显式 turn id 的历史数据：使用“当前 user 到下一 user”的区间作为旧数据回合边界。

建议给前端 `Message` 增加仅用于视图状态的字段：

```ts
turnId?: string
status?: 'running' | 'completed' | 'failed' | 'cancelled'
```

新请求使用 `task_id` 作为实时 `turnId`；历史数据使用可重复计算的本地回合键，不修改数据库。

### 阶段 B：统一实时流归并

调整 `frontend/src/stores/session.ts`：

1. 提交任务成功后立即创建一个与 `task_id` 绑定的空 assistant 占位回合。
2. `thinking`、`text`、`tool_call`、`tool_result` 都按当前 `turnId/tool_id` 原位更新，不再依赖“最后一条 assistant”。
3. 所有 reasoning 片段只更新同一个 `thinking` 区域。
4. 所有 text 片段只更新同一个最终回答区域。
5. `end`、`error`、`interrupted` 和 SSE 重试耗尽统一进入 `finalizeTurn`；该函数必须幂等，重复调用不会新增消息或重复关闭工具。
6. 页面刷新和断点续传时，先用历史投影重建回合，再把活跃 task 的后续事件归并到最后一个未完成回合。
7. 每次新请求重置本轮 `seenToolIds`、thinking 聚合状态和当前工具指针，避免跨问题串线。

### 阶段 C：简化聊天区展示

调整 `MessageBubble.tsx`：

1. 每个 assistant 回合最多渲染一个 `ThinkingBlock`。
2. 执行中显示稳定的单个折叠标题，例如“正在分析”；结束后显示“思考过程”。
3. 聊天区不再渲染通用 `ToolCallBlock`。工具详情统一由 TerminalPanel、PlanPanel、FilesPanel 承担。
4. 最终回答只渲染一次。
5. 若任务失败且没有最终回答，在同一 assistant 回合内显示明确失败摘要，不额外插入多个 system 气泡。

### 阶段 D：修正工具生命周期协议

后端和前端共同调整：

1. `tool_call`：`started/running`。
2. 有真实工具结果的 `tool_result`：`completed/completed`；工具结果包含错误时为 `failed/failed`。
3. 用户中断：`cancelled/cancelled`。
4. 流断开、超时或缺少配对结果：`failed/failed` 或明确的 `unknown` 映射，禁止伪装为成功。
5. `TerminalPanel` 优先读取显式 `execution_status`，仅对旧历史数据回退到结果文本推断。
6. 历史加载缺少 `plugin_call_output` 时保留 `result=undefined`；若任务已不活跃，则投影为“执行记录不完整/已终止”，不得显示成功。
7. 替换 `_build_terminal_tool_results` 的无条件成功补偿：
   - 能从真实 Agent 状态/持久化 `plugin_call_output` 找到结果时，补发真实 completed 结果；
   - 找不到结果时发 failed/cancelled 终态；
   - 补偿事件必须使用原始 `tool_id`，且只发送一次。
8. 修复异步任务登记顺序：在启动后台任务前写入 `session_task` 映射，避免极快任务先清理、API 随后又写回过期活跃任务的竞态。
9. `clear_session_task` 放入任务执行的 `finally` 收尾路径，确保异常分支同样清理。

### 阶段 E：约束简单请求的过度规划

同时更新仓库默认提示词和数据库当前活动提示词：

1. 明确“问候、能力说明、单文件概览/讲解、单次查看、简单统计”为简单请求。
2. 简单请求禁止调用 `preview_plan/create_plan/update_subtask_state/finish_subtask/finish_plan`。
3. 单文件讲解原则上最多一次 `run_kuncode`；若无需读取文件内容则直接回答。
4. 只有用户明确要求多份交付物、跨文件分析或多阶段处理时才建立计划。
5. 保留 `max_iters` 作为最终安全上限，但不把降低迭代次数作为主要修复手段，避免复杂分析被提前截断。

由于运行时优先读取数据库 `system_prompts`，实施时应先备份当前活动提示词，再通过受认证管理 API 更新；不得只改 `system_prompt.md`。

## 5. 预计修改文件

| 文件 | 修改内容 |
| --- | --- |
| `frontend/src/stores/session.ts` | 实时回合占位、按 turn/tool id 合并、统一收尾、历史投影接入 |
| `frontend/src/types/index.ts` | 增加回合和显式工具状态字段 |
| `frontend/src/components/chat/MessageBubble.tsx` | 单思考块、单回答、移除聊天区内部工具卡 |
| `frontend/src/components/panels/TerminalPanel.tsx` | 使用显式终态，兼容旧历史回退 |
| `frontend/src/api/client.ts` | SSE 结束/异常统一通知收尾，避免漏掉网络错误 |
| `app/services/agent_service.py` | 工具结果状态、真实结果补偿、缺失结果失败收尾 |
| `app/tasks.py` | 任务映射登记/清理竞态和 finally 收尾 |
| `app/api/conversation.py` | 提交异步任务前登记活跃任务，保持事件标识一致 |
| `system_prompt.md` | 简单请求分类和禁止过度规划规则 |
| `tests/test_task_regressions.py` | 后端任务及工具终态回归测试 |

建议新增一个前端纯函数文件承载聚合逻辑，使 store 修改保持可读；不新增大型状态管理依赖，也不修改数据库表结构。

## 6. 测试计划

### 6.1 静态与自动化检查

```powershell
cd E:\Full_Stack_Challenge\dataagent
.\.venv\Scripts\python.exe -m unittest tests.test_task_regressions -v
cd frontend
npm.cmd run lint
npm.cmd run build
cd ..
git diff --check
```

后端至少新增以下回归用例：

- `tool_result` 默认进入 completed，而不是 running。
- 未配对工具在成功、异常、中断时分别进入正确终态。
- 补偿结果复用原 `tool_id` 且幂等。
- 异步任务无论正常或异常都清除 `session_task`。
- 后台任务启动与活跃映射不存在“先清理、后写回”的竞态。

前端当前没有测试框架。为保持改动小，第一阶段以纯函数、TypeScript 构建和真实浏览器矩阵验证为主；若后续继续扩展事件协议，再单独引入轻量前端测试框架，不在本次顺带增加依赖。

### 6.2 真实浏览器验收矩阵

| 场景 | 预期聊天区 | 预期终端/任务状态 |
| --- | --- | --- |
| 输入“你好” | 一个 assistant 回答；无计划、无 KunCode、最多一个折叠思考块 | 无工具运行项，任务结束 |
| 询问“你能做什么” | 一个直接回答 | 无工具运行项 |
| 上传单个 DOCX 并问“讲解这个文件怎么分析” | 一个持续更新的思考块，最终一个回答；不展示计划工具条 | 最多一次必要的 KunCode；最终 completed/failed，不转圈 |
| 简单 KunCode 计算 | 一个思考块和一个最终答案 | `run_kuncode` 从 running 进入 completed |
| KunCode 主动报错 | 同一回合显示一次失败说明 | `run_kuncode` 为 failed，不转圈 |
| 用户中断 | 同一回合显示一次中断说明 | `run_kuncode` 为 cancelled，不转圈 |
| 模拟 SSE 断开并重连 | 不新增思考或回答气泡 | 重连后继续；重试耗尽则 failed |
| 完成后刷新页面 | 仍是一个思考块和一个最终回答 | 工具历史终态保持一致 |
| 打开旧的多步骤历史对话 | 每个用户问题只投影为一个 assistant 回合 | 工具详情仍可在终端查看 |

### 6.3 服务健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8090/ready | ConvertTo-Json -Depth 4
```

真实验证完成后清理测试会话和测试文件，但不修改用户已有会话历史。

## 7. 验收标准

满足以下全部条件方可视为完成：

1. 任意一个用户问题在聊天区最多产生一个 assistant 回合。
2. 每个 assistant 回合最多有一个默认折叠的思考区域。
3. `preview_plan`、`update_subtask_state`、`finish_subtask`、`finish_plan`、`run_kuncode` 不再作为聊天工具卡展示。
4. 完成回合最多显示一个最终回答。
5. 实时显示与刷新后的历史回放结构一致。
6. KunCode 的成功、失败、中断和网络异常路径均不会永久 `RUNNING`。
7. 简单问候和能力说明不调用计划或 KunCode。
8. 单文件讲解不再默认拆成多子任务长流程。
9. 后端回归测试、前端 lint/build、真实浏览器矩阵和 `/ready` 检查全部通过。

## 8. 风险与回退

- 聚合时若简单地拼接所有 assistant 文本，可能把中间过渡话术和最终答案混在一起；因此必须采用“过程更新同一回合、最终保留最后有效交付文本”的规则。
- `ask_user` 属于真正需要用户响应的中间终点，不能被普通内部工具规则完全吞掉；等待用户输入时应在当前回合显示一次明确问题，用户继续后再创建下一回合。
- 旧历史缺少显式任务状态，只能根据配对结果和当前活跃任务保守推断；不应批量改写历史数据库。
- 如果修改活动系统提示词后简单任务仍过度规划，应优先增加可观测的复杂度路由日志，再决定是否做确定性工具门控，避免一次性扩大后端改造。
- 实施前保留当前未提交修改；若需要回退，应逐文件撤销本计划对应补丁，不使用破坏性 Git 重置。

## 9. 推荐实施顺序

1. 先修复工具状态协议和任务清理竞态，保证执行一定能结束。
2. 再实现统一回合投影和实时归并，解决一问多思考/多回答。
3. 隐藏聊天区内部工具展示，保留终端和计划面板。
4. 更新默认及活动系统提示词，减少简单任务过度规划。
5. 依次完成自动化测试、真实浏览器矩阵、历史刷新验证和测试数据清理。

## 10. 本次执行结果

- 已建立统一的历史消息投影和实时 `task_id` 回合归并，同一用户问题只渲染一个 assistant 回合。
- 聊天区只保留一个折叠思考块和一个最终回答；计划及工具调用仍在右侧面板展示。
- 已修正工具完成、失败、中断及缺失结果的终态映射，并修复异步任务登记/清理竞态。
- 已更新仓库默认提示词和数据库活动提示词；更新前内容已备份为 `product_manager_backup_20260723_conversation_fix`。
- 后端 14 项回归测试、前端 lint/build、`git diff --check` 和 `/ready` 健康检查通过。
- 真实浏览器确认多步骤历史只显示一个思考块和一个回答，历史 KunCode 均为 `DONE`。
- 当前模型供应商返回余额不足，因此无法完成成功模型调用；真实失败路径已验证 KunCode 从 `RUNNING` 正确进入 `ERROR`，不会永久转圈。
- 本次创建的两条测试会话已清理，未修改用户原有历史会话。
