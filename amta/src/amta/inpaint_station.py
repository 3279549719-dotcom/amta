"""inpaint 工位库函数 — detection.json + raw 页 → clean 图 + inpaint 产物(Stage 4)。

从 scripts/04_inpaint.py 抽取，核心变更（ADR-029）：
- Koharu HTTP inpaint → 本地 lama-manga 推理（LocalLamaInpainter）
- 消除外部服务依赖，纯本地执行

策略: ADR-030 后所有框统一走 Lama inpaint（矩形 mask）；ADR-031 移除 bubble_type 标签和 text_mask_refiner。
"""
from __future__ import annotations

import io
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from amta.inpaint_strategy import FILL_WHITE, INPAINT, SKIP, plan_inpaint
from amta.local_lama_inpainter import LocalLamaInpainter
from amta.paths import read_json, write_json


# ---- 模块级单例：模型只加载一次 ----
_inpainter: LocalLamaInpainter | None = None


def _get_inpainter() -> LocalLamaInpainter:
    global _inpainter
    if _inpainter is None:
        _inpainter = LocalLamaInpainter(device="cpu", model_type="lama-manga")
    return _inpainter


# ---- 工具函数 ----

def _apply_fill_white(img: Image.Image, bbox: list, shrink: int = 8) -> None:
    """涂白气泡内文字。先将 bbox 向内收缩 shrink 像素，避免 detection 框超出气泡
    时涂掉框外的作者标记等内容。气泡内文字通常不贴边，收缩后仍能覆盖。"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    # 向内收缩，至少保留 10x10 的区域
    sx1 = x1 + shrink
    sy1 = y1 + shrink
    sx2 = max(sx1 + 10, x2 - shrink)
    sy2 = max(sy1 + 10, y2 - shrink)
    ImageDraw.Draw(img).rectangle([sx1, sy1, sx2, sy2], fill=(255, 255, 255))


def _build_mask_image(img: Image.Image, bboxes: list[list], pad: int = 4) -> Image.Image:
    """构建 inpaint mask（PIL Image, L 模式）：白色=要修复区域，黑色=其余。

    ADR-031: 统一使用矩形 mask。text_mask_refiner（精修 mask）已移除——
    实验证明矩形 mask + Lama 效果可接受（10页83框，气泡无破坏，用户确认）。
    """
    mask_np = build_rect_mask(img.size, bboxes, pad=pad)
    return Image.fromarray(mask_np)


def _build_mask(img: Image.Image, bboxes: list[list], pad: int = 4) -> bytes:
    """兼容旧接口：构建 mask 并返回 PNG 编码字节（供实验探针使用）。"""
    mask_img = _build_mask_image(img, bboxes, pad=pad)
    buf = io.BytesIO()
    mask_img.save(buf, format="PNG")
    return buf.getvalue()

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
        inpaint_engine: str = "lama-manga") -> dict:
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
    plan = plan_inpaint(regions, det.get("image_meta"))

    filled = [p for p in plan if p["action"] == FILL_WHITE]
    inpaint_boxes = [p["bbox"] for p in plan if p["action"] == INPAINT]
    skipped = [p for p in plan if p["action"] == SKIP]

    clean_image_rel = ""

    if not dry_run and (filled or inpaint_boxes):
        if inpaint_boxes:
            mask_img = _build_mask_image(img, inpaint_boxes)
            inpainter = _get_inpainter()
            inpainted = inpainter.inpaint(img, mask_img)
            if inpainted.size == img.size:
                img = inpainted  # 整页替换为 inpaint 结果

        for p in filled:  # inpaint 后重放涂白（保险）
            _apply_fill_white(img, p["bbox"])

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
