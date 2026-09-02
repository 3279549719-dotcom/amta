"""OCR 引擎分发器 — baberu（默认，ONNX）/ hayai（HayaiOCR-v2.1，PyTorch）/ manga_ocr（kha-white，PyTorch）。

统一接口: ocr_batch(crops, engine="baberu") -> list[{"crop": path, "ocr": text}]
模型路径可通过环境变量覆盖:
  HAYAI_OCR_MODEL  (默认 E:\\models\\hayai-ocr-v2)
  MANGA_OCR_MODEL  (默认 E:\\models\\manga-ocr-base)
"""
from __future__ import annotations

import os
import sys

ENGINES = ("baberu", "hayai", "manga_ocr")

_HAYAI_DEFAULT = r"E:\models\hayai-ocr-v2"
_MANGA_OCR_DEFAULT = r"E:\models\manga-ocr-base"


# ============================================================
# baberu (ONNX, CPU, 默认)
# ============================================================

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


# ============================================================
# HayaiOCR-v2.1 (PyTorch, SigLIP2 + transformer)
# ============================================================

_hayai_instance = None


def _get_hayai():
    global _hayai_instance
    if _hayai_instance is None:
        from hayai_ocr import HayaiOcr
        model_path = os.environ.get("HAYAI_OCR_MODEL", _HAYAI_DEFAULT)
        _hayai_instance = HayaiOcr(pretrained_model_name_or_path=model_path)
    return _hayai_instance


def _hayai_batch(crops) -> list[dict]:
    """HayaiOCR-v2.1 — 支持多行单次前向，中日韩三语。"""
    ocr = _get_hayai()
    out = []
    for p in crops:
        try:
            text = ocr(str(p))
        except Exception as e:  # noqa: BLE001
            text = f"__ERROR__ {e}"
        out.append({"crop": p, "ocr": (text or "").strip()})
    return out


# ============================================================
# manga-ocr (kha-white, TrOCR, 日语漫画专用)
# ============================================================

_manga_ocr_instance = None


def _get_manga_ocr():
    global _manga_ocr_instance
    if _manga_ocr_instance is None:
        from manga_ocr import MangaOcr
        model_path = os.environ.get("MANGA_OCR_MODEL", _MANGA_OCR_DEFAULT)
        _manga_ocr_instance = MangaOcr(pretrained_model_name_or_path=model_path)
    return _manga_ocr_instance


def _manga_ocr_batch(crops) -> list[dict]:
    """manga-ocr (kha-white/manga-ocr-base) — TrOCR 架构，日语漫画专用。"""
    ocr = _get_manga_ocr()
    out = []
    for p in crops:
        try:
            text = ocr(str(p))
        except Exception as e:  # noqa: BLE001
            text = f"__ERROR__ {e}"
        out.append({"crop": p, "ocr": (text or "").strip()})
    return out


# ============================================================
# 统一分发器
# ============================================================

_ENGINE_FN = {
    "baberu": _baberu_batch,
    "hayai": _hayai_batch,
    "manga_ocr": _manga_ocr_batch,
}


def ocr_batch(crops, engine: str = "baberu", **_kwargs) -> list[dict]:
    """统一 OCR 分发器。

    Args:
        crops: 图片路径列表
        engine: "baberu" (默认, ONNX/CPU) | "hayai" (HayaiOCR-v2.1) | "manga_ocr" (kha-white)
    """
    if engine not in _ENGINE_FN:
        raise ValueError(f"未知 OCR 引擎: {engine}，可选: {', '.join(ENGINES)}")
    return _ENGINE_FN[engine](crops)
