---
name: cycle-close
description: Use when a task/loop reaches its boundary — goal achieved (update_goal complete), task done, or explicitly aborted (blocked/cancelled) — to run the full /finish protocol: re-read task, inspect diff, run deterministic validation, repair, reflect, promote knowledge, persist, and produce a structured Finish Report. Triggers: "/finish", "收尾", "落盘", "循环结束", "任务完成", goal complete/blocked moment.
---

# Finish / Cycle Close（任务收尾 + 学习落盘）

> 这不是"任务完成了"的口头声明，而是一条**可复现的收尾协议**。核心哲学：把重复犯错编译成更强的系统约束（lesson → rule → test/hook），而不是让记忆文件无限膨胀。

## 触发条件（满足其一）

- 任务达成 / `update_goal complete`
- 明确中止（blocked / cancelled）
- 用户说 "/finish" / "收尾" / "落盘"

**不触发**：轮次中途、未达目标继续推进时（只在边界落一次，避免半成品噪音）。

## 完整协议（按序执行）

### Step 1 — 复读任务
重读原始目标、验收标准、约束、受影响文件。**不要因为"代码能跑"就宣布成功**。

### Step 2 — 审查 diff
- 改了什么、是否夹带无关文件改动
- 死代码 / 临时调试代码 / 生成文件 / 架构越界（如 src 直接依赖不该依赖的模块）
- 确认没有误改 `output/`、`models/`、`testsets/pages/` 等被忽略产物

### Step 3 — 确定性验证
- 快门：`npm run check`（语法门）
- 单测：`npm run test`（确定性结构/输出/常量不变量）
- 合并快门：`npm run fastcheck`
- 涉及 koharu_client / 流水线 / 引擎：`npm run smoke`（需先 `npm start`）
- 发布前完整门禁：`npm run finish`
- 遵循项目真实工具，不发明等价新工具

### Step 4 — 修复
失败 → 诊断 → 修复 → 重跑验证。**能修就修，不停在报错。**

### Step 5 — 反思（最重要）
问："本轮是否暴露可复用教训？"
- A. 无可复用 → 丢弃
- B. 一次性实现细节 → 不写
- C. 可复用 lesson → 进 `docs/lessons.md`
- D. 稳定项目规则 → 进 `CLAUDE.md`（保持精简）
- E. 可机械校验的不变量 → 转成 **测试 / lint / hook**

**不要每条观察都写进记忆**（防记忆污染）。晋升管线见下方。

### Step 6 — 知识晋升
```
Observation → 可复用? → No 丢弃 / Yes → 会复发? → No lesson(docs/lessons.md)
                                                    / Yes → project rule(CLAUDE.md)
                                                              ↓ 机械可测?
                                                            No → 规则 / Yes → test/lint/hook
```

### Step 7 — 只更新真正变化的工件
| 工件 | 何时更新 |
|---|---|
| `docs/progress.md` | 当前状态 / 里程碑 / 下一步 |
| `docs/lessons.md` | 可复用 lesson |
| `docs/decisions/` | 架构决策（为什么这样选） |
| `CLAUDE.md` | 稳定操作规则（保持精简，别膨胀） |
| `tests/` · `.githooks/` · `scripts/` | 机械可校验不变量 |

**不要每个任务都改全部文件。**

### Step 8 — git 落盘
- 明确文件 add（**不用 `git add -A`**）→ commit（type: 摘要）→ fetch → push
- Windows 下 stderr 报错但看到 `main -> main` 即成功
- 确认 `git status -sb` ahead=0 behind=0

## 数据真实性校验（先于任何落盘，最致命）

每条要落盘的数据必须是**本会话实测/真实产出**，有证据文件可查（`output/*.json`、脚本输出）。**禁止把"假设/虚构/规划中"的结果当真数据落盘**。拿不出证据 → 只写"待验证/规划"。审计：`npm run audit`。

## Finish Report（收尾输出，给下一个 Agent 读）

```
## Finish Report
Status: PASS / PASS WITH NOTES / FAIL
Validation:
- lint:      （本仓无独立 lint；语法门 = check）
- typecheck: （无类型检查器；结构由单测覆盖）
- tests:     n passed / n failed
- build:     n/a
- other:     smoke / precheck
Files changed:
- ...
Knowledge updated:
- progress:  是/否
- lessons:   L#（标题）
- rules:     是/否（CLAUDE.md）
- decisions: ADR-#（标题）
New constraints created:
- tests/xxx.py 校验 ...
Remaining risks:
- ...
```

不要写成长篇流水账。

## 常见坑

- **假数据落盘（最致命）**：见上方数据真实性校验。实测教训：曾把虚构 "PaddleOCR-VL CER 0.11" 当真落盘推送需回滚。
- **职责重复**：坑/经验只进 `docs/lessons.md`（唯一归属），CLAUDE.md 只留一行指针 + 稳定规则，progress.md 只写状态，不重复。
- **git add -A**：会把临时文件卷进去 → 明确文件列表。
- **Windows stderr 误报**：push 成功但标 exit 1 → 看 `main -> main` 与 `git status -sb`。
- **记忆膨胀**：lesson 已自动化（有测试/hook）后，在 lessons.md 标注 `[已自动化]`，不要把重复规则再堆进 CLAUDE.md。
