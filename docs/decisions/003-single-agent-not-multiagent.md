# ADR-003：单 Agent + 确定性工具层，而非 Multi-Agent

**状态**：已采纳

## 决策

架构 = **一个 LLM Agent（导演）+ 确定性 Python 工具层（执行器）+ koharu 引擎**。不是 Planner/Coder/Reviewer/Tester 多 Agent 编排。

## 理由

- 本项目的 LLM 真正需要的只是推理/决策/QA/验收；视觉与确定性工作由专业模型与脚本承担，不需要"思考"。
- 多 Agent 编排引入编排、消息、状态同步等额外维护面，对个人 DIY 项目是净负担。
- 与 Harness 核心哲学一致：让**一个**能力更强的 Agent 在更好设计的环境里更可靠，而不是构造复杂的 Agent 团队。

## 后果 / 约束

- 需要并行标注时用**轻量子 Agent fan-out**（oracle-label skill），但那是任务并行，不是架构上的多 Agent 编排。
- 不加 Slack/Jira/事件总线/Redis 等外部基础设施。
