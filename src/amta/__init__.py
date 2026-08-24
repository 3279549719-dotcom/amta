"""AMTA 纯库包：被 scripts/ 薄 CLI 与 tests/ 引用。

对外稳定接口：
- koharu_client.KoharuClient — koharu REST 封装
- pipeline.* — 引擎 DAG 常量
- metrics.* — CER/EM/归一化/匹配
- geometry.* — bbox/iou/并集
- runner.* — 单页流水线执行器（建项目→跑→回读→关项目）
- ocr_engines.* — OpenAI 兼容 OCR 引擎（本地 llama-server / DashScope）
- gt_alignment.* — GT→detector 框对齐裁剪
- images.* — 图片裁剪工具
- evalkit.* — CER/EM 评测聚合
- paths.* — 项目路径与 JSON/UTF-8 IO 工具
"""
from amta import (  # noqa: F401
    evalkit,
    geometry,
    gt_alignment,
    images,
    koharu_client,
    metrics,
    ocr_engines,
    paths,
    pipeline,
    runner,
)

__all__ = [
    "evalkit",
    "geometry",
    "gt_alignment",
    "images",
    "koharu_client",
    "metrics",
    "ocr_engines",
    "paths",
    "pipeline",
    "runner",
]
