"""AMTA 纯库包：被 scripts/ 薄 CLI 与 tests/ 引用。

对外稳定接口（全量模块导出，refactor/modular-architecture 起补齐）：
- koharu_client.KoharuClient — koharu REST 封装
- koharu_blocks.* — koharu scene 节点→文字块 纯整形（collect_blocks/排序）
- chat_client.* — OpenAI 兼容 chat/completions 深模块（翻译/OCR 共用接缝）
- chat_config.* — CHAT_* 配置读取（环境变量/.env 接缝）
- translate.* — 翻译编排（三借鉴机制 + Context 组装 + translate_with_retry）
- translate_tools.* — 真 function calling 工具机（TOOLS_SCHEMA/预算/execute/loop）
- guardrails.* — 翻译机械护栏（结构错/日文残留）
- canon_schema.* — pre-translate Input schema gate
- glossary.* — Glossary Validator（Knowledge guardrail）
- pipeline.* — 引擎 DAG 常量
- pipeline_log.* — step tracing 执行日志（ADR-018）
- metrics.* — CER/EM/归一化/匹配/日文残留判据
- geometry.* — bbox/iou/并集（纯几何原语）
- regions.* — 区域契约层（region 构建/嵌套标记/主次分级/分类/展平）
- runner.* — 单页流水线执行器（建项目→跑→回读→关项目）
- ocr_engines.* — OpenAI 兼容 OCR 引擎（本地 llama-server / DashScope）
- gt_alignment.* — GT→detector 框对齐裁剪
- images.* — 图片裁剪工具
- evalkit.* — CER/EM 评测聚合
- workstate.* — per-work workspace + work_state（ADR-013 产物结构）
- tickets.* — needs_review 工单状态机（ADR-017）
- page_judge.* / stage3_planner.* / stage3_planner_vision.* / vlm_verify.* — 页判定 / Stage3 规划 / Vision QA
- inpaint_strategy.* / fonts.* / typeset_engine.* / typeset_render.* — Stage 4-6（ADR-019/020/021）
- paths.* — 项目路径与 JSON/UTF-8 IO 工具
"""
from amta import (  # noqa: F401
    canon_schema,
    chat_client,
    chat_config,
    evalkit,
    fonts,
    geometry,
    glossary,
    gt_alignment,
    guardrails,
    images,
    inpaint_strategy,
    koharu_blocks,
    koharu_client,
    metrics,
    ocr_engines,
    page_judge,
    paths,
    pipeline,
    pipeline_log,
    regions,
    runner,
    stage3_planner,
    stage3_planner_vision,
    tickets,
    translate,
    translate_tools,
    typeset_engine,
    typeset_render,
    vlm_verify,
    workstate,
)

__all__ = [
    "canon_schema",
    "chat_client",
    "chat_config",
    "evalkit",
    "fonts",
    "geometry",
    "glossary",
    "gt_alignment",
    "guardrails",
    "images",
    "inpaint_strategy",
    "koharu_blocks",
    "koharu_client",
    "metrics",
    "ocr_engines",
    "page_judge",
    "paths",
    "pipeline",
    "pipeline_log",
    "regions",
    "runner",
    "stage3_planner",
    "stage3_planner_vision",
    "tickets",
    "translate",
    "translate_tools",
    "typeset_engine",
    "typeset_render",
    "vlm_verify",
    "workstate",
]
