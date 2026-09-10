# 2026-09-09 治理资产静态台账（硬盘家底，单一事实源）

> 目的：回答"我到底有什么"。**全部来自硬盘实读，不凭印象。**
> 状态标记三态：
> - `[挂载]` 静态可证已接上（配置/代码里有挂点）；
> - `[断线]` 零件在但没接上（静态可判）；
> - `[待观测]` 接上了，但"运行时 AI 真用没用"静态判不了，必须 DSH 仪表盘/trace 验证。
>
> 边界：本台账只回答"有什么 / 设计上接没接"。"用没用、用几次"是动态问题，
> 见 dsh-dashboard-reading-guide，不在此表下结论。

## 总览：治理层共 9 层

| 层 | 是什么（比喻） | 规模 | 静态结论 |
|---|---|---|---|
| 1 协议手册 | 员工手册 | 4 份 | CLAUDE.md 偏胖(85行)，4 份职责有重叠待梳 |
| 2 命令入口 | 快捷键 | npm 20 + ps1 2 | 基本健康 |
| 3 脚本 | 专用工具 | 39 | 六堆 T1–T6（详见 inventory 文档） |
| 4 skill | 工具架 | 36+31+1，归档 82 | 重复/冗余多，待观测后砍 |
| 5 强制层 hook | 打卡机/门禁 | 2 活 + 2 停 | git 门可靠；CC 专有 hook 迁 DSH 待做 |
| 6 MCP | 外线电话 | 2 | amta-memory + context7 |
| 7 DSH 增强插件 | 第三方改装件 | 14 | **含三套记忆重叠，需重点厘清** |
| 8 知识资产 | 经验档案库 | 45 lessons + 33 ADR + 55 测试 | 厚实，是真资产 |
| 9 记忆机制 | 备忘录系统 | **3 套并存** | **重叠，最该先收敛** |

---

## 层 1 · 协议手册（AI 每次会话读的"员工手册"）

| 文件 | 体量 | 职责 | 状态 |
|---|---|---|---|
| CLAUDE.md | 14.3KB / 85 行 | 主手册：核心事实+坑速查+渐进式加载表+工作协议 | `[挂载]` agent-instructions 自动注入；偏胖，6→3 手术待做 |
| AGENTS.md | 5.1KB / 98 行 | Python 运行规范 + Ralph Loop 4 条强制 | `[挂载]`；与 CLAUDE.md "Python 运行规范"段重复 |
| prompt.md | 10.1KB / 148 行 | Ralph 使命会话 11 步强制工作流 | `[待观测]` 仅 ralph 使命会话用，交互会话不读 |
| CLAUDE.local.md | 0.8KB / 9 行 | 自动生成的记忆注入包 | `[挂载]` 每次 SessionStart 重生成；内容仅指针+stale 状态（见层 9） |

重叠点：CLAUDE.md 与 AGENTS.md 都写了 Python 运行规范；"何时用何工具"在 CLAUDE.md 表格与
各 skill 内文也重复。收敛方向：一份权威、其余只留指针。

## 层 2 · 命令入口

- **npm scripts（package.json，20 个）**：
  质量门 = fastcheck / finish(check+test) / check / test / lint / typecheck / depcheck；
  流程 = hooks:install / audit / smoke / precheck / start；
  bench = bench / bench:a/b/c / ingest:a / prescreen；调研 = ctx7:search / ctx7:ctx。
- **ps1**：run.ps1（常用短命令）、ralph.ps1（使命循环驱动）。
- 静态结论：入口清晰，fastcheck 是汇聚点（compile+ruff+pyright+pytest+depguard）。

## 层 3 · 脚本 scripts/（39 个，六堆）

> 逐文件清单与处置见 `2026-09-09-harness-inventory-tracing.md` 第 2 节，摘要：
- T1 已通电 embedded：fastcheck、hook_sessionstart、00_run_all
- T2 **断线零件（最高 ROI）**：memory_autoinject（没挂 UserPromptSubmit）、
  gen_report/inpaint 在 00 里 flag-gated 默认关、hook_pretooluse 该改 .disabled
- T3 生产工位 01–05、run_pipeline、detect/ocr 引擎
- T4 chained 按需：memory、mcp_memory、audit、benchmark、review、context7、trace_probe 等
- T5 历史薄壳：gen_{final,ab,stage4,inpaint_ab}_report、run_stage4_e2e_11_20 → 查消费者后归档
- T6 数据杂项：apply_revisions、merge_labels、merge_suggestions

## 层 4 · skill（三个根 + 一个归档）

| 根 | 数量 | 角色 | 静态结论 |
|---|---|---|---|
| 项目 `.dsh/skills` | 36 | 项目维护唯一事实源(ADR-009) | 10 命脉 S1 / 重复簇 S2 / 18 候选归档 S3 |
| 全局 `~/.agents/skills` | 31 | 只读下载根 | 14 个与项目双份重复；混有 supabase/firecrawl 他项目残留 |
| 个人 `~/.dsh/skills` | 1 | 跨项目 | 仅 genui-chart-spec（来自 dsh-genui 插件） |
| 归档 skills-archive-2026-09-08 | 82 | 已砍 | 113−82=31 已核实 |

S1 命脉（保留）：koharu-drive、benchmark、oracle-label、dependency-guard、verify、
cycle-close、finisher、researcher、audit、background-monitoring。
**砍哪个不拍脑袋：等 DSH 观测一周，Read SKILL.md 次数=0 的归档。**

## 层 5 · 强制层（hook / 门禁）

| 机制 | 触发 | 状态 |
|---|---|---|
| `.githooks/pre-push` | 每次 git push，harness 无关 | `[挂载]` 可靠，fastcheck 门，坏代码上不了 main |
| SessionStart hook（.claude/settings.json） | 每次 **Claude Code** 会话 | `[挂载]` 但仅 CC 生效；DSH 里由 agent-instructions 插件替代 |
| memory_autoinject（UserPromptSubmit） | 每次提问 push 相关记忆 | `[断线]` settings 没挂，从没运行 |
| pre-commit / PreToolUse | — | `[停]` 重复/误杀，脚本残留建议 .disabled |

安全项：`~/.dsh/settings.yaml` 的 permission.defaultPreset = **danger-full-access（整机全开）**。
无人值守前必须降回 workspace-write，否则 agent 出错可越出工作区。

## 层 6 · MCP（外线）

- 项目 `.mcp.json`：amta-memory → `python scripts/mcp_memory.py`（记忆 pull 层）`[挂载] [待观测]`
- 全局：context7（最新库文档）。

## 层 7 · DSH 社区增强插件（web profile，14 个 bundle）

dsh-web-ui-all、dsh-deep-whale+maid-atelier(皮肤)、modlens、dsh-agent-teams(多agent)、
dsh-genui(图表)、archify(架构)、**aegis(护栏)**、dsh-context(上下文)、dsh-design-skills、
**dsh-memory(记忆)**、dsh-pocket、dshmarket、**graph-memory(图谱记忆)**。

静态问题：
- 这些是第三方 github/npm 件，**哪些真在干活、哪些只是皮肤/吃 context，全部 `[待观测]`**；
- 与层 4 skill 存在功能重叠（design-skills vs 项目 skill、agent-teams vs 自研 subagent 流程）；
- 残留 `package.json.bak-dup-genui` 备份文件可清。
- 判据同样是 dump-config 看挂载 + 仪表盘看是否产生事件。

## 层 8 · 知识资产（真家底，最厚实）

- lessons **45 条** L1–L45（docs/lessons.md，290 行）
- ADR **33 个**（docs/decisions/）
- 测试 **55 个** test_*.py（fastcheck 汇聚）
- docs：architecture / debug / decisions / reference / superpowers / archive
- .remember：会话档案与 logs
- 这层是"经验不重踩"的本钱，问题不在多少，而在**调用率**（层 9 + 观测）。

## 层 9 · 记忆机制（三套并存 —— 最该先收敛的重叠）

| # | 机制 | 组成 | 触发 | 问题 |
|---|---|---|---|---|
| M1 自研 amta memory | src/amta/memory + scripts/memory.py + mcp_memory + .remember + CLAUDE.local.md | SessionStart 推指针 / MCP 按需 pull / autoinject 断线 | 主力，但推送只给 9 行指针，强推层没接线 |
| M2 dsh-memory 插件 | qwert702/dsh-memory（web profile 已装） | DSH 插件生命周期 | 与 M1 职责重叠，是否在用 `[待观测]` |
| M3 graph-memory 插件 | adoresever/graph-memory（~/.dsh/graph-memory 有数据目录） | 图谱式记忆 | 第三套，是否真产生价值 `[待观测]` |

收敛原则（先观测后动手）：一周内看三套各自产生/被读多少次，
只留"被用且不可替代"的一套为主，其余停插件但保留数据目录。**别在没数据前删。**

---

## 静态台账能下的结论 vs 必须等观测的结论

**现在就能拍板（静态证据已足）：**
1. T2 三个断线零件可修（autoinject 接线 / report 默认 on / pretooluse 改名）——但一次只改一个
2. 三套记忆、14 插件、36+31 skill 的"重叠关系"已定位
3. danger-full-access 是无人值守前必改的安全项
4. CLAUDE.md/AGENTS.md 重复段可收敛

**必须等 DSH 观测才能拍板（静态判不了"用没用"）：**
1. 36 个项目 skill / 31 全局 skill 各被读几次 → 决定砍谁
2. 14 个社区插件谁在产生事件、谁空转
3. 三套记忆谁真被调用
4. 路由表（CLAUDE.md 渐进式加载）AI 到底路不路过

## 下一步顺序（修正版）
1. **静态台账（本文）已完成** → 你已经知道"有什么"
2. 回电脑前花 10 分钟按 dsh-dashboard-reading-guide 看一次真实任务 → 点亮观测
3. 观测跑满一周拿命中数据 → 再动层 4/7/9 的删减与层 5 的 hook 迁移
4. T2 断线零件可在观测点亮后、作为"用轨迹验证修复"的第一批练习
