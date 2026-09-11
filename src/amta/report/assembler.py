"""数据组装器 — 从 artifacts JSON 读取各阶段产物，组装成 PageReport。

这是唯一碰 IO 的层。引擎(render_report)是纯函数，不关心数据从哪来。
支持全管线 5 阶段: detect / ocr / filter / translate / inpaint / typeset。
缺失的阶段自动跳过（报告里自然少一列）。

支持 stages_filter：只加载指定阶段，减少 IO 和报告体积。
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from amta.stores.artifact_store import ArtifactStore

from .model import PageReport
from .stages.detect import from_detection
from .stages.filter import from_detection_and_canon
from .stages.inpaint import from_inpaint
from .stages.ocr import from_canon
from .stages.translate import from_translation
from .stages.typeset import from_typeset

# 阶段名 → artifact 目录名的映射
_STAGE_TO_ARTIFACT = {
    "detect": "detection",
    "ocr": "canon",
    "translate": "translation",
    "inpaint": "inpaint",
    "typeset": "typeset",
}


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
    stages_filter: list[str] | None = None,
) -> PageReport:
    """从各阶段 artifact 路径加载数据，组装 PageReport。

    缺失的阶段会被跳过（不报错，报告里自然少一列）。

    Args:
        artifacts_dir: artifact 所在目录，用于解析 inpaint/typeset 里的相对图片路径。
        stages_filter: 只加载指定阶段（如 ["detect", "inpaint"]）。None 表示全部加载。
                       "raw" 表示只看原图（不加载任何 artifact 阶段）。
    """
    stages = []
    art_dir = Path(artifacts_dir) if artifacts_dir else None

    def _want(stage_name: str) -> bool:
        if stages_filter is None:
            return True
        return stage_name in stages_filter

    det = _load_json(Path(detection_path)) if detection_path else {}
    canon = _load_json(Path(canon_path)) if canon_path else {}
    trans = _load_json(Path(translation_path)) if translation_path else {}
    inpaint = _load_json(Path(inpaint_path)) if inpaint_path else {}
    typeset = _load_json(Path(typeset_path)) if typeset_path else {}

    if _want("detect") and det:
        stages.append(from_detection(det))
    if _want("ocr") and canon:
        stages.append(from_canon(canon))
    if _want("filter") and det and canon:
        stages.append(from_detection_and_canon(det, canon))
    if _want("translate") and trans:
        stages.append(from_translation(trans))

    # inpaint: 需要 clean_image（相对 artifacts_dir）+ canon bboxes
    if _want("inpaint") and inpaint and inpaint.get("clean_image"):
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
    if _want("typeset") and typeset and typeset.get("layout"):
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
    stages_filter: list[str] | None = None,
) -> PageReport:
    """从 workspace 约定路径加载：workspace/<work_id>/artifacts（目录即索引）。

    自动加载全部 6 个 artifact（detection/canon/translation/inpaint/typeset），
    各阶段先查新布局 <stage>/<page>.json、回退旧平铺 page_<idx>_<stage>.json，
    缺失的阶段自动跳过。

    stages_filter: 只加载指定阶段（如 ["detect", "inpaint"]）。None 表示全部。
    """
    from amta.common.paths import ROOT

    ws_root = Path(workspace_root) if workspace_root else ROOT / "workspace"
    art_dir = ws_root / work_id / "artifacts"
    page = f"page_{page_idx}"
    raw = Path(src_dir) / f"{page_idx}.jpg"
    store = ArtifactStore(art_dir)

    # 阶段依赖：某些阶段组装时需要其他阶段的数据
    # inpaint 需要 canon 的 bboxes；filter 需要 detect + canon
    _DEPENDENCIES = {
        "inpaint": ["ocr"],
        "filter": ["detect", "ocr"],
        "typeset": ["ocr", "translate", "inpaint"],
    }

    def _want(stage_name: str) -> bool:
        if stages_filter is None:
            return True
        if stage_name in stages_filter:
            return True
        # 被依赖的阶段也需要加载
        for requested in stages_filter:
            if stage_name in _DEPENDENCIES.get(requested, []):
                return True
        return False

    def _resolve(stage_name: str) -> Path | None:
        if not _want(stage_name):
            return None
        artifact_name = _STAGE_TO_ARTIFACT.get(stage_name)
        if artifact_name is None:
            return None
        return store.resolve(artifact_name, page)

    # 传给 load_page_report 的 filter 包含依赖阶段，确保数据齐全
    effective_filter = None
    if stages_filter is not None:
        effective_filter = set(stages_filter)
        for s in stages_filter:
            effective_filter.update(_DEPENDENCIES.get(s, []))
        effective_filter = list(effective_filter)

    return load_page_report(
        page_idx=page_idx,
        raw_image=raw,
        detection_path=_resolve("detect"),
        canon_path=_resolve("ocr"),
        translation_path=_resolve("translate"),
        inpaint_path=_resolve("inpaint"),
        typeset_path=_resolve("typeset"),
        artifacts_dir=art_dir,
        stages_filter=effective_filter,
    )
