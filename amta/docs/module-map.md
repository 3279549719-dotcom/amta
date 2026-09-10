# AMTA 模块功能地图（自动生成）

> 由 `scripts/find_code.py --index` 自动生成。AI 找代码先看这个，再 grep。
> 更新：`uv run python scripts/find_code.py --index`

## `backends/` — amta.backends — 引擎/传输后端（本地或远程确定性执行面）。

- **`chat_client.py`** — OpenAI 兼容 chat/completions 的深模块：统一所有「POST /chat/completions + 解析 message」调用。（函数: _headers, chat, chat_text）
- **`koharu_blocks.py`** — koharu scene 节点 → 文字块 的纯结果整形（从 koharu_client 拆出的深模块）。（函数: collect_blocks, sort_by_reading_order）
- **`koharu_client.py`** — Koharu v0.59.1 REST API client — AMTA 执行器的确定性封装。（类: KoharuError, KoharuClient；函数: ensure_no_proxy）
- **`ocr_engines.py`** — OCR 引擎分发器 — baberu（默认，ONNX）/ hayai（HayaiOCR-v2.1，PyTorch）。（函数: _baberu_batch, _get_hayai, _hayai_greedy_decode_with_conf, _hayai_batch, ocr_batch）
- **`runner.py`** — koharu 流水线执行器 — 统一「建项目→传图→跑流水线→等待→回读→关项目」模式。（函数: run_pipeline_once, compact_blocks, page_key, run_all_pages）
- **`vlm_verify.py`** — VLM contact sheet 批量校验模块。（函数: make_contact_sheet, parse_vlm_output, vlm_verify_batch, vlm_verify_ocr_single）

## `common/` — amta.common — 跨阶段共享叶子库（纯通用，不依赖其他域）。

- **`config.py`** — 密钥与模型配置 — env → .env 回退唯一归属（深接口改造，修 F4 三处重复解析）。（函数: _read_key, _resolve, get_chat_config, get_vlm_api_key, get_dashscope_key）
- **`evalkit.py`** — (无 docstring)
- **`geometry.py`** — 共享几何库：bbox 解析、IoU、并集聚合、嵌套标记、category 映射。（函数: bbox_from_block, iou, union_boxes, union_blocks, _area）
- **`images.py`** — 图片工具：带 padding 的裁剪（benchmark / recall_crop / ocr_run 共用）。（函数: crop_with_pad）
- **`metrics.py`** — 共享指标库：OCR/recall 评分用的归一化、编辑距离、CER/EM 与匹配函数。（函数: contains_japanese, norm, levenshtein, cer, best_match）
- **`paths.py`** — 项目路径与公共 IO 工具 — 消除各脚本重复的 ROOT/OUTPUT/DATA 样板。（函数: ensure_output, ensure_utf8_stdio, read_json, write_json）
- **`pipeline_log.py`** — pipeline_log — 流水线 step-level tracing(借鉴 OTel span 思想,零依赖,ADR-018)。（类: PipelineLog；函数: _now, git_head）
- **`punctuation_align.py`** — 机械标点对齐（P2）：原文可删除标点数量是译文上限。（函数: _count_removable, align_punctuation）
- **`tickets.py`** — tickets — needs_review 工单机制（ADR-017，借鉴 CMMS 工单状态机 + 维修手册归档）。（类: TicketStore；函数: _now, classify_kind）
- **`workstate.py`** — per-work workspace + work_state — 产物结构 rebaseline（ADR-013）。（函数: work_dir, ensure_workspace, empty_state, init_workspace, load_state）

## `guards/` — amta.guards — 翻译机械护栏 / 术语 / VLM 裁决（Stage 3 质量面）。

- **`canon_schema.py`** — pre-translate Input schema 校验（ADR-016）— 逻辑已收编 amta.stores.artifacts（深接口改造）。
- **`glossary.py`** — Knowledge guardrail（ADR-016）：confirmed 术语译名一致性校验。（函数: check_glossary）
- **`guardrails.py`** — 翻译机械护栏 — 从 translate.py 拆出的深模块。（函数: mechanical_guardrails, japanese_residue_check, _run_guardrails_for_test）
- **`pre_scan.py`** — Pre-scan: build per-work locked terminology dictionary from all OCR text.（函数: run_pre_scan）
- **`rule_filter.py`** — 规则过滤 — OCR 后假框过滤（已废弃，保留接口兼容）。（函数: rule_filter）
- **`suggestions.py`** — suggestions 机制唯一归属（修 F5）：片假名术语提取 → 追加落盘 → 跨页合并。（类: SuggestionsExtractor；函数: append_suggestions, merge_into_state）
- **`term_dict.py`** — Term dictionary: load THBWiki master dictionary and match terms in text.（函数: load_master_dict, match_terms）
- **`term_replace.py`** — Direct term replacement: replace locked terms in source text with Chinese translations.（函数: replace_terms, replace_in_canon）
- **`vlm_filter.py`** — VLM 三态过滤 — keep(保留) / fix(修正) / drop(丢弃)。（函数: _parse_json_safe, vlm_filter_v2）

## `inpaint/` — amta.inpaint — Stage 4 去文字/重绘（lama 家族落地）。

- **`_lama_ffc.py`** — FFC (Fast Fourier Convolution) ResNet Generator — 从 BallonsTranslator 复制。（类: FourierUnit, SpectralTransform, FFC；函数: get_activation）
- **`_lama_model.py`** — (无 docstring)（类: SimpleLama）
- **`_lama_util.py`** — (无 docstring)（函数: get_image, ceil_modulo, scale_image, pad_img_to_modulo, prepare_img_and_mask）
- **`inpaint_station.py`** — inpaint 工位库函数 — detection.json + raw 页 → clean 图 + inpaint 产物(Stage 4)。（函数: _get_inpainter, _apply_fill_white, _build_mask_image, _build_mask, _pixel_diff_ratio）
- **`inpaint_strategy.py`** — Stage 4 擦除策略(纯函数,零依赖): 所有框统一走 mask+inpaint(本地 lama-manga)。（函数: plan_inpaint）
- **`local_lama_inpainter.py`** — 本地 LaMa inpainting 封装 — 支持 big-lama (TorchScript) 和 lama-manga (FFC ResNet)。（类: _LamaMangaModel, LocalLamaInpainter；函数: _find_lama_manga_path）

## `memory/` — amta.memory — agent 记忆机制包（ADR-025/027）。

- **`estate.py`** — estate — 知识地产的只读解析层。（类: Entry；函数: estate_root, read_lines, _entries_from_headers, parse_lessons, lesson_sections）
- **`gc.py`** — gc — 记忆地产自动清理（腐坏不再等人工点出来）。（函数: _read, _write, archive_today, refresh_now, prune_tmp）
- **`inject.py`** — inject — DSH 原生记忆注入：把记忆包写进 CLAUDE.local.md（随会话自动加载）。（函数: _pack, build_local_md, main）
- **`lint.py`** — lint — 记忆机制检查引擎（同引擎双入口：memory_lint --strict 门禁 / memory_status agent 自检）。（类: Finding；函数: run_checks）
- **`loop_state.py`** — loop_state — 循环接续状态（自主循环的记账本，schema v2）。（函数: path, load, plan_list, plan_progress, summarize）
- **`tools.py`** — tools — 检索操作核心：grep/read/index/recent。（类: Hit；函数: _scopes, _fmt, do_grep, _valid_re, do_read）

## `orchestrator/` — amta.orchestrator — 管线编排器（深模块）。

- **`context.py`** — 编排器统一数据契约 — StationContext / StationResult / PipelineConfig / PipelineResult。（类: StationContext, StationResult, PipelineConfig）
- **`pipeline.py`** — 管线编排器 — run_pipeline() 唯一入口。（函数: _resolve_page_list, _build_context, _stage_code_paths, _stage_input_files, _fail_result）
- **`registry.py`** — 阶段注册表 — 声明式定义每个阶段的工位函数、依赖关系、默认配置。（类: StageSpec；函数: _build_registry, _not_implemented, get_registry, get_stage, available_stages）

## `report/` — amta.report — 深接口 HTML 报告工具（ADR-024）。

- **`ab_report.py`** — ab_report — Stage4 框外字去除 A/B 对比实验报告（深接口模块）。（函数: _img_to_base64, _compute_averages, _build_table_rows, render_ab_report）
- **`align.py`** — 跨阶段区域对齐 — 优先 region_id 精确匹配，回退 bbox IoU 物理匹配。（函数: iou, match_region）
- **`assembler.py`** — 数据组装器 — 从 artifacts JSON 读取各阶段产物，组装成 PageReport。（函数: _load_json, _resolve_image, load_page_report, load_from_workspace）
- **`engine.py`** — 报告引擎 — render_report 核心实现（纯函数，零 IO，零副作用）。（函数: _load_image, _composite_overlays, _img_to_base64, _align_regions, _render_table）
- **`final_report.py`** — final_report — 三阶段流水线最终报告（自包含 HTML，内嵌原图 base64）。（函数: img_to_base64, _load_json, render_final_report）
- **`inpaint_ab_report.py`** — inpaint_ab_report — Inpainting 速度 A/B 对比报告（深接口模块）。（函数: _img_to_base64, load_summary, build_speed_table, build_speed_chart, _build_page_comparison）
- **`model.py`** — 报告工具数据模型 — PageReport / StageOutput / ReportResult + 构造校验。（类: StageOutput, PageReport, ReportResult）
- **`stage4_report.py`** — stage4_report — Stage4 mask+inpaint 逐页验证报告（深接口模块）。（函数: _img_to_b64, extract_inpaint_boxes, _render_page_section, _render_no_free_section, render_stage4_report）

## `stations/` — amta.stations — 各 Stage 顶层薄工位（脚本 CLI 对接的确定性入口）。

- **`detect_station.py`** — (无 docstring)
- **`ocr_station.py`** — Stage 2 OCR 工位 — detection + raw 页 → CanonArtifact（深模块）。（函数: _crop_by_region, _should_filter_by_conf, ocr_page）

## `stores/` — amta.stores — 产物/工件存储层。

- **`artifact_cache.py`** — Artifact Cache — 基于内容哈希的增量构建模块。（函数: compute_file_hash, compute_code_hash, compute_config_hash, compute_fingerprint, fingerprint_path）
- **`artifact_store.py`** — ArtifactStore — 目录即索引（dir-as-index）产物访问门。（类: ArtifactStore；函数: fingerprint_of, _page_no, _unlink_if_exists, _rmdir_if_empty, resolve_artifact）
- **`artifacts.py`** — (无 docstring)

## `translation/` — amta.translation — Stage 3 翻译核心（minimal 纯文本 LLM 路径，ADR-014/016/023）。

- **`stage3_minimal.py`** — Stage 3 Minimal Translation — 1 LLM call per page, zero tools, zero loops.（函数: build_semantic_context, _read_page_blocks_from_artifacts, _read_fallback_context, _format_relationships, _format_relevant_terms）
- **`translate.py`** — 纯文本翻译模块 — minimal 路径唯一实现（1 LLM call/page, zero tools）。（函数: get_chat_config, text_chat, extract_relevant_terms, parse_translation_response, parse_translation_array）
- **`translate_station.py`** — Stage 3 翻译工位 — canon → TranslationArtifact（深模块）。（函数: translate_page）

## `typeset/` — amta.typeset — Stage 5/6 排版（自研 Pillow 引擎，ADR-019/020/021）。

- **`fonts.py`** — 字体注册表(Stage 5): 4 级字体映射 + 探测 + 降级。（类: FontNotFoundError；函数: _level_for, resolve_font）
- **`typeset_engine.py`** — 排版引擎核心纯函数(Stage 5, Spec §3): 折行/避头尾/字号二分双方向选优。（函数: infer_direction_from_bbox, wrap_text, wrap_vertical, _fits, _max_size_for_direction）
- **`typeset_render.py`** — 渲染器(Stage 5): 横排居中 / 竖排多列 / 白色描边。就地绘制到 PIL Image。（函数: render_item, _render_vertical, _draw_rotated_char）
- **`typeset_station.py`** — typeset 工位库函数 — clean 图 + canon + translation + detection → final.png + typeset 产物(Stage 5)。（函数: run）

## `scripts/` — CLI 工具入口

- **`00_run_all.py`** — 00_run_all 编排器 — 断点续跑 + step tracing + 全链驱动(ADR-018)。
- **`01_detect.py`** — 01_detect 工位 CLI — 检测: raw 页 → artifacts/{page}_detection.json（薄包装）。
- **`02_ocr.py`** — 02_ocr 工位 — OCR: detection.json + raw 页 → artifacts/{page}_canon.json（薄 CLI）。
- **`03_translate.py`** — 03_translate 工位 — 读 canon → DeepSeek 翻译 → translation.json（薄 CLI）。
- **`04_inpaint.py`** — 04_inpaint 工位 CLI — detection.json + raw 页 → clean 图 + inpaint 产物（薄包装）。
- **`05_typeset.py`** — 05_typeset 工位 CLI — clean 图 + canon + translation + detection → final.png（薄包装）。
- **`apply_revisions.py`** — apply_revisions — 导演语义 loop 的修订落盘（ADR-016）。
- **`audit.py`** — audit — 轻量 Harness 熵审计（/audit 的确定性部分）。
- **`baberu_ocr.py`** — Baberu OCR 封装：对裁剪图批量推理，输出每图文字。
- **`benchmark.py`** — Benchmark A/B/C — 用数据钉死 koharu v0.59.1 的能力边界。
- **`context7.py`** — Context7 CLI wrapper — query up-to-date library documentation.
- **`depguard.py`** — depguard — 依赖膨胀守卫（vibe-check-mcp 的机械落点，ADR-015）。
- **`detect_rtdetr.py`** — RT-DETR-v2 漫画文本检测器（ONNX，CPU 友好）。
- **`detectors.py`** — 检测器统一接口 — 所有方案 A/B/C 的检测器都实现 detect(img_bgr) -> blocks。
- **`fastcheck.py`** — fastcheck — 编码期快速校验（Level 1，秒级，默认不连 koharu）。
- **`find_code.py`** — find_code — amta 代码/模块智能检索工具（深接口）。
- **`gen_ab_report.py`** — gen_ab_report — Stage4 框外字去除 A/B 对比报告 CLI（amta.report.ab_report 的薄壳）。
- **`gen_final_report.py`** — gen_final_report — 三阶段流水线最终报告 CLI（amta.report.final_report 的薄壳）。
- **`gen_inpaint_ab_report.py`** — gen_inpaint_ab_report — Inpainting 速度 A/B 对比报告 CLI（amta.report.inpaint_ab_report 的薄壳）。
- **`gen_report.py`** — gen_report — amta HTML 报告统一入口（深接口 amta.report 的薄壳 CLI）。
- **`gen_stage4_report.py`** — gen_stage4_report — Stage4 验证报告 CLI（amta.report.stage4_report 的薄壳）。
- **`hook_pretooluse.py`** — Claude Code PreToolUse hook: git commit/merge 前自动跑快速 fastcheck。
- **`hook_sessionstart.py`** — Claude Code SessionStart hook: 新会话自动加载项目状态。
- **`loop_state.py`** — loop_state CLI — 查看 / 更新循环状态（RALPH 会话、进程、人共用）。
- **`mcp_memory.py`** — mcp_memory — 记忆检索 MCP 字典工具（stdio，纯 stdlib）。
- **`memory.py`** — memory.py — 记忆系统统一 CLI（ADR-025/026/027 收敛）。
- **`memory_autoinject.py`** — memory_autoinject — UserPromptSubmit hook：按 prompt 关键词自动检索记忆并注入上下文。
- **`merge_labels.py`** — 合并各 subagent 的 labels 片段到 labels_a.json。
- **`merge_suggestions.py`** — merge_suggestions — suggestions.json → work_state 合并。
- **`pre_scan.py`** — CLI: pre-scan a work's canon artifacts to build locked terminology dictionary.
- **`ralph_context.py`** — ralph_context — Ralph Loop 的确定性上下文生成。
- **`ralph_sdk.py`** — ralph_sdk.py — Ralph Loop v5 薄壳（Claude Agent SDK 版）
- **`refactor_module.py`** — refactor_module — 批量重命名模块导入路径（深接口工具）。
- **`review.py`** — review — L6 独立 model 审核门（ADR-030）：让一个"不知道你做了什么"的第二个模型独立审 diff。
- **`run_pipeline.py`** — 管线编排器 CLI — 替代 00_run_all.py 的统一入口。
- **`run_stage4_e2e_11_20.py`** — 批量跑 11-20 页 04_inpaint（精修mask + lama-manga）。
- **`smoke_test.py`** — AMTA 冒烟测试：验证 koharu headless API 通路（建项目→传图→跑检测→读场景→关项目）。
- **`trace_probe.py`** — trace_probe — 读 claude 会话 JSONL 的轻量探针（心跳 / 卡死诊断 / trace 统计）。
- **`verify_stage4.py`** — Stage 4 端到端验证: 修复bug后跑5页, 生成原图vs clean对比报告。

---
*本文件由 find_code.py 自动生成，请勿手动编辑。*