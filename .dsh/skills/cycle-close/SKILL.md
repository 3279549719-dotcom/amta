---
name: cycle-close
description: 'Close a work cycle. Reviews the diff for stray/dead/ignored-file changes, reflects on what this session actually taught, routes each reusable observation to its one home (CLAUDE.md / .dsh/skills/ / ADR / lessons / tests·hook / discard), then lands everything through the single finish entry point — `state.py finish`, which runs the full quality gate and refuses to commit when red. Use when a task reaches its boundary: done, blocked, or cancelled; or when the user says "/finish", "收尾", "落盘", "循环结束", "任务完成". Do NOT use mid-task — one close per boundary.'
---

# cycle-close — 收尾

> 收尾只解决一个问题：**这次会话学到的东西，回到它该去的地方了吗？**
> 其余全是机械动作，而机械动作已经全部沉到一条命令里。

## 三个动作，按此顺序（顺序本身是协议的一部分）

### 1. 审 diff —— 有没有夹带

`git status` + `git diff --stat`。查三样：死代码 / 临时调试代码 / 误改的被忽略产物（`output/`、`models/`、`testsets/pages/`）。
发现就**当场删掉**，不要留给 commit。"代码能跑"不是收尾判据——判据在动作 3。

### 2. 反思 —— 这次会话教会了什么

对着 diff 和会话过程问一遍：**有没有一条观察，下次还会用到？**
没有就跳过——**大多数会话都该跳过，这是正常结果，不是偷懒。**

有就分流，每条观察只去**一个**地方：

| 观察的性质 | 去哪 |
|---|---|
| 全局规则 / 事实 | `CLAUDE.md`（一行，保持精简） |
| 流程 / 程序 | `.dsh/skills/<name>/SKILL.md` |
| 架构 / 方向（为什么这样选） | `docs/decisions/ADR-N` |
| 可复用的坑（不会复发） | `docs/lessons.md` |
| 机械可校验的不变量 | `tests/` · `.githooks/`（唯一真强制层） |
| 瞬时状态 | git 与分支本身 |
| 拿不准 / 一次性的 | **丢弃** |

判不准就用「丢弃」。预防性机制一律不建，宁缺毋滥——**不要每条观察都写进记忆**。

### 3. 落盘 —— 一条命令，一次提交

    uv run python scripts/state.py finish "type: 摘要"

- 它跑**全量**质检（compile+ruff+pyright+pytest+depguard+memory lint/gc+module-map 刷新），**红了就拒绝提交，改动原样留在工作区**。
- 暂存与提交由它一手包办（**不要手工暂存**）。你写的那条摘要就是本次的会话摘要——不需要另写一份报告。
- 因为动作 1、2 都发生在它之前，**反思产出的知识改动和代码改动进的是同一个 commit**，不会留下"反思完了但没提交"的悬空状态。
- 改到一半想秒级只读快检：`uv run python scripts/fastcheck.py --quick`（pre-commit 跑的就是它，两条路同一扇门）。
- **本技能只出现这两条项目工具命令名。**不要发明等价的第三套工具。

推送不属于本技能，但收尾时记得：`git fetch origin` → 评估分叉 → rebase → push → 确认 `git status -sb` 为 ahead=0 behind=0。

## 两条铁律

1. **数据真实性**：要落盘的数据必须是本会话实测产出，有证据文件可查（`output/*.json`、脚本输出）。禁止把假设 / 规划中 / 虚构的结果当真数据落盘——曾把虚构的 "PaddleOCR-VL CER 0.11" 当真落盘推送，需回滚。拿不出证据就写"待验证"。**本仓已无自动审计器（`scripts/audit.py` 已归档），这条是 prompt 级规则，靠自律。**
2. **派生指标口径一致**：入库数据里缓存的派生指标（cer/em 等）必须与当前代码口径一致。有一致性测试的由测试兜底；无测试的，落盘前用现行 metrics 重算一遍（L14）。

## 常见坑

- **Windows push stderr 误报**：看到 `main -> main` 且 `git status -sb` ahead=0 即成功，exit 1 可忽略。
- **记忆膨胀**：lesson 已有测试/hook 兜底后，在 `docs/lessons.md` 标 `[已自动化]`，不要把同一条规则再堆进 CLAUDE.md。
- **收尾规程只有一处**：就是本文件；执行入口只有 `state.py finish`。在别处写第二套等价步骤会被 `tests/test_harness_covenant.py` 的 H7 拦下。
