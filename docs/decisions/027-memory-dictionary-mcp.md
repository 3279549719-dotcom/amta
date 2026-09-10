# 027 — 记忆层 v2：注入瘦身 + loop_state 接续 + MCP 字典

日期：2026-09-01　状态：已采纳

## 决策

1. **注入契约重定义**：`CLAUDE.local.md`（每会话自动加载的记忆包）只装两样——① `loop_state.json` 摘要（接续点）② 字典规则一行（知识在哪 + 遇错/决策前用 memory_search）。砍掉近期 lessons 采样与 `.remember` now/recent 会话摘要（双写重复、内容不精准；知识一律走字典按需查）。
2. **外化状态**：`loop_state.json`（repo 根，机器可读 JSON），由循环/会话每步自动更新（`src/amta/memory/loop_state.py`，原子替换）。字段：mission / current_step / next_action / last_verified / escalation / updated_at。为「自主循环」打底——独立进程 harness 读同一文件（B 可复用）。
3. **检索 = MCP 字典工具**：`scripts/mcp_memory.py`（stdio MCP server，纯 stdlib，复用 `amta.memory.tools`），暴露三只读工具：`memory_search` / `memory_read` / `memory_recent`。渐进式披露（命中行 → 全文）；多词查询 = 条目级 AND；预算 `MAX_MEMORY_CALLS=6`（search/read 计数，每会话一个 MCP 子进程）。注册于 `.mcp.json`。
4. **错误→记忆 writeback**：循环迭代输出带 `memory_delta` 字段，确定性 harness 解析落盘（原始观察 → `.remember/`，晋升 curated docs 走里程碑把关）→ git commit。**零额外 API 调用**——写记忆是迭代的免费尾随步骤，不做成 LLM 工具（避免工具蔓延烧调用）。
5. **循环节奏**：会话续接式起步，每轮 **读 git commit 开始、git commit 结束**（上下文从磁盘重建，崩溃安全）。组件按独立进程可复用设计（渐进式放权，对齐 MISSION.md Stage 1→3）。
6. **选型定案（完成 ADR-026 待定项）**：评估 agentmemory（rohitg00）后**暂缓**——Windows 原生安装弱（fast path 是 WSL2，原生 `connect` 不受支持）+ 当前规模（~30 lessons + 25 ADR）用混合检索/图/向量是杀鸡用牛刀。自建字典先行；规模扩大或捕获质量成瓶颈时再评估。

## 理由

- **病根**（grill 共同理解，2026-09-01）：推送层只解决「看见知识存在」，关键时刻调不调靠 AI 自觉（「你会想起来有查询工具吗，不会吧」= 决策场景漏查的死穴）；注入内容采样既不完整（33 条取 5）又不精准（大概率与当前任务无关）；会话摘要双写重复每次白烧 ~3KB。
- **第一性原理**：知识的「内容」不进上下文，只进 `docs/` 等被查；「字典」= 一个 `memory_search` 工具；注入包只装元信息（接续点 + 规则）。注入任何内容采样都是多余的。
- **MCP 字典 vs hook 预检索**：工具常驻工具面 = 看见即用（Basic Memory 同款背书），零噪音、零成本；hook 每轮预检索贵且噪音。**MCP vs CLI**：CLI 靠记得跑（死穴），MCP 是默认可见。
- **字典先行**：先证明「1 次调用 1 个精准答案」可用（p14 真活验证通过），再谈循环——不先写全套设计、不铺基础设施。
- **writeback 不做成工具**（用户 60 次/页教训）：工具蔓延 = API 调用爆炸；写记忆是确定性 harness 的事，零额外调用。

## 备注

- 注入包实测从 ~2600 字符瘦到 ~600（loop_state 摘要 + 字典规则）。
- `memory_lint` budget 规则语义变化：注入包恒小，地产体量不再由包衡量；budget 检查保留为防御。
- remember 插件维持**纯写者**角色（`.remember/` 档案），其 SessionStart 直注与包去重后，会话摘要不再进包（`memory_recent` 可查）。
- 下一步里程碑：检测调优试点闭环（改配置 → eval → loop_state → commit），复用本 ADR 的 loop_state + 字典 + writeback。
- 相关：ADR-025（四层闭环思路仍有效，实现层按本 ADR 演进）、ADR-026（选型定案见其「定案」节）。
