---
name: background-monitoring
description: Use when launching long-running background work (pipelines, batch jobs, subagent fan-out, heavy compute) that must run autonomously with progress monitoring, failure detection, and completion reporting — instead of being manually watched each step. Triggers: "run in background", "自己监控", "别盯着", long jobs, parallel subagents, /loop style self-monitoring.
---

# Background Monitoring（后台任务监控 loop）

## 核心原则

把"启动后台工作 → 自动监控 → 失败检测 → 完成汇报"固化成可重复的循环，让 Agent 不逐帧盯着，而是用**轮询 + 独立并行工作**填满等待时间。

## 本会话实证的坑（baseline failures）

1. **subagent 关闭消息可能不带实际数据**——只写"见上方 JSON"，父 agent 拿不到。→ 重发时必须要求"第一行开始直接输出纯 JSON，无围栏/前言/后注"，否则可能再次空手。
2. **job_output 只对 background job（pwsh-*）有效**，对 subagent 报 unknown job。→ subagent 用 list_agents/send_message，不要用 job_output。
3. **PowerShell 把原生 stderr 当错误**（git push 成功但标 exit 1）→ 看 `[status: completed]` 和 `To https://...main -> main` 而非 exit code。
4. **Windows Python 不展开 argv 通配符**（`*.json` 原样传）→ 用 PowerShell 展开或脚本接目录参数。
5. **PS5.1 写 UTF-8 带 BOM**（Set-Content -Encoding UTF8）→ 读时用 `utf-8-sig`。
6. **同页重复标注冲突**（测试 + 正式两个 subagent 都标了同一批）→ 分配唯一职责，冲突时以分配任务的为准。

## 标准循环

1. **启动**：长任务用 `run_in_background: true`，拿到 job/subagent id。
2. **不空转**：轮询间隔做独立工作（写文档、准备下游、检查依赖），不要 sleep 空等。
3. **轮询**：用 `job_output(wait: true, timeout_ms: ...)` 设合理窗口；超时返回 running 就继续别的，回头再 poll。
4. **失败检测**：看 `[status: ...]`、真实 exit、stderr 内容；不只看 exit code（见坑 3）。
5. **完成收集**：收齐所有片段 → 合并 → 校验完整性（缺失/重复/格式偏差）。
6. **汇报**：数字 + 定位 + 下一步，不只"完成了"。

## 并行 fan-out 指引

- 独立任务一起后台启动（一个 message 多个 subagent），别串行。
- 每片给**明确、唯一**的职责范围（如"只标 page_0+page_1"），避免重复标注。
- 合并脚本要**容忍格式偏差**（.png 后缀、BOM、缺字段），严格按 manifest id 对齐。
- 中途确认"subagent 工具是否可用"用最小可行性测试（1 个小片），别直接全量。

## 何时用 / 不用

**用**：pipeline 跑批、benchmark 全量、并行 subagent 标注、长 compute。
**不用**：单次快速命令、需要你盯的交互式步骤（那些别后台化）。
