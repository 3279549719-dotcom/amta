# 028 — Ralph Loop：外层循环 + 文件状态的无人值守开发循环

日期：2026-09-04　状态：已采纳（MVP 验证通过，3 次迭代）

## 决策

1. **外层循环 = `ralph.ps1`**：PowerShell for 循环，每次迭代启动一个**新鲜**的 `claude -p` 会话（无上下文继承），用 `prompt.md` 作为强制工作流指令。循环检测 `<promise>COMPLETE</promise>` 信号或达到最大迭代次数后停止。
2. **工作流指令 = `prompt.md`**：10 步强制流程，第 8-9 步**强制写记忆**（更新 `loop_state.json` + 追加 `ralph-log.md`），第 7 步强制沉淀可复用经验到 `docs/lessons.md`。agent 每次迭代都必须走完。
3. **状态外化 = `loop_state.json`**：repo 根的机器可读 JSON（mission / current_step / next_action / last_verified / escalation / updated_at），由 agent 每步读写。这是跨迭代记忆的唯一权威来源——**progress lives in files, NOT in LLM context**。
4. **学习日志 = `ralph-log.md`**：append-only，每次迭代追加"做了什么/改了哪些文件/fastcheck 结果/经验教训/下一步"。
5. **记忆读 = SessionStart hook**：`.claude/settings.json` 的 SessionStart hook 跑 `uv run python scripts/memory_inject.py`，把 `loop_state.json` 摘要注入 `CLAUDE.local.md`。**必须用 `uv run python`**（系统 Python 3.14 无 requests，原 hook 静默失败 3 天）。
6. **记忆写 = prompt 工作流，不是 hook**：写记忆不靠 PostToolUse/Stop hook，靠 `prompt.md` 第 8-9 步的强制指令。验证证明 agent 每次迭代都执行了。
7. **不采用**：多 agent 架构、接第二个模型做判分、SQLite 5-tier memory（forgegod）、LangGraph 等重型框架。单模型 deepseek + 确定性 fastcheck + 文件状态 = 完整循环。

## 理由

- **用户痛点**：每次开完分支执行任务都要人按回车、人提醒写记忆、人提醒读记忆——"我不想当按回车的调度器"。原记忆系统"看起来有实际上一次都没有自动化过"。
- **记忆坏死根因诊断**：`.remember` 已不激活；hook 命令 `python scripts/memory_inject.py` 因系统 Python 3.14 无 requests 而每次静默 `ModuleNotFoundError`；`loop_state.json` 停留在 9/1 stale。记忆引擎本身没坏，坏的是 hook 命令和"写记忆从未自动化"。
- **三开源项目对比结论**（见 `E:\Agent Loop Learning\reference\10-ralph-loop-reference-audit.md`）：
  - `snarktank/ralph`（最简）：bash for 循环 + `claude --print < CLAUDE.md`，记忆=prd.json+progress.txt+git。**直接可照搬**。
  - `shreyasssk/foundry`（中等）：Crucible 规划 + Forge 执行两阶段，6 个 agent。对个人项目过重。
  - `waitdeadai/forgegod`（最完整）：Python 框架，51KB loop.py + 81KB memory.py，SQLite 5-tier memory。**过度设计**。
  - 共同铁律：**"Progress lives in git + files, NOT in LLM context"**。
- **MVP 验证结果**（3 次迭代，全部成功）：
  - 迭代 1：删 3 个编码损坏探针（主动发现连带 import 依赖），compile 转绿，自动更新状态+写日志+commit。
  - 迭代 2：修 depguard PEP 503 归一化 bug，depguard 11→9 项，**主动沉淀 L36 到 docs/lessons.md**。
  - 迭代 3：blocked-on-human 状态不硬编造任务，产出证据包供裁决，新增 L37。
  - 记忆跨迭代流动验证：迭代 1 发现".venv 无 ruff 须用 py -3.13"写进 escalation，迭代 2 的 agent 读了 loop_state 后直接使用。

## 备注

- **与 ADR-027 的关系**：ADR-027 定义了记忆层 v2（注入瘦身 + loop_state + MCP 字典 + writeback）。本 ADR 是其**落地实现**——loop_state 从"为自主循环打底"变成"实际被外层循环读写"；writeback 从"确定性 harness 解析"变成"prompt 第 8-9 步强制"。MCP 字典仍按需检索。
- **fastcheck 仍红但全 pre-existing**：ruff 24 errors（删探针后从 54 回落）、pytest 18 failed（task #6）、depguard 9 项（4 探针命运 + text_mask_refiner cv2，待人类裁决）。ralph loop 不越权修历史债，只修当前任务相关的。
- **沟通护栏**：prompt.md 写死"除非删除/推 main/超预算否则直接做"，把找人变成稀有事件。用户反馈"问 1 个和问 10 个没区别，都按 recommend option 来"。
- **下一步**：① 裁决剩余 fastcheck 红项后继续跑 ralph loop 清账；② 考虑 Windows 任务计划定时触发（夜间无人值守）；③ 加每日摘要（ralph-log.md 当日条目汇总）；④ 把 ralph.ps1/prompt.md 收编进项目规范（本文档即收编第一步）。
- **相关**：ADR-025（四层闭环）、ADR-026（记忆选型）、ADR-027（记忆层 v2）。
