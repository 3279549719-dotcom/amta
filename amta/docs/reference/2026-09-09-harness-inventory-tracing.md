# 2026-09-09 Harness 实证盘点 + tracing 第一步（治理会话）

> 承接 2026-09-08 两份文档（tool-governance-tutor-session / p33-fullchain-experiment）。
> 本次方法：**不凭印象，逐个读真实文件**。盘点 scripts/ 39 个脚本、.dsh/skills 36 个、
> 全局 ~/.agents/skills 31 个、两个 hook、记忆注入链。结论用于回答三问：
> ① memory inject 到底注入了什么、有没有用；② 哪些工具/skill 该 embedded/chained/丢；
> ③ tracing 第一步做什么。

## 0. 一句话结论

不是原地踏步。实证后：**真·embedded 资产比以为的多；同时有两个"写好却没接线"的断线零件，
其中一个正是自己想要的"自动 push 记忆"。** 缺的不是更多整治，是先给 harness 装仪表盘（tracing），
让后续每一次删除/保留都有命中数据支撑，不再拍脑袋。

---

## 1. 五个被证据钉死的发现

### F1. 记忆注入：强的那层没通电，弱的那层只给指针
- SessionStart hook（`hook_sessionstart.py` → `memory.py inject`）**已通电**，每次会话跑。
- 但注入包预算仅 1536 字符，ADR-027 **刻意**只放「loop_state 接续状态 + 一句字典指针」，
  不注入任何 lessons/ADR 内容（`estate.py: build_pack` 契约原文）。
- 实际产物 `CLAUDE.local.md` 只有 9 行，且 loop_state 停在 **2026-09-07T21:40（stale）**。
- **断线零件**：`scripts/memory_autoinject.py` 是 UserPromptSubmit hook——每次提问按关键词
  自动检索 lessons/ADR 并 push 进上下文，文档自称「记忆字典唯一的真强制层」，正是 L34
  「记忆检索要 hook push，别只靠 MCP pull」的实现。**但 `.claude/settings.json` 只挂了
  SessionStart，没挂 UserPromptSubmit → 它从没运行过。**
- 结论：不是注入思路没用，是「强注入层没接线 + 弱注入层只说『去查』却不给目录」。
- 改进（二选一或都做）：
  (a) 给 memory_autoinject 接线 UserPromptSubmit，立刻实测一次命中；
  (b) startup 包加「知识索引块」= L1–L45 标题一行 + ADR-N 标题一行（约 2KB；
      解析正则 `LESSONS_LINE/ADR_INDEX_LINE` 在 estate.py 已现成），让 agent 知道
      「有哪些坑」，全文仍按需 read。预算从 1536 提到 4096（memory.py 默认已是 4096，
      但 build_pack 默认 FULL_BUDGET=1536，存在不一致）。

### F2. gen_report 不是纯 embedded，是 flag-gated（"全手动"的代码级证据）
- `00_run_all.py:78 _maybe_gen_report`，第 85 行 `if not with_report: return`，
  默认 **关**，必须手动加 `--with-report` 才跑。
- p33「零人工提醒」成立的前提是命令里手写了 --with-report。
- 真 embedded 应反过来：**默认 on，用 `--no-report` 才能关**。inpaint 同理（--with-inpaint）。
- 判据：一个 stage 是不是产出的默认组成部分？是 → opt-out；实验性 → opt-in。

### F3. hook 4→2 是熵减不是萎缩，且 depguard 已 embedded
- 留下的两个都是真强制：SessionStart（会话现场）、pre-push（fastcheck 门，坏代码上不了 main）。
- 砍掉的：pre-commit（与 pre-push 逐字节重复）、PreToolUse（merge-base 子串误杀 + 2.1.220
  schema 被拒，见 L45）——砍得有据。
- `fastcheck.py` 5 步 = compile + ruff + pyright + pytest + **depguard**（第 108 行），
  依赖守卫已在门里。→ 考题 4「depguard 为何没拦 onnxruntime」方向收窄：不是没接，
  是它没扫到「在用却未声明」的那一形态（延迟 import / 间接依赖），属方向性能力缺口，另查。
- `hook_pretooluse.py` 已停用却仍以 .py 躺在 scripts/，造成「看起来有」的错觉 → 改名 .disabled。

### F4. skill：项目 36 + 全局 31，大量整包冗余与双份重复
- 全局归档 82 个已核实（skills-archive-2026-09-08，113−82=31，数字对得上）。
- 但项目 `.dsh/skills` 还有 36 个没经历同尺度减脂，且与全局根**双份重复** 14 个
  （ask-matt/c4/code-review/codebase-design/diagnosing-bugs/grill-me/handoff/implement/
  improve-codebase-architecture/setup-matt-pocock-skills/teach/to-questionnaire/wizard/
  writing-for-agents）。
- 全局根还混着别的项目残留（supabase-postgres-best-practices、firecrawl-cli）。
- 近重复簇：grilling≈grill-me≈grill-with-docs（三个拷问）；research≈researcher；
  c4≈codebase-design≈domain-modeling≈improve-codebase-architecture（四个架构思考）。
- 一整套 issue-tracker 工作流（to-spec/to-tickets/to-questionnaire/wayfinder/triage/
  setup-matt-pocock-skills）依赖外部 tracker，单人本地项目无 tracker，基本空转。

### F5. tracing 的砖早就烧好，只差常驻接线
- `scripts/trace_probe.py stats` 已能读会话 JSONL，输出工具调用数 / Top 工具 /
  最大停顿 / **重复调用**。
- 现场演示（历史会话 9a8fe381）：107 次调用 Bash=64/Read=10/Write=8；**最大停顿 746 秒**；
  同一个 SKILL.md 被 Read **3 次**（注意力浪费的铁证）。
- 缺：① 会话结束不自动跑；② 没有「skill 命中次数 / memory 调用次数」两个维度，
  回答不了「AI 到底用没用 skill / 查没查记忆」。

---

## 2. scripts/ 39 个脚本 → 六堆（三命运盘点）

| 堆 | 命运 | 脚本 | 处置 |
|---|---|---|---|
| T1 已通电 embedded | 资产，别动 | fastcheck（含depguard）、hook_sessionstart、00_run_all | 保持 |
| T2 断线零件（**最高 ROI**） | 差一步通电 | **memory_autoinject**（挂 UserPromptSubmit）；gen_report/inpaint 在 00 里**改默认 on**；hook_pretooluse 改 .disabled | 今天处理 |
| T3 生产管线本体 | workflow，默认 on 候选 | 01_detect/02_ocr/03_translate/04_inpaint/05_typeset、run_pipeline、detect_rtdetr、detectors、baberu_ocr | 随 F2 一起理默认值 |
| T4 chained 按需工具 | 进路由槽位 | memory、mcp_memory、loop_state、ralph_sdk/ralph_context、audit、benchmark、review、verify_stage4、pre_scan、context7、smoke_test、**trace_probe（升级常驻）** | 保留，靠路由表触发 |
| T5 历史薄壳 | 查消费者后归档 | gen_final/gen_ab/gen_stage4/gen_inpaint_ab_report（自承"优先 gen_report"，被 run.ps1/pyproject 引用，先改引用）；run_stage4_e2e_11_20（带页码=一次性，按 L44 进 probes/） | P2 |
| T6 数据处理杂项 | 逐个确认 | apply_revisions、merge_labels、merge_suggestions | P2 定去留 |

---

## 3. skill 处置建议（项目 .dsh/skills 36 个）

### S1 项目命脉（10 个，保留 = 真 chained 资产）
koharu-drive、benchmark、oracle-label、dependency-guard、verify、cycle-close、
finisher、researcher、audit、background-monitoring。
（均为 amta 自己长出、绑定真实业务，且多数已在 CLAUDE.md 渐进式加载表挂了槽位。）

### S2 近重复簇（每簇最多留 1）
- grilling / grill-me / grill-with-docs → 留 0~1（苏格拉底式追问现在由对话承担，可全归档）
- research / researcher → 留 researcher（subagent 护上下文）
- c4-codebase-architecture / codebase-design / domain-modeling / improve-codebase-architecture
  → 最多留 codebase-design

### S3 候选归档（等 tracing 命中数据再最终拍板，不直接删）
to-spec、to-tickets、to-questionnaire、wayfinder、triage、**setup-matt-pocock-skills
（一次性安装器，装完即应删）**、implement、prototype、wizard、wait-what、teach、handoff、
resolving-merge-conflicts、code-review、writing-for-agents、diagnosing-bugs、tdd、ask-matt。
判据：trace 统计 30 天内被 Read 次数 = 0 的，归档；>0 的留。删除决策全部等数据。

### 全局根 ~/.agents/skills（31）
只应放「跨项目复用」。与项目重复的 14 个去重（单一事实源在项目 .dsh，ADR-009）；
supabase-postgres-best-practices、firecrawl-cli 等他项目残留移走或归档。

---

## 4. tracing 第一步（<1 小时，P1）

目标：让"AI 用没用 skill / 查没查记忆 / 哪里在空转"从感觉变成数字。

1. **会话结束自动留痕**：挂 Stop hook（或并进 cycle-close）自动跑
   `trace_probe.py stats <当前会话jsonl>`，追加到 `.remember/logs/trace-YYYY-MM-DD.log`。
2. **给 stats 加两个计数维度**：
   - Read 调用中路径含 `skills/` 的次数，按 skill 名聚合 → 回答"哪个 skill 真被用过"；
   - Bash 调用中命令含 `memory.py` / MCP memory_* 的次数 → 回答"记忆层有没有被查"。
3. **累积成周表**：skill/工具 × 30 天命中次数。0 命中 = S3 归档的实证依据；
   同一文件重复 Read ≥3 / 单段停顿 >5min = harness 摩擦点清单。
4. 跑满一周再做 skill 二次瘦身与 CLAUDE.md 6→3，所有删减引用命中数据。

闭环：**tracing 跑一周 → 真实命中表 → 该 embedded 的补通电、该 chained 的修槽位、
0 命中的归档**，整治第一次有了归因依据。

---

## 5. 行动优先级（沿用 A/B/C 与"一次只改一个变量"）

- **P0（今天，合计 <1h，高杠杆，互不共用变量）**
  - [ ] memory_autoinject 接线 UserPromptSubmit，造一个含已知坑关键词的 prompt 实测 push
  - [ ] 00_run_all 的 report/inpaint 默认值改 opt-out（先只改 report，单独可回滚）
  - [ ] hook_pretooluse.py → .disabled，消除假资产
- **P1（本周）**：第 4 节 tracing 常驻 + 两个命中维度
- **P2（拿 P1 数据后）**：skill 二次瘦身（S2/S3）、scripts T5/T6 归档、CLAUDE.md 6→3、
  onnxruntime 声明 + depguard 方向性缺口（考题 4）
- 纪律：P2 每个删除都要能引用 trace 命中数；P0 三项各自独立 commit，便于归因/回滚。

## 6. 与既有待裁决清单的衔接
- 本文 P0-F2 对应实验文档「合 main 前确认自动化默认值」；
- F1 是比考题 1–4 更靠前的 harness 地基问题（记忆层不 push，后续 agent 化都踩同一坑）；
- 原 6 项待裁决不变，本文新增第 7 项：tracing 常驻化，且建议排在 CLAUDE.md 手术之前。
