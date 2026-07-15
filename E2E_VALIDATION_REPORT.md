# DataAgent 数据分析 Skill / 知识库端到端验收报告

日期：2026-07-15

## 结论

**有条件通过。**

受认证 API、PostgreSQL、Milvus、Skill 文件管理、Agent 权限、沙箱注入、KunCode 实际调用、SSE 生命周期、会话持久化和结果文件读取均已通过。管理页面 UI 自动化因 Windows 浏览器控制组件无法可靠确认 Edge 当前 URL 而被安全策略阻断，因此没有把 API 结果冒充为 UI 验证；这是当前唯一核心覆盖缺口。

## 已部署内容

- 知识库：8 条，分类覆盖 `计算公式`、`概念定义`、`分析方法`、`分析流程`。
- Skill：`tabular-data-cleaning`、`business-metric-formulas`，均启用。
- Agent：`e2e-data-analyst`，主 Agent、启用、可见。
- 权限：两个 Skill 对 `e2e-data-analyst` 均为 `allow`。

## 验收结果

| 项目 | 结果 | 证据摘要 |
| --- | --- | --- |
| 管理员认证与权限 | 通过 | 使用真实 `/api/auth/login`；确认 `is_admin=true`，未绕过 JWT |
| 知识 CRUD | 通过 | 8 条知识成功写入 PostgreSQL，刷新后数量一致 |
| Milvus 检索 | 通过 | 加权平均、重复记录、毛利率三个独特查询均命中目标条目 |
| Agent 知识工具 | 通过 | 对话中真实调用 `search_knowledge`，命中 `[E2E] 加权平均公式` |
| Skill 上传与文件树 | 通过 | 两个 ZIP 上传成功，`SKILL.md`、脚本、参考文件均可枚举 |
| Skill 权限 | 通过 | 两个 Skill 的 Agent 权限均持久化为 `allow` |
| 沙箱注入 | 通过 | 容器中 8 个 Skill 文件均使用标准 POSIX 路径 |
| 数据清洗 | 通过 | 10 行变 9 行；识别并移除 1 条完全重复；原文件未覆盖 |
| 公式计算 | 通过 | 收入 12800、成本 4720、毛利 8080、毛利率 0.63125、转化率 0.0977777778、加权平均 4.2307692308 |
| 零分母 | 通过 | 毛利率、转化率、加权平均返回 `undefined_zero_denominator` |
| SSE 生命周期 | 通过 | `tool_call/tool_result` 的 `tool_id` 配对；无 error；最终收到 `end` |
| 生成文件事件 | 通过 | 第二次完整复测返回 5 个 `generated_files` 相对路径 |
| 文件预览接口 | 通过 | 通过认证 workspace content API 读取并复算 JSON 结果 |
| 会话状态 | 通过 | 历史消息持久化；任务结束后 `has_active_task=false` |
| 后端回归 | 通过 | `tests.test_task_regressions` 共 10 项通过 |
| 前端质量门禁 | 通过 | ESLint 与生产 build 通过；仅保留既有大 chunk 警告 |
| 服务健康 | 通过 | PostgreSQL、Redis、Sandbox、Milvus、Embedding 均为 `ok` |
| 管理 UI 操作 | 阻塞 | Windows 控制组件无法可靠识别 Edge URL，安全策略强制停止 |

## 实际生成文件

端到端会话成功生成并通过认证接口读取：

- `e2e_results/cleaning/cleaned_data.csv`
- `e2e_results/cleaning/data_quality_report.md`
- `e2e_results/cleaning/data_quality_summary.json`
- `e2e_results/metrics/metric_report.md`
- `e2e_results/metrics/metric_results.json`

测试会话清理前，上述文件均存在于会话工作区。测试报告和事件证据保存在 `artifacts/e2e_data_skills/`。

## 发现并修复的问题

### 1. Windows 主机向 Linux 容器注入错误路径

首次真实执行中，Skill 被注入为 `scripts\profile_and_clean.py` 形式的单个 Linux 文件名，标准路径首次执行失败。根因是 Windows `Path` 被直接转换成字符串后写入 TAR。

修复：相对路径统一使用 `Path.as_posix()` 后再创建归档，并新增 TAR 成员路径回归测试。修复后容器内路径为：

```text
/root/.config/kuncode/skill/tabular-data-cleaning/scripts/profile_and_clean.py
/root/.config/kuncode/skill/business-metric-formulas/scripts/calculate_metrics.py
```

### 2. 生成文件通知验证

首次运行文件实际存在，但运行中的服务没有返回 `generated_files`。补充直接 KunCode 文件提取回归、排除 `data/uploads/` 原始输入，并重启服务加载当前代码。第二次全流程复测准确返回 5 个结果文件，文件页刷新所需事件恢复正常。

## 清理与保留

- 已删除 4 个本次测试会话及关联沙箱/上传文件。
- 已删除临时明文凭据文件和 JWT 文件。
- 保留 8 条正式知识、2 个正式 Skill 和 `e2e-data-analyst` Agent，供项目继续使用。
- 未修改 `.env`、密钥、数据库密码或其他 Docker 项目资源。

## 未覆盖项

- 管理后台页面的浏览器点击、ZIP 文件选择、列表刷新和成功提示未能自动化验证。
- Skill `deny` 后在新会话中拒绝调用的负向用例未执行；本次已验证 `allow` 权限持久化和实际调用。

建议后续人工在独立浏览器中完成一次简短冒烟：知识列表查看、Skill 文件树预览、权限下拉保存。其余核心端到端链路已由真实接口和真实沙箱执行覆盖。
