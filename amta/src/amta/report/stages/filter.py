"""filter 阶段适配器 — 对比 detection 与 canon，展示筛选留痕。

conf=0.7 在 detect 阶段已砍低置信框；OCR 规则过滤(pure_punct/pure_number/
extreme_aspect/edge_box)会再砍一部分。本阶段对比 detection blocks 与 canon items，
标出哪些框通过了筛选、哪些被 OCR 规则砍掉。
"""
from __future__ import annotations

from typing import Any

from ..model import StageOutput


def render_cell(data: Any) -> str:
    if not data:
        return '<span style="color:#999">—</span>'
    status = data.get("status", "unknown")
    reason = data.get("reason", "")
    if status == "kept":
        return '<span style="color:#16a34a;font-weight:600">✓ 保留</span>'
    elif status == "cut":
        return f'<span style="color:#dc2626;font-weight:600">✗ 砍掉</span> <span style="font-size:10px;color:#666">{reason}</span>'
    return status


def from_detection_and_canon(det: dict, canon: dict) -> StageOutput:
    """对比 detection 和 canon，生成筛选留痕。"""
    canon_ids = {item.get("region_id") for item in canon.get("items", [])}
    cells: dict[str, Any] = {}

    for b in det.get("blocks", []):
        rid = b.get("region_id", "")
        if not rid:
            continue
        if rid in canon_ids:
            cells[rid] = {"status": "kept", "reason": ""}
        else:
            cells[rid] = {"status": "cut", "reason": "OCR规则过滤"}

    return StageOutput(
        key="filter",
        label="筛选留痕",
        cells=cells,
        render_cell=render_cell,
    )
