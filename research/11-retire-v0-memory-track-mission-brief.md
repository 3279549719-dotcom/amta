# Mission Brief — 退役 v0 记忆轨道（INDEX / project_memory），estate 单一事实源

> 本文件是 mission 的**技术简报**：承载 2026-09-05 覆盖度调研的全部证据，
> agent 首轮拆 plan 前**先读本文件**，据此拆 chunk，无需重做调研。
> 这是 seed 上下文（人写的 mission 定义），不是 agent 输出物。mission 跑完合并 main 后本文件存档即可。

## 1. Mission 一句话

把记忆系统的 **v0 轨道（docs/INDEX.md + src/amta/memory/project_memory.py + memory.py 的
search/read-rid/add/stats）整体退役**，让 **estate 轨道（ADR-027：lessons/ADR/remember 动态解析）成为
记忆检索与写回的单一事实源**；顺手修掉 `memory.py read <ID>` 的断裂读路径。

- **跑在**：分支 `feat/retire-v0-memory-track`（已从 main 拉出；main 基线 fastcheck ALL PASS 368 passed）
- **预先授权**：本简报「§5 删除/改动清单」列出的文件删除 = 已授权，**不要为删它们 BLOCK**
  （mission 的靶子就是删 v0 轨道；只对清单之外的删除才需人裁决）
- **最终验收**：见 §7。合 main 由人类 + L6 review 把关，agent 不自己合。

## 2. 为什么退役（覆盖度实测证据）

记忆系统有两套并存检索，读同一批知识却各有一套 ID 命名空间——这是 code-simplify 靶子，c55eeed 收敛时漏收干净：

| 维度 | v0 轨道（INDEX.md / project_memory） | estate 轨道（tools / ADR-027，现行） |
|---|---|---|
| lessons 覆盖 | **14/44**（L-001..L-014）+ 1 条腐坏孤儿行 | **44/44**（`parse_lessons` 扫 `## L\d+ —` 头） |
| decisions 覆盖 | 30/30（D-001..D-030） | 30/30（ADR-001..030，扫 `0*.md`） |
| remember / research | ✗ | ✓ |
| 检索面 | 静态表格 + 固定语料 glob | 条目级正文扫描 |
| 机械护栏 | **无**（lint 只管 estate 的 ADR README 索引，不碰 INDEX.md） | ✓（memory lint / gc / inject 全 estate） |
| 活跃消费 | MCP✗ / 注入包✗ / ralph preamble✗ | MCP 字典、注入包、ralph 注入、CLAUDE.md 渐进表全部 estate |

**实锤一 — 停更即死**：LESSON L15~L44（30 条，近 3 周）从未进 INDEX。
CLAUDE.md:64 规定"迭代结束 `memory.py add` 写回 INDEX"，实际没人写——写协议早已废弃。
一个没人喂、喂了也没人读的索引 = 死索引。

**实锤二 — 双命名空间制造真实坏路径（已实证）**：
- ralph 注入清单 / `memory.py index` 输出的是 **estate ID**（`L19` / `ADR-016`）；
- 但旧 `memory.py read <positional>` 路由到 v0 INDEX（只认 `L-001` / `D-016`）。
- 实测：`memory.py read L19` → `[miss] 索引里没有 L19`；`read ADR-016` → `[miss]`。
- **本批已在 scripts/memory.py 修好**：positional 先按 estate 条目解析，解析不到才回落 v0
  （v0 退役后回落分支一并删除，见 §5 改 2）。**agent 执行期间 `read L19` 已是好的**。

**实锤三 — 内部已腐坏**：INDEX.md 有 L34 孤儿行（非零填充格式 + 值里混管道符），
**连 v0 自己的 `ROW_RE` 都解析不了**——是某次手动追加没走 add 协议的残留。

**实锤四 — trigger 列无迁移价值**：INDEX 唯一 estate 无法从正文再生的是 trigger（情境措辞）。
但 (a) 主动检索模型已废弃 grep 猜词（prompt.md 自述关键词匹配仅 25% 召回），改扫全标题再按 ID 读，
scan-then-read 下 trigger 冗余；(b) 只有 14/44 条 lesson 有过 trigger，30 条没有也被正常检索——
trigger 从来不是检索必要条件；(c) INDEX.md 在 git 历史里，删文件不毁数据。
→ **不把 trigger 文案迁移进 lessons/ADR 正文**（会污染经验/决策文档）。

## 3. 目标态

- 记忆检索/写回单一事实源 = **estate**（docs/lessons.md + docs/decisions/* + .remember 动态解析）。
- `memory.py` CLI 收敛：`read`（positional=estate 条目，可配 `--section`）、`grep`、`index`、
  `recent`、`status`、`lint`、`gc`、`inject`。**删 `search` / `add` / `stats` 三个 v0 子命令**。
- 不再有第二套 ID 命名空间；`docs/INDEX.md` 删除后文档引读写协议的地方改指 estate。

## 4. 关键陷阱（必读，避免删崩）

1. **删除必须原子**：`project_memory.py` 与 `memory/__init__.py` 的 re-export **同一 commit 删/摘**。
   `__init__.py` 现在 `from amta.memory.project_memory import (...)`,任何 `from amta.memory import tools`
   都会先执行 `__init__`——若只删 project_memory.py 没摘 __init__，estate 整条 import 链直接崩。
2. **scripts/memory.py 的 read 回落分支**（"地产无此条目 → project_memory.read"）必须随 v0 一起删，
   否则残留对已删模块的 import。删后 read positional 纯走 estate。
3. **tests/test_memory.py** 需先读：它 `from amta import memory`（触发 __init__）测 v0 的
   parse_index/search/read/add/stats。判断它是否还含 estate 工具测试——有则只删 v0 部分，无则整体删。
   另跑 `grep -rn "from amta import memory\b"` 看还有没有别处触发包 __init__。
4. **CLAUDE.md:64** 项目记忆写回协议还在教 agent `memory.py add` 写 INDEX —— 要改成 estate 措辞
   （晋升本来就落 lessons.md/decisions，无需额外索引登记）。
5. **只删 v0，勿碰**：estate/tools/lint/inject/gc/loop_state(schema v2 已完成)/.remember/MCP 字典。
6. 引用豁免（历史档案，**不追改**，报告里列明即可）：
   `docs/decisions/025`（设计时描述）、`docs/progress.md:253`（当时结构记录）、
   `docs/superpowers/plans/2026-08-29-lesson03-p0p1.md`（已实施的历史 plan）。
   `docs/decisions/README.md` / estate 的 ADR 索引是 estate 自己，别动。

## 5. 删除 / 改动清单（此单 = 授权边界）

**删（授权）**：
- [ ] `src/amta/memory/project_memory.py`（191 行，整文件）
- [ ] `docs/INDEX.md`（整文件）
- [ ] `tests/test_memory.py` 里的 v0 测试（parse_index/search/read/add/stats；先判断是否混 estate 测试）

**改**：
- [ ] `src/amta/memory/__init__.py`：摘 project_memory re-export + 更新模块 docstring（不再"两层并存"，只剩 estate 系）
- [ ] `scripts/memory.py`：删 `search`/`add`/`stats` 子命令 + 对应 handler + `project_memory` import +
      read 的 v0 回落分支；更新顶部用法 docstring（去掉 v0 示例行）
- [ ] `CLAUDE.md`：第 ~64 行"项目记忆写回"协议改为 estate 措辞（删 `memory.py add` / `INDEX.md` 语义）
- [ ] 其他 grep 到的 v0 引用（`project_memory` / `INDEX.md` / `memory.py search|add|stats` /
      `L-0\d\d` / `D-0\d\d`），逐一判断：活的改，历史档案豁免列明

**留（确认勿动）**：`docs/lessons.md`、`docs/decisions/`、`.remember/`、`research/`（除本简报）、
`src/amta/memory/{estate,tools,lint,inject,gc,loop_state}.py`、`scripts/mcp_memory.py`、`.mcp.json`。

## 6. 建议拆 chunk（agent 可自行调整，仅供参考）

- **C1 摸底确认**：重跑本简报实证（read L19/ADR-016 命中 + memory.py index 行数），读 test_memory.py
  结构定删法；跑 fastcheck 确认起步绿。
- **C2 原子删 v0 代码**：project_memory.py 删除 + __init__ 摘 re-export + scripts/memory.py 收 search/add/stats
  + read 回落分支删除；单测改/删；**fastcheck 必须一次绿**（验证陷阱 1/2 处理对）。
- **C3 清引用 + 文档**：CLAUDE.md:64 写协议改 estate；grep 扫全仓 v0 引用逐一处理/列豁免；docs/INDEX.md 删除。
- **C4 端到端验收**：fastcheck ALL PASS + §7 各项机械验证 + 记忆注入仍含接续状态。
  若 C1-C4 中某块大到一轮装不下，自行再细分。

## 7. 最终验收（mission 完成判据，全过才 COMPLETE）

1. `uv run python scripts/fastcheck.py` → ALL PASS。
2. `git grep -n -E "project_memory|docs/INDEX\.md|memory\.py (search|add|stats)"`（排除 .worktrees）：
   活的零残留；历史档案豁免已列明清单。
3. `memory.py read L19` 与 `memory.py read ADR-016` 直接命中地产条目（不再 [miss]）。
4. `memory.py --help` / `memory.py` 无 search/add/stats 子命令；`memory.py index` 仍列出全部 lessons+ADR。
5. MCP 字典不受影响（memory_search/read/recent 走 estate，本来就不依赖 v0）。
6. `uv run python scripts/memory.py inject` 生成的 CLAUDE.local.md 仍含"接续状态"块（loop_state summarize 正常）。
7. 分支提交历史干净：harness commit（schema v2 + prompt v2）→ mission seed commit → 各 chunk commit；
   commit body 写清成果/依据/验证。删除用 `git rm`，别留半删状态。

## 8. 交接备注（给接手/审核人）

- 前置 harness 已就位并 commit：loop_state schema v2（plan/resume_req）、prompt.md v2（mission 拆解+自续）、
  scripts/memory.py read positional→estate（带 v0 回落，待 C2 摘）、scripts/loop_state.py plan CLI、测试 20 passed。
- loop_state.json 的 mission 字段只放简洁指针，**详细上下文在本文件**（避免注入包超预算丢接续状态）。
- 完成后走 L6：`uv run python scripts/review.py --base main --mission "<退役 v0 轨道…验收标准>"`，人类合并。
