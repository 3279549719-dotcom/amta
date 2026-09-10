# ADR-032：Hook 体系审计收敛（停用 pre-commit + PreToolUse，保留 pre-push + SessionStart）

> **本决策部分被推翻**（2026-09-10）：pre-commit 已重新启用，但不再跑完整 fastcheck 8步，改为只跑 `fastcheck --quick`（5步：compile + ruff + pyright + ROOT check + env check，秒级）。完整 8 步留给 /finish 收尾。停用 pre-commit 的原始理由（完整8步太慢、误报历史债务）已通过分层设计解决。


> 状态：已采纳（2026-09-07 执行，commit 5fac83f）
> 审计员：仓库 hook 体系审计（claude agent，经 ralph_sdk.py 壳）· 日期：2026-09-07
> 审计范围：`.githooks/pre-commit`、`.githooks/pre-push`、`.claude/settings.json`（SessionStart + PreToolUse）、`scripts/hook_sessionstart.py`、`scripts/hook_pretooluse.py`、`scripts/fastcheck.py`
> 结论方向（用户已定）：hook 冗余、过度追求验证阶梯，倾向只保留「合 main 前 fastcheck」。

---

## 0. 现状核实（事实层）

- `git config core.hooksPath` = `E:/manga translator agent/amta/.githooks`，**已生效**（`.git/hooks/` 为空，由 install_hooks.ps1 重定向）。
- `.githooks/` 下仅 `pre-commit`、`pre-push` 两个 git 钩子。
- `.claude/settings.json` 注册 2 个 claude 钩子：`SessionStart`、`PreToolUse(matcher=Bash)`。
- `fastcheck.py` 的 main 串行跑 **8 环节**：compile / ruff lint / pyright typecheck / pytest / depguard / memory lint / memory gc(dry-run) / memory inject。

**关键结构性事实**：所有检查都是**整棵工作区**级（`compileall src scripts`、`ruff check src scripts tests`、`pyright src`、整批 pytest），**没有任何一个钩子按 git diff / staged 范围只查「本次提交引入」**。这是「无法区分本次引入 vs 历史在途债务」的根因，且为多个钩子共享，不是单点可修。

---

## 1. 逐钩子审计

### 1.1 `.githooks/pre-commit`（Level 2）

| 维度 | 结论 |
|---|---|
| 职责 | 每次 commit 前跑**完整** fastcheck（8 环节全量） |
| 与其它钩子重叠 | 与 `.githooks/pre-push` 的 fastcheck 段**逐字节相同**（同一 `$PY scripts/fastcheck.py`），纯重复；与 PreToolUse 钩子的 compile+ruff+pyright 段子集重复 |
| agent 自主工作流下 | **摩擦为主**。agent 走小而频繁的提交，每次 commit 都付全量 fastcheck 代价（~分钟级）；且命中真实事件——commit `ee8f7dd` 时 6 个拦截问题里 5 个是工作区历史在途改动（docs/lessons.md、ocr_engines.py、translate.py 等未提交脏改动）导致，**与本次提交无关**。小改动提交被整树历史债务持续卡死。 |
| 区分「本次引入 vs 历史在途」 | **无**。全量整树检查，无法按 diff 判定归属 |
| 处置建议 | **删除 / 停用**（内容与 pre-push 完全重复，频率却是每次 commit，误报债务最高） |

理由：fastcheck 已是「整树干净才过」的验证，天然只该在**工作区应干净**的边界点（合 main 前）跑一次；塞进每 commit 只会让历史上任何一笔在途改动反复阻塞无关提交。把唯一一次全量验证留给 merge 边界即可，commit 层不需要独立再付一份。

### 1.2 `.githooks/pre-push`（Level 3）

| 维度 | 结论 |
|---|---|
| 职责 | push 前跑**同一份完整** fastcheck + 可选 smoke（koharu 可达才跑，不硬绑） |
| 与其它钩子重叠 | fastcheck 段与 pre-commit 逐字节重复；smoke 独有 |
| agent 自主工作流下 | **保护为主**，且是对的方向。这是「合 main 前 fastcheck」的自然落点：push main 时工作区理论应干净，整树校验合理；smoke 为 koharu 引擎改动提供端到端可选验证（ADR-030 由 agent 按改动自选），不强制、不猜测。 |
| 区分「本次引入 vs 历史在途」 | 仍无 diff 判定，但 merge 边界本身要求整树干净，语义上可接受 |
| 处置建议 | **保留** —— 作为唯一一处「合 main 前 fastcheck」门（在合并进 main 的 push 边界触发） |

理由：用户要的「合 main 前 fastcheck」只有这一个钩子能站住。保留后，commit 层（1.1）即可去掉，fastcheck 由「每 commit + 每 push」降为「每 push 一次」。

> 注意边界盲区：若 agent **本地 merge 到 main 而不 push**（无远端推进），pre-push 不触发。故「合 main 前」若要绝对保证，应由 agent 的收尾协议（cycle-close / verify skill 已含 fastcheck 步骤）作为兜底，而非单押 git 钩子——这与 CLAUDE.md「任务收尾必须走 /finish 确定性验证」一致，属 agent 自主调用的确定性门，不增加钩子冗余。

### 1.3 `.claude/settings.json → SessionStart`（`scripts/hook_sessionstart.py`）

| 维度 | 结论 |
|---|---|
| 职责 | 新会话跑 `memory.py inject` 刷新注入包 + 打印分支 / git status / 最近 commit / loop_state 摘要 |
| 与其它钩子重叠 | 其中 `memory inject` 一步与 `fastcheck._memory_inject` 重复（两处都重建 CLAUDE.local.md） |
| agent 自主工作流下 | **保护为主，成本低**。纯只读展示 + 记忆注入推送，不 gate、不 deny、不拦工具；只在 SessionStart 触发一次，对会话是「接续状态」刚需（loop_state / mission 需在每会话开头加载） |
| 区分「本次引入 vs 历史在途」 | 不适用（非验证门） |
| 处置建议 | **保留**（memory inject 与其放在 fastcheck，不如留在 SessionStart 作为推送机制触发点更合理；fastcheck 里的 `_memory_inject` 才是可省那侧） |

理由：它不是验证阶梯的一部分，不制造提交/审计摩擦，是记忆推送机制（DSH agent-instructions 注入 CLAUDE.local.md）的刷新触发点。唯一重复是 memory inject 也在 fastcheck 每轮跑——属于 fastcheck 内环节过多的问题，不应砍 SessionStart 来解。

### 1.4 `.claude/settings.json → PreToolUse(matcher=Bash)`（`scripts/hook_pretooluse.py`）

| 维度 | 结论 |
|---|---|
| 职责 | 拦截 Bash 中含 `"git commit"` 或 `"git merge"` 的调用，跑**子集** fastcheck（compile + ruff + pyright，不跑 pytest，30s 超时），FAIL 则 deny 阻止 |
| 与其它钩子重叠 | 与 pre-commit 的 compile+ruff+pyright 段重复；且**真正的 git commit/merge 本就走 git 钩子**（1.1/1.2），这一层纯属在会话层对同一动作重复设卡 |
| agent 自主工作流下 | **纯摩擦 + 有 bug**。① 子串匹配：`"git merge" in command` 会把只读审计命令 `git merge-base` 误判成 merge → 真实事件中连拦 4 轮只读 git 命令；② 只对 claude 会话内 Bash 生效，cli 直跑/CI 全绕过；③ git 钩子已兜底，它拦不住的东西不多、拦错的东西不少 |
| 区分「本次引入 vs 历史在途」 | 无（整树 compile/ruff/pyright） |
| 处置建议 | **删除 / 停用**。matcher 本身可用，但该策略（会话层重复 git 钩子的全量校验 + 脆弱的子串判词）在 agent 自主执行下弊大于利 |

理由：它存在的唯一价值是在 claude 会话里 commit/merge 前提前暴露错误，但真实提交仍会被 git 钩子拦截，故它只是「提前一点点、还常误报」的重复层；`git merge-base` 误杀只读分支审计即不可接受的负价值。删掉后，「合 main 前 fastcheck」由 pre-push（1.2）+ agent 收尾协议兜底，无缺口。

---

## 2. 冗余/重叠汇总矩阵

| 验证动作 | pre-commit | pre-push | PreToolUse | SessionStart | fastcheck.py(直接跑) |
|---|---|---|---|---|---|
| compile + ruff + pyright | ✅全量 | ✅全量 | ✅子集(无pytest) | — | ✅ |
| pytest 单测 | ✅ | ✅ | — | — | ✅ |
| depguard | ✅ | ✅ | — | — | ✅ |
| memory lint/gc/inject | ✅ | ✅ | — | ✅(仅 inject) | ✅ |
| smoke(koharu) | — | ✅可选 | — | — | (verify skill) |

- **同一份完整 fastcheck 被 2 个 git 钩子各跑一次**（pre-commit + pre-push 逐字节同源）。
- **memory inject 在两个入口重复**（fastcheck 每轮 + SessionStart 每会话）。
- **PreToolUse 又叠一层 compile+ruff+pyright 子集**在会话层。
- 实质上是 **3 个独立触发点对同一整树验证各自跑一遍**（commit 时 / push 时 / 会话 command 时），全部无 diff 归属判定。

---

## 3. 整体结论

1. **验证阶梯过度**：全量 fastcheck（8 环节、分钟级、整树、无 diff 归属）被安排在 commit + push + 会话三个触发点重复执行，在 agent 小步提交的自主工作流下，命中「ee8f7dd 5/6 无关拦截」「git merge-base 连拦 4 轮」两类实证摩擦。
2. **「区分本次引入 vs 历史在途」是所有钩子的共同缺口**：fastcheck 是整树设计，任何钩子都做不到按提交归类——这正是它不该高频触发（每 commit）的根因，而非某个钩子单点可修。
3. **真正的价值收敛到一点**：「合 main 前」工作区应干净、做一次全量验证（pre-push / 或 agent 收尾协议），其余触发点的同类重复均可移除。这与用户既定方向一致。

---

## 4. 最小动作建议

| 动作 | 对象 | 类型 | 影响 |
|---|---|---|---|
| **保留** | `.githooks/pre-push` | 合 main 前唯一 fastcheck + 可选 smoke | 唯一验证门，最低摩擦 |
| **删除** | `.githooks/pre-commit` | 内容与 pre-push 逐字节重复，且每 commit 触发 + 整树债务误报 | fastcheck 从「每 commit+每 push」降为「每 push 一次」 |
| **删除** | `.claude/settings.json` PreToolUse 块 + `scripts/hook_pretooluse.py` | 会话层重复 git 钩子的子集校验，`git merge-base` 误杀只读命令 | 消除只读审计被拦摩擦 |
| **保留** | `.claude/settings.json` SessionStart 块 + `scripts/hook_sessionstart.py` | 只读状态展示 + 记忆注入推送，非验证门、成本低 | 接续状态刚需，无摩擦 |
| **（可选）后续** | 从 `fastcheck.py` main 去掉 `_memory_inject`（`_memory_gc` dry-run 同理），因 SessionStart 已负责刷新 | 消除「memory inject 双入口」 | 缩短 fastcheck 单轮耗时 |

> 若想「可恢复」而非彻底删除：pre-commit / PreToolUse 的文件改扩展名（如 `.pre-commit.disabled`）并注释 settings 引用即可随时还原，无需 `git rm`。此报告中删除均指**停用**，非销毁源码。

**收尾风险提醒**：改动 git 钩子生效（删除/改名文件）后需同步 CLAUDE.md「机械护栏三级」描述与 `docs/lessons.md`，避免协议与实际 hook 面脱节。