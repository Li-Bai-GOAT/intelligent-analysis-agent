# 计划确认与 SSE 心跳修复验收

- 验收日期：2026-10-28
- 范围：缺陷 A（确认后重复 `plan_preview`）、缺陷 B（长任务 SSE 无心跳导致 90s 读超时）
- 结论：**两项均已修复并在真实链路验证通过**。单测层 20 项新增用例、全量后端 160 项通过；真实链路端到端断言 6/6 通过。

## 1. 缺陷 A：确认后的重复 `plan_preview`

### 现象

用户确认计划后，同一份计划又被要求确认一次；有时模型会连续调用两次 `preview_plan`，前端连弹两个确认面板。

### 根因（两段叠加）

1. `PlanConfirmationGate.consume()` 把**计划名称**也当作身份的一部分：`create_plan` 的 `name` 必须与用户确认时的 `name` 在归一化后完全相等。而 `preview_plan` 收的是给用户看的自然语言，`create_plan` 收的是结构化入参，两者名称几乎不可能逐字一致（模型会缩略/补全/换标点，用户也可能在面板里改名字）。于是**合法确认被判为"未确认"**。
2. 拒绝时的工具输出写着 `Call preview_plan and wait for confirmation before create_plan`。模型照做 → 再弹一次确认面板。这是"重复弹窗"的直接触发点。

### 修复

| 改动 | 说明 |
| --- | --- |
| `consume()` 判定口径 | 改为「子任务序列是实质身份」：数量一致 + 每个子任务都能匹配已确认项 → 通过；名称差异只记一条 `info` 日志。子任务数量不符、子任务被替换、用户已取消，仍然拒绝 |
| `ConfirmedPlanNotebook._describe_rejection()` | 拒绝文案改为**把用户已确认的 name/subtasks 原文回给模型**，并明确要求"立即用这份内容重新调用 `create_plan`，不要再调用 `preview_plan`" |
| `preview_plan` 幂等 | 同一轮内记录「计划指纹 → 结论」。对同一份计划重复调用直接返回上次结论，不再发 `plan_preview`、不再阻塞等待。缓存挂在按轮创建的工具闭包上，**不会跨轮**，用户下次真要重做同样的计划仍会正常确认 |

安全边界没有放松：闸门依然保证"只能创建用户确认过的那份计划"，只是把身份从"名称+子任务"收敛到"子任务"，并把拒绝路径从"让用户再点一次"变成"让模型自我纠正"。

## 2. 缺陷 B：长任务 SSE 无心跳

### 现象

模型思考或沙箱执行期间可能连续几十秒没有任何 token，代理层（nginx 默认 `proxy_read_timeout` 60s、多数网关 90s）判定后端失联后断开，前端只看到"任务流意外结束"，任务本身还在跑。

### 根因

两条 SSE 端点都是"有事件才写字节"：`/api/conversation/chat` 直接转发 `agent_service.chat()` 的 chunk，`/api/conversation/stream/{task_id}` 转发 Redis Stream 条目。静默期响应体一个字节都不产出，代理就按空闲超时断开。

### 修复

| 改动 | 说明 |
| --- | --- |
| 新增 `app/utils/sse.py` | `iter_with_heartbeat()` 在源静默超过间隔时产出心跳；`encode_sse_event()` 统一帧格式 |
| 心跳帧 | `: keep-alive\n\n`（SSE 注释帧，无 data 段，`EventSource` 与手写解析器都会忽略） |
| `/conversation/chat` 与 `/conversation/stream/{task_id}` | 都改为经 `_stream_frames()`，心跳与业务帧共用一条管道 |
| 断线检测 | 不再只在收到事件时检查 `is_disconnected()`，心跳产出时也检查，避免僵尸连接一直发心跳 |
| 可配置 | `SSE_HEARTBEAT_SECONDS`（默认 15s，下限 0.05s），每次建流时读配置 |

### 一个实现陷阱（值得记下来）

最初用 `asyncio.wait_for(source.__anext__(), timeout)` 实现心跳。它超时时会 **cancel** 那个 `__anext__`，`CancelledError` 会打进内层异步生成器并把它关闭——也就是"心跳把模型流杀了"。改成 `asyncio.wait({task}, timeout)` 后超时只是"这一轮不取"，任务保留到下一轮继续等同一个 `__anext__`，源生成器始终不被打断。

另外 `source.__aiter__()` 必须**只调用一次**：对每次返回新生成器的对象（测试里的 `_SlowSource` 就是）重复调用会让流永远停在第一个元素上——这一点是被新增单测抓出来的。

## 3. 验证

### 单测 / 契约层（`tests/test_plan_hitl_and_sse.py`，20 项）

- 闸门：名称差异通过、用户改名通过、子任务数量不符拒绝、子任务替换拒绝、确认只能用一次、取消后全拒
- 拒绝提示：包含"不要再 preview"与已确认原文；取消态文案不含"重新预览"
- 幂等：同一计划重复预览只推 1 次 `plan_preview`、只等待 1 次确认；不同计划仍会分别询问
- 心跳：静默期产出心跳且不丢数据、快源不产心跳、**源生成器不被心跳提前关闭**、帧格式合法、消费方提前退出会取消挂起读
- 帧封装：心跳与业务帧交替、断线后停止产出

`tests/test_api_contract.py` 另加 1 项走真实路由的断言：让任务流先静默 0.3s（6 倍心跳周期），断言响应体含心跳帧、且业务事件的 `id:` 顺序不变。

**反向验证**：把 `app/` 三处修复 stash 掉后重跑，这两批用例 **6 failures + 4 errors**，恢复后全绿。

### 真实链路（`tests/run_plan_hitl_e2e.py`）

真实服务 + 真实模型 + PostgreSQL + Redis，流程：注册 → 建会话 → `POST /conversation/async` → 订阅 SSE → 收到 `plan_preview` 后调确认接口 → 校验计划落库。

| 断言 | 结果 |
| --- | --- |
| 只出现 1 次 `plan_preview` | PASS（1 次） |
| 收到 `plan_confirmed` | PASS |
| 计划已落库 | PASS（`GET /api/plans` 返回 3 项子任务） |
| 落库子任务数与确认内容一致 | PASS（3 / 3） |
| 静默期收到心跳帧 | PASS（4 个） |
| 相邻数据块间隔 ≤ 2×心跳周期 | PASS（最大 3.30s，周期 3s） |

事件分布：`status 1 / thinking 28 / text 26 / tool_call 6 / tool_result 3 / step_complete 7 / plan_preview 1 / plan_confirmed 1 / plan 1 / end 1`。

说明：为了在有限时间内复现"长静默"，这次把服务端心跳临时调成 3s 启动。默认 15s 的那次运行同样跑完（`plan_preview` 仍是 1 次、计划正常落库），只是这一轮模型响应很快、最大静默只有 6.12s 未达到 15s，因此没有心跳可发——这属于正常表现，不是缺陷复现。

## 4. 复跑方式

```bash
# 单测
PYTHONPATH=. python -m unittest tests.test_plan_hitl_and_sse -v

# 全量后端
PYTHONPATH=. python -m unittest discover -s tests -p "test_*.py"

# 真实链路（需先起服务与模型）
python tests/run_plan_hitl_e2e.py --base-url http://127.0.0.1:8090
# 想快速看到心跳，把服务端心跳调小：
SSE_HEARTBEAT_SECONDS=3 python -m uvicorn app.main:app --port 8091
python tests/run_plan_hitl_e2e.py --base-url http://127.0.0.1:8091 --heartbeat 3
```

## 5. 已知边界

- 闸门的名称差异容忍依赖"子任务序列"这一实质身份。如果模型把计划换成另一份**子任务完全一致**但语义不同的计划，闸门无法识别——这属于模型行为异常，由模型审计与人工复核兜底。
- 心跳不解决"任务已经死掉但流还开着"的问题：`read_task_stream` 在流键消失后会一直轮询。要彻底解决需要任务心跳/超时（`task_heartbeat` 键 + 无心跳超时关闭），属于下一步工作。
- 本轮未处理单次请求产生 393 条 `thinking` 事件的问题（前端去重/节流），与本次两个缺陷无耦合。
