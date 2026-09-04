"""框内文字像素精修模块 (Plan A)。

核心思路: 放弃全页像素级分割, 检测框已经够用。在每个 text_free 框内
用传统图像处理 (Otsu + 颜色直方图 + 连通域过滤) 精修出文字像素。

移植自 BallonsTranslator textmask.py + comic-translate content.py 的生产级实现。

用法:
    from amta.text_mask_refiner import refine_text_mask
    mask = refine_text_mask(img_rgb, free_bboxes, pad=4)
"""
from __future__ import annotations

import cv2
import numpy as np


def get_topk_colors(gray: np.ndarray, k: int = 3, color_var: int = 10) -> list[int]:
    """取灰度直方图 top-k 主导颜色。"""
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    idx = np.argsort(hist)[::-1]
    top_colors = [int(idx[0])]
    bin_tol = hist.sum() * 0.001
    for color in idx[1:]:
        color = int(color)
        if hist[color] < bin_tol:
            break
        if min(abs(c - color) for c in top_colors) > color_var:
            top_colors.append(color)
        if len(top_colors) >= k:
            break
    return top_colors


def filter_connected_components(binary: np.ndarray, min_area: int = 10,
                                 max_area_ratio: float = 0.5, margin: int = 1) -> np.ndarray:
    """连通域分析: 过滤太小、太大、贴边的组件, 保留标点大小的小组件。"""
    h, w = binary.shape[:2]
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        (binary > 0).astype(np.uint8), connectivity=8)
    if num_labels <= 1:
        return np.zeros_like(binary)

    result = np.zeros_like(binary)
    max_area = int(h * w * max_area_ratio) if h * w > 150 else h * w

    for i in range(1, num_labels):
        x, y, cw, ch, area = stats[i]
        # 太小: 排除噪点 (但保留标点大小)
        if area < min_area and not (area >= 4 and cw <= 6 and ch <= 6):
            continue
        # 太大: 排除大块背景
        if area > max_area:
            continue
        # 贴边: 排除与框边界相连的背景
        if x < margin or y < margin or (x + cw) > (w - margin) or (y + ch) > (h - margin):
            continue
        result[labels == i] = 255

    return result


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """填充 mask 内部的洞。"""
    if mask.size == 0:
        return mask
    h, w = mask.shape
    flood = mask.copy()
    mask_flood = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, mask_flood, (0, 0), 255)
    holes = cv2.bitwise_not(flood)
    return cv2.bitwise_or(mask, holes)


def refine_text_in_bbox(crop_img: np.ndarray) -> np.ndarray:
    """在框内精修文字像素 mask。

    方法:
    1. Otsu 阈值 (同时考虑黑字和白字)
    2. 灰度直方图 top-3 颜色范围
    3. 连通域过滤
    4. 形态学闭运算 + 膨胀 + 填洞
    """
    if crop_img.size == 0:
        return np.zeros((0, 0), dtype=np.uint8)

    gray = cv2.cvtColor(crop_img, cv2.COLOR_RGB2GRAY)

    # 方法1: Otsu 阈值 (黑字 + 白字)
    _, binary_black = cv2.threshold(gray, 0, 255, cv2.THRESH_OTSU + cv2.THRESH_BINARY)
    binary_white = 255 - binary_black

    # 方法2: 灰度直方图 top-3 颜色范围
    top_colors = get_topk_colors(gray, k=3, color_var=10)
    color_masks = []
    for c in top_colors:
        lo = max(0, c - 30)
        hi = min(255, c + 30)
        color_masks.append(cv2.inRange(gray, lo, hi))

    # 合并所有候选, 逐个做连通域过滤
    text_mask = np.zeros_like(gray)
    candidates = [binary_black, binary_white] + color_masks
    for cand in candidates:
        filtered = filter_connected_components(cand, min_area=10, max_area_ratio=0.5, margin=1)
        text_mask = cv2.bitwise_or(text_mask, filtered)

    # 形态学后处理
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    text_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, close_kernel)
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    text_mask = cv2.dilate(text_mask, dilate_kernel, iterations=1)
    text_mask = fill_holes(text_mask)

    return text_mask


def refine_text_mask(img_rgb: np.ndarray, bboxes: list[list[float]],
                      pad: int = 4) -> np.ndarray:
    """对全页的 text_free 框生成精修像素级 mask。

    Args:
        img_rgb: 全页 RGB 图像 (H, W, 3)
        bboxes: text_free 框列表 [[x1, y1, x2, y2], ...]
        pad: 框外扩像素 (给精修留余量)

    Returns:
        全页 mask (H, W), 255=文字像素, 0=背景
    """
    h, w = img_rgb.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)

    for bb in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bb]
        # 加 padding 给精修留余量
        cx1, cy1 = max(0, x1 - pad), max(0, y1 - pad)
        cx2, cy2 = min(w, x2 + pad), min(h, y2 + pad)
        if cx2 <= cx1 or cy2 <= cy1:
            continue

        crop = img_rgb[cy1:cy2, cx1:cx2]
        crop_mask = refine_text_in_bbox(crop)

        if crop_mask.size > 0:
            # 只保留原始框内 + 2px 的部分 (防止 padding 区域引入背景)
            rx1, ry1 = x1 - cx1 - 2, y1 - cy1 - 2
            rx2, ry2 = x2 - cx1 + 2, y2 - cy1 + 2
            rx1, ry1 = max(0, rx1), max(0, ry1)
            rx2, ry2 = min(crop_mask.shape[1], rx2), min(crop_mask.shape[0], ry2)
            if rx2 > rx1 and ry2 > ry1:
                restricted = np.zeros_like(crop_mask)
                restricted[ry1:ry2, rx1:rx2] = crop_mask[ry1:ry2, rx1:rx2]
                mask[cy1:cy2, cx1:cx2] = cv2.bitwise_or(
                    mask[cy1:cy2, cx1:cx2], restricted)

    return mask


def build_rect_mask(img_size: tuple[int, int], bboxes: list[list[float]],
                    pad: int = 4) -> np.ndarray:
    """矩形 mask (当前默认方案, 用于对比和回退)。"""
    w, h = img_size
    mask = np.zeros((h, w), dtype=np.uint8)
    for bb in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
        if x2 > x1 and y2 > y1:
            cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
    return mask