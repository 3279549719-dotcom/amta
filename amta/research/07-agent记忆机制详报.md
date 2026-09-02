# 07 — Agent 记忆机制详报：注入、检索与测试护栏

> 任务来源：2026-08-29 Patrick 发起（amta 接手 agent"不读取文档"问题，/grill-me + /research）。
> 结论状态：注入侧与运行时侧为**一手源码/官方文档核实**；工具面 schema 参照三个开源范例；测试阈值为提案，待 Round 3 定案。
> 调研方法：本地源码核查（amta、claude-remember 插件缓存、deepseek-harness 仓库）+ 官方文档抓取（code.claude.com hooks 参考）+ GitHub README 一手抓取。三个外部调研子代理超时/失败，主 agent 降级自查完成。

---

## 1. 问题定义

接手 amta 的 agent 不会主动读取 CLAUDE.md 渐进式加载表指向的文档；CLAUDE.md 本身"看两眼就忘"于长会话。文档地产（27+ lessons、23 ADR、plans、research）实质是坟场：写入端自动化程度高，读取端零机械化。

## 2. 本地事实链（一手核实）

### 2.1 `.remember` = claude-remember 官方插件（Claude Code 侧）

- 写入器：`claude-plugins-official` 市场的 **remember 插件 v0.15.0**（上游 Digital-Process-Tools/claude-remember），hook 驱动：SessionStart / UserPromptSubmit / PostToolUse + Haiku 整合（consolidation，每条约 $0.03）。
- 证据：`.remember/logs/memory-2026-08-27.log`（`[hook] session-start: ... PIPELINE_DIR=E:/claude/.claude/plugins/cache/claude-plugins-official/remember/0.15.0`）。
- 活动窗口：8-25 ~ 8-27 有真实写入，之后停。
- **注入范围缺口（关键）**：其 session-start-hook.sh 注入 identity / core memories / today / now / recent / archive —— 全部是 `.remember` 自有文件。**docs/lessons.md、ADR、progress、research 从未被注入**。

### 2.2 DSH 运行时能力（deepseek-harness 源码核查）

- `packages/hooks/hook-protocol`：hook 协议原生支持 **SessionStart + `additionalContext` 注入**，源码注释明确对齐 Claude Code / Codex 语义（"CC `additionalContext`"、"Codex SessionStart/UserPromptSubmit"）。
- `hooks-claude-code` / `hooks-codex` 两个桥接插件：**直接复用现有 hooks.json**，把外部 shell hook 翻译到 harness 的拦截点。
- 结论：同一份 SessionStart 注入脚本 → Claude Code 原生跑、DSH 经桥跑、Codex 经桥跑。**跨运行时注入在机制上成立。**

### 2.3 CLAUDE.md 自身的记忆腐坏（活标本）

- 渐进式加载表 4 行指向 `research/`（README、01/02/03 详报），但 hygiene 提交 `0ab552e` 删除 docs/ 重复调研报告并声称"已归位 research/"——**而 research/ 目录在当前分支不存在**。索引指向幽灵路径。
- 加载表是**任务名枚举**（"跑 Benchmark 时读 X"），不是**问题域启发式**（"遇到报错先搜 Y"）。踩坑场景对不上触发词 → 永远检索不到。

## 3. 外部一手调研

### 3.1 Claude Code hooks 官方参考（https://code.claude.com/docs/en/hooks）

- SessionStart matcher 的 source 值：**startup / resume / clear / compact / fork**。
- **`compact` 在自动/手动压缩后触发** → 支持在上下文被压缩的瞬间重注入记忆包。这是治"长会话遗忘"的官方正解：压缩 = 上下文丢失点 = 重注入点。
- 输出协议：SessionStart 的 plain stdout 直接入上下文；或 JSON `hookSpecificOutput.additionalContext`（包在 system reminder 里，对用户不可见）。
- **输出上限 10,000 字符**：超限被落盘替换为预览+路径。注入预算设计必须 < 10K chars。
- 官方要求 "keep these hooks fast"（每个会话都跑）；另有 `initialUserMessage`（headless 首轮）、`reloadSkills` 等事件专属字段。

### 3.2 claude-remember（本项目在用，https://github.com/Digital-Process-Tools/claude-remember）

- 3 个 hook 点（SessionStart/UserPromptSubmit/PostToolUse）+ Haiku 整合 + git 备份；自带 tests/ + CI（Linux/macOS/Windows 矩阵徽章）——**hook 型记忆插件可测试的开源先例**。
- 短板（本项目实测）：只覆盖会话续接记忆，不覆盖工程知识地产；注入一次性、无按需打捞。

### 3.3 claude-mem（https://github.com/thedotmack/claude-mem）

- 5 个生命周期 hook（SessionStart/UserPromptSubmit/PostToolUse/Stop/SessionEnd）+ SQLite FTS5 + Chroma 向量混合检索。
- **4 个 MCP 工具、三层省 token 工作流**：`search`（紧凑索引带 ID，~50-100 token/条）→ `timeline`（围绕某条观察的时间线上下文）→ 读取全文。**"先索引后展开"的渐进检索范式，验证"职责单一、不搞一个大而全工具"的方向。**

### 3.4 MCP 官方 memory server（https://github.com/modelcontextprotocol/servers/tree/main/src/memory）

- 本地知识图谱存储，工具面按读写职责切分：
  - 读：`read_graph`（全图）/ `search_nodes`（按关键词搜节点）/ `open_nodes`（按名取特定节点）
  - 写：`create_entities` / `create_relations` / `add_observations` / `delete_*` 三族
- 单工具单职责、参数 schema 明确、返回值即查询结果——工具面设计的官方参照系。

### 3.5 AGENTS.md 标准（https://agents.md/）

- 开放标准，60k+ 开源项目采用；30+ agent 读取（OpenAI Codex、Claude Code（经 import）、GitHub Copilot、Cursor、Gemini CLI、Google Jules、Amp 等）。
- 基线层结论：**约定文件自动加载是唯一全运行时覆盖的层**；amta 的 AGENTS.md（5 行指针防漂移设计）已符合。

## 4. Verdicts（设计分层定案建议）

| 层 | 机制 | 覆盖运行时 | 强制等级 |
|---|---|---|---|
| 基线 | AGENTS.md/CLAUDE.md 自动加载 + 问题域启发式表 | 全部 | prompt 级（软） |
| 注入 | SessionStart hook（matcher: startup **+ compact**），输出 .remember + 知识层摘要，≤10K chars（设计目标 ≤1.5KB） | CC 原生、DSH/Codex 经桥 | **hook 级（机械）** |
| 打捞 | 单职责检索脚本（lessons/ADR/handoff 各一），返回带路径+行号 | 任何能 exec 的 agent | 工具级（半机械） |
| 护栏 | pytest 测 hook 脚本（stdin JSON→stdout 纯函数）+ staleness linter 并入 fastcheck + 冷启动探针挂 audit | CI/本地 | **test/lint 级（机械）** |

核心洞察：**压缩（compact）是长会话记忆丢失的机制性时刻，官方 matcher 恰好提供该时点的重注入钩子**；读取端机械化的最小闭环 = "startup 注入 + compact 重注入 + 工具打捞 + linter 防腐"。

## 5. 补充调研（2026-08-29 深抓，第一调研员迟到交付，与主调研互为印证）

以下为官方文档逐页抓取的增量事实（与第 3 节结论不冲突，均为加固或细化）：

### 5.1 Claude Code 细节加固
- **stdout 注入面收窄**：exit-0 纯文本 stdout 直入上下文的事件只有四个（SessionStart / UserPromptSubmit / UserPromptExpansion / PostModelSwitch）——本方案选 SessionStart 是四者中唯一在会话开头 + compact 后双时点触发的。
- **matcher 全覆盖建议**：SessionStart 不配 matcher = startup/resume/clear/compact/fork 全跑，脚本按 stdin JSON 的 `source` 分支全量/瘦包（本方案采用；官方 hooks-guide 给的 compact 重注入示例即 `"matcher": "compact"`）。
- **SessionStart 无阻断能力**：exit 2 对 SessionStart 不阻塞（仅 stderr 展示），纯注入语义——hook 恒 exit 0 的纪律是双保险而非必需。
- **版本门控**：resume 专属字段需 CC ≥ v2.1.251；v2.1.214 前 fork 报 `resume`。落地前确认实际 CC 版本（本方案不依赖 resume 专属字段，风险低）。
- **CLAUDE.md 规模上限**：官方建议单文件 <200 行、Auto memory 每会话只载前 200 行/25KB——本方案 <120 行红线合规且有余量。

### 5.2 跨运行时确定性分级（写入设计纪律）
| 机制 | 确定性 | 结论 |
|---|---|---|
| CC SessionStart stdout / `additionalContext` | 确定 | 关键记忆唯一承载通道 |
| Cursor `alwaysApply: true` / Windsurf `trigger: always_on` / Cline 无 frontmatter 规则 / OpenHands `triggers`+`paths` | 确定 | 可承载关键记忆（本方案未用） |
| Cursor `description` / Windsurf `model_decision` / Cline Memory Bank / 各家 memories | LLM 自主 | **绝不承载关键记忆**；Cline Memory Bank 是提示词方法论不是注入机制 |

### 5.3 AGENTS.md 桥接细化（未来扩展用）
- Claude Code **不原生读 AGENTS.md**（agents.md 站点原生列表无 CC）；官方推荐 `CLAUDE.md` 内一行 `@AGENTS.md` import 桥（≤4 跳展开）。amta 现为反桥（AGENTS.md 5 行指针 → CLAUDE.md），对 CC+DSH 已够；若未来接 Cursor/OpenHands 等，把正文迁入 AGENTS.md + CLAUDE.md `@AGENTS.md` 反转即可，工具层脚本不受影响。
- Aider 属配置式接入（`.aider.conf.yml` 的 `read: AGENTS.md`），非原生；无 hook 机制，注入层不可用，只能靠基线+工具层。
- Windsurf 文档已并入 docs.devin.ai，旧 Cascade memories 不适用于新 Devin agent——引用其文档注意时效。

### 5.4 对四层设计的最终印证
- L2（注入）确认为**唯一确定性强保证**，且 CC 是唯一有 session-start 注入机制的运行时——把 hook 脚本写成与运行时无关的纯 stdin/stdout 程序（本方案 Task 5）是正确的可移植投资。
- L3 一手佐证：claude-mem 的 search→timeline→read 与 MCP memory server 的读写拆分同属“确定性检索工具”范式；description 类自主召回只配做补充。

## 6. 待定问题（Round 3 拷问项）

1. 注入包最终内容与预算（Q7：推荐 .remember + lessons 最近 5 条标题行 + handoff 一行，≤1.5KB）
2. 打捞工具面切分与返回 schema（Q8/Q10：脚本优先 vs MCP 壳；按知识类型切 3-4 个工具）
3. 测试阈值数字（Q11：staleness 天数、注入预算字节数、探针题目）
4. CLAUDE.md 启发式表重写与幽灵路径清理（Q9，顺手修复 research/ 失联）
