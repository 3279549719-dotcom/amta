# Ralph Loop — 无人值守开发循环

> 架构决策见 [ADR-028](decisions/028-ralph-loop-autonomous-development.md)。本文档跟踪 ralph.ps1/prompt.md 现行语义（**v4，2026-09-06**）。

## 一句话

**一次 `claude -p` 跑完整使命**（claude -p 自压紧上下文，单个会话能跑完跨多 commit 的工作）。agent 读 `loop_state.json` → 按 `plan` 顺序执行全部 chunk（每个 chunk：跑 fastcheck → 更新状态 → commit）→ plan 全 done 跑收尾轮 → `<promise>COMPLETE</promise>`。**人只需要设任务和裁决 BLOCKED，不需要按回车。**

## 为什么从 v3 分片迭代改成 v4 单会话

2026-09-06 教训（artifact-store mission）：v3 每 chunk 冷启动一个新 `claude -p`，900s 墙钟超时掐死过 productive agent（两次死在干活中途），每轮从零重建上下文重读 = **纯空耗 token**。claude -p 自压紧（v2.1.218+ 实证）后，分片重启整台机器过时。**教训不是"不要长跑"，是"不要按时间杀 + 不要为分片而冷重启"。**

## 快速开始

```powershell
# 1. 设使命：research/ 写 mission 简报（范围/授权/验收口径），把 mission + plan 填进 loop_state.json
# 2. 启动（跑完自然结束；崩溃才自动重试）
.\ralph.ps1                 # 默认最多 2 次整使命尝试
.\ralph.ps1 -MaxAttempts 3
.\ralph.ps1 -PromptFile my-mission.md
```

## 核心文件

| 文件 | 作用 | 谁写 | 谁读 |
|------|------|------|------|
| `ralph.ps1` | 单会话 runner：启动 claude -p / 心跳 churn 兜底 / attempt 重试 | 人 | 人运行 |
| `prompt.md` | mission 工作流指令（v4：本会话 = 整个 mission） | 人 | agent（每次 spawn 一次） |
| `loop_state.json` | mission/plan/status（idle 态 + 每使命 seed） | 人 seed / agent 边界更新 | agent + ralph |
| `ralph-log.md` | append-only 运行记录（start/COMPLETE/BLOCKED/failed） | ralph | 人 |
| `scripts/trace_probe.py` | 读 claude transcript JSONL（live/tail/stats），卡死诊断 | — | ralph |
| `scripts/ralph_context.py` | spawn 前拼 preamble（memory 清单 + git log）+ DONE commit msg | — | ralph |
| `scripts/loop_state.py` | loop_state 读写 CLI（show/update/blocked/plan） | agent / ralph | agent / ralph |

## 退出路径（ralph 只认这三个）

1. **COMPLETE**（agent 输出 `<promise>COMPLETE</promise>`）→ 写 DONE commit，exit 0
2. **BLOCKED**（agent 写 `status=BLOCKED` 等人）→ exit 2；人清 status 后续跑
3. **异常/无信号退出** → trace 诊断写 ralph-log → 从 git HEAD 整使命重试（≤ MaxAttempts）→ 仍失败 exit 3

**没有"每 chunk 一次迭代"路径。** agent 中途主动退出（无 COMPLETE/BLOCKED）= 让 ralph 判失败重试 = 浪费一次整使命 token —— prompt.md 已写死禁止。

## 兜底（只防真卡死，不按时间杀 productive）

- **墙钟超时：无。**
- **心跳失守**：claude transcript JSONL 连续 `HeartbeatStallSeconds`（默认 1800s）无新写入 → 翻尾部判断：
  - 有 `is_error=True` 重复（churn）→ 停
  - 无错误迹象（跑长 fastcheck / 长思考）→ **不杀**，重置观察窗继续等
- 中断靠 git commit 恢复：新 attempt 的 prompt 带 `git HEAD = xxx` resume note，agent 先核实现场再续。

## 关键约束（沿用）

- 所有 Python 用 `uv run python`；fastcheck 用 `py -3.13 scripts/fastcheck.py`（L26，`.venv` 无 ruff）
- pre-existing 红项记 escalation 不越权修历史债
- agent 只在 COMPLETE/BLOCKED/死胡同退出；不主动退出等外层踢下一脚
- 合 main 是人的动作（prompt.md 写死）；合前按需 L6 独立审核（ADR-030，小改动不强制）

## 候选升级（未启用）

claude `--bg` + `claude agents`（原生后台会话 + done/blocked/stopped 状态 + Notification hook + supervisor 崩溃重启）可取代整个外层循环——但当前钉的 claude 2.1.220 上仍是 research preview、无 stall 检测、无结构化结果字段。升级 claude 后再评估（见 research/10-claude-code-headless-and-ralph-optimization.md）。
