# 接口与权限契约验收

- 验收日期：2026-10-28
- 范围：`/api/**` 的认证、授权、状态码语义、跨用户资源隔离、确认动作并发幂等、SSE 重连游标与事件顺序
- 结论：**通过**。进程内契约 41 项、真实依赖契约 7 项全绿；过程中发现并修复 4 个真实缺陷。

## 1. 为什么单独做一层契约测试

原有 90+ 条后端用例以"函数级回归"为主：直接调用 handler 或 service，绕过了
FastAPI 的依赖注入、路由装配和中间件。这类测试能覆盖算法，却看不见**接口层的
行为契约**——比如"这个端点到底有没有挂鉴权""跨用户访问会返回 404 还是 200"。

契约测试把观测面放在 HTTP 语义上：只断言"发什么请求、得到什么状态码和什么形状
的响应"，不关心内部怎么实现。所以它既能防回归，也能当接口文档的可执行版本。

## 2. 发现并修复的缺陷

| # | 缺陷 | 影响 | 修复 |
| --- | --- | --- | --- |
| 1 | `kuncode` 的 7 个 `/{session_id}` 路由只取 `user` 却从不校验会话归属 | 用户 B 拿到 A 的 session_id 就能读 A 的待确认预览、替 A 确认/取消工具执行、重置 A 的倒计时（越权读 + 越权写） | 新增统一依赖 `require_owned_session`，注入路径里的 `session_id` 做归属校验，异常返回 404 |
| 2 | `/api/files/uploads/{session_id}/list` 与 `/download` 完全没有归属校验，且 `filename` 直接拼路径 | 任一登录用户可枚举、下载他人上传件；`filename=../<他人会话>/x` 可目录穿越 | 两个路由改用 `require_owned_session`；文件名只允许单层普通名；`SandboxFileService` 增加 resolve 后的包含性校验作为纵深防御 |
| 3 | 计划确认/工具确认是 read-check-write，无互斥 | 双击或前端重试并发进入时，两个请求都可能读到 `status=pending`，导致一次预览被确认两次（可能触发两轮工具执行） | 用 Redis `SET NX` 加一次性互斥键（TTL 15s），并发第二个请求返回 409 |
| 4 | 未定义的 `/api/**` 路径会落进 SPA 兜底，返回 `200 + index.html` | 客户端把"接口不存在"当成功响应，掩盖前后端版本不一致 | `serve_spa` 对 `api/` 前缀返回 JSON 404 |

第 1 条是最严重的一条：它不是"信息泄漏"级别的瑕疵，而是**可以替他人按下执行按钮**。

## 3. 用例矩阵

### 进程内契约（`tests/test_api_contract.py`，41 项，无需外部依赖）

| 组别 | 覆盖点 |
| --- | --- |
| 认证 | 遍历全部 74 个受保护路由断言匿名访问必须 401（防止新增端点漏挂鉴权）；无 token 与无效 token 的 401 文案；非管理员 403 与 `get_admin_user` 单元契约；写接口必须挂管理员依赖的静态断言 |
| 归属 | 会话读/删、计划读/改、kuncode 全部会话级路由、上传件列表/下载、沙箱绑定，均验证"他人数据 404 或 403 且响应体不含他人数据" |
| 顺序安全 | kuncode 的越权用例都把 Redis 客户端替换成"一被调用就断言失败"的桩，证明归属校验发生在任何副作用之前 |
| 状态码 | 401 / 403 / 404 / 409 / 422 各自的触发场景与 `detail` 结构；422 断言 `loc` 精确到 `["body", "action"]` |
| 并发幂等 | 用能被打断的假 Redis 复现竞态：并发两次确认只有一次生效、另一次 409；重复确认、重复取消、过期预览、未知预览分别 409/404 |
| SSE | 非拥有者订阅 404；游标 `Last-Event-ID` 非法值回退 `0`、合法值原样透传；`id:` 行严格递增有序；`_stream_id` 不进入 data；`content-type` 为 `text/event-stream` |

### 真实依赖契约（`tests/test_api_contract_live.py`，7 项，默认跳过）

连真实 PostgreSQL + Redis，验证契约不是"只在 mock 里成立"：

```bash
CONTRACT_LIVE=1 PYTHONPATH=. python -m unittest tests.test_api_contract_live -v
```

覆盖：注册/重复注册/错误密码、跨用户会话读写、上传件跨用户与目录穿越、跨用户
篡改 kuncode 预览后校验"预览状态未被改变"、他人任务流订阅、管理员路由 403/200、
未知 API 路径 404。用例自动生成 `contract_*_<uuid>` 账号，`tearDownClass` 清理账号、
会话与 Redis 键。

## 4. 反向验证

把 `app/` 的改动 stash 掉后重跑进程内契约：**23 项失败**（kuncode 归属守卫缺失、
上传件越权可下载、穿越未拦截、未知 API 返回 200 等），恢复后全绿。这说明这些用例
不是"跑着好看"，而是真的会在缺陷回归时报警。

## 5. 已知边界

- `plans` 路由没有改成 `require_owned_session`：它对"状态存在但会话行缺失"的历史数据
  保持 200 空结果，改用 404 会改变前端行为。当前它按 `(user_id, session_id)` 双键查询，
  隔离性成立，已在用例里锁定为"返回 null 而非他人数据"。
- 沙箱工作区类路由（`/files/sandbox/{session_id}/**`）返回 **403** 而非 404。这是既有
  契约，改成 404 需要同步前端错误分支，本轮未动。
- 真实依赖契约不进 CI：CI 的 backend job 没有 Postgres/Redis service 容器，且拉起
  sandbox manager 有环境依赖。它作为"发版前手动跑一次"的门禁。

## 6. 复跑方式

```bash
# 进程内契约（CI 已自动执行）
PYTHONPATH=. python -m unittest tests.test_api_contract -v

# 全量后端
PYTHONPATH=. python -m unittest discover -s tests -p "test_*.py"
```
