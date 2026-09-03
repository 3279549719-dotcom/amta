"""端到端探针: text_bubble 涂白 + text_free 像素级mask+inpaint, 输出干净图。

对比三种处理方式:
  A. 全部矩形涂白 (当前实际行为, 因为 category 映射断了)
  B. text_bubble涂白 + text_free矩形mask+inpaint (矩形mask方案)
  C. text_bubble涂白 + text_free CTD像素mask+inpaint (推荐方案)

样本: page_13 (14.jpg), 有 4 个 text_free 框
输出: output/tmp/e2e_inpaint/
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from ctd_detector import letterbox, SegDetectorRepresenter  # noqa: E402
from amta.koharu_client import KoharuClient  # noqa: E402

CTD_MODEL = ROOT / "models" / "CTD" / "comictextdetector.pt.onnx"
SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "e2e_inpaint"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGE = {"page_idx": 13, "file": "14.jpg", "name": "page_13"}


def load_ctd_net():
    net = cv2.dnn.readNetFromONNX(str(CTD_MODEL))
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return net


def ctd_shrink_map(net, img_bgr, input_size=1024):
    """返回与原图同尺寸的 DBNet shrink_map 概率图。"""
    im_h, im_w = img_bgr.shape[:2]
    img_in, ratio, (dw, dh) = letterbox(img_bgr, new_shape=(input_size, input_size), auto=False, stride=64)
    blob = cv2.dnn.blobFromImage(img_in, scalefactor=1.0 / 255.0, size=(input_size, input_size), swapRB=False)
    net.setInput(blob)
    outputs = net.forward(net.getUnconnectedOutLayersNames())
    _blks, mask, lines_map = outputs[0], outputs[1], outputs[2]
    if mask.ndim == 4 and mask.shape[1] == 2:
        mask, lines_map = lines_map, mask
    dh_int = int(round(dh))
    dw_int = int(round(dw))
    lines_map_crop = lines_map[:, :, :lines_map.shape[2] - dh_int * 2, :lines_map.shape[3] - dw_int * 2]
    shrink = lines_map_crop[0, 0]
    shrink_orig = cv2.resize(shrink, (im_w, im_h), interpolation=cv2.INTER_LINEAR)
    return np.clip(shrink_orig, 0, 1).astype(np.float32)


def pixel_mask_in_regions(shrink_map, bboxes, thresh=0.1, dilate_iter=7, dilate_kernel=9):
    """在指定 bbox 区域内生成 CTD 像素级 mask (255=文字, 0=背景)。"""
    h, w = shrink_map.shape
    full = np.zeros((h, w), dtype=np.uint8)
    binary = (shrink_map > thresh).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_kernel, dilate_kernel))
    binary = cv2.dilate(binary, kernel, iterations=dilate_iter)
    for bb in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        full[y1:y2, x1:x2] = binary[y1:y2, x1:x2]
    return full


def rect_mask_in_regions(img_size, bboxes, pad=4):
    """矩形 mask (当前做法)。"""
    w, h = img_size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    for bb in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
        if x2 > x1 and y2 > y1:
            d.rectangle([x1, y1, x2, y2], fill=255)
    return np.array(mask)


def mask_to_png(mask_arr: np.ndarray) -> bytes:
    """mask 数组 → PNG 字节 (koharu 需要)。"""
    # koharu 的 mask: 目标区域黑(0), 其余白(255) — 与我们的约定相反
    inverted = 255 - mask_arr
    img = Image.fromarray(inverted, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def fill_white_regions(img: Image.Image, bboxes) -> None:
    """在图上把指定 bbox 区域涂白。"""
    d = ImageDraw.Draw(img)
    for bb in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bb]
        d.rectangle([x1, y1, x2, y2], fill=(255, 255, 255))


def run_koharu_inpaint(client: KoharuClient, raw_path: Path, mask_arr: np.ndarray) -> Image.Image | None:
    """调 koharu lama-manga inpaint, 返回修复后的整页图。"""
    client.wait_server(timeout=30)
    client.close_current_project()
    client.create_project("e2e-probe")
    page_id = client.import_page(raw_path)
    png = mask_to_png(mask_arr)
    client.run_inpaint(page_id, {"segment": png, "bubble": png}, engine="lama-manga")
    data = client.fetch_inpainted(page_id)
    if data:
        return Image.open(io.BytesIO(data)).convert("RGB")
    return None


def main():
    print(f"[e2e] Page: {PAGE['name']} ({PAGE['file']})")
    print(f"[e2e] Output: {OUT_DIR}")

    # 1. 加载检测结果
    det_path = ARTIFACTS_DIR / f"{PAGE['name']}_detection.json"
    with open(det_path, "r", encoding="utf-8") as f:
        det = json.load(f)
    blocks = det["blocks"]
    bubble_boxes = [b["bbox"] for b in blocks if b.get("bubble_type") == "text_bubble"]
    free_boxes = [b["bbox"] for b in blocks if b.get("bubble_type") == "text_free"]
    print(f"[e2e] text_bubble={len(bubble_boxes)}, text_free={len(free_boxes)}")

    raw_path = SRC_DIR / PAGE["file"]
    original = Image.open(raw_path).convert("RGB")
    w, h = original.size
    print(f"[e2e] Image: {w}x{h}")

    # === 方案 A: 全部矩形涂白 (当前实际行为) ===
    print("\n[e2e] Scheme A: all rect fill-white...")
    img_a = original.copy()
    fill_white_regions(img_a, bubble_boxes + free_boxes)
    img_a.save(OUT_DIR / "A_all_rect_white.png")
    print("[e2e]   saved A_all_rect_white.png")

    # === 方案 B: bubble涂白 + free矩形mask+inpaint ===
    print("\n[e2e] Scheme B: bubble white + free rect-mask inpaint...")
    rect_mask = rect_mask_in_regions((w, h), free_boxes, pad=4)
    client = KoharuClient()
    t0 = time.perf_counter()
    inpainted_b = run_koharu_inpaint(client, raw_path, rect_mask)
    inpaint_time_b = time.perf_counter() - t0
    if inpainted_b:
        if inpainted_b.size != (w, h):
            inpainted_b = inpainted_b.resize((w, h))
        fill_white_regions(inpainted_b, bubble_boxes)
        inpainted_b.save(OUT_DIR / "B_free_rect_inpaint.png")
        print(f"[e2e]   saved B_free_rect_inpaint.png (inpaint {inpaint_time_b:.1f}s)")
    else:
        print("[e2e]   WARN: inpaint failed for B")

    # === 方案 C: bubble涂白 + free CTD像素mask+inpaint ===
    print("\n[e2e] Scheme C: bubble white + free CTD pixel-mask inpaint...")
    print("[e2e]   Running CTD DBNet...")
    ctd_net = load_ctd_net()
    img_bgr = cv2.imdecode(np.fromfile(str(raw_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    t0 = time.perf_counter()
    shrink = ctd_shrink_map(ctd_net, img_bgr)
    ctd_time = time.perf_counter() - t0
    pixel_mask = pixel_mask_in_regions(shrink, free_boxes, thresh=0.1, dilate_iter=7, dilate_kernel=9)
    print(f"[e2e]   CTD done in {ctd_time:.1f}s, mask pixels={np.sum(pixel_mask>0)}")

    # 保存 CTD mask 可视化
    Image.fromarray(pixel_mask).save(OUT_DIR / "C_ctd_pixel_mask.png")

    t0 = time.perf_counter()
    inpainted_c = run_koharu_inpaint(client, raw_path, pixel_mask)
    inpaint_time_c = time.perf_counter() - t0
    if inpainted_c:
        if inpainted_c.size != (w, h):
            inpainted_c = inpainted_c.resize((w, h))
        fill_white_regions(inpainted_c, bubble_boxes)
        inpainted_c.save(OUT_DIR / "C_free_pixel_inpaint.png")
        print(f"[e2e]   saved C_free_pixel_inpaint.png (inpaint {inpaint_time_c:.1f}s)")
    else:
        print("[e2e]   WARN: inpaint failed for C")

    # === 生成对比拼图 ===
    print("\n[e2e] Generating comparison...")
    # 缩放便于查看
    target_h = 1200
    def resize_img(im):
        s = target_h / im.height
        return im.resize((int(im.width * s), target_h), Image.LANCZOS)

    panels = [
        ("Original", original),
        ("A: All Rect White (current)", img_a),
    ]
    if inpainted_b:
        panels.append(("B: Rect Mask + Inpaint", inpainted_b))
    if inpainted_c:
        panels.append(("C: CTD Pixel Mask + Inpaint (recommended)", inpainted_c))

    # 2x2 拼图
    cols = 2
    rows = (len(panels) + cols - 1) // cols
    pw = resize_img(panels[0][1]).width
    ph = target_h
    canvas = Image.new("RGB", (pw * cols, ph * rows + 40 * rows), (240, 240, 240))
    draw = ImageDraw.Draw(canvas)
    for i, (label, im) in enumerate(panels):
        r, c = divmod(i, cols)
        x = c * pw
        y = r * (ph + 40)
        canvas.paste(resize_img(im), (x, y + 30))
        draw.text((x + 10, y + 5), label, fill=(0, 0, 0))

    canvas.save(OUT_DIR / "comparison_2x2.png")
    print(f"[e2e] Saved comparison_2x2.png")

    # 保存元数据
    meta = {
        "page": PAGE["name"],
        "file": PAGE["file"],
        "image_size": [w, h],
        "n_bubble": len(bubble_boxes),
        "n_free": len(free_boxes),
        "ctd_time_s": round(ctd_time, 2),
        "inpaint_time_b_s": round(inpaint_time_b, 2) if inpainted_b else None,
        "inpaint_time_c_s": round(inpaint_time_c, 2) if inpainted_c else None,
        "pixel_mask_pixels": int(np.sum(pixel_mask > 0)),
        "rect_mask_pixels": int(np.sum(rect_mask > 0)),
        "schemes": ["A_all_rect_white", "B_free_rect_inpaint", "C_free_pixel_inpaint"],
    }
    with open(OUT_DIR / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("\n[e2e] Done!")
    print(f"[e2e] CTD mask pixels: {meta['pixel_mask_pixels']}")
    print(f"[e2e] Rect mask pixels: {meta['rect_mask_pixels']}")
    print(f"[e2e] Mask size ratio: {meta['pixel_mask_pixels']/max(1,meta['rect_mask_pixels'])*100:.1f}%")


if __name__ == "__main__":
    main()
