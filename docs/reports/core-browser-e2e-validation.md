# DataAgent 核心浏览器 E2E 验收报告

> 状态：已验证
>
> 最近核验日期：2026-09-07；历史全面验收日期：2026-08-30
>
> 对应路线图：P0 原第 4 项“核心浏览器 E2E”

## 2026-09-07 全局内边距恢复（最新复核）

- 按用户要求，仅删除 `frontend/src/index.css` 通配规则中的 `padding: 0`；保留 `box-sizing`、全局 `margin: 0` 和 `html` 自身重置。组件原有样式恢复生效，不额外调整布局；全局变化不限于下列四处控件。
- 新增 E2E `主对话页四处控件保留组件声明的内边距`，在生产构建配合模拟接口下逐项读取计算样式：计划/文件/终端为上下 6px、左右 12px；新建对话/收缩和下载全部(ZIP)/刷新均为四边 4px；思考过程为上下 8px、左右 12px。断言均通过，并确认回复完成、发送按钮恢复可用。
- `npm.cmd run build`、`npm.cmd run lint`、相关 E2E 严格 TypeScript 检查通过。入口 JS 为 507.40 KB / gzip 155.68 KB，仍有非阻断性 500 KB 警告。构建后在 4173 启动生产预览并执行 `npm.cmd run test:e2e`，13/13 通过（40.7 秒），包含 CSS 高亮及 35 秒慢回复回归。
- 主对话页截图附在 HTML 测试报告的 `padding-restored-mock` 项中，文件为该测试输出目录下的 `padding-restored.png`。已检查截图，当前 1280×720 模拟场景未见明显重叠或裁切；这不是完整响应式或所有页面视觉验收。
- 已刷新真实 8090 生产页面，目前显示登录页，需要用户重新登录查看实际会话；未读取或修改凭据、账号或会话数据。`/ready` 五项依赖全部 `ok`。本轮未重跑真实模型冒烟或后端单元套件。

## 2026-09-07 CSS 高亮修复与间距定位（此前复核）

- `MessageBubble.tsx` 保留 PrismLight，显式导入并注册 CSS，纠正“默认自带 CSS”的注释；`app/database.py` 第一行多余的 `c` 已清理，该文件恢复为 Git 基线。
- 新增 CSS 代码块 E2E，断言选择器 `.example` 和属性 `color`、`padding` 均生成带颜色样式的可见节点。使用相同测试验证生产预览：修复前 CSS 只有文本、找不到高亮节点；修复后通过。开发模式中的间接语言加载可能掩盖此类缺陷，因此不能仅测开发服务器。
- 构建后以 `npm.cmd run preview -- --host 127.0.0.1 --port 4173 --strictPort` 启动生产预览，再从另一终端执行 `npm.cmd run test:e2e`；本地配置会复用该 4173 服务。12/12 通过（39.5 秒），包含原有 35 秒慢回复回归。HTML 报告已更新为本轮结果。
- ESLint、相关 E2E 严格 TypeScript 检查、TypeScript/Vite 构建、Python 编译检查通过。入口 JS 为 507.40 KB / gzip 155.69 KB；仍有非阻断性 500 KB 警告。
- 后端 `/ready` 五项依赖全部 `ok`。本轮仅涉及语言注册和编码注释清理，未重新执行真实模型冒烟、管理员写操作或后端单元套件；上次在线验证见下节。

以下为恢复内边距之前的定位记录：在当时的生产主对话页读取实际计算样式，确认问题指控件和容器的内边距，不是页面整体外边距。根字号为 16px，Tailwind 间距单位为 0.25rem：

| 主对话页位置 | 源码设置 | 应有内边距 | 实际内边距 |
| --- | --- | --- | --- |
| 右上角“计划 / 文件 / 终端”页签 | `Tabs.tsx`：`px-3 py-1.5` | 左右 12px，上下 6px | 四边 0px |
| 左侧历史对话标题旁“新建对话 / 收缩”图标 | `Sidebar.tsx`：`p-1` | 四边 4px | 四边 0px |
| 右侧文件栏“下载全部(ZIP) / 刷新”图标 | `FilesPanel.tsx`：`p-1` | 四边 4px | 四边 0px |
| 回复中的“思考过程”折叠按钮 | `MessageBubble.tsx`：`px-3 py-2` | 左右 12px，上下 8px | 四边 0px |

当时 `index.css` 第 26 行开始的未分层通配规则在第 29 行设置 `padding: 0`，覆盖了分层工具类；高亮修复轮次未修改该文件，后续恢复结果见本报告最新复核。发送/上传按钮及“自动 / KunCode”使用固定宽高，不能仅凭 padding 为 0 将它们也判为同一问题。

## 2026-09-07 超时复核与修复（此前复核）

修复前，默认模拟接口用例 9/9 通过，重复三轮 27/27 通过；真实普通用户冒烟 2 项通过、管理员 1 项因未提供凭据跳过。未取得 K3 当时的失败日志，不能断言以下原因就是其全部失败的来源，但两类问题均已独立复现：

| 故障注入 | 修复前 | 修复后 |
| --- | --- | --- |
| 模型 SSE 响应延迟 35 秒 | 回复断言设置 120 秒，但测试在 30 秒总预算处失败 | 模型冒烟单独使用 180 秒预算，回复与结束态共用 120 秒期限；普通测试仍为 30 秒 |
| Google Fonts 样式表延迟 35 秒 | 卡在 `page.goto` 等待 `load`，30 秒超时 | E2E 公共 fixture 拦截字体 CDN；功能测试不依赖外部字体网络 |

- `e2e/support/chatSmoke.ts` 由真实冒烟和慢回复回归共用，避免两套测试逻辑漂移。
- `e2e/harness-regressions.spec.ts` 新增“字体无响应仍可登录”和“模型回复超过 30 秒仍可完成并清理测试会话”。慢回复用例故意等待 35 秒，完整模拟套件耗时至少约 35 秒属于预期。
- 仅修改测试与验收文档，没有修改业务前后端、全局测试超时或增加自动重试。字体隔离不等于修复了生产页面的 CDN 可用性。

### 本次结果

- `npm.cmd run test:e2e -- --reporter=list`：11/11 通过（43.2 秒）。
- `npm.cmd run test:e2e -- --repeat-each=3`：33/33 通过（56.9 秒），HTML 报告位于 `frontend/playwright-report/index.html`。
- `npm.cmd run test:e2e:live -- --trace=off --reporter=list --repeat-each=2 --workers=1`：4 次通过、2 次跳过（20.2 秒）；即登录/会话/实际模型回复、普通用户只读及写请求 403 各验证两轮；两轮管理员测试因无凭据跳过。未使用命令行 `--timeout` 覆盖。
- 真实验证使用独立临时普通用户；测试会话和临时账号均已清理，未调整管理员权限或共享配置。真实账号运行时关闭 trace，避免保留认证请求。
- ESLint、E2E 文件严格 TypeScript 检查、TypeScript/Vite 生产构建、`git diff --check`：通过。入口 JS 为 506.08 KB，既有 500 KB chunk 警告不影响成功。
- `/ready`：PostgreSQL、Redis、Sandbox、Milvus、Embedding 全部 `ok`。
- 本次未复跑后端单元测试、真实管理员写操作或复杂 KunCode 长任务，不能把历史覆盖视为本次重新验证。

## 历史结论（以下为 2026-08-30 验收记录）

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
