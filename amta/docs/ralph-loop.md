# Ralph Loop — 无人值守开发循环

> 架构决策见 [ADR-028](decisions/028-ralph-loop-autonomous-development.md)。

## 一句话

外层 PowerShell 循环每次踢一个新鲜的 `claude -p` 会话，agent 读 `loop_state.json` → 执行 `next_action` → 跑 fastcheck → 更新状态 → 写日志 → commit，然后循环踢下一脚。**人只需要设定任务和裁决阻塞项，不需要按回车。**

## 快速开始

```powershell
# 1. 设定任务（编辑 loop_state.json 的 next_action）
#    例如："删除 scripts/xxx.py，然后重跑 fastcheck"

# 2. 启动循环（默认 10 次迭代）
.\ralph.ps1

# 或指定迭代次数
.\ralph.ps1 -MaxIterations 5

# 或指定自定义 prompt
.\ralph.ps1 -MaxIterations 20 -PromptFile my-prompt.md
```

## 核心文件

| 文件 | 作用 | 谁写 | 谁读 |
|------|------|------|------|
| `ralph.ps1` | 外层循环脚本 | 人 | 人运行 |
| `prompt.md` | 10 步强制工作流指令 | 人 | agent（每次迭代） |
| `loop_state.json` | 任务状态（mission/next_action/last_verified/escalation） | agent（每步更新） | agent（每步读取）+ memory_inject |
| `ralph-log.md` | append-only 学习日志 | agent（每步追加） | 人（复盘） |
| `docs/lessons.md` | 可复用经验库（L1-L37+） | agent（第 7 步沉淀） | agent（memory_search） |
| `.claude/settings.json` | SessionStart hook（`uv run python scripts/memory_inject.py`） | 人 | claude |
| `scripts/trace_probe.py` | claude 会话 JSONL 探针（心跳定位 / 卡死诊断 / trace 统计） | ralph.ps1 | ralph.ps1 |
| `scripts/loop_state.py` | loop_state 读写 CLI（含 `blocked` 快捷命令，写 status=BLOCKED） | agent / ralph | agent / ralph |
| `CLAUDE.local.md` | 自动注入的记忆包（loop_state 摘要 + 字典规则） | memory_inject.py | agent（会话启动） |

## prompt.md 10 步工作流

每次迭代的 agent 必须按顺序执行：

1. **读状态**：读 `loop_state.json`，理解 mission 和 next_action
2. **读经验**：`memory_search` 查相关 lessons，避免重踩坑
3. **执行**：完成 next_action 指定的任务
4. **验证**：跑 fastcheck（`py -3.13 scripts/fastcheck.py`，注意不是 uv run）
5. **判断**：fastcheck 红项是本次引入还是 pre-existing？pre-existing 记入 escalation，不越权修
6. **沉淀**：有新经验就写 `docs/lessons.md`（Problem/Root cause/Durable lesson/Prevention 格式）
7. **更新状态**：写 `loop_state.json`（current_step/next_action/last_verified/escalation/updated_at）
8. **写日志**：追加 `ralph-log.md`（做了什么/改了哪些文件/fastcheck 结果/经验教训/下一步）
9. **commit**：`git add -A && git commit -m "..."`
10. **信号**：任务完成输出 `<promise>COMPLETE</promise>`；需要人裁决则写 `status=BLOCKED`（`loop_state.py blocked`）停止，ralph 检测到即停循环等人

## 记忆机制（读 + 写）

### 读记忆（自动）
- SessionStart hook 跑 `memory_inject.py`，把 `loop_state.json` 摘要注入 `CLAUDE.local.md`
- agent 会话启动时自动看到当前任务状态
- 需要历史经验时用 `memory_search` 查 `docs/lessons.md`

### 写记忆（强制）
- prompt.md 第 7-9 步强制要求，agent 每次迭代都执行
- **不靠 hook**，靠工作流指令
- 验证：3 次迭代全部自动更新了 loop_state + ralph-log，其中 2 次主动沉淀了 lessons（L36、L37）

## 关键约束

- **所有 Python 命令用 `uv run python`**，但 fastcheck 例外：`.venv` 无 ruff，须用 `py -3.13 scripts/fastcheck.py`（L26）
- **不越权修历史债**：fastcheck 红项如果是 pre-existing，记入 escalation，不试图全修
- **blocked-on-human 时不硬编造任务**：产出证据包让裁决一次到位（迭代 3 的做法）；同时写 `status=BLOCKED` 让 ralph 停循环等人（v3），不再空转
- **每次迭代一个新鲜 agent**：无上下文继承，所有状态从文件重建
- **commit 用 `--no-verify`**：fastcheck 红时 pre-commit 会拦，ralph loop 自己跑 fastcheck 做验证

## 常见问题

**Q: hook 不生效怎么办？**
A: 检查 `.claude/settings.json` 的 SessionStart command 是不是 `uv run python scripts/memory_inject.py`。系统 Python 3.14 无 requests，用 `python` 会静默失败。

**Q: agent 不写记忆怎么办？**
A: 检查 prompt.md 第 7-9 步是否还在。写记忆是工作流指令，不是 hook。如果 agent 跳过，加强 prompt 措辞。

**Q: fastcheck 一直红怎么办？**
A: 看 loop_state.escalation，区分"本次引入"和"pre-existing"。pre-existing 等人裁决，不要让 ralph loop 无限循环修历史债。

**Q: 怎么停止循环？**
A: Ctrl+C，或者 agent 输出 `<promise>COMPLETE</promise>`，或者写 `status=BLOCKED`（ralph 自动停循环），或者达到 MaxIterations。

**Q: 怎么加新任务？**
A: 编辑 `loop_state.json` 的 `next_action`，然后重新跑 `.\ralph.ps1`。
