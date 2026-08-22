# AMTA 项目进度（外部持久化记忆 / 交接文档）

> 本文件是**项目状态的唯一事实来源**，任何 AI（Claude Code / Cursor / DSH / 未来 agent）接手第一件事先读它。
> 与 hindsight（DSH 会话内记忆）互补：hindsight 是会话内快速召回，本文件是工具无关的交接文档。
> 每次完成任务后更新本节「当前状态」与「下一步」。

## 一句话

会话驱动漫画翻译自动化：**DSH 会话=导演，amta Python=确定性执行器，koharu v0.59.1 headless(:4000)=引擎**。第一里程碑：Benchmark A/B/C 定量钉死能力边界。

## 当前状态（2026-07，最后一笔：第二轮 OCR 测评完成）

- **第二轮 OCR 测评完成（本会话）**：框外对白 OCR 换引擎——**PaddleOCR-VL-For-Manga**（本地 GGUF + 独立 llama-server b10582，端口 8118）全量 126 crops 实测：
  - **dialogue_out（框外对白）：CER 0.453 → 0.037 / EM 0.265 → 0.667**（主目标达成，远超预期）
  - dialogue_in：CER 0.16 → 0.103；sfx：1.0 → 0.15；bg_text：0.727 → 0.038；ALL：0.462 → 0.316
  - 证据：`output/data/benchmark_b_paddle_manga.json`（126 rows 全量）+ `output/reports/benchmark_b_paddle_manga_report.html`（报表）
- **koharu paddle 引擎坏因定案**：内置 llama.cpp b8935 太旧，mmproj/MTMD 投影初始化失败（`completed_with_errors`，ocr 全空）；同 GGUF 用 b10582 秒加载、OCR 正常 → koharu 的 paddle/mit48px OCR 引擎**不可用，弃用**（ADR-008）。
- **通用 VLM 竖排日语系统性差**（arXiv 2511.15059 + qwen-vl-ocr 实测词序错乱）→ 远程 API 基座 OCR 路线放弃（无需注入 SiliconFlow key）；GLM-OCR-Manga-LoRA 出局（无 API、需 GPU≥4GB）。
- **context7 接入**：`scripts/context7.py`（`npm run ctx7:search` / `ctx7:ctx`），读 `.env` 的 `CONTEXT7_API_KEY`，已实测通过（dogfood 查了 SiliconFlow docs）。
- 快速检查 `npm run fastcheck`（ruff+pyright+16 tests）通过。

- 工程脚手架已就位并推送（commit `854e170`、`119df6e`、`95ab73c`，origin/main 已同步）。
- CLAUDE.md v2 = 渐进式加载模型（核心事实+坑，~2k tokens）；AGENTS.md = 薄指针（避免双份漂移）。两者 DSH 均自动注入。
- 3 个 skill 已建：`benchmark` / `koharu-drive` / `verify`（.claude/skills/，按需加载）。
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
5. 翻译通道 = koharu 内 `llm` 引擎（做法 1，systemPrompt 注入 Story Memory）。
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

1. **将 PaddleOCR-VL-For-Manga 接入 pipeline**（repair loop 用）：独立 llama-server:8118 是常驻服务，需 start/stop 脚本 + `src/` OCR 封装（当前是 output/ 下的测评脚本，未正式化）。
2. Benchmark C（mask + lama-manga inpainting 区域评分）。
3. Benchmark A 框外漏检（真 recall）人工抽查 detector 均漏区域——detector 假框少(precision 0.963)，重点转向 recall。
4. 结果回填本节「当前状态」并推送。
