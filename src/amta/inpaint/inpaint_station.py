"""inpaint 工位库函数 — detection.json + raw 页 → clean 图 + inpaint 产物(Stage 4)。

从 scripts/04_inpaint.py 抽取，核心变更（ADR-029）：
- Koharu HTTP inpaint → 本地 lama-manga 推理（LocalLamaInpainter）
- 消除外部服务依赖，纯本地执行

策略：气泡内字用 CTD 像素 mask + LaMa 重建（不再矩形涂白）；
框外字按背景均匀度分流至填色或 LaMa。
"""
from __future__ import annotations

import io
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageChops, ImageDraw

from amta.common.paths import read_json, write_json
from amta.inpaint.ctd_text_mask import CtdTextMaskGenerator
from amta.inpaint.inpaint_strategy import FILL_WHITE, INPAINT, SKIP, plan_inpaint
from amta.inpaint.local_lama_inpainter import LocalLamaInpainter

# ---- 模块级单例：模型只加载一次 ----
_inpainter: LocalLamaInpainter | None = None


def _get_inpainter() -> LocalLamaInpainter:
    global _inpainter
    if _inpainter is None:
        # 自动检测设备：有 CUDA 用 GPU，否则用 CPU（禁止硬编码 device）
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _inpainter = LocalLamaInpainter(device=device, model_type="lama-manga")
    return _inpainter


# ---- 工具函数 ----

def _apply_fill_white(img: Image.Image, bbox: list, shrink: int = 8) -> None:
    """涂白气泡内文字。先将 bbox 向内收缩 shrink 像素，避免 detection 框超出气泡
    时涂掉框外的作者标记等内容。气泡内文字通常不贴边，收缩后仍能覆盖。"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img.width, x2), min(img.height, y2)
    if x2 <= x1 or y2 <= y1:
        return
    # 小框减少收缩量，不能为凑最小尺寸而涂到检测框外。
    dx = min(shrink, max(0, (x2 - x1 - 10) // 2))
    dy = min(shrink, max(0, (y2 - y1 - 10) // 2))
    ImageDraw.Draw(img).rectangle([x1 + dx, y1 + dy, x2 - dx - 1, y2 - dy - 1], fill=(255, 255, 255))


def _build_mask_image(img: Image.Image, bboxes: list[list], pad: int = 4) -> Image.Image:
    """构建 inpaint mask（PIL Image, L 模式）：白色=要修复区域，黑色=其余。

    ADR-033: 统一使用矩形 mask。text_mask_refiner（精修 mask）已移除——
    实验证明矩形 mask + Lama 效果可接受（10页83框，气泡无破坏，用户确认）。
    """
    w, h = img.size
    mask_np = np.zeros((h, w), dtype=np.uint8)
    for bbox in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bbox]
        x1 = max(0, x1 - pad); y1 = max(0, y1 - pad)
        x2 = min(w, x2 + pad); y2 = min(h, y2 + pad)
        mask_np[y1:y2, x1:x2] = 255
    return Image.fromarray(mask_np)


def _build_mask(img: Image.Image, bboxes: list[list], pad: int = 4) -> bytes:
    """兼容旧接口：构建 mask 并返回 PNG 编码字节（供实验探针使用）。"""
    mask_img = _build_mask_image(img, bboxes, pad=pad)
    buf = io.BytesIO()
    mask_img.save(buf, format="PNG")
    return buf.getvalue()

def _route_by_uniformity(img: Image.Image, bboxes: list[list],
                         uniform_std: float = 25.0,
                         bg_ksize: int = 15, thr: int = 10) -> tuple[Image.Image, list[list]]:
    """按背景均匀性分流：均匀背景直接填色，复杂背景送 LaMa。

    判据：原始灰度区域的标准差。std < uniform_std 说明区域接近纯色
    （白泡、纯色气泡），直接用 median 色覆盖文字像素，不需要 LaMa 重建。
    std >= uniform_std 说明背景有纹理（网点、渐变、画稿），送 LaMa。

    返回 (处理后的图, 复杂框列表)。
    """
    import cv2

    arr = np.array(img.convert("RGB")).copy()
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    complex_boxes = []

    kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    for bb in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1 = max(0, x1); y1 = max(0, y1)
        x2 = min(w, x2); y2 = min(h, y2)
        crop_gray = gray[y1:y2, x1:x2]
        crop_rgb = arr[y1:y2, x1:x2]
        if crop_gray.size == 0:
            continue

        # 局部背景估计 + 复杂度判断
        bg_gray = cv2.medianBlur(crop_gray, bg_ksize)
        # 复杂度：原始 crop 的标准差（median blur 后的会被磨平，用原始的）
        complexity = float(crop_gray.std())

        if complexity < uniform_std:
            # 均匀背景：直接填色
            diff = np.abs(crop_gray.astype(np.int16) - bg_gray.astype(np.int16))
            ink = (diff > thr).astype(np.uint8)
            ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kc, iterations=2)
            ink = cv2.dilate(ink, np.ones((3, 3), np.uint8), iterations=1)
            # 用 median 背景色填文字像素（按通道）
            bg_rgb = cv2.medianBlur(crop_rgb, bg_ksize)
            mask_bool = ink > 0
            crop_rgb[mask_bool] = bg_rgb[mask_bool]
        else:
            # 复杂背景：送 LaMa
            complex_boxes.append(bb)

    return Image.fromarray(arr), complex_boxes


def _pixel_diff_ratio(a: Image.Image, b: Image.Image) -> float:
    """clean vs raw 像素差异比例（>0 证明有擦除发生）。"""
    if a.size != b.size:
        return 1.0
    hist = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L").histogram()
    changed = sum(hist[1:])
    return round(changed / (a.width * a.height), 4)


# ---- 工位函数 ----

def run(work_id: str, det_path: Path, raw_page: Path, out_path: Path,
        clean_dir: Path | None = None, dry_run: bool = False,
        inpaint_engine: str = "lama-manga",
        trans_path: Path | None = None) -> dict:
    """单页 inpaint：detection.json + raw → clean.png + inpaint.json。

    Args:
        work_id: 工作区 ID
        det_path: detection.json 路径
        raw_page: 原始图片路径
        out_path: inpaint.json 输出路径
        clean_dir: clean 图输出目录（None 则不保存 clean 图）
        dry_run: 只规划不执行
        inpaint_engine: 引擎名（目前仅 "lama-manga"，保留参数供未来扩展）
    """
    det = read_json(det_path)
    raw_img = Image.open(raw_page).convert("RGB")
    img = raw_img.copy()
    regions = det.get("blocks") or det.get("regions") or []

    # 契约：只擦有译文的框——上游 translate 已经判断过哪些需要翻
    if trans_path and trans_path.exists():
        trans = read_json(trans_path)
        translations = trans.get("translations", {})
        keep_rids = {rid for rid, dst in translations.items() if dst and dst.strip()}
        regions = [r for r in regions if r.get("region_id") in keep_rids]

    plan = plan_inpaint(regions, det.get("image_meta"))

    filled = [p for p in plan if p["action"] == FILL_WHITE]
    inpaint_boxes = [p["bbox"] for p in plan if p["action"] == INPAINT]
    skipped = [p for p in plan if p["action"] == SKIP]

    clean_image_rel = ""

    if not dry_run and (filled or inpaint_boxes):
        # 框外字：均匀背景直接 median 填色，复杂背景留矩形 mask 给 LaMa
        complex_boxes: list[list] = []
        if inpaint_boxes:
            img, complex_boxes = _route_by_uniformity(img, inpaint_boxes)

        # 气泡字：用 CTD 像素级文字 mask（不再矩形涂白）
        bubble_mask_np: np.ndarray | None = None
        if filled:
            ctd_gen = CtdTextMaskGenerator.get()
            ctd_mask = ctd_gen.generate(img)
            ctd_arr = np.array(ctd_mask)
            # 只保留气泡 bbox 内的文字像素
            bubble_mask_np = np.zeros_like(ctd_arr)
            for p in filled:
                x1, y1, x2, y2 = [int(v) for v in p["bbox"]]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(img.width, x2), min(img.height, y2)
                if x2 > x1 and y2 > y1:
                    bubble_mask_np[y1:y2, x1:x2] = ctd_arr[y1:y2, x1:x2]

        # 合并所有需要 LaMa 的 mask：气泡文字像素 + 框外复杂矩形
        laMa_boxes = list(complex_boxes)
        if laMa_boxes or bubble_mask_np is not None and bubble_mask_np.any():
            w, h = img.size
            mask_np = np.zeros((h, w), dtype=np.uint8)
            for bb in laMa_boxes:
                x1, y1, x2, y2 = [int(v) for v in bb]
                x1 = max(0, x1 - 4); y1 = max(0, y1 - 4)
                x2 = min(w, x2 + 4); y2 = min(h, y2 + 4)
                mask_np[y1:y2, x1:x2] = 255
            if bubble_mask_np is not None and bubble_mask_np.any():
                mask_np = np.maximum(mask_np, bubble_mask_np)
            mask_img = Image.fromarray(mask_np)
            inpainter = _get_inpainter()
            inpainted = inpainter.inpaint(img, mask_img)
            if inpainted.size == img.size:
                img = inpainted

        if clean_dir:
            clean_dir.mkdir(parents=True, exist_ok=True)
            page_key = out_path.stem.removesuffix("_inpaint")
            clean_path = clean_dir / f"{page_key}_clean.png"
            img.save(clean_path)
            clean_image_rel = f"clean/{clean_path.name}"

    doc = {
        "work_id": work_id,
        "page": det.get("page", raw_page.stem),
        "actions": plan,
        "checks": {
            "filled": len(filled),
            "inpainted": len(inpaint_boxes),
            "skipped": len(skipped),
            "size_ok": True,
            "inpaint_engine": inpaint_engine,
            "pixel_diff_ratio": _pixel_diff_ratio(img, raw_img),
        },
        "clean_image": clean_image_rel,
        "dry_run": dry_run,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(out_path, doc)
    return doc
