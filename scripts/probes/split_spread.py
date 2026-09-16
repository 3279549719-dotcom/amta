"""一次性：把跨页扫图（一张 jpg=左右两页）按阅读顺序切成单页。

日文漫画从右往左读：摊开后右半是前一页，左半是后一页。
每张跨页切成两半，输出顺序 = 先右后左，连续编号。

用法:
  uv run python scripts/probes/split_spread.py
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image

SRC = Path(r"D:\我的汉化\汉化作品\东方\月天新地")
DST = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")


def page_key(p: Path) -> int:
    return int(p.stem)


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("*.jpg"), key=page_key)
    if not files:
        raise SystemExit(f"no jpg under {SRC}")

    out_no = 1
    n_split = n_single = 0
    for f in files:
        im = Image.open(f)
        im = im.convert("RGB")
        w, h = im.size
        if h > w:
            # 竖版 = 单页，整页保留不切
            im.save(DST / f"{out_no}.jpg", quality=95)
            out_no += 1
            n_single += 1
            continue
        # 横版 = 跨页，日文漫画先右后左
        mid = w // 2
        right = im.crop((mid, 0, w, h))   # 前一页（先读）
        left = im.crop((0, 0, mid, h))   # 后一页
        for half in (right, left):
            half.save(DST / f"{out_no}.jpg", quality=95)
            out_no += 1
        n_split += 1

    print(f"split spreads: {n_split}, kept single pages: {n_single}")
    print(f"output singles: {out_no - 1} -> {DST}")


if __name__ == "__main__":
    main()
