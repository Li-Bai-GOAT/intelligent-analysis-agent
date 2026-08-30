# DataAgent 文档索引

本目录收纳当前路线图、专项计划、安全指南和验收记录。项目介绍从根目录 README 开始；实际行为始终以当前代码和可重复验证结果为准。

## 当前入口

| 文档 | 用途 |
| --- | --- |
| [项目 README](../README.md) | 项目定位、架构、功能和本地运行。 |
| [协作与运行基线](../AGENTS.md) | 端口、事件协议、数据边界、开发和验收约束。 |
| [统一优化路线图](ROADMAP.md) | 当前 P0/P1、依赖、完成定义和专项状态；后续排期以此为准。 |
| [项目目录地图](project-structure.md) | 按文件夹定位代码、基础设施和运行时数据。 |
| [默认系统提示词](../system_prompt.md) | DataPM 默认行为约束。 |

## 当前活跃专项

| 专项 | 状态 | 优先级 |
| --- | --- | --- |
| [沙箱容器回收与生命周期](plans/sandbox-container-lifecycle-design.md) | 部分实施，持久状态和租约待完成 | P0 |
| [管理后台重构](plans/admin-ui-refactor-plan.md) | 基础页面已完成，治理能力待完成 | P1 |
| [KunCode 终端与运行时 UX](plans/kuncode-terminal-runtime-ux-optimization-plan.md) | 核心协议已实施，安全/性能/自动化待完成 | P1 |

## 已实施或有条件通过

| 专项 | 状态 | 剩余验收 |
| --- | --- | --- |
| [单轮对话聚合与结束态](plans/conversation-turn-stream-lifecycle-fix-plan.md) | 已验证 | 前端自动化回归 |
| [普通用户后台只读访问](plans/read-only-admin-access-plan.md) | 已归档 | 无 |
| [计划面板实时更新](plans/plan-panel-realtime-update-plan.md) | 已实施 | 多会话切换 E2E |
| [数据 Skill / 知识库 E2E](plans/data-skill-knowledge-e2e-plan.md) | 有条件通过 | 后台 UI、Skill deny 负向用例 |

## 历史基线

| 文档 | 说明 |
| --- | --- |
| [项目缺陷整改指导](plans/project-remediation-guide.md) | 以 2026-07-11 代码为基线，大量问题已经解决；剩余项已转入统一路线图。 |

## 安全与运行指南

- [MCP 密钥引用](mcp-secret-references.md)：敏感配置的引用、白名单和运行时解析规则。

## 验收与 QA 报告

| 报告 | 状态 |
| --- | --- |
| [核心浏览器 E2E 验收](reports/core-browser-e2e-validation.md) | 已验证；9 项确定性用例与 3 项真实服务冒烟通过。 |
| [数据 Skill / 知识库 E2E 验收](reports/data-skill-knowledge-e2e-validation.md) | 有条件通过；历史真实接口与沙箱证据。 |
| [聊天输入视觉 QA](reports/chat-input-visual-qa.md) | 被认证状态阻塞，尚未完成登录后视觉对比。 |

## 不属于项目规划的 Markdown

- `sandbox_skills/`：沙箱 Skill 说明、参考资料和模板，是运行时资产。
- `artifacts/`：端到端验证产物、事件证据和历史归档。
- `mcp_test_postgres/README.md`：独立 MCP 测试服务说明。

这些文件应留在对应资产目录，不并入统一路线图。
