"""segment 阶段适配器（预留空壳 — text segmentation 接入时实现）。"""
from __future__ import annotations

from typing import Any

from ..model import StageOutput


def render_cell(data: Any) -> str:
    return '<span style="color:#999">(待实现)</span>'


def from_segment(segment_data: dict) -> StageOutput:
    return StageOutput(
        key="segment",
        label="文本切分",
        cells={},
        render_cell=render_cell,
    )
