# 009 — Harness 机制 DSH 原生化：`.dsh/skills` 唯一技能根 + 判断链五路分流 + hook 仅走 git

## Context

- harness 曾沿用 Claude Code 目录约定：`.claude/skills`、`.claude/rules`、`.claude/agents`、`.claude/settings.json`（hooks 声明）。
- 实测（2026-08-23 本地源码审计 + `npx dsh-movein` dry-run）：DSH 只自动加载 `AGENTS.md`/`CLAUDE.md`；技能发现根是项目 `.dsh/skills` 与 `.agents/skills`；`.claude/rules`、`.claude/agents`、`.claude/settings.json` **均不被 DSH 解释**（死配置）。
- CC 生命周期 hook 桥（`hooks-claude-code`）为 opt-in 插件：**进程级 configPath**（整进程一份，跨项目泄漏）、仅 command hook、PreToolUse **deny-only**、需 bash、改配置需重启进程。
- dsh-movein 在 Windows 上 symlink 不可用 → 回退 **copy**（产生双份），且其 manifest 记录用户级资产（grill-me/project-vibe-spec/context7 MCP）。

## Decision

1. **技能唯一事实源 = `.dsh/skills/<name>/SKILL.md`**（git 正常跟踪）。经 `npx dsh-movein` 迁移 + `git mv` 定唯一源，删除 `.claude/skills` 与空 `.claude/`。**三路径职责**：`.dsh/skills`=项目维护根（git 钉版）；`~/.agents/skills`=只读下载根（`npx skills add` 落点，`.skill-lock.json` 登记）；`~/.dsh/skills`=个人跨项目根。
2. **判断链五路分流**：`观察 → 可复用?No 丢弃 / Yes → 会复发?No lesson(docs/lessons.md) / Yes → 五路：全局规则(CLAUDE.md) · 流程(.dsh/skills/) · 架构(docs/decisions/ADR-N) · 瞬时(docs/progress.md) · 机械(test/lint/hook)`。**test/lint/hook 是唯一真强制层**，rules/lesson 均为 prompt 级。
3. **hook 层仅 git hooks**（`.githooks/pre-commit`、`pre-push`，fastcheck 门禁）；**不装** hooks-claude-code 桥、**不装** 权限类插件（本项目全权限模式，deny/ask 无需求）。
4. **finisher / researcher 以技能形式实现**（技能正文 = subagent 委派 prompt 模板），由主 agent 在任务边界按 cycle-close 协议主动 spawn subagent。DSH 无 `.claude/agents` 注册表、无描述自动匹配委派 → 不做 CC 兼容声明层。
5. 不维护 CC 兼容双份（无 `.claude/rules`、无 `.claude/agents` 文件、无 `.claude/settings.json`）。
6. **第三方包技能钉版机制**：包技能（Matt Pocock 技能包 2026-08-25，commit 702e452）原样钉入 `.dsh/skills` git 版（逐字节 diff 校验一致）；`~/.agents/skills` 仅当只读上游，`npx skills update` 后需重复制同步钉版。CC 专有 `disable-model-invocation` 标记 DSH 丢弃（L11），"仅用户触发"在 DSH 下不生效。

## Consequences

- ✅ 技能进入 DSH skill catalog（新会话生效；catalog 每会话快照）；无死配置；单一事实源（git 内可追踪）。
- ✅ hook 决策有据可查；判断链收敛为五路分流，audit 可 GC。
- ⚠️ **subagent 委派依赖主 agent 按技能触发，非运行时自动唤醒**（DSH 无此机制；"自动"仅指 goal 自动轮次与后台任务通知）。
- ⚠️ 若未来用 Claude Code 打开本仓，需另行适配（`dsh-movein --reverse` 或重写）。
- ⚠️ `~/.dsh/movein-manifest.json` 残留 2 条用户级记录（已删拷贝），doctor 会提示 2/11 缺失（无害，属工具账本陈旧）。
