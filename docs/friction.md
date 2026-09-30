# 不顺账 — 白天卡一下，写一行；晚上只还账上的条目

> 建立 2026-09-12。**条目由使用者本人写**（AI 代记时必须标注「AI 代记」）。
> 一行一条，**上限 20 行**；满了先还账，再记新账。
>
> **为什么只认这本账**：任何新增机制都必须能追到白天真实发生过的一次卡顿，否则它就没过准入条件
> （准入 = 能被一条命令判定真假 **且** 拦下过一次真实事故；预防性机制一律不建）。
> 判据补充：**一个坏了 N 天没人发现的机制，等于没人用** —— 账上没有它的痕迹，就该删。
> **删/生判定必须横跨全部 harness**：用户同时跑 DSH / Claude Code / 豆包三个 harness，
> 只统计其中一两份的调用数据 = 不成立的证据（2026-09-15 `find_code.py` 误删事故，豆包实际用了 81 次）。判"没人用"前逐个查轨迹，位置见 lessons `L51`。

## 格式

- [2026-09-28] 改进排版仍需人反复发“继续”，且计划未交付给可运行的本机 Agent（AI 代记）→ 文件检查点驱动真实 headless 调用；`uv run python -m pytest tests/test_agent_loop.py -q` 检查两轮自动推进及假成功拒绝 | 实跑验收中

`- [YYYY-MM-DD] 白天卡在哪 → 期望它怎样 | 状态`

状态：`未还` / `已还：<commit>` / `否决：<理由>`

## 账目

- [2026-09-12] 交接清单被做成 dsh-ui 表格，对方没渲染出来 → 说了等于没说 | 未还
- [2026-09-12] 每次开对话，注入包都写「idle — ralph v4 待命，更新 09-07」，而实际在改 typeset | 已还：包 A（注入包不再带接续状态）
- [2026-09-12] 同一件收尾（finish）有三套说法，其中一套写着假事实（「本仓无 lint／无 typecheck」）| 已还：2026-09-12 收敛到 `state.py finish` 单一执行入口 + `tests/test_harness_covenant.py` H7 探针持续拦截；2026-09-17 清掉 cycle-close 与 CLAUDE.md 里残留的旧说法与 9 步枚举（AI 代记）
- [2026-09-12] `audit.py --strict` 报「未发现 Harness 熵」，而 `workspace/` 躺着 34 个目录 629MB（判据 glob `ws-*`，实际 0 个）| 否决：工具已归档到 `scripts/archive/`——判据 glob 写错且无消费者，"坏了 N 天没人发现 = 没人用 = 该删"（AI 代记）

- [2026-09-16] 跑完管线只报 failed=0，39 页真台词被 conf 过滤误删系统一声不吭，质量信号全埋 JSON 里靠人眼捞（豆包手写 PowerShell 三轮才拼出体检表）→ run_pipeline 收尾直接吐质量红榜 | 已还：feat/quality-audit（AI 代记：豆包 18:19 自报告）
- [2026-09-16] 看小泡三态对比要手写 PIL 裁图拼画布（错一次）→ 期望给个 region_id 自动拼三态裁片 | 未还（AI 代记：豆包 18:19 自报告；等第二次真实卡壳——红榜+gen_report --granularity region 可能已覆盖）
- [2026-09-20] CLAUDE.md 有「HTML 报告铁律」却零断言：一周内 `scripts/probes/` 新写 4 个手写 HTML 生成器（~170 行，commit 5f99f10）、同日归档 3 个、`grep` 命中 14 个文件 1516 行，没有一处会失败 → 期望 grep 一次就能判真假 | 已还：`tests/test_lessons_guard.py::test_L50_no_ad_hoc_html_report`（AI 代记）
- [2026-09-30] 跑了 N 本同人志，书内自造词（ヤミツキ茸/クズ）前页译过、后页又变回片假名——磁盘上 29 个 `work_state.json` 实扫：活 terms 全部是 `pre_scan` 从静态主词典机械匹配来的 confirmed，没有一条是 LLM 翻译决定长出来的；`candidate` 10 条全是片假名正则误抓的普通词（ルール/メリット/ガチャ），`suggestions.py` 在 src/ 零调用方；跨页上下文硬编码 3 页、candidate 不进 prompt → 期望：第一次翻译决定即暂定可注入，重复出现累加证据页，不要四态审批；可翻译日文残留不能静默以 ok 出货 | 未还（AI 代记：豆包验尸，Stage 2 任务承接）
- [2026-10-01] `state.py finish` 全量门禁被两条**与本次改动无关**的红项拦下：① depguard 对 `deepseek-harness-sdk` 既报「未声明」又报「已声明但未 import」——声明名是连字符、import 名是下划线（`deepseek_harness`），PEP 503 归一化对不上，同一条合法依赖被同时判两个罪（`scripts/run_sdk_task.py`、`scripts/_run_high_effort_verify.py`，最后改动 `80974c9`）；② memory lint 报 `recent.md` 已 11 天未更新（数据新鲜度，非代码问题）→ 期望：depguard 的声明名↔import 名映射能识别连字符/下划线别名，而不是把一条真实依赖同时判死两次 | 未还（AI 代记：本次 Stage 2 收尾实测；两条红项均属既有、非本次引入）
- [2026-10-01] `state.py finish` 内部的 `git add -A` 把**用户自己改的两个文件**（`.dsh/skills/handoff/SKILL.md`、`.gitignore`）一并提交进收尾 commit，违反"不得提交用户自有改动"→ 已 `git reset --soft` 撤回并 `git restore` 还原这两个文件，改用显式路径提交 → 期望：收尾入口不该用 `git add -A` 扫全树，或至少在提交前把"非本次任务所属的已修改文件"列出来让人确认 | 未还（AI 代记：本次 Stage 2 收尾实测；`.git/info/exclude` 只能挡未跟踪文件，挡不住已跟踪文件的改动）
