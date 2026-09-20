# AMTA 模块功能地图（自动生成）

> 由 `scripts/peek.py --index` 自动生成。AI 找代码先看这个，再 grep。
> 更新：`uv run python scripts/peek.py --index`

## `backends/` — amta.backends — 引擎/传输后端（本地或远程确定性执行面）。

- **`chat_client.py`** — OpenAI 兼容 chat/completions 的深模块：统一所有「POST /chat/completions + 解析 message」调用。（函数: _headers, chat, chat_text）
- **`ocr_engines.py`** — OCR 引擎分发器 — baberu（默认，ONNX）/ hayai（HayaiOCR-v2.1，PyTorch）。（函数: _baberu_batch, _get_hayai, _hayai_greedy_decode_with_conf, _hayai_batch, ocr_batch）
- **`vlm_verify.py`** — VLM contact sheet 批量校验模块。（函数: make_contact_sheet, parse_vlm_output, vlm_verify_batch, vlm_verify_ocr_single）

## `common/` — amta.common — 跨阶段共享叶子库（纯通用，不依赖其他域）。

- **`config.py`** — 密钥与模型配置 — env → .env 回退唯一归属（深接口改造，修 F4 三处重复解析）。（函数: _read_key, _resolve, get_chat_config, get_vlm_api_key, get_dashscope_key）
- **`encoding.py`** — encoding — Windows 编码收口：跨边界文本只在这里处理一次。（类: TextResult；函数: _decode, run_text, run_text_or, force_utf8_stdio）
- **`environment.py`** — 环境自检门卫 — 管线启动前自动检查并修复环境问题。（函数: _check_proxy, _check_root, _check_models, _check_env, run_environment_check）
- **`geometry.py`** — 共享几何库：bbox 解析、IoU、并集聚合、嵌套标记、category 映射。（函数: bbox_from_block, iou, union_boxes, union_blocks, _area）
- **`images.py`** — 图片工具：带 padding 的裁剪（benchmark / recall_crop / ocr_run 共用）。（函数: crop_with_pad）
- **`metrics.py`** — 共享指标库：OCR/recall 评分用的归一化、编辑距离、CER/EM 与匹配函数。（函数: contains_japanese, norm, levenshtein, cer, best_match）
- **`paths.py`** — 项目路径与公共 IO 工具 — 消除各脚本重复的 ROOT/OUTPUT/DATA 样板。（函数: ensure_output, ensure_utf8_stdio, read_json, write_json）
- **`pipeline_log.py`** — pipeline_log — 流水线 step-level tracing(借鉴 OTel span 思想,零依赖,ADR-018)。（类: PipelineLog；函数: _now, git_head）
- **`state_manager.py`** — state_manager — 对话状态管理（合并 context-bootstrap + finisher）。（类: StateSnapshot, StateManager, GitCommandFailed；函数: quality_gate_command, _run_quality_gate, finish_verified）
- **`tickets.py`** — tickets — needs_review 工单机制（ADR-017，借鉴 CMMS 工单状态机 + 维修手册归档）。（类: TicketStore；函数: _now, classify_kind）
- **`workstate.py`** — per-work workspace + work_state — 产物结构 rebaseline（ADR-013）。（函数: work_dir, ensure_workspace, empty_state, init_workspace, load_state）

## `guards/` — amta.guards — 翻译机械护栏 / 术语 / VLM 裁决（Stage 3 质量面）。

- **`canon_schema.py`** — pre-translate Input schema 校验（ADR-016）— 逻辑已收编 amta.stores.artifacts（深接口改造）。
- **`glossary.py`** — Knowledge guardrail（ADR-016）：confirmed 术语译名一致性校验。（函数: check_glossary）
- **`guardrails.py`** — 翻译机械护栏 — 从 translate.py 拆出的深模块。（函数: mechanical_guardrails, japanese_residue_check, _run_guardrails_for_test）
- **`pre_scan.py`** — Pre-scan: build per-work locked terminology dictionary from all OCR text.（函数: run_pre_scan）
- **`suggestions.py`** — suggestions 机制唯一归属（修 F5）：片假名术语提取 → 追加落盘 → 跨页合并。（类: SuggestionsExtractor；函数: append_suggestions, merge_into_state）
- **`term_dict.py`** — Term dictionary: load THBWiki master dictionary and match terms in text.（函数: load_master_dict, match_terms）
- **`term_replace.py`** — Direct term replacement: replace locked terms in source text with Chinese translations.（函数: replace_terms, replace_in_canon）
- **`vlm_filter.py`** — VLM 三态过滤 — keep(保留) / fix(修正) / drop(丢弃)。（函数: _parse_json_safe, vlm_filter_v2）

## `inpaint/` — amta.inpaint — Stage 4 去文字/重绘（lama 家族落地）。

- **`_lama_ffc.py`** — FFC (Fast Fourier Convolution) ResNet Generator — 从 BallonsTranslator 复制。（类: FourierUnit, SpectralTransform, FFC；函数: get_activation）
- **`_lama_model.py`** — (无 docstring)（类: SimpleLama）
- **`_lama_util.py`** — (无 docstring)（函数: get_image, ceil_modulo, scale_image, pad_img_to_modulo, prepare_img_and_mask）
- **`inpaint_station.py`** — inpaint 工位库函数 — detection.json + raw 页 → clean 图 + inpaint 产物(Stage 4)。（函数: _get_inpainter, _apply_fill_white, _build_mask_image, _build_mask, _route_by_uniformity）
- **`inpaint_strategy.py`** — Stage 4 擦除策略(纯函数,零依赖): 所有框统一走 mask+inpaint(本地 lama-manga)。（函数: plan_inpaint）
- **`local_lama_inpainter.py`** — 本地 LaMa inpainting 封装 — 支持 big-lama (TorchScript) 和 lama-manga (FFC ResNet)。（类: _LamaMangaModel, LocalLamaInpainter；函数: _find_lama_manga_path）

## `memory/` — amta.memory — agent 记忆机制包（ADR-025/027）。

- **`estate.py`** — estate — 知识地产的只读解析层。（类: Entry；函数: estate_root, read_lines, _entries_from_headers, parse_lessons, lesson_sections）
- **`gc.py`** — gc — 记忆地产自动清理（腐坏不再等人工点出来）。（函数: _read, _write, archive_today, refresh_now, prune_tmp）
- **`inject.py`** — inject — DSH 原生记忆注入：把记忆包写进 CLAUDE.local.md（随会话自动加载）。（函数: _pack, build_local_md, main）
- **`lint.py`** — lint — 记忆机制检查引擎（同引擎双入口：memory_lint --strict 门禁 / memory_status agent 自检）。（类: Finding；函数: is_historical_note, run_checks）
- **`tools.py`** — tools — 检索操作核心：grep/read/index/recent。（类: Hit；函数: _scopes, _fmt, do_grep, _valid_re, do_read）

## `orchestrator/` — amta.orchestrator — 管线编排器（深模块）。

- **`context.py`** — 编排器统一数据契约 — StationContext / StationResult / PipelineConfig / PipelineResult。（类: StationContext, StationResult, PipelineConfig）
- **`pipeline.py`** — 管线编排器 — run_pipeline() 唯一入口。（函数: _resolve_page_list, _build_context, _stage_code_paths, _stage_input_files, _fail_result）
- **`quality_audit.py`** — quality_audit — 跑后质量体检聚合（红榜）。（类: PageFlags；函数: audit_page, audit_run, format_redlist, _load_json）
- **`registry.py`** — 阶段注册表 — 声明式定义每个阶段的工位函数、依赖关系、默认配置。（类: StageSpec；函数: _build_registry, _not_implemented, get_registry, get_stage, available_stages）

## `report/` — amta.report — 深接口 HTML 报告工具（ADR-024）。

- **`align.py`** — 跨阶段区域对齐 — 优先 region_id 精确匹配，回退 bbox IoU 物理匹配。（函数: iou, match_region）
- **`assembler.py`** — 数据组装器 — 从 artifacts JSON 读取各阶段产物，组装成 PageReport。（函数: _load_json, _resolve_image, load_page_report, load_from_workspace）
- **`engine.py`** — 报告引擎 — 深接口渲染原语 + 薄封装入口。（函数: _load_image, _composite_overlays, _img_to_base64, _align_regions, _compute_stats）
- **`model.py`** — 报告工具数据模型 — PageReport / StageOutput / ReportResult + 构造校验。（类: StageOutput, PageReport, ReportResult）

## `stations/` — amta.stations — 各 Stage 顶层薄工位（脚本 CLI 对接的确定性入口）。

- **`detect_station.py`** — (无 docstring)
- **`ocr_station.py`** — (无 docstring)

## `stores/` — amta.stores — 产物/工件存储层。

- **`artifact_cache.py`** — Artifact Cache — 基于内容哈希的增量构建模块。（函数: compute_file_hash, compute_code_hash, compute_config_hash, compute_fingerprint, fingerprint_path）
- **`artifacts.py`** — (无 docstring)

## `translation/` — amta.translation — Stage 3 翻译核心（minimal 纯文本 LLM 路径，ADR-014/016/023）。

- **`stage3_minimal.py`** — Stage 3 Minimal Translation — 1 LLM call per page, zero tools, zero loops.（函数: build_semantic_context, _read_page_blocks_from_artifacts, _read_fallback_context, _format_relationships, _format_relevant_terms）
- **`translate.py`** — 纯文本翻译模块 — minimal 路径唯一实现（1 LLM call/page, zero tools）。（函数: get_chat_config, text_chat, extract_relevant_terms, parse_translation_response, parse_translation_array）
- **`translate_station.py`** — Stage 3 翻译工位 — canon → TranslationArtifact（深模块）。（函数: translate_page）

## `typeset/` — amta.typeset — Stage 5/6 排版（自研 Pillow 引擎，ADR-019/020/021）。

- **`fonts.py`** — 字体注册表(Stage 5): 4 级字体映射 + 探测 + 降级。（类: FontNotFoundError；函数: _level_for, resolve_font）
- **`typeset_engine.py`** — 排版引擎核心纯函数(Stage 5, Spec §3): 折行/避头尾/字号二分双方向选优。（函数: compute_base_font_size, infer_direction_from_bbox, break_lines, wrap_text, wrap_vertical）
- **`typeset_render.py`** — 渲染器(Stage 5): 横排居中 / 竖排多列 / 白色描边。就地绘制到 PIL Image。（函数: _decide_color_and_stroke, render_item, _normalize_text_for_render, _font_for_char, _paste_glyph_centered）
- **`typeset_station.py`** — typeset 工位库函数 — clean 图 + canon + translation + detection → final.png + typeset 产物(Stage 5)。（函数: run）
- **`vertical_punct.py`** — 竖排标点处理（接口层）：按 Unicode 标准自动推导，不针对具体字符硬编码。（函数: verticalize_text, should_rotate）

## `scripts/` — CLI 工具入口

- **`artifact.py`** — artifact — 统一产物管理 CLI（深接口版）。
- **`context7.py`** — Context7 CLI wrapper — query up-to-date library documentation.
- **`depguard.py`** — depguard — 依赖膨胀守卫（vibe-check-mcp 的机械落点，ADR-015）。
- **`detect_rtdetr.py`** — RT-DETR-v2 漫画文本检测器（ONNX，CPU 友好）。
- **`detectors.py`** — 检测器统一接口 — 所有方案 A/B/C 的检测器都实现 detect(img_bgr) -> blocks。
- **`fastcheck.py`** — fastcheck — 机械质检（分层：--quick 秒级 / 默认完整 9 步）。
- **`gen_report.py`** — gen_report — amta HTML 报告统一入口（深接口模式）。
- **`memory.py`** — memory.py — 记忆系统统一 CLI（ADR-025/026/027 收敛）。
- **`peek.py`** — peek — 看一眼这个项目现在长什么样：管线全貌 + 模块地图。
- **`pre_scan.py`** — CLI: pre-scan a work's canon artifacts to build locked terminology dictionary.
- **`refactor_module.py`** — refactor_module — 批量重命名模块导入路径（深接口工具）。
- **`run_pipeline.py`** — 管线编排器 CLI — 替代 00_run_all.py 的统一入口。
- **`share_file.py`** — 一键上传本地文件到飞书云空间并生成公网链接。
- **`state.py`** — state — StateManager 的 CLI 入口（Embedded 模式）。

---
*本文件由 peek.py 自动生成，请勿手动编辑。*