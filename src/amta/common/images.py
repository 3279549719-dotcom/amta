"""图片工具：带 padding 的裁剪（benchmark / recall_crop / ocr_run 共用）。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image


def crop_with_pad(page: Path, bbox, dest: Path, pad: int = 8) -> bool:
    """按 [x0,y0,x1,y1] 裁剪原图并保存；越界/空框返回 False（不写文件）。"""
    img = Image.open(page).convert("RGB")
    x0, y0, x1, y1 = (max(0, int(v)) for v in bbox)
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(img.width, x1 + pad)
    y1 = min(img.height, y1 + pad)
    if x1 <= x0 or y1 <= y0:
        return False
    img.crop((x0, y0, x1, y1)).save(dest)
    return True
