"""探针：p52 r02 逐字号 fit 过程，找出真正卡字号的硬规则。"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from PIL import ImageFont
from amta.typeset.typeset_engine import (
    _font_metrics, _fits, wrap_vertical, break_lines, SAFE_RATIO,
)

# p52 r02 实际 bbox
bbox = [787.0, 1409.0, 1038.0, 1842.0]
w, h = (bbox[2]-bbox[0])*SAFE_RATIO, (bbox[3]-bbox[1])*SAFE_RATIO
text = "就这样，原本就信用不足、没人愿意靠近的姐妹宅邸，再也没有月人来访了"

font_path = Path("C:/Windows/Fonts/msyh.ttc")

print(f"框: {bbox[2]-bbox[0]:.0f}x{bbox[3]-bbox[1]:.0f}, Safe后 w={w:.1f} h={h:.1f}")
print(f"译文: {len(text)} 字")
print(f"译文: {text}")
print()

for sz in range(15, 40):
    font = ImageFont.truetype(str(font_path), sz)
    char_w, line_h = _font_metrics(font)
    chars_per_col = max(1, int(h / line_h))
    lines = wrap_vertical(text, chars_per_col)
    max_col = max(len(c) for c in lines) if lines else 0
    total_w = len(lines) * char_w
    w_ok = total_w <= w
    h_ok = max_col * line_h <= h
    fits = w_ok and h_ok
    print(f"sz={sz:2d} char_w={char_w:5.1f} line_h={line_h:5.1f} "
          f"cpc={chars_per_col:2d} cols={len(lines)} maxcol={max_col:2d} "
          f"total_w={total_w:6.1f}/{w:.0f}({'OK' if w_ok else 'X'}) "
          f"h_used={max_col*line_h:6.1f}/{h:.0f}({'OK' if h_ok else 'X'}) "
          f"=> {'FIT' if fits else 'no'}")
