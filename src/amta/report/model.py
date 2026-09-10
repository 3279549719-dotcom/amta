"""报告工具数据模型 — PageReport / StageOutput / ReportResult + 构造校验。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StageOutput:
    """一个阶段的输出，自描述：我叫什么、我有什么数据、怎么画一格、要不要叠图。"""
    key: str
    label: str
    cells: dict[str, Any]
    render_cell: Callable[[Any], str]
    render_overlay: Callable[..., None] | None = None
    page_artifact: Any = None

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            raise ValueError("StageOutput.key 不能为空")
        if not self.label or not self.label.strip():
            raise ValueError("StageOutput.label 不能为空")
        if self.cells is None:
            self.cells = {}


@dataclass
class PageReport:
    """一页报告的全部输入。构造时校验，不把脏数据放进引擎。"""
    page_idx: int
    raw_image: str | Path
    stages: list[StageOutput]

    def __post_init__(self) -> None:
        p = Path(self.raw_image)
        if not p.exists():
            raise ValueError(f"原图不存在: {p}")
        if not self.stages:
            raise ValueError("PageReport.stages 不能为空")
        keys = [s.key for s in self.stages]
        dup = {k for k in keys if keys.count(k) > 1}
        if dup:
            raise ValueError(f"StageOutput.key 重复: {dup}")

    @property
    def all_region_ids(self) -> list[str]:
        """所有阶段的区域并集（保持首次出现顺序）。"""
        seen: list[str] = []
        for s in self.stages:
            for rid in s.cells:
                if rid not in seen:
                    seen.append(rid)
        return seen


@dataclass
class ReportResult:
    """可观测返回：不只是 HTML，还有渲染过程中发生了什么。"""
    html: str
    page_idx: int
    stages_rendered: list[str] = field(default_factory=list)
    regions_total: int = 0
    regions_aligned: int = 0
    regions_dropped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    render_time_ms: float = 0.0
