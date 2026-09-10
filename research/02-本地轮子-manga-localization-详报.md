# 本地轮子 manga-localization 详报（subagent 3 完整报告）

> 来源：`F:\opencode data\projects\manga-localization` 深度盘点（subagent 54f230f3 最终报告全文归档）
> 与主报告 `01-调研报告与集成编排方案.md` §3 互为补充。

## (a) 目的与范围
东方同人漫画日译中本地化工具链，围绕 Koharu（mayocream/koharu，自带 OCR/LLM/inpaint/render 的汉化引擎，headless HTTP 服务）做包装与编排。从「上下文注入 wrapper」（解决单气泡孤立翻译导致的人名不一致、跨页不连贯）演进为完整批量引擎：角色预扫描、批量并发翻译、断点续传、质量检查与自动修正、翻译记忆、后编辑重渲染、Flask Web UI、OCR 验收。

**真实使用**：2026-06-29 用 `src/manga_translator.py` 全量跑完《单翼停留之地》41 页（40 成功 1 失败，约 2h20m）；另有《灵梦和妹红》《幻想乡居民们的赚钱大法！》等试跑。工程痕迹：`.omo/evidence/`（18+ 任务记录）、loop bus runbook、audit 报告。

## (b) 技术栈
- Python 3.12/3.13/3.14 共存（实际用 `%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe`，`src/ocr_env.py:18-20`）；依赖 requests/tqdm/Pillow/pytesseract/Flask；**无 requirements.txt/pyproject.toml**；`.venv-manga` 空壳。
- Koharu headless `127.0.0.1:4000`（外部只读 `D:\我的汉化\workflow\`）；LLM = DashScope/Qwen(qwen-plus)，key 在 `F:\clip analyzation\.env`。
- 验收 OCR = Koharu 内置 paddle-ocr-vl-1.5（GGUF）；Tesseract 仅诊断（MANGA_CLAW_RUNBOOK.md：「Tesseract — diagnostics only, not acceptance」）。
- 环境坑：Clash 代理下 localhost 502，必须 `NO_PROXY=127.0.0.1,localhost`（`koharu_context_wrapper.py:21-30` 自动设置）。

## (c) Pipeline 各阶段
Koharu 内部 steps（`manga_translator.py:54-63`）：
`pp-doclayout-v3 → comic-text-detector-seg → speech-bubble-segmentation → yuzumarker-font-detection → manga-ocr → llm → lama-manga → koharu-renderer`

OCR/inpainting/排版渲染全由 Koharu 完成，本项目只做编排/prompt 注入/结果回读/后处理。对外只调：`POST /projects`、`POST /pages`、`POST /pipelines`（body 带 systemPrompt/targetLanguage:"zh"/defaultFont:"SimHei"）、`GET /operations` 轮询、`GET /scene.json` 读回、`POST /projects/current/export`（zip 解包）。

项目侧流程：
1. **启动**：`scripts/start_koharu.ps1`（`--headless --cpu`）+ 配 DashScope LLM + 健康检查。
2. **角色预扫描**（`src/cast_scanner.py`）：OCR-only steps 并发扫所有页 → 聚合 OCR → LLM 结构化抽取角色/术语（`EXTRACTION_SYSTEM_PROMPT` L44-66）→ 失败回退正则 + 东方角色库 `context/_touhou_database.json` 交叉引用 → 候选 cast JSON 供人工审核。
3. **批量翻译**（`src/manga_translator.py`）：逐页「建项目→传图→全流水线（带 systemPrompt）→轮询（1200s）→读 scene.json→collect_blocks→sort_blocks_by_reading_order→导出 rendered.png+page.psd→写 text_layout.json/translation_report.json→PSD 后处理→progress.json→回填 TM」。并发 ThreadPoolExecutor（默认 2；AGENTS.md 警告 CPU/集显下 >1 worker 会 Vulkan ConnectionReset 10054），progress.json 断点续传（`--resume`），指数退避重试（1s→2s→4s，最多 3 次），页间共享 dict 传前页上下文。
4. **译后质量检查**（`src/quality_checker.py`）：人名一致性（OCR 日文名 ↔ cast name_zh，≥2 字子串）、低置信度（<0.7）、空翻译、术语合规；可自动 string_replace 修正并写 `name_fixes.json`。
5. **后编辑/重渲染**（`post_edit.py`/`rerender_from_report.py`）：重传原图 → 只跑 detect+inpaint → 用 text_layout.json 空间 IoU（阈值 0.12）把译文 patch 到 scene（`POST /history/apply`，OCR 字符串匹配 fallback）→ **必须重跑 koharu-renderer**（否则导出缓存旧位图，踩过的坑）→ 导出。
6. **同步**（`sync_final_from_process.py`）：`process/{NN}/rendered.png → final/{NN}.png`、`page.psd → psd/{NN}.psd`。
7. **验收**：Tesseract 版 `verify_image_translation.py`（诊断）；权威版 `verify_koharu_acceptance.py`（渲染空检查 + scene 回放 + paddle-ocr-vl-1.5 逐 region OCR 对比）。
8. **质量审计**（`quality_audit.py`）：files / erase（像素方差启发式）/ accuracy / names / bubble_type 五项，`--check all` 出 summary_report.json。

## (d) 输入/输出格式与目录约定
- 输入：整页图片目录（整数编号文件名，自然排序）；或 `process/{NN}`（需带 source 路径的 layout/report）。
- **cast JSON schema**（`context/gensokyo_cast.json`）：`series_title / series_title_zh / genre / characters[{name, name_zh, honorifics, honorifics_zh, personality_notes}] / glossary[{term, term_zh, notes}] / context_pages[]`
- 输出根 `D:\我的汉化\output\{系列名}\`：
  - `process/{NN}/`：rendered.png、page.psd、translation_report.json（blocks: block_id/node_id/ocr/translation/confidence/transform/bubble_type/model_name）、text_layout.json、system_prompt.txt、pipeline_log.json、diagnostic_block_map.json
  - `final/{NN}.png`、`psd/{NN}.psd`、progress.json（{completed:[], failed:{}}）、batch_summary.json、quality_report.json、name_fixes.json、rerender_summary.json、sync_summary.json、verification_summary.json、audit_report.json
- **翻译记忆** `context/translation_memory.json`：`entries[{source_hash(md5), source, translation, pages[], confidence}]`，上限 500 条。

## (e) 运行方式
- CLI 主入口：`python src/manga_translator.py <输入图片目录> --cast-json context/{系列}_cast.json --pages 9-15 --workers 1 --resume --output "D:\我的汉化\output\{系列}"`
- 一键：`scripts/run_complete_workflow.ps1 -OutputRoot ...`（start→translate|rerender→sync→verify）；`scripts/rerender_sync_verify.ps1`
- Web UI：`cd src/web && python app.py` → `http://127.0.0.1:5000`（Flask + SSE 进度；作品设置/角色管理/翻译控制/质量看板四 tab）
- 前置：Koharu 4000 端口运行、LLM ready、NO_PROXY。

## (f) 可用 vs 破损
**可用（真实产出）**：41 页全量批跑（40/41，page 05 超时 600s×3 失败）；context wrapper 全套 API 集成（README「未实现」是过时注释）；阅读顺序排序、bubble_type 分类、scene 回读、zip 解包、PSD 后处理、TM 写入 prompt；布局 IoU 重渲染修复空白气泡；cast 预扫描 + 角色库交叉引用；quality_checker/audit 可跑。

**破损/坑**：零 TODO/FIXME 注释，状态全记在过时文档里（README L27/L39、STATUS.md「POST /pipelines 未实现」、AGENTS.md「TM NOT YET WIRED」均过时）；Claw 试跑 CLI: FAILED（shell tool 拒绝，验收链当时没跑成）；`verify_koharu_acceptance.py:14-23` 依赖外部 `D:\我的汉化\scripts` 无法独立跑；大量硬编码绝对路径；根目录 7 个乱码废稿脚本勿用；`quality_audit.check_names` 是 stub、`check_erase` 是粗像素启发式；page 05 超时；`--workers>1` CPU/集显崩。

## (g) 可复用清单（新 agent 直接抄）
1. **Koharu HTTP API 集成层**（`koharu_context_wrapper.py:253-341`）——最直接可搬
2. **Prompt 工程**（`build_system_prompt` L100-194）：角色表+术语表+前页上下文（≤3000 字符）+ 人名强制规则 + bubble_type + TM 注入
3. **阅读顺序排序**（y 升序、同行 x 降序）与 **bubble_type 推断**（`collect_blocks_from_scene:344-388`）
4. **批量编排**：自然排序、progress.json 续传、并发+页间上下文、指数退避、pipeline_log 计时、batch_summary
5. **翻译记忆**（`translation_memory.py`）：md5 + difflib 模糊匹配 + 从 report 重建
6. **重渲染/后编辑流**（IoU 0.12 匹配优先 + OCR 兜底）；教训：patch 后必须重跑 renderer
7. **质量检查**：人名一致性、术语、低置信/空翻译、自动改名
8. **cast schema + 预扫描 LLM 抽取 prompt** + 角色库交叉引用
9. **OCR 文本归一化**（全角标点/省略号，U+FF0E 坑已修）
10. **目录/产物约定**（process/final/psd + translation_report.json schema）
11. **约束经验**：CPU/集显 workers=1；NO_PROXY；PIPELINE_TIMEOUT 600–1200s + 3 次重试；LLM ready 检查；SimHei 默认字体

**不建议复用**：乱码废稿脚本；Tesseract 作验收；硬编码路径；过时文档。
