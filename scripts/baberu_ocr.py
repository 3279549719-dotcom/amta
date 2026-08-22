"""Baberu OCR 封装：对裁剪图批量推理，输出每图文字。

基于官方 onnx_infer.py（纯 onnxruntime+numpy+PIL，无 torch）。
用法: python scripts/baberu_ocr.py <image_dir> <out.json>
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "models" / "baberu-ocr"))
from PIL import Image

from onnx_infer import BaberuOnnxOCR  # noqa: E402  # type: ignore[import-not-found]  # 运行时动态路径(models/ 不入库)

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "baberu-ocr"


def main(argv: list[str]) -> int:
    img_dir = Path(argv[0])
    out_json = Path(argv[1]) if len(argv) > 1 else ROOT / "output" / "data" / "baberu_result.json"
    vision = argv[2] if len(argv) > 2 else "vision_int4.onnx"  # int4 更小，CPU 友好
    ocr = BaberuOnnxOCR(MODEL / "onnx", MODEL / "tokenizer", vision=vision)
    results = {}
    for img in sorted(img_dir.glob("*.png")):
        try:
            text = ocr(Image.open(img))
            results[img.stem] = text
            print(f"{img.stem}: {text!r}", flush=True)
        except Exception as e:  # noqa: BLE001
            results[img.stem] = f"__ERROR__ {e}"
            print(f"{img.stem}: ERROR {e}", flush=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[baberu] {len(results)} images -> {out_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
