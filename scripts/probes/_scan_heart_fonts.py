"""一次性探针：扫描 C:/Windows/Fonts，用像素对比法找真有 ♡(U+2661) 字形的字体。

判据：渲染 U+E000（私用区，任何字体都没有）= .notdef 空框基准。
♡ 若与基准几乎一致 → 也是空框；若差异显著 → 是真字形。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path("C:/Windows/Fonts")
SIZE = 64
CANVAS = 100
HEART = "\u2661"
NOTDEF = "\uE000"  # 私用区，必为 .notdef


def _ink_mask(font_path: Path, ch: str) -> np.ndarray | None:
    try:
        font = ImageFont.truetype(str(font_path), SIZE)
        img = Image.new("L", (CANVAS, CANVAS), 255)
        d = ImageDraw.Draw(img)
        d.text((20, 20), ch, font=font, fill=0)
        arr = np.array(img)
        return (arr < 128).astype(np.uint8)
    except Exception:
        return None


def _diff_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """两图黑像素的差异比例（越高越不像）。"""
    if a is None or b is None:
        return 1.0
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 1.0
    inter = np.logical_and(a, b).sum()
    return 1.0 - inter / union


cands = list(FONT_DIR.glob("*.tt?"))
print(f"scanning {len(cands)} fonts...")
hits = []
for p in cands:
    nd = _ink_mask(p, NOTDEF)
    ht = _ink_mask(p, HEART)
    if nd is None or ht is None:
        continue
    # 真字形：和 .notdef 差异大；且爱心确实有墨迹
    d = _diff_ratio(nd, ht)
    ink = ht.sum()
    if ink > 20 and d > 0.25:
        hits.append((d, p.name, int(ink)))

hits.sort(reverse=True)
print("=== fonts WITH a real heart glyph (diff vs .notdef) ===")
for d, name, ink in hits[:25]:
    print(f"  diff={d:.2f} ink={ink:5d}  {name}")
if not hits:
    print("  (none found)")
