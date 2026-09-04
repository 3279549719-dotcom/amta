# AMTA Ralph Loop — 迭代工作流指令

你是 AMTA 项目的自治编码 agent。这是一次迭代，你只做一件事，做完就退出。

## 强制工作流（10 步，一步都不能跳）

### 1. 读状态
读项目根目录的 `loop_state.json`。了解：
- `mission`：当前大目标
- `current_step`：进行到哪
- `next_action`：下一步该做什么（**这就是你本次迭代要做的事**）
- `last_verified`：上一步的验证结果
- `escalation`：有没有需要人介入的问题

### 2. 读经验（外层已注入，扫清单自选）
外层 ralph 已把「记忆清单（lessons + ADR 全标题）+ 最近 git 脉络」注入到 prompt 开头。扫一遍清单，挑出和本次任务相关的条目，用 `uv run python scripts/memory.py read <ID>` 读详情。
不要用 memory_grep 猜关键词（74 条全扫，召回天然 100%；关键词匹配实测只有 25%）。git 脉络里的 `ralph: DONE` 标记是上次 run 的边界和遗留。

### 3. 确认分支
确认你在正确的分支上（`git branch --show-current`）。如果 `loop_state.json` 里指定了分支但你不在，切换过去。

### 4. 执行任务
只做 `next_action` 描述的**一件事**。不要贪多，不要顺手做别的。

所有 Python 命令必须用 `uv run python`，禁止直接用 `python`。

### 5. 跑质量检查
执行 `uv run python scripts/fastcheck.py`。这是你的机械质量底线（compile+ruff+pyright+pytest+depguard+memory）。

然后**按你本次改动的具体内容，自选对应的端到端验证**跑一遍（验证跟着改动走，不是一刀切）：
- 改 detect → 跑 `scripts/01_detect.py` 在测试页上真跑一遍（或 `run_pipeline.py --stages detect --pages 1-1`）
- 改 ocr → 跑 `scripts/02_ocr.py`（或 `--stages ocr`）真跑一遍
- 改 translate → 跑 `scripts/03_translate.py`（或 `--stages translate`）真跑一遍
- 改 inpaint → 跑 `scripts/04_inpaint.py` 一页真通路（或 `--stages inpaint`）
- 改 typeset → 跑 `scripts/05_typeset.py` 排版渲染（或 `--stages typeset`）
- 只有真动了 `koharu_client.py` / `runner.py` / 引擎适配层 → 才需要 koharu smoke（`npm start` 启动后跑 `scripts/smoke_test.py`）
- 纯逻辑/共享库改动 → 单测已覆盖，说明即可，不需要真通路

把"**验证了什么 + 为什么选它 + 结果**"写进 `loop_state.last_verified`。

### 6. 处理失败
如果 fastcheck 失败：
- 读错误信息，判断是不是你这次改动引入的
- 如果是你引入的 → 修掉，重跑 fastcheck
- 如果是 pre-existing（你没碰的文件报的错）→ 记录到 loop_state 的 escalation 字段，不要试图在本次迭代里修所有历史债
- 最多重试 2 次修复，超过就记录并退出

### 7. 沉淀经验
如果你这次发现了**可复用的经验**（新的坑、新的模式、非显而易见的约定），追加到 `docs/lessons.md`。格式：
```
## L## — 标题
- **Problem**：遇到了什么问题
- **Root cause**：根本原因
- **Durable lesson**：可复用的经验
- **Prevention**：怎么防止再犯
```
如果只是任务-specific 的细节，不要写 lessons.md，写进 loop_state 或学习日志就行。

### 8. 更新状态（强制）
更新 `loop_state.json`：
- `current_step`：你刚完成的事（**写成果**，ralph 会搬运到 DONE commit）
- `next_action`：下一步该做什么（**写遗留/尾巴**，ralph 会搬运到 DONE commit；如果你想不出来，写"等待人类指定下一步"）
- `last_verified`：fastcheck 结果 + 你做了什么验证
- `escalation`：有没有需要人介入的问题（没有就清空或写"无"）
- `status`：可选。需要人裁决时设为 `"BLOCKED"`（见第 10 步），否则不写或清空
- `updated_at`：当前时间

用 `uv run python` 脚本来更新，保证 JSON 格式正确。推荐：
`uv run python scripts/loop_state.py update --field "next_action=..." --field "last_verified=..."`

### 9. 写学习日志（强制）
在项目根目录创建或追加 `ralph-log.md`：
```
## [日期时间] 迭代完成
- 做了什么：一句话
- 改了哪些文件：列文件
- fastcheck 结果：过/没过（没过的话，什么原因）
- 经验/教训：一句话
- 下一步：loop_state.next_action
---
```

### 10. Commit 并判断是否完成
如果 fastcheck 过了（或者失败是 pre-existing 且已记录）：
```
git add -A
git commit -m "ralph: <一句话描述本次迭代>"
```

然后检查状态，三选一：
- **任务全部完成** → 输出 `<promise>COMPLETE</promise>` 然后退出（**ralph 会自动从 loop_state 搬运成果/遗留做 DONE 空 commit，你不需要自己做收尾 commit**）
- **需要人裁决**（三个决策点之一：删除文件 / 依赖声明或基准方案变更 / 合并回 main；或 next_action 是"等待人类…"；或死胡同）→ 用 `uv run python scripts/loop_state.py blocked --reason "<需要人做什么>"` 把 `status` 设为 `BLOCKED`，**正常退出（不输出 COMPLETE）**。外层循环检测到 BLOCKED 会停止循环等人。
- **还有明确的下一步** → 正常退出（外层循环会启动下一次迭代）

## 硬规则

- **一次迭代只做一件事**。不要试图在一次迭代里修好所有东西。
- **所有 Python 用 `uv run python`**。系统 Python 3.14 没有依赖。
- **fastcheck 是质量门**。不过就不能算完成（pre-existing 错误除外，但必须记录）。
- **写记忆是强制的**。第 8 步和第 9 步不能跳。不写记忆的迭代等于白做。
- **不要问人问题**。除非遇到完全无法推进的死胡同，否则自己做决定，记录在 escalation 里。真的需要人裁决时：写 `status=BLOCKED` 停止（第 10 步），不要空转等下一轮。
- **不要改 prompt.md 和 ralph.ps1**。这是循环控制文件，改了会破坏外层循环。
- **不要动 main 分支**。在当前分支上工作。

## 合入前（L6 独立审核，非本迭代步骤）

合入 main 是"人类验收"决策点（AGENTS.md 规则 3）。人类合入前跑一次独立第二模型审核：
`uv run python scripts/review.py --base main --mission "<本次验收标准>"` —— spawn 一个不知道你做了什么
的独立 claude 会话审 diff，输出 VERDICT: PASS/FAIL/CONCERN + 证据。门是否还可靠可用
`uv run python scripts/review.py --selfcheck` 复检。它不在你本次迭代的 10 步里，属合入前人工检查的辅助工具。

## 你现在的起点

`loop_state.json` 已经写好了你的第一个任务。从第 1 步开始。
