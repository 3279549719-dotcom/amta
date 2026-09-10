# 026 — 记忆系统选型：不自造轮子，改用开源高星项目

日期：2026-08-31　状态：已采纳（具体项目待定）

## 背景

ADR-025 设计了自造的四层记忆闭环（基线/推送/拉取/护栏），实现为 `scripts/memory*.py` 一族工具 + `memory_inject.py` 写 `CLAUDE.local.md`。实战中暴露四个问题：

1. **推送层不通用**：`CLAUDE.local.md` 只在 DSH 环境经 `agent-instructions` 插件自动加载；OpenClaw、Cursor 等其他 AI 工具不读该文件，等于没有推送层。
2. **AI 不知道系统存在**：没有 session hooks 自动触发记忆检索/注入，完全依赖 AI 主动想起调用 `memory_grep`；实际会话中经常被忽略。
3. **推送内容不精准**：`memory_inject.py` 只推最近 5 条 lessons + 最近状态，与当前任务（如翻译层重构）可能完全无关；缺任务相关性过滤。
4. **重复造轮子**：GitHub 上已有多个高星、活跃维护的本地持久化记忆系统，功能更全（自动会话捕获、语义检索、知识图谱、多 harness 兼容），自造实现远达不到同等成熟度。

2026-08-31 调研确认的候选项目（均开源、可本地部署、支持 MCP 协议）：

| 项目 | Stars | 核心特点 |
|---|---|---|
| **agentmemory** (rohitg00) | ~9.3K | 明确支持 OpenClaw/Cursor/Claude Code/Codex；基于 Karpathy's LLM Wiki pattern（与现有 lessons.md 思路一致）；12 hooks + 17 skills + 54 MCP tools 自动接线；零云依赖 |
| **mem0** | ~14.4K | 领域最大；三层记忆模型（World/Experiences/Mental Models）；managed cloud + self-hosted 双模式；生态最完整 |
| **Mimir** | 中 | MCP-native，Rust 单二进制；embedded SQLite + FTS5 + vector 混合检索；AES-256-GCM 静态加密；极简 |
| **memory-agent** (victorqnguyen) | 中 | one binary, zero cloud；encrypted local database；`memory-agent install <harness>` 一键接入 |
| **project-memory-mcp** | 小 | 最简，stateless，plain files on disk；与现有纯文件设计最接近 |

## 决策

记忆系统**不自造轮子**，改用开源高星项目。现有 `scripts/memory*.py` 一族工具进入维护模式（不新增功能），待选定开源项目并完成数据迁移后退役。

具体选型待定（agentmemory vs mem0 vs 其他），后续调研后另开 ADR 或在本 ADR 补充定案。

## 理由

- 自造实现的核心问题（不通用、不自动触发、内容不精准）正是开源项目的主打卖点——它们有 session hooks、多 harness 兼容、语义检索、自动上下文注入。
- agentmemory 基于 LLM Wiki pattern，与现有 `lessons.md`（条目化 Problem/Root cause/Durable lesson）和 `docs/decisions/`（ADR 条目）的数据模型一致，迁移成本低。
- 9K+ stars 的项目有社区维护、bug 修复、新功能开发，自造实现无法匹敌。
- 符合 ADR-015（dependency-bloat-governance）的精神：能用成熟开源就不自造，把精力放在项目独有的业务逻辑上。

## 行动项

1. **调研 agentmemory**：安装方式、数据存储格式、MCP tools 清单、与 OpenClaw 的集成方式、是否支持导入现有 lessons.md/ADR。
2. **评估迁移路径**：现有 `lessons.md`（33 条）+ `docs/decisions/`（26 个 ADR）+ `.remember/` 如何迁移到选定系统。
3. **定案后**：另开 ADR 记录最终选型、迁移计划、退役自造工具的时间表。

## 定案（2026-09-01，完成「具体项目待定」）

评估 agentmemory（rohitg00，头号候选）后**暂缓采用，自建字典先行**（详见 ADR-027）：

- **暂缓理由**：
  1. **Windows 原生是弱项**：官方文档明说 fast path 是 WSL2，原生安装需手动 ~10-20 分钟，且 `agentmemory connect` 在 Windows 原生**不受支持**——本机是 Windows 11 CPU-only 纯原生环境。
  2. **规模不匹配**：知识库 ~30 lessons + 25 ADR，agentmemory 的混合检索（BM25+向量+图）+ 实时 viewer 是给大型长期多 agent 工作负载的，当前是杀鸡用牛刀。
- **替代方案**（ADR-027 采纳）：注入瘦身 + `loop_state.json` 接续 + 自建 MCP 字典（`memory_search/read/recent`，纯 stdlib 复用现有 tools）。它覆盖 ADR-026 指出的四个问题：① 注入包跨 harness 可读（MCP 工具面常驻）② 字典默认可见（不再靠 AI 自觉）③ 注入内容从「采样」改为「元信息+按需查」④ 不引依赖、规模匹配。
- **复审触发**：循环规模扩大（多 work 并发 / 长跑 context 膨胀）或捕获质量成为瓶颈、或本机获得 WSL2/原生安装通畅时，重开本 ADR 评估 agentmemory。

## 备注

- ADR-025 的**四层闭环设计思路**（基线/推送/拉取/护栏）仍然有效，只是实现层从自造 `scripts/memory*.py` 换成开源项目。
- 现有 `CLAUDE.local.md` 推送机制在 DSH 环境继续有效，直到迁移完成。
- 本决策不影响 Stage 5（长时间自主工作）的目标——恰恰是为了让记忆层更可靠，支撑 Stage 5。
