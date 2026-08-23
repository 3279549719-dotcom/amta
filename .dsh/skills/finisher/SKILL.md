---
name: finisher
description: 'Delegate the finish/reflection step to a background finisher subagent. Use when a task/loop reaches its boundary (/finish, 收尾, 落盘, 循环结束, goal complete/blocked moment) and the session produced knowledge that must be classified into its right home (lessons / CLAUDE.md / skill / decision / progress) with concrete file-level update proposals. The AI judgment (classification + drafting) runs in the subagent; the main agent only reviews and applies. Do NOT use mid-task. Triggers: /finish, 收尾, 落盘, 循环结束, goal complete, blocked.'
---

# Finisher（收尾知识归类委派）

> 把 /finish 里的「反思 + 知识晋升」从主 agent 手里**委派给一个隔离上下文的 finisher subagent**。
> 主 agent 只做两件事：喂会话摘要 → 审查/应用 proposals。中间的分类判断与草拟全部在子代理里完成，
> 不污染主 agent context（与 researcher 同原理）。

## 触发（满足其一，与 cycle-close 同步）

- /finish / 收尾 / 落盘 / 循环结束
- goal complete / blocked / cancelled 边界
- 用户明确要求"把本轮学到的东西归档"

**不触发**：任务中途、轮次中间（只在边界落一次）。

## 委派协议

1. 组装**会话摘要**（3-8 行）：做了什么 / 决策了什么 / 踩了什么坑 / 验证结果 / 待办。
2. spawn 一个 **background subagent**（`subagent` 工具，`run_in_background: true`），
   description = "finisher：知识归类提案"，prompt = 下方【finisher prompt 模板】+ 会话摘要。
3. 子代理返回 proposals 后，主 agent **审查 → 应用**（应用仍走 cycle-close Step 7「只更新真正变化的工件」+ Step 8 git 落盘）。
4. 若子代理失败/超时：退回主 agent 亲自按五路分类树快速归类（降级路径，不阻塞收尾）。

## 【finisher prompt 模板】—— 原样复制给 subagent

```
你是本项目的 finisher（记忆管家）。输入 = 一段会话摘要（做了什么/决策/学到什么）。
输出 = 一组【具体的文件级更新提案】，不是泛泛建议。动笔前先读目标文件，绝不重复已有内容。

对摘要里每一条知识，按下面五路分类树裁决：

1. 可复用坑/经验（Problem/Root cause/Durable lesson/Prevention/Regression）→ docs/lessons.md
   新条目 Lx，遵循文件内模板；若某条已被测试/hook 自动化，标注 [已自动化]。
2. 全局稳定规则/事实（架构、约定、命令、布局、不变量、硬约束）→ CLAUDE.md
   在对应小节加一行精简 bullet；是规则就写成规则句式（必须/禁止）。CLAUDE.md 保持精简（目标 <120 行），
   能合并进既有行就不新增。
3. 可复用流程/程序（怎么做某事，多步）→ .dsh/skills/<name>/SKILL.md
   带触发 description（"Use when…"）与编号步骤。不要埋在 CLAUDE.md。
4. 架构/方向决策（为什么这样选，有真实备选与后果）→ docs/decisions/ADR-N（NNN-标题.md，
   Context/Decision/Consequences）；已有相似 ADR 则提议修订而不是新建。
5. 可机械校验的不变量 → tests / lint / git-hook（提案写"加一条测试/检查，校验 X"）。
   这是唯一真强制层；规则/lesson 都是 prompt 级。

另外：瞬时状态（已完成/下一步/阻塞）→ docs/progress.md；一次性细节 → 丢弃，不提案。

输出格式：每条 `[目标文件] → [精确位置] → [草拟文本] → [理由]`，按影响排序。
纪律：不直接改文件（只产提案，由主 agent 审查应用）；不提案没读过的文件；与现有内容重复则写
"already covered" 跳过；结尾 5 行总结提了什么、为什么。
```

## 与 cycle-close 的关系

cycle-close Step 5（反思）与 Step 6（知识晋升）＝本技能的执行点：Step 5 调本技能委派，
Step 6 拿回 proposals 走五路分流应用。本技能是 cycle-close 的「反思委派」实现，不替代整个收尾协议。

## 常见坑

- **子代理直接改文件**：模板里已禁止（只产提案），主 agent 必须保持"编辑审查权"。
- **proposals 里夹带瞬时状态**：progress 是状态通道不是知识通道，别把"下一步"写进 CLAUDE.md。
- **重复提案**：子代理必须读文件去重；主 agent 应用时再扫一遍。
