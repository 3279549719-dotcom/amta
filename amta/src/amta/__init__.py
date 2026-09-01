"""AMTA 纯库包：被 scripts/ 薄 CLI 与 tests/ 引用。

最终选型三阶段：
- 检测: RT-DETR-v2（scripts/detect_rtdetr.py，ONNX）
- OCR: baberu-OCR（src/amta/ocr_engines.py + ocr_station.py，本地 ONNX）
- 翻译: v2 三态（stage3_minimal.py：qwen VLM + deepseek flash LLM + keep/fix/drop + 上下文 + 术语）

对外稳定接口：
- chat_client.* — OpenAI 兼容 chat/completions 深模块（翻译共用接缝）
- translate.* — minimal 纯文本翻译（LLM 调用）
- stage3_minimal.* — Stage 3 minimal 翻译实现（VLM 三态 + LLM + 上下文 + 术语）
- translate_station.* — 翻译工位薄封装
- ocr_engines.* — baberu-OCR 引擎（本地 ONNX）
- ocr_station.* — OCR 工位（裁框 → baberu → canon）
- guardrails.* — 翻译机械护栏（结构错/日文残留）
- metrics.* — CER/EM/归一化/匹配/日文残留判据
- geometry.* — bbox/iou/并集
- images.* — 图片裁剪工具
- evalkit.* — CER/EM 评测聚合
- workstate.* — per-work workspace + work_state（ADR-013 产物结构）
- paths.* — 项目路径与 JSON/UTF-8 IO 工具
- artifacts.* — 产物读写（detection/canon/translation）
- config.* — 密钥与模型配置（env → .env 回退）
- pipeline_log.* — 流水线 step tracing
"""
from amta import (  # noqa: F401
    artifacts,
    chat_client,
    config,
    evalkit,
    geometry,
    guardrails,
    images,
    metrics,
    ocr_engines,
    ocr_station,
    paths,
    pipeline_log,
    rule_filter,
    stage3_minimal,
    translate,
    translate_station,
    workstate,
)

__all__ = [
    "artifacts",
    "chat_client",
    "config",
    "evalkit",
    "geometry",
    "guardrails",
    "images",
    "metrics",
    "ocr_engines",
    "ocr_station",
    "paths",
    "pipeline_log",
    "rule_filter",
    "stage3_minimal",
    "translate",
    "translate_station",
    "workstate",
]
