# 长期记忆机制景观调研（2026-09-01）

> 调研存档。触发：grill-me 中用户担心"自造轮子"，先横向扫一遍高星记忆机制再定案。
> 结论已入 ADR-026（选型定案）+ ADR-027（自建字典）。本文是证据，不是决策。

## 高星方案一句话对照

| 方案 | Stars | 本质 | 依赖 | 对本项目 |
|---|---|---|---|---|
| **agentmemory** (rohitg00) | ~9.3K | 记忆引擎 + MCP server；基于 Karpathy LLM Wiki pattern；12 hooks 自动捕获 + 17 skills + ~54 MCP tools；置信度加权规则（/lesson） | SQLite + iii-engine（pin 版本），本地 embedding 可 $0 | ✅ 最对齐，但 Windows 原生弱、规模过重 → **暂缓**（ADR-026 定案） |
| **Basic Memory** (basicmachines-co) | 高星 | 本地 Markdown 为真相 + SQLite 索引 + 知识图谱 + MCP server；**专门给 Claude Code**（SessionStart 简报 / PreCompact 检查点 / typed notes）；渐进式披露检索 | pip install，本地 | ✅ **同款设计背书**：文件为真相 + MCP 检索就是我们要的路 |
| **mem0** | ~14.4K | LLM 抽原子事实 → 向量库；add/search API | 向量库 + embedding | ❌ 违反零依赖铁律 |
| **Letta (MemGPT)** | — | **完整 agent 运行时**：core(常驻)/archival(向量)/recall(历史)；agent 自编辑记忆 | Postgres + 服务器，1.5-3× token | ❌ 为多 agent 生产系统设计 |
| **Zep** | — | 企业级时序知识图谱（bi-temporal 有效性窗口） | 托管/Graphiti，重 | ❌ 太重 |
| **Mimir** | 中 | MCP-native，Rust 单二进制，SQLite+FTS5+vector | 单二进制 | ⚠️ 可关注，但非必要 |
| **Cline Memory Bank** | — | 纯文件 MD 记忆库（projectbrief/productContext/activeContext/progress） | 无 | ⚠️ 已调研（research/mb-research/），与 lessons/ADR 思路同源但为"每会话从零"设计，不采纳 |

## 值得抄的模式（已进 ADR-027 实现）

1. **渐进式披露**（Basic Memory）：search 只回 ID/标题（~50 token）→ 预览 → fetch 才取全文。= 我们的 memory_search（命中行）→ memory_read（全文），MCP 工具照此分层。
2. **SessionStart 简报**（Basic Memory）：每会话把「活跃任务 + 最近工作」端上来。= 我们的注入包（loop_state 摘要）。
3. **typed notes**（`[bugfix]`/`[method]`/`[decision]`）：= 我们的 L## lessons + ADR。
4. **/lesson 纠错变规则**（agentmemory）：= 我们的 错误→记忆 writeback 目标（memory_delta + 确定性落盘）。
5. **多词查询语义**：条目级 AND（每词在条目内任意行出现即中），自建字典按此做。

## 不抄的（及原因）

- **向量/语义检索**：规模 ~30 lessons + 25 ADR，关键词 + FTS 足够；加了向量就是引入 embedding 模型依赖（违反零依赖）。
- **知识图谱/时序有效性**：无多实体时序需求。
- **agent 运行时（Letta 式）**：记忆管理是 agent 自编辑行为 → 我们反而要确定性 harness 落盘（不烧 API）。
- **实时 viewer / 长跑仪表盘**：个人项目，`memory_status` / `memory_lint` 够用。

## 参考文献

- agentmemory: github.com/rohitg00/agentmemory
- Basic Memory: basic-memory 官方文档 + plugins/claude-code/README
- Letta/Mem0/Zep 对比: agentmarketcap.ai/blog/2026/04/08/agent-long-term-memory-architecture
- Cline Memory Bank: research/mb-research/ 全套模板
