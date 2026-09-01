"""OCR 引擎 — Baberu-OCR（本地 ONNX，CPU 友好）。

最终选型：baberu（v2 评测 ALL CER 0.1135，比 paddle llama-server 快 ~22 倍）。
local（paddle llama-server）与 dashscope（qwen-vl-ocr）已废弃。
"""
from __future__ import annotations

import sys
from pathlib import Path

ENGINES = ("baberu",)


def _baberu_batch(crops) -> list[dict]:
    """懒加载 baberu-OCR（models/baberu-ocr/ 内嵌 onnx）。"""
    from PIL import Image

    from amta.paths import ROOT

    model_root = ROOT / "models" / "baberu-ocr"
    if not (model_root / "onnx").exists():
        raise RuntimeError("baberu-OCR 模型缺失（models/baberu-ocr/onnx）——请先下载模型")
    sys.path.insert(0, str(model_root))
    from onnx_infer import BaberuOnnxOCR  # noqa: PLC0415  # type: ignore[import-not-found]

    ocr = BaberuOnnxOCR(model_root / "onnx", model_root / "tokenizer", vision="vision_int4.onnx")
    out = []
    for p in crops:
        try:
            text = ocr(Image.open(p))
        except Exception as e:  # noqa: BLE001
            text = f"__ERROR__ {e}"
        out.append({"crop": p, "ocr": text or ""})
    return out


def ocr_batch(crops, engine: str = "baberu", **_kwargs) -> list[dict]:
    """统一 OCR 分发器（最终选型：baberu）。

    engine 参数保留仅为向后兼容，实际只走 baberu。
    """
    return _baberu_batch(crops)
