"""蹇€熸帰閽? 绮句慨 mask + aot-inpainting vs 绮句慨 mask + lama-manga銆?
鍙窇 page_11, 楠岃瘉绮句慨 mask 涓嬩笉鍚?inpaint 寮曟搸鐨勬晥鏋溿€?"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from amta.koharu_client import KoharuClient  # noqa: E402
from probe_refine_mask import build_refined_mask  # noqa: E402

SRC_DIR = Path(r"D:\鎴戠殑姹夊寲\姹夊寲浣滃搧\涓滄柟\鍗曠考鍋滅暀涔嬪湴")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "refined_aot_compare"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ENGINES = ["lama-manga", "aot-inpainting"]


def mask_to_png(mask: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(mask).save(buf, format="PNG")
    return buf.getvalue()


def run_inpaint(client, raw_path, mask_png, engine):
    client.close_current_project()
    client.create_project(f"refined-{engine}-{int(time.time())}")
    page_id = client.import_page(raw_path)
    client.run_inpaint(page_id, {"segment": mask_png, "bubble": mask_png}, engine=engine)
    data = client.fetch_inpainted(page_id)
    if data:
        return Image.open(io.BytesIO(data)).convert("RGB")
    return None


def main():
    print("[compare] Refined mask + engine comparison")
    client = KoharuClient()
    client.wait_server(timeout=30)

    page = {"page_idx": 11, "file": "12.jpg", "name": "page_11"}
    raw_path = SRC_DIR / page["file"]
    det_path = ARTIFACTS_DIR / f"{page['name']}_detection.json"

    img_pil = Image.open(raw_path).convert("RGB")
    img_rgb = np.array(img_pil)
    h, w = img_rgb.shape[:2]

    with open(det_path, encoding="utf-8") as f:
        det = json.load(f)
    blocks = det.get("blocks") or det.get("regions") or []
    free_boxes = [b["bbox"] for b in blocks if b.get("bubble_type") == "text_free"]
    bubble_boxes = [b["bbox"] for b in blocks if b.get("bubble_type") == "text_bubble"]
    print(f"  free={len(free_boxes)}, bubble={len(bubble_boxes)}")

    # 绮句慨 mask
    refined_mask = build_refined_mask(img_rgb, free_boxes, pad=4)
    refined_png = mask_to_png(refined_mask)
    refined_pixels = int((refined_mask > 128).sum())
    print(f"  Refined mask: {refined_pixels:,} px")

    results = {}
    for engine in ENGINES:
        print(f"  Running {engine}...")
        t0 = time.perf_counter()
        result = run_inpaint(client, raw_path, refined_png, engine)
        elapsed = time.perf_counter() - t0
        if result and result.size != img_pil.size:
            result = result.resize(img_pil.size)
        if result:
            # 娑傜櫧 bubble
            d = ImageDraw.Draw(result)
            for bb in bubble_boxes:
                x1, y1, x2, y2 = [int(v) for v in bb]
                d.rectangle([x1, y1, x2, y2], fill=(255, 255, 255))
            result.save(OUT_DIR / f"page_11_refined_{engine.replace('-', '_')}.png")
            results[engine] = result
            print(f"    done in {elapsed:.1f}s")
        else:
            print("    FAILED")

    # 瀵规瘮鍥?    target_h = 1000
    scale = target_h / img_pil.height
    def resize(im):
        return im.resize((int(im.width * scale), target_h), Image.LANCZOS)

    panels = [("Original", img_pil)] + [(k, v) for k, v in results.items()]
    pw = resize(panels[0][1]).width
    canvas = Image.new("RGB", (pw * len(panels), target_h + 30), (240, 240, 240))
    d = ImageDraw.Draw(canvas)
    for i, (label, im) in enumerate(panels):
        x = i * pw
        d.text((x + 8, 5), f"Refined mask + {label}", fill=(0, 0, 0))
        canvas.paste(resize(im), (x, 28))
    canvas.save(OUT_DIR / "page_11_comparison.png")
    print("  comparison saved")

    print("\n[compare] Done.")


if __name__ == "__main__":
    main()
