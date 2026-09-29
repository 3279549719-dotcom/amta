"""竖排列末逗号消冗 —— before/after 视觉对比图（Task 4）。

读取 `render_page_before_after.py` 产出的 before/after 图与 render_report.json，
生成三类图（全部走 PIL，不改任何成品图内容，只做拼贴与标注）：

1. `page_<N>_comparison.png` —— 整页 before | after 并排，红框标出含列末逗号的区域；
2. `page_<N>_diff.png`        —— before 上把"被隐藏的字形像素"高亮成红色；
3. `page_<N>_zoom_<rid>.png`   —— 每个问题区域的原尺寸放大裁剪 before | after。

用法：
  uv run python scripts/probes/make_comparison.py --pages 4 12 13 16
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from amta.common.encoding import force_utf8_stdio  # noqa: E402

force_utf8_stdio()  # Windows stdout 默认 cp936，中文输出必须走 UTF-8 收口点

OUT_ROOT = Path("workspace/column-end-comma-fix")
SRC_ROOT = Path(r"E:\manga translator agent\workspace\touhou-getten-shinchi")
LABEL_FONT = "C:/Windows/Fonts/arialbd.ttf"
GAP = 24
LABEL_H = 48
RED = (220, 30, 30)
GREEN = (0, 140, 60)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(LABEL_FONT, size)
    except OSError:
        return ImageFont.load_default()


def _banner(img: Image.Image, text: str, color) -> Image.Image:
    out = Image.new("RGB", (img.width, img.height + LABEL_H), "white")
    out.paste(img, (0, LABEL_H))
    d = ImageDraw.Draw(out)
    d.rectangle([0, 0, out.width - 1, LABEL_H - 1], fill=color)
    d.text((12, 10), text, font=_font(28), fill="white")
    return out


def _detection_bboxes(page: str, src_root: Path) -> dict[str, list]:
    p = src_root / "artifacts" / "detection" / f"page_{page}.json"
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {b["region_id"]: b["bbox"] for b in doc.get("blocks", [])
            if b.get("region_id") and b.get("bbox")}


def _changed_pixels(before: Image.Image, after: Image.Image) -> list[tuple[int, int]]:
    pb, pa = before.load(), after.load()
    return [(x, y)
            for y in range(before.height)
            for x in range(before.width)
            if pb[x, y] != pa[x, y]]


def _pad_clamp(bbox, size, pad: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    w, h = size
    return (max(0, int(x1) - pad), max(0, int(y1) - pad),
            min(w, int(x2) + pad), min(h, int(y2) + pad))


def build_page(page: str, out_root: Path, src_root: Path, report: dict) -> list[Path]:
    before = Image.open(out_root / "before" / f"page_{page}_final.png").convert("RGB")
    after = Image.open(out_root / "after" / f"page_{page}_final.png").convert("RGB")
    det = _detection_bboxes(page, src_root)
    regions = report["regions"]
    written: list[Path] = []

    # --- 1. 整页并排 + 红框 ---
    comp = Image.new("RGB", (before.width * 2 + GAP, before.height + LABEL_H), "white")
    comp.paste(_banner(before, f"BEFORE  page_{page}", RED), (0, 0))
    comp.paste(_banner(after, f"AFTER  page_{page}", GREEN),
               (before.width + GAP, 0))
    d = ImageDraw.Draw(comp)
    for rid in regions:
        box = det.get(rid)
        if not box:
            continue
        for dx in (0, before.width + GAP):
            d.rectangle([box[0] + dx, box[1] + LABEL_H, box[2] + dx, box[3] + LABEL_H],
                        outline=RED, width=4)
            d.text((box[0] + dx + 6, box[1] + LABEL_H + 6), rid,
                   font=_font(26), fill=RED)
    p = out_root / f"page_{page}_comparison.png"
    comp.save(p)
    written.append(p)

    # --- 2. 差异高亮（被隐藏的字形像素）---
    diff_img = before.copy()
    dp = diff_img.load()
    pts = _changed_pixels(before, after)
    for x, y in pts:
        for yy in range(max(0, y - 1), min(diff_img.height, y + 2)):
            for xx in range(max(0, x - 1), min(diff_img.width, x + 2)):
                dp[xx, yy] = RED
    d = ImageDraw.Draw(diff_img)
    for rid in regions:
        box = det.get(rid)
        if box:
            d.rectangle(box, outline=GREEN, width=3)
    p = out_root / f"page_{page}_diff.png"
    _banner(diff_img, f"DIFF (removed glyph pixels in red)  page_{page}  "
                      f"{len(pts)}px", RED).save(p)
    written.append(p)

    # --- 3. 每个问题区域放大裁剪 before | after ---
    for rid in regions:
        box = det.get(rid)
        if not box:
            continue
        crop_box = _pad_clamp(box, before.size, 16)
        cb = before.crop(crop_box)
        ca = after.crop(crop_box)
        scale = max(1, min(3, 480 // max(1, cb.width)))
        cb = cb.resize((cb.width * scale, cb.height * scale), Image.NEAREST)
        ca = ca.resize((ca.width * scale, ca.height * scale), Image.NEAREST)
        zoom = Image.new("RGB", (cb.width * 2 + GAP, cb.height + LABEL_H), "white")
        zoom.paste(_banner(cb, f"BEFORE {rid}", RED), (0, 0))
        zoom.paste(_banner(ca, f"AFTER {rid}", GREEN), (cb.width + GAP, 0))
        p = out_root / f"page_{page}_zoom_{rid}.png"
        zoom.save(p)
        written.append(p)

    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", required=True)
    ap.add_argument("--out-root", type=Path, default=OUT_ROOT)
    ap.add_argument("--src-root", type=Path, default=SRC_ROOT)
    args = ap.parse_args()

    report_path = args.out_root / "render_report.json"
    if not report_path.exists():
        raise SystemExit(f"缺少 {report_path}，请先跑 render_page_before_after.py")
    reports = {r["page"]: r for r in json.loads(report_path.read_text(encoding="utf-8"))}

    for page in args.pages:
        if page not in reports:
            raise SystemExit(f"render_report.json 中没有 page_{page}")
        written = build_page(page, args.out_root, args.src_root, reports[page])
        print(f"page_{page}: 生成 {len(written)} 张图")
        for p in written:
            print(f"  {p}  ({p.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
