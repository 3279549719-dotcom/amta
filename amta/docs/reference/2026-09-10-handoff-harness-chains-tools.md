# Handoff — Harness 第二轮：chained checklist + 深接口工具 + hooks 分层

- **日期**：2026-09-10（下午，承接当天早上两份 handoff）
- **主 commit**：`443936d` feat(harness): chained checklist + find_code/refactor_module 深接口 + hooks 分层 + fastcheck basetemp 修复（13 files, +675/-129）
- **承接文档**（先读这两份，本篇只记增量，不重复）：
  - `docs/reference/2026-09-10-handoff-governance-sprint.md`（三库分层、手动/自动砍法、裁决记录）
  - `docs/reference/2026-09-10-handoff-automation-harness-next-steps.md`（九层静态台账、DSH 观测、5 思考方向）

---

## 1. TL;DR

早上完成"盘点 + 砍除"后，本轮把多轮苏格拉底讨论**落地成代码**：CLAUDE.md 从 94 行瘦到 26 行并加了 7 条 chained checklist；新造两个"深接口"工具 `find_code.py`（代码检索）/`refactor_module.py`（导入重构）+ 自动生成的 `docs/module-map.md`；hooks 最终定为**方案 A 分层**（pre-commit 只跑秒级 `--quick`，完整 8 步留 /finish）；用 diagnosing-bugs 实战修了两个诡异 bug（pytest 僵尸目录退化、双 ruff 版本漂移）；顺手清了文档腐化和 memory。收尾时 fastcheck **436 passed / 3 skipped / 0 error，ALL PASS**。

一句话：**"我有什么"(module-map) → "AI 该用什么"(chained checklist) → "AI 实际用了什么"(造深接口让轨迹可观测)** 这条闭环，本轮把前两步建成了实物。

---

## 2. 本轮新增认知（可复用判断框架）

1. **skill ≠ tool**（Patrick 自己推出的本质区分）：skill = instruction（解题思路/流程，**不产生独立工具调用**，它"命中"要看 AI 的行为模式，所以 DSH 轨迹里看不到"调用了某 skill"是正常的）；tool = 可调用的"二级结论"/深接口。比喻：`read` 是"读书"这个动作，skill 是"先读整体架构再看模块耦合"的读书方法，`grep` 是"一目十行"的能力。
2. **三命运判据**（决定一条规则靠不靠谱）：
   - `embedded`：写进代码/hook，**必然执行**（如 pre-commit、fastcheck）；
   - `chained`：写进 CLAUDE.md checklist，每次会话自动注入，**手动会话与无人 agent 都有效**（因为 CLAUDE.md 两者都加载）；
   - `standalone`：只存在于某个文档，赌 AI 注意力，最不可靠（现状大量规则在这层）。
3. **"观测是事前设计痕迹，不是事后找痕迹"**（DeepSeek 提示，Patrick 高度认可）：Trajectory 是设计的镜子。DSH 轨迹面板本就有第二层动作观测；看不到 skill，是因为 AI 只用 pwsh/read/grep 原子工具拼凑、没有可识别的高层动作。**解法是造 `find_code` 这种深接口**——AI 调它，轨迹里就出现 `TOOL find_code {"kw":...}`，一眼可辨。
4. **文档防腐三层**：① 能动态生成绝不静态写死（module-map 由 `find_code --index` 生成）；② 静态文档只写原则 + 指针（CLAUDE.md 只 26 行，细节指向 module-map/ADR）；③ 静态事实集中一处，禁止散落多处副本。
5. **手动会话的瓶颈常在人**：Patrick 自己是注意力调度器；harness 整治对手动会话的价值 = 降低人的调度负担。手动会话与无人 agent 环境一致（都注入 CLAUDE.md），所以 chained 对两者都生效，embedded（hook）更是对所有会话生效。
6. **DSH 的 44 个原子工具是平台固定税**（约 10.6k token/轮，改不了）；要组合"二级结论"只能在本项目 `scripts/` 自己造深接口。fastcheck 是第一个范例，本轮加 find_code/refactor_module。
7. **"缺工具"常常是"缺声明"**：`run_pipeline.py --stages` 的 artifact_cache 增量复用（改 typeset 可复用前面 detect/translate 产物、从中间工位接入）**功能早就存在**，AI 却反复造轮子——根因是 CLAUDE.md 没声明，不是管线不支持。

---

## 3. 落地改动清单（细节都在 commit 443936d）

| 项 | 路径 | 干了什么 |
| --- | --- | --- |
| CLAUDE.md 瘦身 | `CLAUDE.md` | 94→26 行；删翻译通道/OCR/Stage4-6/技能三路径/Vision QA/2000字坑速查等高腐化动态事实，改为指向 module-map + ADR；新增 **7 条必执行 chained checklist**（finisher/diagnosing-bugs/grilling/research 四个 skill + gen_report/find_code/run_pipeline 三个工具）+ 5 行渐进式加载表 |
| 深接口① | `scripts/find_code.py` | ast 解析模块 docstring/类/函数做代码检索；`find_code <kw>` 搜索、`--map <dir>` 文件夹地图、`--index` 生成 module-map |
| 深接口② | `scripts/refactor_module.py` | 模块导入路径批量重构，`--dry-run`/`--test`/`--scope` |
| 动态索引 | `docs/module-map.md` | `find_code --index` 自动生成，11 子包 + scripts 索引（11.7k），替代手写代码地图 |
| hooks 方案A | `.githooks/pre-commit`（新）、`pre-push`（瘦身）、删 `pre-commit.disabled` | pre-commit 走 `uv run fastcheck --quick`（compile+ruff+pyright，17s）；完整 8 步留 /finish；pre-push 只在 koharu:4000 可达时跑可选 smoke |
| fastcheck | `scripts/fastcheck.py` | 加 `--quick` 分层；basetemp 改 pid 唯一目录（修 bug，见 §4） |
| lint 配置 | `pyproject.toml` | scripts/**、tests/** 豁免 E402（sys.path bootstrap 正当），消除双 ruff 漂移（见 §4） |
| 腐化修正 | `translation/__init__.py`、`translation/translate.py`、`backends/__init__.py`、`CLAUDE.md` | VLM refine 2026-09-09 已移除但多处仍写着 → 删；translate docstring "2 LLM call/page"→"1"；backends 补本地 OCR 部署指针（llama-server:8118/PaddleOCR-VL GGUF/baberu fast path/koharu 内置 OCR 不可用） |
| memory | `.remember/`（gitignored） | `memory.py gc` 真清理：today-2026-09-07 归档 recent.md、刷 now.md、清 tmp/logs，70h 未归档 WARN 消除 |
| 补漏 | `examples/use_artifact_cache_typeset.py` | 带上之前 lint 清零遗漏的 ruff isort/F541 修复 |

---

## 4. 两个 diagnosing-bugs 实战案例（下次遇到同类直接套）

**案例 A：pytest 从 436 passed 退化成 253 passed + 183 ERROR。**
- 反馈回路：单跑一个测试文件复现，traceback 显示 teardown 删固定 basetemp `output/logs/.pytest-basetemp` 时 `WinError 5 拒绝访问`，每文件只有第一个用例 passed、其后全 ERROR。
- 假设验证：换全新 basetemp 路径 → 立刻 5 passed；`rd /s /q`、`icacls /grant` 都 Access denied → 确认是**权限损坏的僵尸目录**（无残留 python 进程）。
- 修复：basetemp 改 `output/logs/.pytest-bt-{os.getpid()}` 唯一目录，跑完 `shutil.rmtree(ignore_errors=True)`。坏目录从设计上无法再污染。恢复 436 passed。
- 遗留：僵尸目录 `.pytest-basetemp` 本身删不掉（系统句柄锁），**重启后手动删**；新代码不再引用它。

**案例 B：pre-commit 报 12 个 E402，但手动 `uv run fastcheck` 全过。**
- 根因：**两个 ruff**。`.venv`（uv run）= ruff **0.16.6**（新版把 sys.path.insert 后的 import 视为合法 bootstrap，不报 E402）；git hook 探测到的 `py -3.13` = ruff **0.15.22**（旧版报 E402）。同一份 pyproject、同一条命令，版本不同结果不同。
- 修复（双保险）：① pre-commit 统一改 `uv run`，和手动/项目铁律一致，根除版本漂移；② pyproject 给 scripts/**、tests/** 补 E402 豁免（bootstrap 本就正当）。验证两个 ruff 都 All passed。

---

## 5. 硬事实（数字 / 路径 / 命令）

- **所有 Python 必须 `uv run python`**。环境里有三个 python，别踩错：
  - `uv run` → `.venv`（Python 3.12 + ruff 0.16.6 + 全部依赖，**唯一正确**）；
  - `py -3.13` → 全局（ruff 0.15.22，旧，会误报 E402）；
  - PowerShell 直接敲 `python` → 豆包 sandbox runtime（**无 ruff/pytest，假失败**，勿用）。
  - uv 位置 `C:\Users\asus\.local\bin\uv.exe`。
- fastcheck 分层：`--quick` = compileall+ruff+pyright，实测 **17.5s**；默认完整 8 步 = quick+pytest(436)+depguard+mem-lint+mem-gc(dry)+mem-inject，约 **47s**（输出结束才一次性吐出，无输出≠卡死）。pytest 结果以汇总行 "N passed" 正则判定，不以 exit code 判定。
- 测试基线：**436 passed, 3 skipped, 0 error**。
- CLAUDE.md 最终 26 行；src/amta 11 子包（backends/common/guards/inpaint/memory/orchestrator/report/stations/stores/translation/typeset）；项目库 `.dsh/skills` 23 个 skill。
- 关键入口：`run_pipeline.py --stages`（artifact_cache 内容哈希增量复用，支持 detect,ocr,translate,inpaint,typeset 子集/中间接入）、`gen_report.py --type`、`fastcheck.py [--quick]`、`find_code.py [kw|--map|--index]`、`refactor_module.py`、`memory.py {read,grep,index,recent,status,lint,gc,inject}`、`context7.py`。
- git：本轮 commit `443936d`；**main 领先 origin/main 17 个 commit**（本篇入库后 18；origin 停在 69ba274）。推 GitHub 需开 Clash（git 走 127.0.0.1），铁律 fetch→评估分叉→push、禁 force-push，**等 Patrick 发令才推**。commit 是本地操作不需要代理。
- `.remember/`、`*.local`（CLAUDE.local.md）被 gitignore，不进版本库。

---

## 6. 未决入口（下个会话从这里挑）

1. **推 commit**：18 个 commit 待推（需 Clash，Patrick 发令）。
2. **4 个旧 untracked 待处置**：`docs/ai-collab-protocol-2026-09-07.html`、`docs/cleanup-survey-2026-09-07.html`、`fastcheck-2026-09-09.log`、`fastcheck-2026-09-09b.log`（刻意没进 commit；建议两个 log 加 .gitignore，两个 HTML 由 Patrick 决定去留）。
3. **观测验证（下次 DSH 会话收尾时做）**：① finisher 是否自动触发（看 subagent 调用 + lessons/progress 文件变化）；② chained 是否生效——在 DSH 轨迹里找 `find_code`、`run_pipeline --stages` 这类**高层动作**，而不是原子 grep/pwsh（这正是 §2.3 的实证）。
4. **下一个 deep module 候选**（讨论过未动工）：`debug_translation`（某话原图/OCR/译文并排对比，但可能与 stores 的 artifact cache/store 重合，**先判断是否伪需求**再写）；`new_adr`（ADR/lesson/progress 模板 + 索引 + estate 指针）。
5. **全局库重名**：`~/.agents/skills` 31 个里 8 个与项目归档重名（ask-matt/grill-me/implement/improve-codebase-architecture/setup-matt-pocock-skills/to-questionnaire/wizard/writing-for-agents），superpowers 核心指定保留；清理待 Patrick 拍板。
6. **工具面对齐 8 领域子包**（P1）：module-map 已部分缓解，仍需把 CLAUDE.md 工具面与子包边界对齐。
7. 低优无害：pyright v1.1.411→v1.1.413 提示；Pillow `Image.getdata` DeprecationWarning（2027-10 才移除，tests/test_typeset_render.py:75/90）。

---

## 7. 陷阱清单（本轮新踩，第三次实证的加粗）

- **Edit 工具匹配含中文/特殊字符的长 old_string 会报 "Native execution failed"**：改用纯 ASCII 唯一片段匹配，或 Read 后用 Write 整体重写（本轮 fastcheck.py 即整体重写解决）。
- **PowerShell `Get-Content` 读中文 .py docstring 乱码**：用 Read 工具，或加 `-Encoding UTF8`。
- **基于旧文档重写新文档会把腐化信息再抄一遍**（本轮误抄已移除的 qwen VLM refine）：重写前必须读代码现状核实，不能信旧文档。
- **多 Python/多 ruff 环境漂移**：见 §5，一律 uv run；git hook 也要 uv run。
- **PowerShell 会把 git hook 走 stderr 的输出显示成红色 NativeCommandError 甚至报 exit 1，但 commit 实际成功**——认准输出里有没有 `[main <hash>]` 那一行，有就是成了。
- `git add` 的 LF→CRLF warning 是 Windows 正常现象，无害。
- Bash 命令超 15s 自动转后台，用 TaskOutput(block=true) 等；完整 fastcheck 47s 必转后台。

---

## 8. Suggested Skills（下个会话该调谁）

- **handoff**：接续本篇或再次交接时先调（本篇即按它写；注意它默认说存 OS 临时目录，但本项目惯例存 `docs/reference/` 并入库，从项目惯例）。
- **finisher / cycle-close**：收尾五路分流（lessons/CLAUDE.md/skill/ADR/progress），完整 fastcheck 在这里跑。
- **diagnosing-bugs**：再遇"诡异/时好时坏"bug，先按 Phase 1 建一条能变红的反馈回路，禁止先读代码猜因（本轮两个 bug 都靠它定位）。
- **c4-codebase-architecture**：推进未决 #6 工具面对齐子包时用。
- **grilling**：需求模糊（如 debug_translation 是否伪需求）时用苏格拉底式逼问。
