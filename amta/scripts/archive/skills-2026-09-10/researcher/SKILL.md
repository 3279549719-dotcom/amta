---
name: researcher
description: 'Delegate external research to a background researcher subagent. Use when current external information is needed (models, papers, APIs, benchmarks, GitHub projects, pricing, latest on X) and the raw search/scrape dumps should stay out of the main context — the subagent returns only conclusions + citations, and the main agent keeps a clean context. Not for reading project files. Triggers: 调研, 查一下, research, latest on X, benchmark numbers, model/API comparison, 找 GitHub 项目.'
---

# Researcher（外部调研委派）

> 把「查资料」隔离到子代理上下文：主 agent 只收**结论 + 引用**，几十页搜索原文不进场。
> 与本会话 5 路调研同原理（hooks/rules/agents/知识链/DSH 审计各一个 researcher 子代理）。

## 触发

- 需要模型/论文/API/基准数字/GitHub 项目/定价等外部信息
- 需要对比多个方案（模型选型、API 选型）
- 需要"最新进展"类信息
- 用户说"调研 / 查一下 / research / 去查 X"

**不触发**：读项目自身文件（那是 read/glob 的事，不是 research）。

## 委派协议

1. 把调研问题收敛成一句可执行的问题（明确边界：要什么结论、什么范围、什么时间窗）。
2. spawn 一个 **background subagent**，description = "researcher：<主题>"，
   prompt = 下方【researcher prompt 模板】+ 调研问题。
3. 子代理返回后：按 TL;DR 行动项推进；发现冲突/低置信结论时先核实再采用。
4. 若子代理失败/超时：可降级为主 agent 直接 web_search（少而精），或缩小问题重派。

## 【researcher prompt 模板】—— 原样复制给 subagent

```
你是某 manga-OCR / LLM 项目的 researcher，在自己隔离的上下文里工作：
所有原始材料（搜索结果页、抓取文本、中间笔记）留在你自己这边，只把结论+引用交回。

过程：
1. 把问题拆成 2-4 个子问题（如 模型/API/基准/仓库），逐个搜索；优先官方文档、论文(arXiv)、
   GitHub 仓库、近期日期。
2. 每条发现记录：结论、来源 URL、日期、置信度。基准数字必须对照一手来源（论文/榜单），
   不信博客转述。
3. 范围过滤：只保留与「漫画/竖排文本的 OCR、文字检测识别、image-to-text、LLM 管线
   （模型/API/评测）」相关的内容，跳过无关 AI 新闻。
4. 可选：把中间笔记写入自己的临时文件（不要写回主会话）。

输出（只交这些）：
- TL;DR（≤5 条 bullet）：主 agent 应该行动什么
- Findings：按子问题分组，每条 = 结论 + 链接 URL
- Verdicts：每个子问题给推荐（模型/API/仓库）+ 一行理由
- Open questions / risks：缺口、冲突来源、未证实声明

纪律：每条结论必须带 URL；绝不把原文整段贴进结果；来源冲突要明说并标低置信一方；
没有可靠答案就写"no reliable source found"，不硬凑。
```

## 与本项目的配合

- 调研结论要落盘时走正常知识通道（finisher / cycle-close），researcher 只负责"查"。
- 涉及 .env 密钥的 API 调研：只报告能力/价格/限制，不把密钥写进任何文件。
