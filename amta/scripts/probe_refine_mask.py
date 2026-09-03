"""鎺㈤拡鏂规 A: 妗嗗唴浼犵粺鏂规硶绮句慨 mask (绉绘 BallonsTranslator textmask.py + comic-translate content.py)銆?
鏍稿績鎬濊矾:
- 鏀惧純鍏ㄩ〉鍍忕礌绾у垎鍓? 妫€娴嬫宸茬粡澶熺敤
- 鍦ㄦ瘡涓?text_free 妗嗗唴鐢ㄤ紶缁熸柟娉曠簿淇? Otsu + 棰滆壊鐩存柟鍥?+ 杩為€氬煙杩囨护
- 瀵规瘮: 鐭╁舰 mask vs 绮句慨 mask 鐨勫儚绱犺鐩栫巼鍜屽彲瑙嗗寲

鏍锋湰: page_11(12.jpg), page_12(13.jpg) 鈥?闂鏈€鏄庢樉鐨勪袱椤?"""
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

SRC_DIR = Path(r"D:\鎴戠殑姹夊寲\姹夊寲浣滃搧\涓滄柟\鍗曠考鍋滅暀涔嬪湴")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "refine_mask_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    {"page_idx": 11, "file": "12.jpg", "name": "page_11"},
    {"page_idx": 12, "file": "13.jpg", "name": "page_12"},
]


# ========== 妗嗗唴绮句慨鏍稿績绠楁硶 ==========

def get_topk_colors(gray: np.ndarray, k: int = 3, color_var: int = 10) -> list[int]:
    """鍙栫伆搴︾洿鏂瑰浘 top-k 涓诲棰滆壊銆?""
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
    """杩為€氬煙鍒嗘瀽: 杩囨护澶皬銆佸お澶с€佽创杈圭殑缁勪欢, 淇濈暀鏍囩偣澶у皬鐨勫皬缁勪欢銆?""
    h, w = binary.shape[:2]
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        (binary > 0).astype(np.uint8), connectivity=8)
    if num_labels <= 1:
        return np.zeros_like(binary)

    result = np.zeros_like(binary)
    max_area = int(h * w * max_area_ratio) if h * w > 150 else h * w

    for i in range(1, num_labels):
        x, y, cw, ch, area = stats[i]
        # 澶皬: 鎺掗櫎鍣偣 (浣嗕繚鐣欐爣鐐瑰ぇ灏?
        if area < min_area and not (area >= 4 and cw <= 6 and ch <= 6):
            continue
        # 澶ぇ: 鎺掗櫎澶у潡鑳屾櫙
        if area > max_area:
            continue
        # 璐磋竟: 鎺掗櫎涓庢杈圭晫鐩歌繛鐨勮儗鏅?        if x < margin or y < margin or (x + cw) > (w - margin) or (y + ch) > (h - margin):
            continue
        result[labels == i] = 255

    return result


def refine_text_in_bbox(crop_img: np.ndarray, pad: int = 4) -> np.ndarray:
    """鍦ㄦ鍐呯簿淇枃瀛楀儚绱?mask銆?
    鏂规硶:
    1. Otsu 闃堝€?(鍚屾椂鑰冭檻榛戝瓧鍜岀櫧瀛?
    2. 鐏板害鐩存柟鍥?top-3 棰滆壊鑼冨洿
    3. 杩為€氬煙杩囨护
    4. 褰㈡€佸闂繍绠?+ 鑶ㄨ儉
    """
    if crop_img.size == 0:
        return np.zeros((0, 0), dtype=np.uint8)

    gray = cv2.cvtColor(crop_img, cv2.COLOR_RGB2GRAY)

    # 鏂规硶1: Otsu 闃堝€?(榛戝瓧 + 鐧藉瓧)
    _, binary_black = cv2.threshold(gray, 0, 255, cv2.THRESH_OTSU + cv2.THRESH_BINARY)
    binary_white = 255 - binary_black

    # 鏂规硶2: 鐏板害鐩存柟鍥?top-3 棰滆壊鑼冨洿
    top_colors = get_topk_colors(gray, k=3, color_var=10)
    color_masks = []
    for c in top_colors:
        lo = max(0, c - 30)
        hi = min(255, c + 30)
        color_masks.append(cv2.inRange(gray, lo, hi))

    # 鍚堝苟鎵€鏈夊€欓€? 閫愪釜鍋氳繛閫氬煙杩囨护
    text_mask = np.zeros_like(gray)
    candidates = [binary_black, binary_white] + color_masks
    for cand in candidates:
        filtered = filter_connected_components(cand, min_area=10, max_area_ratio=0.5, margin=1)
        text_mask = cv2.bitwise_or(text_mask, filtered)

    # 褰㈡€佸鍚庡鐞?    # 闂繍绠楄繛鎺ョ浉閭荤瑪鐢?    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    text_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, close_kernel)
    # 鑶ㄨ儉瑕嗙洊鎶楅敮榻胯竟缂?    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    text_mask = cv2.dilate(text_mask, dilate_kernel, iterations=1)
    # 濉礊
    text_mask = fill_holes(text_mask)

    return text_mask


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """濉厖 mask 鍐呴儴鐨勬礊銆?""
    if mask.size == 0:
        return mask
    h, w = mask.shape
    # 浠庤竟缂?flood fill 鑳屾櫙
    flood = mask.copy()
    mask_flood = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, mask_flood, (0, 0), 255)
    # 鑳屾櫙鍙栧弽 = 娲?+ 鏂囧瓧
    holes = cv2.bitwise_not(flood)
    return cv2.bitwise_or(mask, holes)


# ========== 鍏ㄩ〉 mask 鐢熸垚 ==========

def build_rect_mask(img_size: tuple, bboxes: list, pad: int = 4) -> np.ndarray:
    """鐭╁舰 mask (褰撳墠鏂规)銆?""
    h, w = img_size
    mask = np.zeros((h, w), dtype=np.uint8)
    for bb in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
        if x2 > x1 and y2 > y1:
            cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
    return mask


def build_refined_mask(img_rgb: np.ndarray, bboxes: list, pad: int = 4) -> np.ndarray:
    """绮句慨 mask (鏂规 A): 鍦ㄦ瘡涓鍐呯敤浼犵粺鏂规硶绮句慨銆?""
    h, w = img_rgb.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)

    for bb in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bb]
        # 鍔?padding 缁欑簿淇暀浣欓噺
        cx1, cy1 = max(0, x1 - pad), max(0, y1 - pad)
        cx2, cy2 = min(w, x2 + pad), min(h, y2 + pad)
        if cx2 <= cx1 or cy2 <= cy1:
            continue

        crop = img_rgb[cy1:cy2, cx1:cx2]
        crop_mask = refine_text_in_bbox(crop)

        if crop_mask.size > 0:
            # 鍙繚鐣欏師濮嬫鍐呯殑閮ㄥ垎 (闃叉 padding 鍖哄煙寮曞叆鑳屾櫙)
            # 浣嗙◢寰斁瀹戒竴鐐?(妗嗗唴 + 2px) 浠ヨ鐩栨枃瀛楄竟缂?            rx1, ry1 = x1 - cx1 - 2, y1 - cy1 - 2
            rx2, ry2 = x2 - cx1 + 2, y2 - cy1 + 2
            rx1, ry1 = max(0, rx1), max(0, ry1)
            rx2, ry2 = min(crop_mask.shape[1], rx2), min(crop_mask.shape[0], ry2)
            if rx2 > rx1 and ry2 > ry1:
                restricted = np.zeros_like(crop_mask)
                restricted[ry1:ry2, rx1:rx2] = crop_mask[ry1:ry2, rx1:rx2]
                mask[cy1:cy2, cx1:cx2] = cv2.bitwise_or(
                    mask[cy1:cy2, cx1:cx2], restricted)

    return mask


# ========== 鍙鍖?==========

def mask_overlay(img_rgb: np.ndarray, mask: np.ndarray, color: tuple = (255, 0, 0),
                 alpha: float = 0.4) -> np.ndarray:
    """mask 鍗婇€忔槑鍙犲姞鍦ㄥ師鍥句笂銆?""
    overlay = img_rgb.copy().astype(np.float32)
    mask_bin = (mask > 128).astype(np.float32)[:, :, np.newaxis]
    color_arr = np.array(color, dtype=np.float32).reshape(1, 1, 3)
    overlay = overlay * (1 - alpha * mask_bin) + color_arr * alpha * mask_bin
    return overlay.astype(np.uint8)


def make_comparison(img_rgb: np.ndarray, rect_mask: np.ndarray, refined_mask: np.ndarray,
                    title: str) -> Image.Image:
    """鐢熸垚瀵规瘮鍥? 鍘熷浘 | 鐭╁舰mask | 绮句慨mask | 宸紓鍥俱€?""
    h, w = img_rgb.shape[:2]
    target_h = 900
    scale = target_h / h

    def resize(im):
        new_w = int(im.width * scale) if hasattr(im, 'width') else int(im.shape[1] * scale)
        if hasattr(im, 'width'):
            return im.resize((new_w, target_h), Image.LANCZOS)
        return Image.fromarray(im).resize((new_w, target_h), Image.LANCZOS)

    # 鍥涗釜闈㈡澘
    panels = [
        ("Original", Image.fromarray(img_rgb)),
        ("Rect mask (current)", Image.fromarray(mask_overlay(img_rgb, rect_mask, (255, 0, 0)))),
        ("Refined mask (plan A)", Image.fromarray(mask_overlay(img_rgb, refined_mask, (0, 128, 255)))),
    ]

    # 宸紓鍥? 绾?鐭╁舰鐙湁, 钃?绮句慨鐙湁, 缁?閲嶅彔
    diff = np.zeros((h, w, 3), dtype=np.uint8)
    rect_bin = rect_mask > 128
    refined_bin = refined_mask > 128
    diff[rect_bin & ~refined_bin] = [255, 0, 0]    # 绾? 鐭╁舰杩囧害瑕嗙洊
    diff[~rect_bin & refined_bin] = [0, 0, 255]     # 钃? 绮句慨澶氳鐩?    diff[rect_bin & refined_bin] = [0, 255, 0]       # 缁? 閲嶅彔
    panels.append(("Diff (red=over, blue=under, green=match)", Image.fromarray(diff)))

    # 鎷兼帴 2x2
    pw = resize(panels[0][1]).width
    ph = target_h
    canvas = Image.new("RGB", (pw * 2, (ph + 30) * 2), (240, 240, 240))
    d = ImageDraw.Draw(canvas)
    for i, (label, im) in enumerate(panels):
        r, c = divmod(i, 2)
        x = c * pw
        y = r * (ph + 30)
        d.text((x + 8, y + 5), label, fill=(0, 0, 0))
        canvas.paste(resize(im), (x, y + 28))

    return canvas


# ========== 涓绘祦绋?==========

def main():
    print(f"[probe] Output: {OUT_DIR}")
    print(f"[probe] Plan A: 妗嗗唴浼犵粺鏂规硶绮句慨 mask")

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

        # 1. 鐭╁舰 mask (褰撳墠鏂规)
        t0 = time.perf_counter()
        rect_mask = build_rect_mask((h, w), free_boxes, pad=4)
        rect_time = time.perf_counter() - t0

        # 2. 绮句慨 mask (鏂规 A)
        t0 = time.perf_counter()
        refined_mask = build_refined_mask(img_rgb, free_boxes, pad=4)
        refined_time = time.perf_counter() - t0

        # 3. 閲忓寲瀵规瘮
        rect_pixels = int((rect_mask > 128).sum())
        refined_pixels = int((refined_mask > 128).sum())
        rect_ratio = rect_pixels / (h * w) * 100
        refined_ratio = refined_pixels / (h * w) * 100
        reduction = (1 - refined_pixels / rect_pixels) * 100 if rect_pixels > 0 else 0

        # IoU
        rect_bin = rect_mask > 128
        refined_bin = refined_mask > 128
        intersection = (rect_bin & refined_bin).sum()
        union = (rect_bin | refined_bin).sum()
        iou = intersection / union if union > 0 else 0

        print(f"  Rect mask:    {rect_pixels:>10,} px ({rect_ratio:.2f}%), time={rect_time:.3f}s")
        print(f"  Refined mask: {refined_pixels:>10,} px ({refined_ratio:.2f}%), time={refined_time:.3f}s")
        print(f"  Reduction:    {reduction:.1f}% (绮句慨姣旂煩褰㈠皯瑕嗙洊澶氬皯鍍忕礌)")
        print(f"  IoU:          {iou:.3f}")

        summary[page["name"]] = {
            "rect_pixels": rect_pixels,
            "refined_pixels": refined_pixels,
            "rect_ratio": round(rect_ratio, 2),
            "refined_ratio": round(refined_ratio, 2),
            "reduction_pct": round(reduction, 1),
            "iou": round(float(iou), 3),
            "free_boxes": len(free_boxes),
        }

        # 4. 淇濆瓨 mask
        Image.fromarray(rect_mask).save(OUT_DIR / f"{page['name']}_rect_mask.png")
        Image.fromarray(refined_mask).save(OUT_DIR / f"{page['name']}_refined_mask.png")

        # 5. 鐢熸垚瀵规瘮鍥?        comparison = make_comparison(img_rgb, rect_mask, refined_mask, page["name"])
        comparison.save(OUT_DIR / f"{page['name']}_comparison.png")
        print("  comparison saved")

    # 淇濆瓨 summary
    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n[probe] Done.")
    print(f"[probe] 鍏抽敭鎸囨爣: 绮句慨 mask 姣旂煩褰?mask 灏戣鐩?{summary['page_11']['reduction_pct']}% / {summary['page_12']['reduction_pct']}% 鍍忕礌")


if __name__ == "__main__":
    main()
