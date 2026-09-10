# ADR-007：验证循环分层 + 中止才落盘

**状态**：已采纳（勿改）

## 决策

验证循环采用**分层模式**，且**只在 goal 达成/明确中止时落盘一次**（非每次轮次）：

1. **Benchmark A/B/C = 独立验证**（我自调度，用户不碰终端；改 detector/OCR/prompt 后触发）
2. **Repair Loop / Vision QA = 嵌入 pipeline**（排字后自动质检回修）
3. **发布流程 = 链式**（precheck → smoke → bench，verify skill）
4. **稳定后上 GitHub Actions**（每次 push/PR 自动跑同一验证）

落盘：**中止才落**——goal 达成（update_goal complete）或明确中止时，用 cycle-close（/finish）协议落盘一次，避免半成品噪音。

## 理由

- 官方理念（Anthropic verification loops / getting-started-with-loops）：把人工检查编码成 skill 让 agent 自检，goal loop 有明确 stop condition。
- 用户明确："这些文件不是给人读的，是给 AI 读的"、"中止才落盘"。
- **实测教训**：每次轮次都落盘会产生半成品噪音；边界落一次最干净。

## 后果 / 约束

- 落盘触发 = goal 边界（get_goal/update_goal 时感知），非 DSH hook（DSH 无 SessionEnd hook，Stop hook 有死循环风险）。
- 落盘内容 3 文件分工：progress.md=状态 / lessons.md+CLAUDE.md=坑·结论 / package.json=命令。
- 落盘前强制**数据真实性校验**（禁止虚构/假设当真，见 cycle-close skill）。
