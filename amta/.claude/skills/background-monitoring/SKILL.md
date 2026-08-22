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

## 任务形态判定（完整形态 vs 交互式）

启动长任务前先分类——决定走「goal + 监控 subagent + /finish」完整形态，还是「goal + /finish」轻形态：

| 任务形态 | 特征 | 走哪种 |
|---|---|---|
| **长时运行、可委派** | 有明确等待/轮询点（下载、批量推理、外部服务、跑批） | **完整形态**：goal + background-monitoring subagent 后台盯 |
| **交互式编辑** | 需要我亲手改、每步即时验证（重构、修 bug、写代码） | goal + /finish；监控 subagent 无观察对象，不起 |

判定要点：
- **完整形态的监控对象是"等待"**——任务启动后我不能同时盯着的那段时间，subagent 替我轮询/失败检测/汇报；如果全程我在场且必须在场，监控代理是空转。
- **缺了不算错，但要明说**：轻形态收尾时必须说明"本轮未走完整形态 + 原因"，不默认掩盖。
- 误判实例（诚实记录）：第二轮 OCR 测评有 30 分钟 llama-server 推理等待窗口，本应完整形态但走了轻形态——那是"该补而没补"；重构轮则正确地走了轻形态。

## /simplify 式并行审查（重构类任务的半完整形态）

重构/收尾时，审查环节可照抄 Claude Code /simplify：**3 个并行 subagent 审查 diff，编辑留给我**。
- **Code Reuse Agent**：找重复逻辑/可抽共享函数/该用现有工具而新写的代码。
- **Code Quality Agent**：命名一致性/控制流/过度设计（gold-plating）/与 CLAUDE.md 规范对齐。
- **Efficiency Agent**：多余分配/重复计算/可批量循环/不必要的 IO。
- 流程：`git diff` 定范围 → 3 agent 并行 → 聚合去重 → 我应用修复（false positive 跳过）→ fastcheck 验证。
- 这满足"审查委派 + 编辑保留"，比完整监控形态更适合交互式任务。
