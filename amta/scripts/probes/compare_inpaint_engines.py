"""对比 inpaint 引擎: lama-manga vs aot-inpainting, 不同 pad 值。

样本: page_11(12.jpg), page_12(13.jpg) — 问题最明显的两页
变量:
  - 引擎: lama-manga vs aot-inpainting
  - pad: 0 vs 4 (mask 膨胀量)
输出: output/tmp/inpaint_compare/
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent  # 仓库根（本文件在 scripts/probes/ 下）
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from amta.backends.koharu_client import KoharuClient  # noqa: E402

SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "inpaint_compare"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    {"page_idx": 11, "file": "12.jpg", "name": "page_11"},
    {"page_idx": 12, "file": "13.jpg", "name": "page_12"},
]

ENGINES = ["lama-manga", "aot-inpainting"]
PADS = [0, 4]


def build_mask(img: Image.Image, bboxes: list, pad: int = 4) -> bytes:
    """koharu mask: 要修复区域=白(255), 其余=黑(0)。"""
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    for bb in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(img.width, x2 + pad), min(img.height, y2 + pad)
        if x2 > x1 and y2 > y1:
            d.rectangle([x1, y1, x2, y2], fill=255)
    buf = io.BytesIO()
    mask.save(buf, format="PNG")
    return buf.getvalue()


def run_inpaint(raw_path: Path, free_boxes: list, engine: str, pad: int) -> Image.Image | None:
    """跑一次 inpaint, 返回修复后的图。"""
    client = KoharuClient()
    client.wait_server(timeout=30)
    client.close_current_project()
    client.create_project(f"compare-{engine}-pad{pad}")
    page_id = client.import_page(raw_path)
    raw_img = Image.open(raw_path).convert("RGB")
    mask_png = build_mask(raw_img, free_boxes, pad=pad)
    client.run_inpaint(page_id, {"segment": mask_png, "bubble": mask_png}, engine=engine)
    data = client.fetch_inpainted(page_id)
    if data:
        return Image.open(io.BytesIO(data)).convert("RGB")
    return None


def main():
    print(f"[compare] Output: {OUT_DIR}")

    for page in PAGES:
        print(f"\n=== {page['name']} ({page['file']}) ===")
        raw_path = SRC_DIR / page["file"]
        det_path = ARTIFACTS_DIR / f"{page['name']}_detection.json"

        with open(det_path, encoding="utf-8") as f:
            det = json.load(f)
        free_boxes = [b["bbox"] for b in det["blocks"] if b["bubble_type"] == "text_free"]
        bubble_boxes = [b["bbox"] for b in det["blocks"] if b["bubble_type"] == "text_bubble"]
        print(f"  free={len(free_boxes)}, bubble={len(bubble_boxes)}")

        raw_img = Image.open(raw_path).convert("RGB")
        results = {}

        for engine in ENGINES:
            for pad in PADS:
                key = f"{engine}_pad{pad}"
                print(f"  Running {key}...")
                t0 = time.perf_counter()
                try:
                    inpainted = run_inpaint(raw_path, free_boxes, engine, pad)
                    elapsed = time.perf_counter() - t0
                    if inpainted:
                        if inpainted.size != raw_img.size:
                            inpainted = inpainted.resize(raw_img.size)
                        # 涂白 bubble
                        d = ImageDraw.Draw(inpainted)
                        for bb in bubble_boxes:
                            x1, y1, x2, y2 = [int(v) for v in bb]
                            d.rectangle([x1, y1, x2, y2], fill=(255, 255, 255))
                        results[key] = inpainted
                        inpainted.save(OUT_DIR / f"{page['name']}_{key}.png")
                        print(f"    done in {elapsed:.1f}s")
                    else:
                        print("    FAILED: no result")
                except Exception as e:
                    print(f"    ERROR: {e}")

        # 生成对比图: 原图 + 各方案
        target_h = 1200
        def resize(im):
            s = target_h / im.height
            return im.resize((int(im.width * s), target_h), Image.LANCZOS)

        panels = [("Original", raw_img)] + [(k, v) for k, v in results.items()]
        cols = 2
        rows = (len(panels) + cols - 1) // cols
        pw = resize(panels[0][1]).width
        ph = target_h
        canvas = Image.new("RGB", (pw * cols, (ph + 35) * rows), (240, 240, 240))
        d = ImageDraw.Draw(canvas)
        for i, (label, im) in enumerate(panels):
            r, c = divmod(i, cols)
            x = c * pw
            y = r * (ph + 35)
            d.text((x + 8, y + 5), label, fill=(0, 0, 0))
            canvas.paste(resize(im), (x, y + 30))
        canvas.save(OUT_DIR / f"{page['name']}_comparison.png")
        print("  comparison saved")

    print("\n[compare] Done.")


if __name__ == "__main__":
    main()
