"""探针: CTD DBNet 概率热图 → 像素级 text mask，与当前矩形 mask 对比。

一次性探针，跑完看效果。输出到 output/tmp/ctd_mask_probe/。

对比维度:
1. 矩形 mask (当前 04_inpaint._build_mask: bbox + pad=4)
2. CTD DBNet 热图 mask (阈值化 + 膨胀)
3. 叠加可视化 (红=矩形, 蓝=CTD, 紫=重叠)
4. 统计: mask 像素数、覆盖率、重叠率
"""
from __future__ import annotations

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

CTD_MODEL = ROOT / "models" / "CTD" / "comictextdetector.pt.onnx"
SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "ctd_mask_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    {"file": "21.jpg", "page_idx": 20, "name": "page_20"},
    {"file": "22.jpg", "page_idx": 21, "name": "page_21"},
]


def load_ctd_net():
    """加载 CTD ONNX 模型 (OpenCV DNN 后端)。"""
    net = cv2.dnn.readNetFromONNX(str(CTD_MODEL))
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return net


def ctd_infer_with_heatmap(net, img_bgr, input_size=1024):
    """CTD 推理，返回 (blocks, shrink_map_orig, threshold_map_orig)。

    shrink_map: DBNet 收缩文本核概率图
    threshold_map: DBNet 阈值图 (对文字边界更敏感)
    """
    im_h, im_w = img_bgr.shape[:2]
    img_in, ratio, (dw, dh) = letterbox(img_bgr, new_shape=(input_size, input_size), auto=False, stride=64)

    blob = cv2.dnn.blobFromImage(img_in, scalefactor=1.0 / 255.0, size=(input_size, input_size), swapRB=False)
    net.setInput(blob)
    outputs = net.forward(net.getUnconnectedOutLayersNames())

    _blks, mask, lines_map = outputs[0], outputs[1], outputs[2]
    if mask.ndim == 4 and mask.shape[1] == 2:
        mask, lines_map = lines_map, mask

    # 裁剪 padding
    dh_int = int(round(dh))
    dw_int = int(round(dw))
    if mask.ndim == 4:
        mask = mask[0, 0]
    mask = mask[:mask.shape[0] - dh_int * 2, :mask.shape[1] - dw_int * 2]
    lines_map_crop = lines_map[:, :, :lines_map.shape[2] - dh_int * 2, :lines_map.shape[3] - dw_int * 2]

    # DBNet 后提取四边形
    seg_rep = SegDetectorRepresenter(thresh=0.3, box_thresh=0.6)
    boxes, scores = seg_rep(lines_map_crop, height=im_h, width=im_w)
    idx = np.where(scores[0] > 0.6)
    quads = boxes[0][idx]
    quad_scores = scores[0][idx]

    blocks = []
    for i, (quad, score) in enumerate(zip(quads, quad_scores)):
        bbox = [float(quad[:, 0].min()), float(quad[:, 1].min()),
                float(quad[:, 0].max()), float(quad[:, 1].max())]
        if bbox[2] - bbox[0] < 3 or bbox[3] - bbox[1] < 3:
            continue
        blocks.append({"bbox": bbox, "quad": quad.tolist(), "score": float(score)})

    # shrink_map (第0通道) 和 threshold_map (第1通道) → resize 回原图
    shrink = lines_map_crop[0, 0]
    thresh_map = lines_map_crop[0, 1] if lines_map_crop.shape[1] > 1 else shrink
    shrink_orig = cv2.resize(shrink, (im_w, im_h), interpolation=cv2.INTER_LINEAR)
    thresh_orig = cv2.resize(thresh_map, (im_w, im_h), interpolation=cv2.INTER_LINEAR)
    shrink_orig = np.clip(shrink_orig, 0, 1).astype(np.float32)
    thresh_orig = np.clip(thresh_orig, 0, 1).astype(np.float32)

    return blocks, shrink_orig, thresh_orig


def heatmap_to_mask(heatmap, thresh=0.3, dilate_iter=2, dilate_kernel=3):
    """DBNet 概率热图 → 二值 mask (255=文字, 0=背景)。"""
    binary = (heatmap > thresh).astype(np.uint8) * 255
    if dilate_iter > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_kernel, dilate_kernel))
        binary = cv2.dilate(binary, kernel, iterations=dilate_iter)
    return binary


def heatmap_to_mask_v2(shrink_map, threshold_map, thresh=0.2, dilate_iter=4, dilate_kernel=5):
    """改进版: shrink_map 低阈值 + 大膨胀，模拟 DBNet unclip 效果。

    DBNet 原理: shrink_map 是文本核(收缩)，需要膨胀回完整文字区域。
    这里用大核膨胀近似 unclip_ratio=1.5~2.0 的效果。
    """
    binary = (shrink_map > thresh).astype(np.uint8) * 255
    if dilate_iter > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_kernel, dilate_kernel))
        binary = cv2.dilate(binary, kernel, iterations=dilate_iter)
    return binary


def rect_mask_from_bboxes(img_size, bboxes, pad=4):
    """当前做法: 矩形 + pad。返回 255=文字区域。"""
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


def overlay_mask(img_rgb, mask, color, alpha=0.4):
    """在原图上叠加半透明 mask。color=(R,G,B)。"""
    overlay = img_rgb.copy()
    mask_bool = mask > 0
    overlay[mask_bool] = (1 - alpha) * overlay[mask_bool] + alpha * np.array(color)
    return overlay


def make_comparison(img_rgb, rect_m, ctd_m, out_path):
    """生成 2x2 对比图。"""
    h, w = img_rgb.shape[:2]
    # 缩放便于查看
    scale = min(1.0, 1200 / max(h, w))
    new_h, new_w = int(h * scale), int(w * scale)

    def resize(arr):
        if arr.ndim == 2:
            return cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
        return cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)

    img_s = resize(img_rgb)
    rect_s = resize(rect_m)
    ctd_s = resize(ctd_m)

    # 1. 原图 + 矩形mask (红)
    panel1 = overlay_mask(img_s, rect_s, (255, 0, 0), alpha=0.4)
    # 2. 原图 + CTD mask (蓝)
    panel2 = overlay_mask(img_s, ctd_s, (0, 0, 255), alpha=0.4)
    # 3. 差异: 红=仅矩形, 蓝=仅CTD, 绿=重叠
    diff = np.zeros_like(img_s)
    only_rect = (rect_s > 0) & (ctd_s == 0)
    only_ctd = (rect_s == 0) & (ctd_s > 0)
    both = (rect_s > 0) & (ctd_s > 0)
    diff[only_rect] = (255, 0, 0)
    diff[only_ctd] = (0, 0, 255)
    diff[both] = (0, 255, 0)
    # 4. CTD 热图 (伪彩色)
    heatmap_vis = cv2.applyColorMap((ctd_s).astype(np.uint8), cv2.COLORMAP_JET)
    heatmap_vis = cv2.cvtColor(heatmap_vis, cv2.COLOR_BGR2RGB)

    # 拼 2x2
    top = np.hstack([panel1, panel2])
    bot = np.hstack([diff, heatmap_vis])
    full = np.vstack([top, bot])

    # 加标签
    from PIL import Image as PILImage, ImageDraw as PILDraw
    pil = PILImage.fromarray(full)
    draw = PILDraw.Draw(pil)
    draw.text((10, 5), "Rect Mask (current)", fill=(255, 255, 255))
    draw.text((new_w + 10, 5), "CTD DBNet Mask", fill=(255, 255, 255))
    draw.text((10, new_h + 5), "Diff: R=rect-only B=ctd-only G=both", fill=(255, 255, 255))
    draw.text((new_w + 10, new_h + 5), "CTD Heatmap (thresh=0.3+dilate)", fill=(255, 255, 255))
    pil.save(out_path)


def main():
    net = load_ctd_net()
    print(f"[probe] CTD model loaded: {CTD_MODEL}")
    print(f"[probe] Output dir: {OUT_DIR}")

    summary = []

    for page in PAGES:
        img_path = SRC_DIR / page["file"]
        det_path = ARTIFACTS_DIR / f"{page['name']}_detection.json"

        print(f"\n=== {page['name']} ({page['file']}) ===")

        # 读原图
        img_bgr = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w = img_rgb.shape[:2]
        print(f"  image: {w}x{h}")

        # 读 RT-DETR-v2 检测结果
        with open(det_path, "r", encoding="utf-8") as f:
            det = json.load(f)
        rtdetr_boxes = [b["bbox"] for b in det["blocks"]]
        print(f"  RT-DETR-v2 boxes: {len(rtdetr_boxes)}")

        # 矩形 mask (当前做法)
        rect_m = rect_mask_from_bboxes((w, h), rtdetr_boxes, pad=4)
        rect_pixels = int(np.sum(rect_m > 0))

        # CTD 推理 + 热图
        t0 = time.perf_counter()
        ctd_blocks, shrink_map, thresh_map = ctd_infer_with_heatmap(net, img_bgr)
        ctd_time = time.perf_counter() - t0
        print(f"  CTD infer: {ctd_time:.2f}s, blocks: {len(ctd_blocks)}")

        # 多组参数生成 mask
        mask_variants = {
            "v1_t03_d3x2": heatmap_to_mask(shrink_map, thresh=0.3, dilate_iter=2, dilate_kernel=3),
            "v2_t015_d5x4": heatmap_to_mask_v2(shrink_map, thresh_map, thresh=0.15, dilate_iter=4, dilate_kernel=5),
            "v3_t01_d7x5": heatmap_to_mask_v2(shrink_map, thresh_map, thresh=0.1, dilate_iter=5, dilate_kernel=7),
            "v4_threshmap": heatmap_to_mask(thresh_map, thresh=0.3, dilate_iter=3, dilate_kernel=5),
        }

        total_pixels = h * w
        page_stats = {"page": page["name"], "file": page["file"], "image_size": [w, h],
                      "rtdetr_boxes": len(rtdetr_boxes), "ctd_blocks": len(ctd_blocks),
                      "ctd_infer_s": round(ctd_time, 2),
                      "rect_mask_pixels": rect_pixels, "rect_coverage": round(rect_pixels / total_pixels, 4),
                      "variants": {}}

        print(f"  rect mask: {rect_pixels} px ({page_stats['rect_coverage']*100:.2f}%)")

        for vname, ctd_m in mask_variants.items():
            ctd_pixels = int(np.sum(ctd_m > 0))
            overlap = int(np.sum((rect_m > 0) & (ctd_m > 0)))
            iou = overlap / max(1, rect_pixels + ctd_pixels - overlap)
            page_stats["variants"][vname] = {
                "pixels": ctd_pixels,
                "coverage": round(ctd_pixels / total_pixels, 4),
                "overlap_with_rect": overlap,
                "iou_with_rect": round(iou, 4),
            }
            print(f"  {vname}: {ctd_pixels} px ({ctd_pixels/total_pixels*100:.2f}%), IoU={iou:.4f}")
            cv2.imwrite(str(OUT_DIR / f"{page['name']}_{vname}_mask.png"), ctd_m)

        summary.append(page_stats)

        # 保存热图
        cv2.imwrite(str(OUT_DIR / f"{page['name']}_shrink_heatmap.png"),
                    cv2.applyColorMap((shrink_map * 255).astype(np.uint8), cv2.COLORMAP_JET))
        cv2.imwrite(str(OUT_DIR / f"{page['name']}_thresh_heatmap.png"),
                    cv2.applyColorMap((thresh_map * 255).astype(np.uint8), cv2.COLORMAP_JET))

        # 用最好的 v2 生成对比图 (低阈值大膨胀)
        ctd_m_best = mask_variants["v2_t015_d5x4"]
        comp_path = OUT_DIR / f"{page['name']}_comparison.png"
        make_comparison(img_rgb, rect_m, ctd_m_best, comp_path)
        print(f"  comparison saved: {comp_path}")

        # 保存 CTD 检测框 (供对比检测效果)
        ctd_det_path = OUT_DIR / f"{page['name']}_ctd_detection.json"
        with open(ctd_det_path, "w", encoding="utf-8") as f:
            json.dump({"blocks": ctd_blocks, "n_blocks": len(ctd_blocks)}, f, ensure_ascii=False, indent=2)

    # 保存汇总
    summary_path = OUT_DIR / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[probe] Summary saved: {summary_path}")
    print("[probe] Done.")


if __name__ == "__main__":
    main()
