# Handoff · AMTA 治理冲刺落地（2026-09-09 晚 → 09-10 晨）

> 给下一个 OpenClaw 对话的接续文档。项目根 `E:\manga translator agent\amta`（Windows / PowerShell）。
> 用户 Patrick，vibe coder，比喻+少术语+保留关键英文。本文不含任何密钥。
> 前置阅读：`docs/reference/2026-09-09-harness-inventory-tracing.md`（九层台账）+ 本文件。昨晚 handoff（temp）已被本文件取代。

---

## 0. TL;DR（昨晚到今晨发生了什么）

治理冲刺四包全部落地：**AGENTS.md 98→6 行、skill 36→23（catalog 税 −25%）、书脊补全（lessons 45 条目录 + ADR 索引 031–033 + 撞号修复）、lint 251→0**。fastcheck 在 main 上拿到**首次被证实的 8/8 ALL PASS**（pytest 436 passed）。aegis Patrick 已手动从 DSH profile 摘除——**P0 全清**。当前 main 领先 origin **13 commit 待推**。治理 commit：`44bd63a`（书脊+撞号+台账入库）、`72caa26`（lint 清零）。

期间第三次实证"单 checkout 多会话互踩"：一个并行会话在同一 checkout 完成 domain 子包化（40 平铺模块 → 8 领域子包）并合入 main，还把我未提交的手术成果扫进了它的 `29f790e`——内容零丢失但归属混淆。

## 1. 认知框架（已认同，勿重讲；增量两条）

继承 09-09 台账全部框架：三命运判据（embedded/chained/standalone）、Agent=Model+Harness、注意力税、马斯克五步（质疑→删除→简化→加速→自动化，顺序不可颠倒）、静态盘点→动态观测→自动化接力顺序。

**09-10 新增两条**：
- **skill catalog 三库分层**：amta 项目库 `.dsh/skills`（23，只进 DSH 会话）｜全局库 `~/.agents/skills`（31，superpowers 老家，服务所有工具）｜aegis 插件（已删）。同名 skill 可能同时住多层——aegis 当年就是抄了全局库的名字。判断 skill 归属先问"它住哪层"，再谈砍不砍。
- **手动款 vs 自动款的砍法不同**：`disable-model-invocation: true` 的手动 skill，用户没印象 = 零命中，可直接归档；自动款没印象 ≠ 没命中（命中发生在 AI 决策瞬间），必须 Trajectory 观测一周才有资格判死刑。

## 2. Patrick 的裁决记录（08-09 晚拍板，后续勿再问）

| 裁决 | 内容 |
|------|------|
| skill 留任 | **只留 grilling**（grill 家族归档 grill-me/grill-with-docs/to-questionnaire）；**research 留**（researcher 归档）；**finisher 保留且要利用起来**（Patrick 自造，用于项目收尾后自动沉淀 progress/decision/lesson） |
| 第一刀 | 11 个手动+无印象 skill 归档，"完全赞同"——已执行（13 个，含 grill-me/researcher） |
| 问题 a=c | src/amta 的"乱"是纯视觉型 → 不建文件夹。（讽刺：并行会话当晚已做子包化，视觉问题被它顺手解决） |
| lint 存量 | "机械的东西自己搞定" → 已清零 |

## 3. 硬事实（可复现）

- **fastcheck 基线**：8/8 ALL PASS（compile/lint/typecheck/pytest 436/depguard/mem-lint/mem-gc/mem-inject）。lint 步曾被 merge commit `402bd6c` 的 "ALL PASS" 谎报——那是 ruff 缺装窗口期的假象，`72caa26` 后才是真的。
- **lint 清零路径**：251 = 160 自动修 + 45 定向 unsafe-fixes + ~50 配置豁免（pyproject `[tool.ruff.lint]` ignore：BLE001/S110/PLW1510/TRY004/TRY002，per-file：`scripts/**` DTZ、`src/amta/memory/**` DTZ 本地日期设计、`src/amta/inpaint/_lama*.py` B008 按 L38 对齐参考实现）+ 4 处手工（闭包默认参数绑定、report/stages `__all__`、ocr_station enumerate、test with 合并）。
- **catalog 房租**：项目库 frontmatter 8569B≈2678 token → 6080B≈1900 token/轮。归档 13 个 skill 在 `amta/scripts/archive/skills-2026-09-10/`，随时可装回。
- **ADR 编号**：bubble_type 移除 = **ADR-033**（原误占 031，撞 09-05 的 translation-quality-triple-fix）；全仓 15 文件引用已同步；`docs/adr/` 目录已并入 `docs/decisions/`。
- **git**：main 领先 origin/main **13 commit**（origin 停在 `69ba274`）。待推清单含 5e4ed7a(Q1)/fda1644(ADR-Q1 conf 0.5)/3d174d9(子包化)/29f790e/402bd6c(merge)/44bd63a/72caa26。
- **CLAUDE.md 路由表**：ask-matt/researcher 鬼路径已修（→ grilling/research）；estate.py 字典指针已增强（L1–L45 书脊 + ADR-001–033 索引提示，ADR-027 契约内最小改动，60 记忆测试过）。

## 4. 发现未决（下一个会话的入口）

1. **推 13 个 commit**（需 Clash 代理，铁律：先 fetch 评估分叉，禁 force-push）。
2. **CLAUDE.md 工具面对齐 8 领域子包**（P1 地图项）：子包结构 backends/common/guards/inpaint/memory/orchestrator/report/stations/stores/translation/typeset。素材：`scripts/probes/_resid.py` 的 LEGACY 映射表（旧平铺名→新子包完整对照）+ `docs/refactor/amta-domain-packages.md`。
3. **全局库 31 个中有 8 个与昨晚项目库归档重名**（ask-matt/grill-me/implement/improve-codebase-architecture/setup-matt-pocock-skills/to-questionnaire/wizard/writing-for-agents）——是否清全局层 = Patrick 拍板，注意 superpowers 核心（brainstorming/writing-plans/executing-plans/TDD/verification 等）是指定保留的跨工具纪律，别动。
4. **finisher 激活**：Patrick 明确要用。机制：DSH 会话收尾说"收尾/落盘//finish"即触发（与 cycle-close 触发词重叠——两者留了 cycle-close，若观测发现路由打架再裁）。
5. **观测一周**（Phase 4 入口）：dsh web → amta → Trajectory 工具调用树，采集 23 个项目 skill 的真实命中 → 第二刀（0 命中归档）；同时定 M2/M3 记忆件去留。
6. 小杂务：`today-2026-09-07.md` 未归档 WARN（memory lint 持续提醒）；`fastcheck-2026-09-09*.log` 两个日志建议 gitignore；`amta/docs/ai-collab-protocol-2026-09-07.html`、`cleanup-survey-2026-09-07.html` 仍 untracked 待定命运；aegis 若要双保险验证可跑 `dsh --profile web --dump-config` 搜 skill 名。

## 5. 陷阱（勿重踩，第三次教训加粗）

- Python 一律 `uv run python`；裸 python 落到沙箱解释器假失败。
- PowerShell 无 `&&`；中文 JSON 用 node 解析；**改中文文件用 read/edit/write 工具，PowerShell 管道会编码崩**；lessons.md 是 **CRLF** 行尾（edit 匹配时注意，L30）。
- **单 checkout 多会话互踩已三次实证（09-08 深夜、09-09 白天、09-10 凌晨）**：并行会话必须各走 `.worktrees/`，或在开始前 `git status` + `git log -3` 确认没人动过；staged 改动会被别的会话 commit 扫走。
- `_lama_*.py` 与模型推理代码勿随手重构（L38 参考对齐）。
- detect 层已定死 conf 0.5（ADR-Q1，瓦片化默认关）——别再用旧记忆里的 0.7。
- fastcheck 输出缓冲到结束才吐，4 分钟无输出≠卡死；但 CPU 全零 + 超 6 分钟要先查子进程。

## 6. Suggested skills（下一个 agent 调用）

- **handoff**（amta 项目库）：再次交接时。
- **c4-codebase-architecture**（全局/项目都有）：做 CLAUDE.md 工具面对齐盘查时。
- **finisher / cycle-close**（项目库）：会话收尾沉淀时（Patrick 指名要用 finisher）。
- OpenClaw 侧 memory skill：更新 MEMORY.md 时。

## 7. 记忆指针（OpenClaw 侧已更新）

- `MEMORY.md` amta 行：09-10 晨状态（aegis 摘除、13 commit 待推、fastcheck 真全绿、交接文档路径）。
- `memory/2026-09-09-evening.md`（与交接文档的差异核查）、`memory/2026-09-09-skill-triage.md`（skill 摸底全量数据）。
- 治理台账四份 + 进度地图：`amta/docs/reference/2026-09-09-*`（已入库 44bd63a）。
