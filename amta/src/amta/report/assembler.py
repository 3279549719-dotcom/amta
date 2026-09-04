"""数据组装器 — 从 artifacts JSON 读取各阶段产物，组装成 PageReport。

这是唯一碰 IO 的层。引擎(render_report)是纯函数，不关心数据从哪来。
支持全管线 5 阶段: detect / ocr / filter / translate / inpaint / typeset。
缺失的阶段自动跳过（报告里自然少一列）。
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from .model import PageReport
from .stages.detect import from_detection
from .stages.ocr import from_canon
from .stages.filter import from_detection_and_canon
from .stages.translate import from_translation
from .stages.inpaint import from_inpaint
from .stages.typeset import from_typeset


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _resolve_image(artifacts_dir: Path | None, file_path: Path | None,
                   relative_name: str) -> Image.Image | None:
    """解析相对路径的图片，返回 PIL Image；不存在返回 None。"""
    if not relative_name:
        return None
    if artifacts_dir:
        p = Path(artifacts_dir) / relative_name
    elif file_path:
        p = Path(file_path).parent / relative_name
    else:
        return None
    if not p.exists():
        return None
    return Image.open(p).convert("RGB")


def load_page_report(
    page_idx: int,
    raw_image: str | Path,
    detection_path: str | Path | None = None,
    canon_path: str | Path | None = None,
    translation_path: str | Path | None = None,
    inpaint_path: str | Path | None = None,
    typeset_path: str | Path | None = None,
    artifacts_dir: str | Path | None = None,
) -> PageReport:
    """从各阶段 artifact 路径加载数据，组装 PageReport。

    缺失的阶段会被跳过（不报错，报告里自然少一列）。

    Args:
        artifacts_dir: artifact 所在目录，用于解析 inpaint/typeset 里的相对图片路径。
                       不传则从 inpaint_path/typeset_path 的父目录推导。
    """
    stages = []
    art_dir = Path(artifacts_dir) if artifacts_dir else None

    det = _load_json(Path(detection_path)) if detection_path else {}
    canon = _load_json(Path(canon_path)) if canon_path else {}
    trans = _load_json(Path(translation_path)) if translation_path else {}
    inpaint = _load_json(Path(inpaint_path)) if inpaint_path else {}
    typeset = _load_json(Path(typeset_path)) if typeset_path else {}

    if det:
        stages.append(from_detection(det))
    if canon:
        stages.append(from_canon(canon))
    if det and canon:
        stages.append(from_detection_and_canon(det, canon))
    if trans:
        stages.append(from_translation(trans))

    # inpaint: 需要 clean_image（相对 artifacts_dir）+ canon bboxes
    if inpaint and inpaint.get("clean_image"):
        clean_img = _resolve_image(art_dir, Path(inpaint_path) if inpaint_path else None,
                                   inpaint["clean_image"])
        if clean_img is not None:
            bboxes = {
                item["region_id"]: item["bbox"]
                for item in canon.get("items", [])
                if item.get("bbox") and item.get("region_id")
            }
            if bboxes:
                stages.append(from_inpaint(clean_img, bboxes))

    # typeset: layout + final_image
    if typeset and typeset.get("layout"):
        final_img = _resolve_image(art_dir, Path(typeset_path) if typeset_path else None,
                                   typeset.get("final_image", ""))
        stages.append(from_typeset(typeset, final_img))

    return PageReport(
        page_idx=page_idx,
        raw_image=raw_image,
        stages=stages,
    )


def load_from_workspace(
    work_id: str,
    page_idx: int,
    src_dir: str | Path,
    workspace_root: str | Path | None = None,
) -> PageReport:
    """从 workspace 约定路径加载：workspace/<work_id>/artifacts/page_<idx>_*.json。

    自动加载全部 6 个 artifact（detection/canon/translation/inpaint/typeset），
    缺失的阶段自动跳过。
    """
    from amta.paths import ROOT

    ws_root = Path(workspace_root) if workspace_root else ROOT / "workspace"
    art_dir = ws_root / work_id / "artifacts"
    page = f"page_{page_idx}"
    raw = Path(src_dir) / f"{page_idx}.jpg"

    return load_page_report(
        page_idx=page_idx,
        raw_image=raw,
        detection_path=art_dir / f"{page}_detection.json",
        canon_path=art_dir / f"{page}_canon.json",
        translation_path=art_dir / f"{page}_translation.json",
        inpaint_path=art_dir / f"{page}_inpaint.json",
        typeset_path=art_dir / f"{page}_typeset.json",
        artifacts_dir=art_dir,
    )
