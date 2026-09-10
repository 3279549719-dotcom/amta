# ADR-004：Harness = 脚本/hooks/tests/docs

**状态**：已采纳

## 决策

本仓库的 Harness 只用 **scripts + git hooks + 确定性单测 + 文档** 实现，不引入外部基础设施。

## 理由

- 个人 DIY / vibe-coding 项目，维护面必须最小。
- 目标是把"重复犯错 → lesson → rule → 自动化测试/hook"做成纯本地、零依赖、可随时跑的东西。

## 后果 / 约束

- 不加：Slack 通知、自动建 issue、Jira/Linear、事件总线、Redis、向量库、独立 memory 服务、复杂多 Agent 编排。
- 依赖仅限 Python 标准库 + git + 已有 npm 脚本容器。
- 所有校验必须能用一条命令在本地跑完（`npm run finish` / `npm run audit`）。
