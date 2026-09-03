"""探针: 框外字(overlay_text)检测对比 — RT-DETR-v2 vs CTD。

重点: 框内字直接涂白即可, 框外字才需要像素级 mask。
对比两个检测器对框外字的召回率, 并展示 CTD 像素 mask 在框外字上的效果。

样本: page_13 (14.jpg), page_14 (15.jpg) — 各有 4 个 text_free
输出: output/tmp/overlay_probe/
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from ctd_detector import letterbox, SegDetectorRepresenter  # noqa: E402
from detect_rtdetr import RTDetrDetector  # noqa: E402

CTD_MODEL = ROOT / "models" / "CTD" / "comictextdetector.pt.onnx"
SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "overlay_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    {"page_idx": 13, "file": "14.jpg", "name": "page_13"},
    {"page_idx": 14, "file": "15.jpg", "name": "page_14"},
]

# 颜色
COLOR_BUBBLE = (0, 200, 0)    # 绿 - 框内字
COLOR_FREE = (0, 0, 255)      # 红 - 框外字
COLOR_CTD = (255, 100, 0)     # 橙 - CTD 检测框
COLOR_MASK = (255, 0, 255)    # 紫 - CTD 像素 mask


def load_ctd_net():
    net = cv2.dnn.readNetFromONNX(str(CTD_MODEL))
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return net


def ctd_infer(net, img_bgr, input_size=1024):
    """CTD 推理, 返回 (blocks, shrink_map_orig)。"""
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
    if mask.ndim == 4:
        mask = mask[0, 0]
    lines_map_crop = lines_map[:, :, :lines_map.shape[2] - dh_int * 2, :lines_map.shape[3] - dw_int * 2]
    seg_rep = SegDetectorRepresenter(thresh=0.3, box_thresh=0.6)
    boxes, scores = seg_rep(lines_map_crop, height=im_h, width=im_w)
    idx = np.where(scores[0] > 0.6)
    quads = boxes[0][idx]
    quad_scores = scores[0][idx]
    blocks = []
    for quad, score in zip(quads, quad_scores):
        bbox = [float(quad[:, 0].min()), float(quad[:, 1].min()),
                float(quad[:, 0].max()), float(quad[:, 1].max())]
        if bbox[2] - bbox[0] < 3 or bbox[3] - bbox[1] < 3:
            continue
        blocks.append({"bbox": bbox, "quad": quad.tolist(), "score": float(score)})
    shrink = lines_map_crop[0, 0]
    shrink_orig = cv2.resize(shrink, (im_w, im_h), interpolation=cv2.INTER_LINEAR)
    shrink_orig = np.clip(shrink_orig, 0, 1).astype(np.float32)
    return blocks, shrink_orig


def ctd_mask(shrink_map, thresh=0.1, dilate_iter=7, dilate_kernel=9):
    """shrink_map → 像素级 mask (255=文字)。"""
    binary = (shrink_map > thresh).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_kernel, dilate_kernel))
    return cv2.dilate(binary, kernel, iterations=dilate_iter)


def draw_rtdetr(img, blocks):
    """画 RT-DETR-v2 检测框, 绿=框内, 红=框外。"""
    out = img.copy()
    for b in blocks:
        x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
        label = b.get("bubble_type", "text_bubble")
        color = COLOR_FREE if label == "text_free" else COLOR_BUBBLE
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 3)
        tag = "FREE" if label == "text_free" else "BUBBLE"
        cv2.putText(out, tag, (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    return out


def draw_ctd(img, blocks):
    """画 CTD 检测框 (橙色)。"""
    out = img.copy()
    for i, b in enumerate(blocks):
        x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), COLOR_CTD, 3)
        cv2.putText(out, str(i), (x1 + 3, y1 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLOR_CTD, 2)
    return out


def overlay_mask(img, mask, color=COLOR_MASK, alpha=0.5):
    """在原图上叠加半透明 mask。"""
    out = img.copy()
    m = mask > 0
    out[m] = (1 - alpha) * out[m] + alpha * np.array(color)
    return out


def crop_region(img, bbox, pad=20):
    """裁剪 bbox 区域 (带 padding)。"""
    h, w = img.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
    x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
    return img[y1:y2, x1:x2], (x1, y1, x2, y2)


def main():
    print(f"[overlay_probe] Output: {OUT_DIR}")

    # RT-DETR-v2 检测器
    rtdetr = RTDetrDetector(conf_threshold=0.7)
    ctd_net = load_ctd_net()
    print("[overlay_probe] Models loaded.")

    summary = []

    for page in PAGES:
        print(f"\n=== {page['name']} ({page['file']}) ===")
        img_path = SRC_DIR / page["file"]
        img_bgr = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w = img_rgb.shape[:2]

        # 1. RT-DETR-v2 结果 (从 artifacts 读)
        det_path = ARTIFACTS_DIR / f"{page['name']}_detection.json"
        with open(det_path, "r", encoding="utf-8") as f:
            det = json.load(f)
        rtdetr_blocks = det["blocks"]
        free_blocks = [b for b in rtdetr_blocks if b.get("bubble_type") == "text_free"]
        bubble_blocks = [b for b in rtdetr_blocks if b.get("bubble_type") == "text_bubble"]
        print(f"  RT-DETR-v2: {len(rtdetr_blocks)} boxes (bubble={len(bubble_blocks)}, free={len(free_blocks)})")

        # 2. CTD 推理
        t0 = time.perf_counter()
        ctd_blocks, shrink_map = ctd_infer(ctd_net, img_bgr)
        ctd_time = time.perf_counter() - t0
        print(f"  CTD: {len(ctd_blocks)} boxes ({ctd_time:.2f}s)")

        # 3. CTD 像素级 mask
        ctd_m = ctd_mask(shrink_map)

        # 4. 画对比图 (RT-DETR-v2 vs CTD 检测框)
        img_rtdetr = draw_rtdetr(img_rgb, rtdetr_blocks)
        img_ctd_boxes = draw_ctd(img_rgb, ctd_blocks)

        # 缩放拼接
        target_h = 1400
        def resize_to(im, th):
            s = th / im.shape[0]
            return cv2.resize(im, (int(im.shape[1] * s), th))
        combined = np.hstack([resize_to(img_rtdetr, target_h), resize_to(img_ctd_boxes, target_h)])
        cv2.imwrite(str(OUT_DIR / f"{page['name']}_detectors_comparison.png"),
                    cv2.cvtColor(combined, cv2.COLOR_RGB2BGR))

        # 5. 框外字区域放大对比: 矩形涂白 vs CTD 像素 mask
        for i, fb in enumerate(free_blocks):
            crop_orig, (cx1, cy1, cx2, cy2) = crop_region(img_rgb, fb["bbox"], pad=30)
            # 矩形涂白
            crop_rect = crop_orig.copy()
            x1, y1, x2, y2 = [int(v) for v in fb["bbox"]]
            local_box = [x1 - cx1, y1 - cy1, x2 - cx1, y2 - cy1]
            cv2.rectangle(crop_rect, (local_box[0], local_box[1]), (local_box[2], local_box[3]), (255, 255, 255), -1)
            # CTD 像素 mask (只取这个区域内的)
            crop_mask = ctd_m[cy1:cy2, cx1:cx2]
            crop_ctd = crop_orig.copy()
            crop_ctd[crop_mask > 0] = (255, 255, 255)
            # mask 叠加
            crop_overlay = overlay_mask(crop_orig, crop_mask)
            # 拼接
            h_c = crop_orig.shape[0]
            pad_bar = np.full((h_c, 4, 3), 128, dtype=np.uint8)
            row = np.hstack([crop_orig, pad_bar, crop_rect, pad_bar, crop_overlay, pad_bar, crop_ctd])
            cv2.imwrite(str(OUT_DIR / f"{page['name']}_free{i:02d}_comparison.png"),
                        cv2.cvtColor(row, cv2.COLOR_RGB2BGR))

        # 6. 全页 CTD mask 叠加图
        img_full_mask = overlay_mask(img_rgb, ctd_m)
        cv2.imwrite(str(OUT_DIR / f"{page['name']}_full_ctd_mask.png"),
                    cv2.cvtColor(img_full_mask, cv2.COLOR_RGB2BGR))

        # 7. 统计: CTD 框与 RT-DETR-v2 free 框的匹配
        matched = 0
        for fb in free_blocks:
            fbox = fb["bbox"]
            for cb in ctd_blocks:
                cbox = cb["bbox"]
                # IoU
                ix1 = max(fbox[0], cbox[0])
                iy1 = max(fbox[1], cbox[1])
                ix2 = min(fbox[2], cbox[2])
                iy2 = min(fbox[3], cbox[3])
                iw = max(0, ix2 - ix1)
                ih = max(0, iy2 - iy1)
                inter = iw * ih
                fa = (fbox[2] - fbox[0]) * (fbox[3] - fbox[1])
                ca = (cbox[2] - cbox[0]) * (cbox[3] - cbox[1])
                iou = inter / max(1, fa + ca - inter)
                if iou > 0.1:
                    matched += 1
                    break

        page_summary = {
            "page": page["name"],
            "file": page["file"],
            "rtdetr_total": len(rtdetr_blocks),
            "rtdetr_bubble": len(bubble_blocks),
            "rtdetr_free": len(free_blocks),
            "ctd_total": len(ctd_blocks),
            "ctd_time_s": round(ctd_time, 2),
            "free_boxes": [{"region_id": b["region_id"], "bbox": b["bbox"], "confidence": b.get("confidence", 0)} for b in free_blocks],
            "ctd_matched_free": matched,
        }
        summary.append(page_summary)
        print(f"  Free boxes matched by CTD: {matched}/{len(free_blocks)}")

    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[overlay_probe] Done. Summary: {OUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
