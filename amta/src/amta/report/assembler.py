"""数据组装器 — 从 artifacts JSON 读取各阶段产物，组装成 PageReport。

这是唯一碰 IO 的层。引擎(render_report)是纯函数，不关心数据从哪来。
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import PageReport
from .stages.detect import from_detection
from .stages.ocr import from_canon
from .stages.filter import from_detection_and_canon
from .stages.translate import from_translation


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_page_report(
    page_idx: int,
    raw_image: str | Path,
    detection_path: str | Path | None = None,
    canon_path: str | Path | None = None,
    translation_path: str | Path | None = None,
) -> PageReport:
    """从各阶段 artifact 路径加载数据，组装 PageReport。

    缺失的阶段会被跳过（不报错，报告里自然少一列）。
    """
    stages = []

    det = _load_json(Path(detection_path)) if detection_path else {}
    canon = _load_json(Path(canon_path)) if canon_path else {}
    trans = _load_json(Path(translation_path)) if translation_path else {}

    if det:
        stages.append(from_detection(det))
    if canon:
        stages.append(from_canon(canon))
    if det and canon:
        stages.append(from_detection_and_canon(det, canon))
    if trans:
        stages.append(from_translation(trans))

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
    """从 workspace 约定路径加载：workspace/<work_id>/artifacts/page_<idx>_*.json。"""
    from amta.paths import ROOT

    ws_root = Path(workspace_root) if workspace_root else ROOT / "workspace"
    art_dir = ws_root / work_id / "artifacts"
    page = f"page_{page_idx}"
    raw = Path(src_dir) / f"{page_idx + 1}.jpg"

    return load_page_report(
        page_idx=page_idx,
        raw_image=raw,
        detection_path=art_dir / f"{page}_detection.json",
        canon_path=art_dir / f"{page}_canon.json",
        translation_path=art_dir / f"{page}_translation.json",
    )
