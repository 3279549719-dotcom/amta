"""mask 阶段适配器（预留空壳 — inpaint/masking 接入时实现）。"""
from __future__ import annotations

from typing import Any

from ..model import StageOutput


def render_cell(data: Any) -> str:
    return '<span style="color:#999">(待实现)</span>'


def from_mask(mask_data: dict) -> StageOutput:
    return StageOutput(
        key="mask",
        label="去字蒙版",
        cells={},
        render_cell=render_cell,
    )
