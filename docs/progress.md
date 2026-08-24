# AMTA 项目进度（外部持久化记忆 / 交接文档）

> 本文件是**项目状态的唯一事实来源**，任何 AI（Claude Code / Cursor / DSH / 未来 agent）接手第一件事先读它。
> 与 hindsight（DSH 会话内记忆）互补：hindsight 是会话内快速召回，本文件是工具无关的交接文档。
> 每次完成任务后更新本节「当前状态」与「下一步」。

## 一句话

会话驱动漫画翻译自动化：**DSH 会话=导演，amta Python=确定性执行器，koharu v0.59.1 headless(:4000)=引擎**。第一里程碑：Benchmark A/B/C 定量钉死能力边界。

## 当前状态（2026-08-24，最后一笔：翻译工位架构定稿 ADR-014）

- **翻译工位架构定稿（2026-08-24，ADR-014）**：grill 定案 7 条，产物结构 ADR-013 的落地形态：
  - **翻译层 = 脚本直调 DeepSeek API**（`.env` CHAT_BASE_URL/CHAT_MODEL/CHAT_API_KEY 现成，`https://api.deepseek.com`）→ **修订锁定决策 #5**（弃 koharu 内 llm 引擎，not-ready 悬空）
  - **Harness**：Context+Guardrails+Loop 做，Tools 砍（脚本直读文件，不搞 function calling）
  - **护栏双层**：机械层（结构错/残留错/region_id 一一对应，纯代码，类比 fastcheck/hook）+ 语义层（手搓 VLM 脚本验证译文质量，DASHSCOPE 通道）
  - **工位边界**：translate 只管文本质量；detect/inpaint/typeset 错误归各自工位未来 mechanical check
  - **Loop 分层**：脚本机械 loop（schema 错自动重译 1 次）+ 导演语义 loop（VLM 拦出 → FAILED 附证据 → DSH 会话修订）
  - **术语演进**：suggestions.json 中间层 + 导演自动合并（零人工卡点，可追溯）
  - **工位清单**：00_run_all（文件存在=跳过）→ 01_detect → 02_ocr(For-Manga) → 03_translate(DeepSeek) → 04_inpaint → 05_typeset
  - state/ 四文件：touhou_knowledge / work_state / open_questions（ADR-013）+ suggestions.json（新增）
- **产物结构 rebaseline（2026-08-24，ADR-013）**：按 reference（touhou_doujin_first_principles_dikw.html）第一性原理/DIKW，把产物从"逐页 benchmark 报表"重定为**每本同人志一个工作区**（Touhou 同人志缩域）：
  - `workspace/<work_id>/{raw, artifacts, state}`；state/ 三文件：`touhou_knowledge.json`（共享 canon prior）+ `work_state.json`（当前本子逐页生长）+ `open_questions.json`（未决问题）
  - 三层上下文分离：canon prior ≠ 本子真相（同人志可改关系/语气，当前页证据 ＞ work_state ＞ canon ＞ 猜测）；work_state 逐页生长，首版不做 DB/Vector/Event Graph/Memory Service
  - Evidence tracking：条目带 `status ∈ {confirmed,inferred,candidate}` + source 页码；新证据可修正旧状态；单页可运行
  - 代码：`src/amta/workstate.py`（workspace 布局 + 空 schema + init/update/validate）+ `tests/test_workstate.py`（8 测试）；fastcheck ALL PASS（53）
  - **OCR 评测底座不变**：For-Manga 定案（ADR-011）、指标口径（ADR-010）仍是事实，output/ 旧评测数据保留供迁移
  - 翻译层归属已定（ADR-014）：脚本直调 DeepSeek API，修订决策 #5
- **OCR 引擎三选一对比完成（2026-08-24，86 个 detector 对齐 GT 框）**：锚点=detector 并集 crop 图（全尺寸可靠坐标）+ GT 语义内容（字符重合度≥0.6 对齐，86/101；15 个未检出=page_5 设定页检测不足，单独计数不混入 OCR 指标，ADR-011）：
  - **For-Manga（现役·漫画微调）ALL CER 0.062 / EM 0.779**：dialogue_in 0.001/0.974、sfx 0.161/0.643、bg_text 0.0/1.0 → **保持现役，无需换 1.6**
  - **PaddleOCR-VL-1.6（官方原版）ALL CER 0.113 / EM 0.721**：对白类与 For-Manga 持平，但 **sfx 0.458 明显落后**
  - **qwen-vl-ocr（云端通用）ALL CER 0.266 / EM 0.465**：垫底，且与 GT 同源（Qwen）有虚高风险，仅外部参考
  - 报告：`output/reports/ocr_engine_compare.html`；决策：ADR-011
- **评测坐标源修正（L16）**：OCR 评测必须用 detector 对齐框，勿用 GT 缩略 bbox（VLM 缩略坐标裁图全空白）或单引擎框（manga-ocr 每页仅 5-9 框，55/101）；页码注意 0/1 基偏移。

- **Harness 迁移完成（2026-08-23）**：9 技能从 `.claude/skills/` 迁到 `.dsh/skills/`（DSH 原生技能根，`npx dsh-movein` 迁移 + `git mv` 定唯一事实源）；新增 **finisher**（收尾知识归类委派 subagent）与 **researcher**（外部调研委派 subagent）技能；判断链改**五路分流**（lesson → CLAUDE.md / skill / ADR / progress / test·hook，test/lint/hook 为唯一真强制层）；修复 **#1401 frontmatter bug**（cycle-close / background-monitoring description 未引号 `": "` 被 DSH 静默丢弃）；hook 层维持 git hooks（CC 生命周期 hook 桥 = 进程级 configPath + PreToolUse deny-only，会跨项目泄漏，不装）。机制决策见 **ADR-009**。
- **第二轮 OCR 测评完成（本会话）**：框外对白 OCR 换引擎——**PaddleOCR-VL-For-Manga**（本地 GGUF + 独立 llama-server b10582，端口 8118）全量 126 crops 实测：
  - **QA 修正后（现行 norm 去标点口径 + unmatched 归因）：ALL CER 0.316→0.121 / EM 0.516→0.770；99 行（排除 27 unmatched）CER 0.035 / EM 0.869**（For-Manga 真实水平；dialogue_out EM 0.857）；48 行重复计数（union 去重漏碎片框，L12）与 25 行不可靠 GT（per-crop 标注，L13）已定案，json 待重生成（L14）
  - dialogue_in：CER 0.16 → 0.103；sfx：1.0 → 0.15；bg_text：0.727 → 0.038；ALL：0.462 → 0.316
  - 证据：`output/data/benchmark_b_paddle_manga.json`（126 rows 全量）+ `output/reports/benchmark_b_paddle_manga_report.html`（报表）
- **koharu paddle 引擎坏因定案**：内置 llama.cpp b8935 太旧，mmproj/MTMD 投影初始化失败（`completed_with_errors`，ocr 全空）；同 GGUF 用 b10582 秒加载、OCR 正常 → koharu 的 paddle/mit48px OCR 引擎**不可用，弃用**（ADR-008）。
- **通用 VLM 竖排日语系统性差**（arXiv 2511.15059 + qwen-vl-ocr 实测词序错乱）→ 远程 API 基座 OCR 路线放弃（无需注入 SiliconFlow key）；GLM-OCR-Manga-LoRA 出局（无 API、需 GPU≥4GB）。
- **context7 接入**：`scripts/context7.py`（`npm run ctx7:search` / `ctx7:ctx`），读 `.env` 的 `CONTEXT7_API_KEY`，已实测通过（dogfood 查了 SiliconFlow docs）。
- 快速检查 `npm run fastcheck`（ruff+pyright+16 tests）通过。

- 工程脚手架已就位并推送（commit `854e170`、`119df6e`、`95ab73c`，origin/main 已同步）。
- CLAUDE.md v2 = 渐进式加载模型（核心事实+坑，~2k tokens）；AGENTS.md = 薄指针（避免双份漂移）。两者 DSH 均自动注入。
- 3 个 skill 已建：`benchmark` / `koharu-drive` / `verify`（.dsh/skills/，DSH 原生技能根，进 skill catalog 按需加载）。
- `src/koharu_client.py`（16 方法）+ `src/pipeline.py`（引擎 DAG 常量）+ smoke_test **PASS**。
- koharu headless 当前在 :4000 运行（--headless --cpu）。
- **Benchmark A 已实现**（`scripts/benchmark.py` 两阶段：emit crops+manifest → ingest 标注算指标；synthetic 自测 + 链路实测通过）。
- **预筛完成**：16 页原文 × 4 detector 全跑通 → **160 crops + `output/data/label_manifest.json`**（无缺失，16 页全覆盖，每页 2-19 框）。
- **Benchmark A 完成**（VLM oracle 标注 160 框 + ingest）：
  - **detection_precision = 0.963**（160 候选，6 个非文字假框）
  - 四类分布：dialogue_in 61 / dialogue_out 53 / sfx 23 / bg_text 17
  - 置信度：127 high + 33 medium，无 low
  - 6 个 FP 均为真实非文字（`!?` 反应符号、纯画面）——detector 假框少，框外字真问题在 recall（detector 均漏区域），需后续抽查
  - 产出 `output/data/benchmark_a.json`、`output/data/labels_a.json`（可复现）
- **Benchmark A recall 完成**（内容级，单翼 1-10 页 101 GT 区域）：
  - **总体 recall = 0.98**（101 检出 99）
  - 分维度：dialogue_in 1.0 / dialogue_out 1.0 / sfx 0.941 / bg_text 0.909
  - 漏检 2 处：英文服装字 "Welcome Hall!"(bg_text) + 1 个 SFX（拟声字）
  - **方法修正**：describe_image 整页坐标不可靠（裁剪验证空白）→ 改用**内容级匹配**（VLM 识别 detector 并集框内容 vs GT 内容清单，字符重合度≥0.6）
  - 产出 `output/data/recall_gt.json`、`recall_detections.json`、`recall_ocr.json`、`recall_result.json`
- **Benchmark B OCR 完成**（manga-ocr，单翼 1-10 页，路2 detector+OCR）：
  - 总体 CER 0.462 / EM 0.426（101 区域）
  - **框内对白最优**：CER 0.16 / EM 0.795；框外对白中：CER 0.45 / EM 0.27
  - **SFX 拟声词全盲**：CER 1.0 / EM 0——manga-ocr 对 SFX 输出为空（竖排/艺术字/特效字认不出）
  - **环境限制**：paddle-ocr-vl-1.5 失败（completed_with_errors，text=null）、mit48px-ocr 输出乱码/空——CPU-only 上仅 manga-ocr 可用
  - 产出 `output/data/benchmark_b.json`、`ocr_result.json`、`scripts/ocr_detect.py`、`ocr_score.py`
  - 修复 koharu_client.wait_operation 卡死 bug（未识别 completed_with_errors 状态）
- git 凭据已修：host 级 `credential.github.com.helper="!gh auth git-credential"` 绕开 GCM 弹窗（否则每次 git 操作弹账户选择框）。

## 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 脚手架 / CLAUDE.md / skills / smoke | ✅ 完成并推送 |
| 1 | Benchmark A/B/C（检测 recall / OCR CER / inpaint 评分） | 🔄 C 待做（B 已出数） |
| 1a | 预筛 16 页测试集（四 detector → 160 crops + manifest） | ✅ 完成 |
| 1b | Benchmark A precision（VLM oracle 标注 160 框） | ✅ 完成（precision 0.963） |
| 1c | Benchmark A recall（单翼 1-10 页，内容级匹配） | ✅ 完成（recall 0.98） |
| 1d | Benchmark B OCR（manga-ocr CER 0.462；Baberu SFX CER 0.181） | ✅ 完成 |
| 2 | Repair Loop / Vision QA 嵌入 pipeline | ⏳ |
| 2b | Story Memory + prompt.py + vqa() + scene 翻译 | ⏳ |
| 3 | GitHub Actions 自动触发验证循环 | ⏳ 待验证循环稳定后 |

## 已锁定决策（grill 定案，勿改）

1. 基线 = 钉 **koharu v0.59.1** headless（REST+MCP+像素 mask）；上游 0.77.5 起删 headless/HTTP/MCP，升级即失去自动化面。
2. Agent 形态 = **会话驱动**（DSH 会话=单 LLM Agent 导演；Python=确定性工具层；describe_image=Vision QA 眼睛）。
3. 第一里程碑 = **Benchmark A/B/C**（VLM 当 oracle，**零人工全量标注**——用户明确拒绝人工标注）。
4. Vision QA 通道 = **describe_image**（用户禁了 ModLens，注入 .env）。
5. 翻译通道 = **脚本直调 DeepSeek API**（`.env` CHAT_*，ADR-014；**修订原 #5**：弃 koharu 内 `llm` 引擎——not-ready 悬空）。
6. 场景级翻译**不在 MVP**（Story Memory + 前页上下文优先；Benchmark D 再定）。
7. 成功标准 = **benchmark 数据 + 失败可定位到具体模块**。
8. skills = 3 个（benchmark/koharu-drive/verify）。
9. 接口全表下沉到 koharu-drive skill；CLAUDE.md 只留一行。
10. package.json 不包 git/gh（原子操作用原生；发布流程在 verify skill）。

## 验证循环设计（新锁定，来自 Claude Code 官方博客）

- 模式 = **分层**：Benchmark A/B/C=独立（我自调度，非手动跑）+ Repair Loop=嵌入 pipeline + verify=链式发布。
- 前端/playwright：**本项目永远不需要**（判卷是 describe_image 看静态图，无浏览器自动化）。
- **调度权在我**：改了 detector/OCR/prompt 后我自记 todo 跑 benchmark，用户不碰终端。
- 稳定后才上 GitHub Actions（每次 push/PR 自动跑同一验证 skill）。

## 关键坑速查（完整经验见 docs/lessons.md）

- 坑/经验的唯一归属 = `docs/lessons.md`；CLAUDE.md 只留一行指针。
- NO_PROXY=127.0.0.1,localhost（Clash 破坏 localhost）· .ps1 含中文必须 UTF-8 带 BOM · ctd_seg 只细化已有框 · patch 后必须重跑 koharu-renderer · workers>1 崩。

## 测试集现状

- 真实源图（**未翻译原文**）已在机器上：`D:\我的汉化\output\灵梦和妹红\process\NN\page.jpg`（NN=11..26，共 16 页，2243×3465）。
- 单翼停留之地 process/ 无 page.jpg（只有 rendered.png=已翻译），**不可做 benchmark 源图**。
- 原图不入库（testsets/pages/ 已 gitignore）；ground_truth/、results/ JSON 入库。

## 下一步

0. ~~重生成 benchmark_b json（GT 对齐 + 去重 + norm 重算）~~ → **已由 86 框 OCR 评测替代完成**（ADR-011）
1. **实现 03_translate.py（ADR-014 核心工位）**：DeepSeek API 直调 + Context 组装（canon/work_state/前 3 页/open_questions）+ 双层护栏（机械：结构/残留/region_id 对应；语义：VLM 脚本验证）+ 机械 loop（schema 错自动重译 1 次）+ suggestions.json 写入。产出 translation.json。
2. **00_run_all.py 编排器 + 01_detect/02_ocr 接入 per-work 契约**：文件存在=跳过断点续跑；detection.json/canon_text.json 落 workspace/<work_id>/artifacts/。
3. **04_inpaint / 05_typeset 工位**（koharu lama-manga + renderer 验证）+ 各自 mechanical check（mask 区域像素变化/译文区渲染）。
4. **VLM 语义护栏脚本**（DASHSCOPE 通道）：crop+译文 → 忠实度/漏译判断；拦出问题标 FAILED 附证据交导演。
5. **最终验收**：final.png 整体 VLM/导演检查（日文残留/溢出/可读性）。
6. Benchmark C（mask + inpainting 评分）与 Benchmark A 框外漏检抽查（15 个未检出 GT 框，检测覆盖缺口）随工位推进穿插。
7. 结果回填本节「当前状态」并推送。
