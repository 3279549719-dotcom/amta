"""AMTA 纯库包：被 scripts/ 薄 CLI 与 tests/ 引用。

对外稳定接口：
- koharu_client.KoharuClient — koharu REST 封装
- koharu_blocks.* — koharu scene 节点→文字块 纯整形（collect_blocks/排序）
- chat_client.* — OpenAI 兼容 chat/completions 深模块（翻译/OCR 共用接缝）
- translate_tools.* — 真 function calling 工具机（TOOLS_SCHEMA/预算/execute/loop）
- guardrails.* — 翻译机械护栏（结构错/日文残留）
- pipeline.* — 引擎 DAG 常量
- metrics.* — CER/EM/归一化/匹配/日文残留判据
- geometry.* — bbox/iou/并集
- runner.* — 单页流水线执行器（建项目→跑→回读→关项目）
- ocr_engines.* — OpenAI 兼容 OCR 引擎（本地 llama-server / DashScope）
- gt_alignment.* — GT→detector 框对齐裁剪
- images.* — 图片裁剪工具
- evalkit.* — CER/EM 评测聚合
- workstate.* — per-work workspace + work_state（ADR-013 产物结构）
- paths.* — 项目路径与 JSON/UTF-8 IO 工具
"""
from amta import (  # noqa: F401
    chat_client,
    evalkit,
    geometry,
    gt_alignment,
    guardrails,
    images,
    koharu_blocks,
    koharu_client,
    metrics,
    ocr_engines,
    paths,
    pipeline,
    runner,
    translate_tools,
    workstate,
)

__all__ = [
    "chat_client",
    "evalkit",
    "geometry",
    "gt_alignment",
    "guardrails",
    "images",
    "koharu_blocks",
    "koharu_client",
    "metrics",
    "ocr_engines",
    "paths",
    "pipeline",
    "runner",
    "translate_tools",
    "workstate",
]
