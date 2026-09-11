# 025 — Agent 记忆机制：四层闭环（注入 + 打捞 + 护栏）

日期：2026-08-30　状态：已采纳

## 决策
1. 读取端机械化四层：基线（CLAUDE.md/AGENTS.md 自动加载 + 问题域启发式表）→ 推送（CC: SessionStart hook 注入记忆包 startup ≤1.5KB/compact ≤0.5KB；DSH: agent-instructions 原生加载 workspace 根 CLAUDE.local.md，memory_inject.py 生成，startup ≤4KB）→ 拉取（memory_grep/index/read/recent/status 五工具，条目级语义返回）→ 护栏（pytest 锁 hook + memory_lint 五规则进 fastcheck + 冷启动探针挂 audit）。
2. 写路径沿用 claude-remember 插件（.remember/）+ cycle-close 晋升管线 + Stage 2-d INDEX 写回（scripts/memory.py add），不重造。
3. **DSH 侧注入走 DSH 原生机制，不接 CC hook 桥**：DSH 的 `agent-instructions` 插件（web 会话经 standard 等 agent preset 挂载）自动加载 workspace 根（amta）的 AGENTS.md/CLAUDE.md 及本地 overlay AGENTS.local.md/CLAUDE.local.md（默认候选，无需改 profile/preset）。故 DSH 推送层实现为：`scripts/memory_inject.py` 把当前记忆包（now/recent/近期 lessons，≤4KB）写入 `amta/CLAUDE.local.md`（gitignore 生成物），随每个 DSH 会话自动注入，改文件后会话内即动态重注入（已实证）。CC hook 桥（进程级 stdio，L11 泄漏风险）仍不接；何时需要：仅当要按 source=compact 做瘦包重注入或按会话事件精确触发时，再评估。不默认，门控。
4. 工具族零第三方依赖（过 depguard）；不建 MCP 壳（脚本对 CC/DSH/Codex 通用）；.remember 维持 gitignore（Q11）。

## 理由
- 实测病根：写入自动化但读取零机械化——.remember 只注入自身文件，lessons/ADR/progress 从未注入；CLAUDE.md 加载表按任务名枚举对不上踩坑场景；research/ 幽灵路径证明索引会腐坏（memory_lint ghost_path 实抓 4 条）。
- compact 重注入是"长会话遗忘"的机制性解药（压缩 = 记忆丢失点 = 官方重注入钩子）。
- 一次性调研证据：research/07-agent记忆机制详报.md（CC hooks 官方协议 / claude-mem / MCP memory server / claude-remember 实测）。

## 备注
- 原 024 编号已被《Stage 1-3 深接口改造》（024-deep-interface-refactor.md）占用，本 ADR 顺延为 025。
- 实施细节见 feature/agent-memory 分支各 commit；实施中的实现修正（end_line 换算、ADR 索引 MULTILINE、subprocess 编码、budget 量法）记录在 feature/agent-memory 分支各 commit。
