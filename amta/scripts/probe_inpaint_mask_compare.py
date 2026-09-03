"""鎺㈤拡: 鐭╁舰 mask vs 绮句慨 mask 鐨?inpaint 鏁堟灉瀵规瘮銆?
鐢ㄥ悓鏍风殑 lama-manga 寮曟搸, 瀵规瘮涓ょ mask 鐨勫疄闄呮摝闄ゆ晥鏋溿€?鏍锋湰: page_11(12.jpg), page_12(13.jpg)
"""
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
from probe_refine_mask import build_rect_mask, build_refined_mask  # noqa: E402

SRC_DIR = Path(r"D:\鎴戠殑姹夊寲\姹夊寲浣滃搧\涓滄柟\鍗曠考鍋滅暀涔嬪湴")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "inpaint_mask_compare"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    {"page_idx": 11, "file": "12.jpg", "name": "page_11"},
    {"page_idx": 12, "file": "13.jpg", "name": "page_12"},
]

ENGINE = "lama-manga"


def mask_to_png(mask: np.ndarray) -> bytes:
    """numpy mask -> PNG bytes (koharu 绾﹀畾: 鐧借壊=瑕佷慨澶嶅尯鍩?銆?""
    buf = io.BytesIO()
    Image.fromarray(mask).save(buf, format="PNG")
    return buf.getvalue()


def run_inpaint(client: KoharuClient, raw_path: Path, mask_png: bytes,
                 engine: str = "lama-manga") -> Image.Image | None:
    """鐢ㄧ粰瀹?mask 璺?inpaint銆?""
    client.close_current_project()
    client.create_project(f"inpaint-compare-{engine}-{int(time.time())}")
    page_id = client.import_page(raw_path)
    client.run_inpaint(page_id, {"segment": mask_png, "bubble": mask_png}, engine=engine)
    data = client.fetch_inpainted(page_id)
    if data:
        return Image.open(io.BytesIO(data)).convert("RGB")
    return None


def pixel_diff(a: Image.Image, b: Image.Image) -> float:
    """涓ゅ浘鍍忕礌宸紓姣斾緥銆?""
    if a.size != b.size:
        return 1.0
    arr_a = np.array(a)
    arr_b = np.array(b)
    diff = np.abs(arr_a.astype(int) - arr_b.astype(int)).sum(axis=2)
    changed = (diff > 10).sum()
    return round(changed / (a.width * a.height), 4)


def make_comparison(original: Image.Image, rect_result: Image.Image,
                     refined_result: Image.Image, title: str) -> Image.Image:
    """鐢熸垚 1x3 瀵规瘮鍥俱€?""
    target_h = 1000
    scale = target_h / original.height

    def resize(im):
        new_w = int(im.width * scale)
        return im.resize((new_w, target_h), Image.LANCZOS)

    panels = [
        ("Original", original),
        ("Rect mask + lama-manga", rect_result),
        ("Refined mask + lama-manga", refined_result),
    ]

    pw = resize(panels[0][1]).width
    canvas = Image.new("RGB", (pw * 3, target_h + 30), (240, 240, 240))
    d = ImageDraw.Draw(canvas)
    for i, (label, im) in enumerate(panels):
        x = i * pw
        d.text((x + 8, 5), label, fill=(0, 0, 0))
        canvas.paste(resize(im), (x, 28))

    return canvas


def main():
    print(f"[compare] Output: {OUT_DIR}")
    print(f"[compare] Engine: {ENGINE}")

    client = KoharuClient()
    client.wait_server(timeout=30)

    summary = {}

    for page in PAGES:
        print(f"\n=== {page['name']} ({page['file']}) ===")
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

        # 1. 鐭╁舰 mask
        rect_mask = build_rect_mask((h, w), free_boxes, pad=4)
        rect_png = mask_to_png(rect_mask)

        # 2. 绮句慨 mask
        refined_mask = build_refined_mask(img_rgb, free_boxes, pad=4)
        refined_png = mask_to_png(refined_mask)

        rect_pixels = int((rect_mask > 128).sum())
        refined_pixels = int((refined_mask > 128).sum())
        print(f"  Rect mask:    {rect_pixels:,} px")
        print(f"  Refined mask: {refined_pixels:,} px ({100 - refined_pixels/rect_pixels*100:.1f}% less)")

        # 3. 璺戠煩褰?mask inpaint
        print("  Running rect mask inpaint...")
        t0 = time.perf_counter()
        rect_result = run_inpaint(client, raw_path, rect_png, engine=ENGINE)
        rect_time = time.perf_counter() - t0
        if rect_result and rect_result.size != img_pil.size:
            rect_result = rect_result.resize(img_pil.size)
        if rect_result:
            # 娑傜櫧 bubble
            d = ImageDraw.Draw(rect_result)
            for bb in bubble_boxes:
                x1, y1, x2, y2 = [int(v) for v in bb]
                d.rectangle([x1, y1, x2, y2], fill=(255, 255, 255))
            rect_result.save(OUT_DIR / f"{page['name']}_rect_inpaint.png")
            rect_diff = pixel_diff(img_pil, rect_result)
            print(f"    done in {rect_time:.1f}s, pixel_diff={rect_diff}")
        else:
            rect_diff = None
            print("    FAILED")

        # 4. 璺戠簿淇?mask inpaint
        print("  Running refined mask inpaint...")
        t0 = time.perf_counter()
        refined_result = run_inpaint(client, raw_path, refined_png, engine=ENGINE)
        refined_time = time.perf_counter() - t0
        if refined_result and refined_result.size != img_pil.size:
            refined_result = refined_result.resize(img_pil.size)
        if refined_result:
            # 娑傜櫧 bubble
            d = ImageDraw.Draw(refined_result)
            for bb in bubble_boxes:
                x1, y1, x2, y2 = [int(v) for v in bb]
                d.rectangle([x1, y1, x2, y2], fill=(255, 255, 255))
            refined_result.save(OUT_DIR / f"{page['name']}_refined_inpaint.png")
            refined_diff = pixel_diff(img_pil, refined_result)
            print(f"    done in {refined_time:.1f}s, pixel_diff={refined_diff}")
        else:
            refined_diff = None
            print("    FAILED")

        # 5. 鐢熸垚瀵规瘮鍥?        if rect_result and refined_result:
            comparison = make_comparison(img_pil, rect_result, refined_result, page["name"])
            comparison.save(OUT_DIR / f"{page['name']}_comparison.png")
            print("  comparison saved")

        summary[page["name"]] = {
            "rect_pixels": rect_pixels,
            "refined_pixels": refined_pixels,
            "reduction_pct": round(100 - refined_pixels / rect_pixels * 100, 1),
            "rect_time": round(rect_time, 1),
            "refined_time": round(refined_time, 1),
            "rect_pixel_diff": rect_diff,
            "refined_pixel_diff": refined_diff,
        }

    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n[compare] Done.")
    for name, s in summary.items():
        print(f"  {name}: rect_diff={s['rect_pixel_diff']}, refined_diff={s['refined_pixel_diff']}, "
              f"mask_reduction={s['reduction_pct']}%")


if __name__ == "__main__":
    main()
