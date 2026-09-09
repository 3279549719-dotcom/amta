"""探针: flux2-klein inpaint 引擎 vs lama-manga。

用同样的矩形 mask, 对比两个引擎的效果。
样本: page_11(12.jpg), page_12(13.jpg)
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

from amta.backends.koharu_client import KoharuClient  # noqa: E402

SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "flux2_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    {"page_idx": 11, "file": "12.jpg", "name": "page_11"},
    {"page_idx": 12, "file": "13.jpg", "name": "page_12"},
]

ENGINES = ["lama-manga", "flux2-klein"]


def build_mask(img: Image.Image, bboxes: list, pad: int = 0) -> bytes:
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


def run_inpaint(client: KoharuClient, raw_path: Path, mask_png: bytes,
                engine: str) -> Image.Image | None:
    client.close_current_project()
    client.create_project(f"flux-{engine}-{int(time.time())}")
    page_id = client.import_page(raw_path)
    client.run_inpaint(page_id, {"segment": mask_png, "bubble": mask_png}, engine=engine)
    data = client.fetch_inpainted(page_id)
    if data:
        return Image.open(io.BytesIO(data)).convert("RGB")
    return None


def main():
    client = KoharuClient()
    client.wait_server(timeout=30)

    for page in PAGES:
        print(f"\n=== {page['name']} ({page['file']}) ===")
        raw_path = SRC_DIR / page["file"]
        det_path = ARTIFACTS_DIR / f"{page['name']}_detection.json"
        raw_img = Image.open(raw_path).convert("RGB")

        with open(det_path, encoding="utf-8") as f:
            det = json.load(f)
        free_boxes = [b["bbox"] for b in det["blocks"] if b["bubble_type"] == "text_free"]
        bubble_boxes = [b["bbox"] for b in det["blocks"] if b["bubble_type"] == "text_bubble"]
        print(f"  free={len(free_boxes)}, bubble={len(bubble_boxes)}")

        mask_png = build_mask(raw_img, free_boxes, pad=0)
        results = {}

        for engine in ENGINES:
            print(f"  Running {engine}...")
            t0 = time.perf_counter()
            try:
                result = run_inpaint(client, raw_path, mask_png, engine)
                elapsed = time.perf_counter() - t0
                if result:
                    if result.size != raw_img.size:
                        result = result.resize(raw_img.size)
                    d = ImageDraw.Draw(result)
                    for bb in bubble_boxes:
                        x1, y1, x2, y2 = [int(v) for v in bb]
                        d.rectangle([x1, y1, x2, y2], fill=(255, 255, 255))
                    results[engine] = result
                    result.save(OUT_DIR / f"{page['name']}_{engine.replace('-', '_')}.png")
                    print(f"    done in {elapsed:.1f}s")
                else:
                    print("    FAILED: no result")
            except Exception as e:
                print(f"    ERROR: {e}")

        # 对比图
        target_h = 1200
        def resize(im):
            s = target_h / im.height
            return im.resize((int(im.width * s), target_h), Image.LANCZOS)

        panels = [("Original", raw_img)] + [(k, v) for k, v in results.items()]
        cols = 2
        rows = (len(panels) + 1) // 2
        pw = resize(panels[0][1]).width
        canvas = Image.new("RGB", (pw * cols, (target_h + 30) * rows), (240, 240, 240))
        d = ImageDraw.Draw(canvas)
        for i, (label, im) in enumerate(panels):
            r, c = divmod(i, cols)
            x = c * pw
            y = r * (target_h + 30)
            d.text((x + 8, y + 5), label, fill=(0, 0, 0))
            canvas.paste(resize(im), (x, y + 28))
        canvas.save(OUT_DIR / f"{page['name']}_comparison.png")
        print("  comparison saved")

    print("\n[probe] Done.")


if __name__ == "__main__":
    main()
