"""探针: 用 koharu comic-text-detector-seg 生成像素级 mask, 再跑 inpaint。

流程:
1. 导入页面
2. 跑 segmentation pipeline (steps=["comic-text-detector-seg"])
3. 从 scene 取回 SegmentMask
4. 用像素级 mask 跑 lama-manga inpaint
5. 对比: 矩形mask vs 像素级mask

样本: page_11(12.jpg), page_12(13.jpg) — 问题最明显的两页
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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


from amta.backends.koharu_client import KoharuClient  # noqa: E402

SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "seg_mask_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    {"page_idx": 11, "file": "12.jpg", "name": "page_11"},
    {"page_idx": 12, "file": "13.jpg", "name": "page_12"},
]


def build_rect_mask(img: Image.Image, bboxes: list, pad: int = 0) -> bytes:
    """矩形 mask: 要修复区域=白(255)。"""
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


def get_segment_mask(client: KoharuClient, page_id: str) -> bytes | None:
    """从 scene 取回 SegmentMask (PNG 字节)。"""
    scene = client.get_scene()
    pages = scene.get("scene", {}).get("pages", {})
    page = pages.get(page_id)
    if page is None:
        return None
    for node_id, node in page.get("nodes", {}).items():
        kind = node.get("kind", {})
        if isinstance(kind, dict):
            mask = kind.get("mask")
            if mask and mask.get("role") == "segment":
                blob_ref = mask.get("blob") or mask.get("hash") or node.get("blob")
                if blob_ref:
                    return client.get_blob(blob_ref)
    return None


def run_inpaint_with_mask(client: KoharuClient, raw_path: Path, mask_png: bytes,
                          engine: str = "lama-manga") -> Image.Image | None:
    """用给定 mask 跑 inpaint。"""
    client.close_current_project()
    client.create_project(f"seg-inpaint-{engine}-{int(time.time())}")
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

        # --- Step 1: 跑 segmentation ---
        print("  Running comic-text-detector-seg...")
        client.close_current_project()
        client.create_project(f"seg-{page['name']}")
        page_id = client.import_page(raw_path)
        op_id = client.run_pipeline([page_id], ["comic-text-detector-seg"])
        op = client.wait_operation(op_id, timeout=300)
        print(f"  Segmentation status: {op.get('status')}")

        # --- Step 2: 取回 SegmentMask ---
        seg_mask_bytes = get_segment_mask(client, page_id)
        if seg_mask_bytes is None:
            print("  ERROR: No SegmentMask found!")
            continue
        seg_mask = Image.open(io.BytesIO(seg_mask_bytes)).convert("L")
        print(f"  SegmentMask size: {seg_mask.size}, mode: {seg_mask.mode}")

        # 保存原始 seg mask
        seg_mask.save(OUT_DIR / f"{page['name']}_seg_mask_raw.png")

        # 统计 mask 覆盖率
        import numpy as np
        arr = np.array(seg_mask)
        white_ratio = (arr > 128).sum() / arr.size
        print(f"  Mask white ratio: {white_ratio*100:.2f}%")

        # --- Step 3: 只保留 free 框内的 seg mask (过滤掉 bubble 区域) ---
        # seg mask 可能包含所有文字, 我们只想要 free 文字
        # 方法: 用 free 框做 ROI, 只保留框内的 seg 像素
        free_only_mask = Image.new("L", raw_img.size, 0)
        for bb in free_boxes:
            x1, y1, x2, y2 = [int(v) for v in bb]
            # 裁剪 seg mask 的对应区域
            crop = seg_mask.crop((x1, y1, x2, y2))
            free_only_mask.paste(crop, (x1, y1))
        free_only_buf = io.BytesIO()
        free_only_mask.save(free_only_buf, format="PNG")
        free_only_mask.save(OUT_DIR / f"{page['name']}_seg_mask_free_only.png")

        # --- Step 4: 用像素级 mask 跑 inpaint ---
        print("  Running inpaint with pixel mask...")
        t0 = time.perf_counter()
        inpainted_pixel = run_inpaint_with_mask(client, raw_path, free_only_buf.getvalue(),
                                                 engine="lama-manga")
        elapsed = time.perf_counter() - t0
        if inpainted_pixel:
            if inpainted_pixel.size != raw_img.size:
                inpainted_pixel = inpainted_pixel.resize(raw_img.size)
            # 涂白 bubble
            d = ImageDraw.Draw(inpainted_pixel)
            for bb in bubble_boxes:
                x1, y1, x2, y2 = [int(v) for v in bb]
                d.rectangle([x1, y1, x2, y2], fill=(255, 255, 255))
            inpainted_pixel.save(OUT_DIR / f"{page['name']}_pixel_mask_inpaint.png")
            print(f"    done in {elapsed:.1f}s")
        else:
            print("    FAILED")

        # --- Step 5: 对比图 ---
        # 原图 | 矩形mask inpaint | 像素mask inpaint | seg mask 可视化
        rect_mask = build_rect_mask(raw_img, free_boxes, pad=0)
        print("  Running inpaint with rect mask (baseline)...")
        inpainted_rect = run_inpaint_with_mask(client, raw_path, rect_mask, engine="lama-manga")
        if inpainted_rect and inpainted_rect.size != raw_img.size:
            inpainted_rect = inpainted_rect.resize(raw_img.size)
        if inpainted_rect:
            d = ImageDraw.Draw(inpainted_rect)
            for bb in bubble_boxes:
                x1, y1, x2, y2 = [int(v) for v in bb]
                d.rectangle([x1, y1, x2, y2], fill=(255, 255, 255))
            inpainted_rect.save(OUT_DIR / f"{page['name']}_rect_mask_inpaint.png")

        # 生成对比
        target_h = 1100
        def resize(im):
            s = target_h / im.height
            return im.resize((int(im.width * s), target_h), Image.LANCZOS)

        panels = [("Original", raw_img)]
        if inpainted_rect:
            panels.append(("Rect mask + lama", inpainted_rect))
        if inpainted_pixel:
            panels.append(("Pixel mask + lama", inpainted_pixel))
        # seg mask 可视化 (叠加在原图上)
        seg_vis = raw_img.copy()
        seg_vis.paste(Image.new("RGB", raw_img.size, (255, 0, 0)),
                      mask=free_only_mask.point(lambda x: 128 if x > 128 else 0))
        panels.append(("Seg mask (red=free text)", seg_vis))

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
