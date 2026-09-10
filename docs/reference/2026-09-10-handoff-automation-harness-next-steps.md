# Handoff · AMTA 自动化 Harness 治理——从静态盘点到动态观测的接力（2026-09-10）

> 给下一个对话的接续文档。项目根 `E:\manga translator agent\amta`（Windows / PowerShell）。
> 用户 Patrick，vibe coder，比喻+少术语+保留关键英文。本文不含任何密钥。
> **前置阅读**：`docs/reference/2026-09-10-handoff-governance-sprint.md`（完整战果+陷阱+裁决）+ 本文件（增量思考+下一步方向）。

---

## 0. 本次对话的两大核心进展

### 进展一：静态台账盘点——"我到底有什么东西"第一次有了精确答案

在这之前，Patrick 对自己项目里的 harness 资产只有模糊印象（"好像有很多 skill"、"hook 可能有用"）。本次对话通过硬盘实证（grep/read/统计），产出了**九层静态台账**：

| 层级 | 盘点结果 | 关键数字 |
|------|----------|----------|
| tools（脚本） | 6 个深接口脚本（T1-T6），其余是薄旋钮 | scripts/ 30+ 文件，src/amta/ 45 模块 |
| context management | CLAUDE.md 98 行漂移（自称入口却写着已停用的 PreToolUse hook） | 已压缩到 6 行 |
| skill | 项目库 36→23，全局库 31，归档 82+13 | catalog 税 2678→1900 token/轮 |
| guardrails | 4 hook→2（memory inject + season start），fastcheck 8 步质检机 | fastcheck 首次真 ALL PASS |
| memory | 三套并存：M1 自研（主力）、M2 dsh-memory（0 条）、M3 graph-memory（2.8MB db 停在 8/31） | M2 语义召回不可用 |
| ADR/lessons | ADR 33 个（撞号修复 031→033），lessons 45 条 | 书脊已补全 |
| aegis 插件 | 偷带 22 skill+3 command+跨工具 hook，与自研治理体系重复 | 已手动摘除 |
| MCP | 开放标准，DSH 装官方 dsh-mcp-client 可直接搬 .mcp.json | context7/supabase/vercel 已授权 |
| DSH 观测 | 44 内置工具定义占 10.6k 固定税，1 轮 153 步累计输入 15.9M tok，缓存命中 99% | 助手+工具结果占 86% |

**产出物**（已入库 `44bd63a`）：
- `docs/reference/2026-09-09-governance-ledger.html`（主交付，九问+九层台账+三态配色）
- `docs/reference/2026-09-09-harness-inventory-tracing.md`（scripts T1-T6 + skill S1-S3 + 发现 F1-F5）
- `docs/reference/2026-09-09-governance-asset-ledger.md`（九层静态台账+三态标记+三套记忆）
- `docs/reference/2026-09-09-dsh-dashboard-reading-guide.md`（DSH 读图对照 A-E + 10 分钟最小动作）

### 进展二：DSH 详细观测——"AI 到底在干嘛"第一次能看见了

Patrick 开 DSH 新会话让 AI"整治 src/amta 归类脚本"，全程观测，上传 3 张截图 + observation.txt。关键发现：

**DSH 上下文构成（18% 已用）**：
- 系统提示 2.8k（2%）
- **工具定义 10.6k（7%，44 项）**——这是固定税，每轮都付
- 用户消息 29（0%）
- 注入 8.4k（6%，4 项：三文档自动注入+其他）
- 助手消息 78.9k（53%）
- 工具结果 49.1k（33%）

**DSH 轨迹（1 轮 153 步）**：
- LLM 13m11s + 工具 17m10s
- 缓存命中 99%（累计输入 15.9M tok，实际计费很少）
- TOOL/ASSISTANT 交替，AI 大量用 pwsh/read/write 等原子工具

**DSH 记忆 tab**：
- M2 dsh-memory **0 条**，未配置小模型路由
- 语义召回不可用（可选依赖未装/模型下载失败），已回退关键词检索
- "暂无记忆。对话结束后会自动提取"

**概念澄清**：DSH 的 TOOL 栏 = AI 的手（44 个原子工具 pwsh/read/write 等），Patrick 的 scripts/src = 车间里的机床。AI 现在用手去按机床，而非机床自带按钮——要让深模块变 AI 可直接调用的工具，需 embedded/chained/MCP。

---

## 1. 当前状态（可复现）

- **分支**：`main`，最新 commit `ca7b874`（handoff 文档）
- **fastcheck**：8/8 ALL PASS（pytest 436 passed / 3 skipped / 0 failed，ruff 251→0，pyright 0 errors）
- **重构**：domain 子包化已合入 main（src/amta 11 子包：backends/common/guards/inpaint/memory/orchestrator/report/stations/stores/translation/typeset）
- **7 旧账**：已清（commit `29f790e`），含 fastcheck.py 本身的 ruff.exe 大小写 bug
- **git**：main 领先 origin/main **13 commit 待推**（origin 停在 `69ba274`）
- **工作区**：4 个未跟踪文件（2 个旧 HTML + 2 个 fastcheck log，不影响代码）

---

## 2. 如果今天继续自动化 Harness 的学习，从何做起？

> 以下是给 Patrick 的思考方向，不是执行计划。每个方向都对应一个"如果搞懂了，能减少多少注意力消耗"的量化问题。

### 方向一：动态观测层——从"我有什么"到"AI 在用什么"

静态台账回答了"我有什么"，但没回答"AI 实际在用什么"。DSH 的 Trajectory tab 已经能看到工具调用树，但你还不会系统性地用它。

**思考问题**：
- 如果连续观测 5 个 DSH 会话，统计 23 个项目 skill 的真实命中率，你觉得有几个会是 0？（手动款 0 命中 = 可直接归档，自动款 0 命中 = 需要观测一周才敢判死刑）
- DSH 的 44 个原子工具里，你觉得 AI 用得最多的前 3 个是什么？如果这 3 个能打包成一个深接口，能省多少步？
- "缓存命中 99%"意味着什么？——是好事（省钱）还是坏事（AI 在重复自己，没有真正推进）？

### 方向二：Embedded vs Chained 的具体落地——把"赌注意力"变成"必然执行"

三命运判据已经认同了，但还没有一个工具真正被 embedded 或 chained。现在所有工具都是 standalone（赌 AI 注意力）。

**思考问题**：
- fastcheck 已经是 embedded 了（写在代码路径里，pre-push 必然执行）——还有哪个工具应该被 embedded？（提示：哪个工具你最常忘记跑？）
- `scripts/` 里的 6 个深接口脚本（T1-T6），如果要让 AI 必然调用，应该做成 chained（写进 CLAUDE.md 的 checklist）还是 embedded（写进 orchestrator 的代码路径）？
- "attention 有限"这个判断，人和 AI 是一样的。你自己每天会忘记做什么事？如果把那件事 embedded 到你的工作流里，会是什么形态？

### 方向三：Harness 四层的整治优先级——tools / context / skill / guardrails

四层都有问题，但不可能同时修。按马斯克五步（质疑→删除→简化→加速→自动化），应该先砍后建。

**思考问题**：
- **tools 层**：你说"工具都没有整合起来，没有打包"——如果只能先打包 1 个工具，你选哪个？（提示：选 AI 用得最频繁、但每次都要重新摸索用法的那个）
- **context 层**：CLAUDE.md 已经从 98 行压到 6 行，但"定时清理、更新文本，避免 context rot"还没做——如果 memory inject 每次只注入 3 条 lesson（而不是全量 45 条），应该选哪 3 条？按什么标准选？
- **skill 层**：项目库 23 个里，你说"玩票的滚、通用方法论无项目级就不要、to 系列滚"——但 grilling/research/finisher 这 3 个你明确要留。这 3 个真的被 AI 用过吗？还是只是"你觉得有用"？
- **guardrails 层**：2 个 hook（memory inject + season start），你说"不知道注入了什么，可能没用"——如果让 memory inject 每次打印"本次注入了 X 条 lesson、Y 条 decision"，你能判断它有没有用吗？

### 方向四：从 Workflow 到 Agent 的演进路径——"我到底在做什么"

你已经认同了"amta 翻译管线是 workflow 不是 agent"，真 agent 包裹其上，公式 Agent=Model+Harness。但 workflow 和 agent 的边界在哪里？

**思考问题**：
- 你说"理想的 agent：我说一句'我要改善 fonts 的类型'，它就全神贯注开始干活，跑通每一个环节，最后告诉我完成了"——这个理想里，哪些环节是 workflow（确定的），哪些是 agent（不确定的、需要决策的）？
- "退而求其次：让 agent 只具备代码层能力，我说一句'来为我审核当前项目情况，进行深度重构，保证 test 全绿'"——这个"退而求其次"其实已经有工具能做了（DSH 的 subagent + fastcheck），你觉得缺的是什么？是工具能力，还是你对"该让 agent 做什么决策"的清晰定义？
- Anthropic 的文章问"你究竟在做 workflow 还是 agent"——如果 amta 翻译管线 90% 是确定的 workflow，那剩下 10% 的不确定性在哪里？（提示：OCR 置信度判断、翻译质量审美、fonts 选择——这些哪些是"确定规则能解决"，哪些是"真的需要 AI 决策"？）

### 方向五：Tracing 机制——"看不见就管不了"

你说"tracing 是第一步"，但 DSH 的 Trajectory tab 你还不会看。观测是治理的前提——没有数据，所有"这个 skill 没用"的判断都是猜。

**思考问题**：
- 如果让你设计一个"harness 健康度仪表盘"，你最想看哪 3 个数字？（提示：skill 命中率、工具调用步数、fastcheck 通过率——这些 DSH 已经能提供原始数据）
- "AI 没有主动用 skill，因为没提醒到位"——这个判断是事实还是猜测？如果看 Trajectory 发现 AI 确实在决策时跳过了某个 skill，是因为它不知道有这个 skill，还是知道但觉得没用？
- 你说"deepseek harness 有很全面的观测机制"——DSH 的观测和 deepseek harness 的观测，哪个更适合你现在的阶段？（提示：你现在用 Claude Code + DSH，切换到 deepseek harness 的成本是什么？）

---

## 3. 一句话总结

> 静态台账让你知道"我有什么"，DSH 观测让你知道"AI 在用什么"——但两者之间还差一个闭环：**"我有什么" → "AI 该用什么" → "AI 实际用了什么" → "没用的砍掉/有用的 embedded"**。
>
> 这个闭环的第一步不是自动化，而是**观测一周**——用 DSH Trajectory 收集真实数据，再决定第二刀砍谁。

---

## 4. Suggested skills（下一个 agent 调用）

- **handoff**（amta 项目库）：再次交接时
- **c4-codebase-architecture**（全局/项目都有）：做 CLAUDE.md 工具面对齐盘查时
- **finisher / cycle-close**（项目库）：会话收尾沉淀时（Patrick 指名要用 finisher）
- **grilling**（项目库）：需要苏格拉底式追问厘清架构时（本次对话证明有效）

---

*文档生成时间：2026-09-10。前置阅读：`docs/reference/2026-09-10-handoff-governance-sprint.md`。*
