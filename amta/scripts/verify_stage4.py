"""Stage 4 端到端验证: 修复bug后跑5页, 生成原图vs clean对比报告。

用法: python scripts/verify_stage4.py
输出: output/tmp/stage4_verify/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from importlib import import_module  # noqa: E402
mod = import_module("04_inpaint")

SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "stage4_verify"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    {"page_idx": 10, "file": "11.jpg", "name": "page_10"},
    {"page_idx": 11, "file": "12.jpg", "name": "page_11"},
    {"page_idx": 12, "file": "13.jpg", "name": "page_12"},
    {"page_idx": 13, "file": "14.jpg", "name": "page_13"},
    {"page_idx": 14, "file": "15.jpg", "name": "page_14"},
]


def main():
    print(f"[verify] Output: {OUT_DIR}")
    all_stats = []

    for page in PAGES:
        print(f"\n=== {page['name']} ({page['file']}) ===")
        raw_path = SRC_DIR / page["file"]
        det_path = ARTIFACTS_DIR / f"{page['name']}_detection.json"
        out_json = OUT_DIR / f"{page['name']}_inpaint.json"
        clean_dir = OUT_DIR / "clean"

        doc = mod.run(
            work_id=page["name"],
            det_path=det_path,
            raw_page=raw_path,
            out_path=out_json,
            clean_dir=clean_dir,
        )

        with open(det_path, encoding="utf-8") as f:
            det = json.load(f)
        n_bubble = sum(1 for b in det["blocks"] if b["bubble_type"] == "text_bubble")
        n_free = sum(1 for b in det["blocks"] if b["bubble_type"] == "text_free")

        stats = {
            "page": page["name"],
            "file": page["file"],
            "n_bubble": n_bubble,
            "n_free": n_free,
            "filled": doc["checks"]["filled"],
            "inpainted": doc["checks"]["inpainted"],
            "skipped": doc["checks"]["skipped"],
            "pixel_diff_ratio": doc["checks"]["pixel_diff_ratio"],
        }
        all_stats.append(stats)
        print(f"  bubble={n_bubble}, free={n_free}, filled={stats['filled']}, "
              f"inpainted={stats['inpainted']}, diff={stats['pixel_diff_ratio']}")

        original = Image.open(raw_path).convert("RGB")
        clean_path = clean_dir / f"{page['name']}_clean.png"
        if clean_path.exists():
            clean = Image.open(clean_path).convert("RGB")
            target_h = 1400
            def resize(im):
                s = target_h / im.height
                return im.resize((int(im.width * s), target_h), Image.LANCZOS)
            orig_r = resize(original)
            clean_r = resize(clean)
            gap = 20
            canvas = Image.new("RGB", (orig_r.width * 2 + gap, target_h + 40), (240, 240, 240))
            d = ImageDraw.Draw(canvas)
            d.text((10, 8), "Original", fill=(0, 0, 0))
            d.text((orig_r.width + gap + 10, 8), "Clean (bubble=white, free=inpaint)", fill=(0, 0, 0))
            canvas.paste(orig_r, (0, 40))
            canvas.paste(clean_r, (orig_r.width + gap, 40))
            canvas.save(OUT_DIR / f"{page['name']}_comparison.png")
            print("  comparison saved")

    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(all_stats, f, ensure_ascii=False, indent=2)

    print(f"\n[verify] Done. {len(all_stats)} pages verified.")
    total_diff = sum(s["pixel_diff_ratio"] for s in all_stats) / len(all_stats)
    print(f"[verify] Avg pixel_diff_ratio: {total_diff:.4f}")


if __name__ == "__main__":
    main()
