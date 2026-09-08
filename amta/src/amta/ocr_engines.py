"""OCR 引擎分发器 — baberu（默认，ONNX）/ hayai（HayaiOCR-v2.1，PyTorch）。

统一接口: ocr_batch(crops, engine="baberu") -> list[{"crop": path, "ocr": text}]
模型路径可通过环境变量覆盖:
  HAYAI_OCR_MODEL  (默认 E:\\models\\hayai-ocr-v2)
"""
from __future__ import annotations

import os
import sys

ENGINES = ("baberu", "hayai")

_HAYAI_DEFAULT = r"E:\models\hayai-ocr-v2"


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
        except Exception:  # noqa: BLE001
            # OCR 崩溃 → 空串（合法结果，下游按"乱码/空框"处理）；
            # 绝不把报错信息当日文原文送翻译制造垃圾数据（Q4）
            text = ""
        out.append({"crop": p, "ocr": text or ""})
    return out


# ============================================================
# HayaiOCR-v2.1 (PyTorch, SigLIP2 + transformer)
# ============================================================

_hayai_instance = None


def _get_hayai():
    global _hayai_instance
    if _hayai_instance is None:
        # 强制离线：hayai v2 内部硬编码 AutoProcessor.from_pretrained("google/siglip2-..."),
        # 会联网拉 processor_config.json（hub 上不存在，429 重试浪费 3 分钟）。
        # 本地缓存已有 preprocessor_config.json，离线模式下 AutoProcessor 会 fallback 到它。
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
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
            res = ocr(str(p))
            # HayaiOCR 类型标注为 list[str]（多行）；单 crop 也可能直接给 str。都归一成 str。
            parts = res if isinstance(res, list) else [res]
            text = "".join(parts)
        except Exception:  # noqa: BLE001
            # 同 baberu：崩溃 → 空串，不把报错信息当 OCR 文本（Q4）
            text = ""
        out.append({"crop": p, "ocr": text.strip()})
    return out


# ============================================================
# 统一分发器
# ============================================================

_ENGINE_FN = {
    "baberu": _baberu_batch,
    "hayai": _hayai_batch,
}


def ocr_batch(crops, engine: str = "baberu") -> list[dict]:
    """统一 OCR 分发器。

    Args:
        crops: 图片路径列表
        engine: "baberu" (默认, ONNX/CPU) | "hayai" (HayaiOCR-v2.1)
    """
    if engine not in _ENGINE_FN:
        raise ValueError(f"未知 OCR 引擎: {engine}，可选: {', '.join(ENGINES)}")
    return _ENGINE_FN[engine](crops)
