# DataAgent 文档索引

本目录收纳项目的规划、审查与验收记录。根目录仅保留项目入口、协作基线与默认系统提示词。

## 入口文档

- [README](../README.md)：项目定位、功能概览、安装和使用入口。
- [AGENTS](../AGENTS.md)：当前架构、运行约定、数据边界与验证要求。
- [system_prompt](../system_prompt.md)：DataPM 默认系统提示词。

## 规划

| 文档 | 用途 | 使用建议 |
| --- | --- | --- |
| [项目缺陷整改指导](plans/project-remediation-guide.md) | 历史问题基线与分阶段整改路线 | 实施前以当前代码和可复现验证结果为准。 |
| [管理后台前端重构方案](plans/admin-ui-refactor-plan.md) | 管理后台的信息架构与重构计划 | 作为规划参考，不代表所有阶段均已落地。 |
| [数据分析 Skill / 知识库 E2E 执行计划](plans/data-skill-knowledge-e2e-plan.md) | 数据技能和知识库的端到端执行计划 | 已有对应验收报告可供对照。 |
| [单轮对话聚合与 KunCode 结束态修复计划](plans/conversation-turn-stream-lifecycle-fix-plan.md) | 修复一问多思考/多回答、过度规划与 KunCode 永久运行态 | 按状态协议、回合投影、提示词和真实浏览器矩阵分阶段实施。 |

## 验收报告

| 文档 | 用途 | 日期 |
| --- | --- | --- |
| [数据分析 Skill / 知识库 E2E 验收报告](reports/data-skill-knowledge-e2e-validation.md) | 已部署资产、验证结果、修复项与未覆盖项 | 2026-07-21 |

## 不纳入本目录的 Markdown

- `sandbox_skills/`：沙箱运行时的 Skill 说明、参考资料和模板。
- `artifacts/e2e_data_skills/`：端到端验证生成的报告产物。

这些文件应与相应运行资产保留在同一目录，避免文档与实际输入、输出脱离。
