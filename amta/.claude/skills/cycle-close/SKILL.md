---
name: cycle-close
description: Use when a goal-based loop reaches its boundary — goal achieved (update_goal complete) or explicitly aborted (blocked/cancelled) — to persist the cycle's outcomes to disk before reporting. Triggers: "落盘", "收尾", "循环结束", "中止才落盘", goal complete/blocked moment.
---

# Cycle Close（循环收尾落盘）

## 核心原则

每次 goal 循环**达成或明确中止时**，把本轮的产出固化到磁盘，让下一个 AI（任何工具）无需对话上下文即可接手。**不是每次轮次都落**——只在循环边界落一次，避免半成品噪音。

**写给 AI 读，不是给人读**：每项写"结论 + 证据"（数据/文件路径），不写流水账。这符合官方理念 "encode it to improve the system for all future iterations"。

## 触发条件（三选一即触发）

- `update_goal complete`（目标达成）
- `update_goal blocked` / cancelled（明确中止）
- 用户说"收尾/落盘/循环结束"

**不触发**：轮次中途、未达目标继续推进时。

## 3 文件分工（唯一事实来源，避免重复）

| 文件 | 职责 | 更新什么 |
|---|---|---|
| `docs/progress.md` | **流程/状态** | 当前状态（完成到哪）、里程碑表、下一步 |
| `CLAUDE.md` | **坑/经验** | 新踩的坑、新结论（数据背书）、决策变更；更新"坑"节与渐进式加载表 |
| `package.json` | **工具调用** | 新增可调用命令（npm scripts 映射真实脚本） |

## 执行顺序

1. **收集**：列出本轮产出——新文件/脚本、新数据（benchmark 指标）、新坑、新命令。
2. **⚠️ 数据真实性校验（必须，先于落盘）**：每条要落盘的数据必须是**本会话实测/真实产出**，有证据文件可查（如 `output/*.json`、脚本输出）。**禁止把"假设/虚构/规划中的结果"当真数据落盘**。检查方式：数据指向的文件存在吗？数字来自哪个实测？拿不出证据的结论→只写"待验证"或"规划"，不写"结论"。
3. **更新 progress.md**：状态节追加本次成果（含数字与文件路径）+ 下一步。
4. **更新 CLAUDE.md**：新坑进"坑"节；新结论进核心事实或相关 skill（不重复）；新增 skill 挂渐进式加载表。
5. **更新 package.json**：新脚本进 scripts（必须映射真实脚本，git/gh 不包）。
6. **git 落盘**：明确文件 add（不用 `git add -A`）→ commit（type: 摘要）→ fetch → push。Windows 下 stderr 报错但看到 `main -> main` 即成功。
7. **确认**：`git status -sb` 显示 ahead=0 behind=0。

## 给 AI 读的格式

```
- **结论**：一句话（如"Baberu 是 SFX 答案"）
  - 证据：CER 0.181 vs manga-ocr 1.0（output/benchmark_b_sfx.json）
  - 产出：src/baberu_ocr.py, src/sfx_compare.py
```

## 常见坑

- **假数据落盘（最致命）**：把"假设/虚构/规划中"的结果当真数据写进仓库并推送。→ 落盘前必须验证：数据指向的文件存在吗？数字来自哪个实测？拿不出证据只写"待验证"。**实测教训**：skill 测试时 subagent 曾把虚构的"PaddleOCR-VL CER 0.11"当真落盘推送，需回滚纠正。
- **职责重复**：同一坑既写 progress.md 又写 CLAUDE.md → 只进 CLAUDE.md（坑的归属），progress.md 只写状态。
- **git add -A**：反模式（会把临时文件卷进去）→ 明确文件列表。
- **Windows stderr 误报**：push 成功但标 exit 1 → 看 `main -> main` 与 `git status -sb`。
- **不要记流水账**：半成品状态不落盘；只在边界落一次。
