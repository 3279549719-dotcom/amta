"""编排器统一数据契约 — StationContext / StationResult / PipelineConfig / PipelineResult。

这是编排器与工位之间的 Interface（接口）：调用方（编排器）和实现方（工位）
都只需要知道这些数据结构，不需要知道对方的内部实现。

设计原则（codebase-design）：
- Interface 小：工位函数只接受一个 StationContext，返回一个 StationResult
- 配置与执行分离：工位配置放在 ctx.config 里，不散落在函数参数中
- 统一返回结构：所有工位返回相同的 StationResult，编排器不需要知道每个工位的细节
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 工位侧：输入 / 输出
# ---------------------------------------------------------------------------

@dataclass
class StationContext:
    """工位执行上下文 — 编排器传递给每个工位的统一输入。

    不管是 detect / ocr / translate / inpaint / typeset，工位函数都只接受这一个参数。
    工位需要的所有信息（原始图片、上游产物、配置、工作区路径）都从这里取。
    """
    work_id: str
    page: str               # 页键，如 "page_11"（1 基，与原图序号一致）
    page_idx: int           # 页号整数，如 11
    raw_image: Path         # 原始图片路径（N.jpg，1 基文件名）
    artifacts_dir: Path     # 产物目录（所有阶段的产物都落在这里）
    state_dir: Path         # 状态目录（work_state.json / pipeline_log.json / tickets.json 等）
    inputs: dict[str, Path] = field(default_factory=dict)
    # 上游产物路径，按阶段名索引，如 {"detect": Path("...page_11_detection.json")}
    config: dict[str, Any] = field(default_factory=dict)
    # 本阶段配置，如 {"engine": "hayai", "vlm_enabled": False, "rule_filter": False}


@dataclass
class StationResult:
    """工位执行结果 — 所有工位统一返回这个结构。

    编排器只需要看 status 和 output_artifact，不需要知道每个工位产出了什么具体内容。
    stats 里放阶段特定的统计数字（检测框数 / OCR 区域数 / 译文数等），供报告和日志用。
    """
    page: str
    stage: str
    status: str             # "ok" / "skipped" / "failed"
    output_artifact: Path | None = None
    duration_s: float = 0.0
    error: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)


# 工位函数签名：所有工位都长这样
StationFn = Callable[[StationContext], StationResult]


# ---------------------------------------------------------------------------
# 编排器侧：输入 / 输出
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """编排器配置 — 调用方告诉编排器"跑哪些页、哪些阶段、什么配置"。

    这是编排器的外部 Interface：调用方只需要构造这个配置，调用 run_pipeline()。
    """
    work_id: str
    src_dir: Path                       # 原始图片目录（N.jpg，1 基文件名）
    start_page: int                     # 起始页（1 基，对应文件名）
    end_page: int                       # 结束页（1 基，包含）
    stages: list[str] = field(default_factory=lambda: ["detect", "ocr", "translate"])
    # 要执行的阶段，按顺序。后续加 inpaint/typeset 只需在这里加名字。
    stage_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 各阶段的覆盖配置，如 {"ocr": {"engine": "hayai", "rule_filter": True}}
    force_rerun: bool = False           # True = 忽略断点，所有阶段强制重跑
    continue_on_error: bool = False     # True = 单页失败后继续下一页；False = 停止


@dataclass
class PipelineResult:
    """编排器执行结果 — run_pipeline() 的返回值。

    调用方可以从这里拿到每页每阶段的执行状态、失败信息、总耗时。
    """
    run_id: str
    work_id: str
    pages: list[str]
    stages: list[str]
    results: dict[str, dict[str, StationResult]] = field(default_factory=dict)
    # {page_key: {stage_name: StationResult}}
    total_duration_s: float = 0.0
    failed_pages: list[str] = field(default_factory=list)
    failed_step: dict[str, Any] | None = None  # 第一个失败的锚点（page, stage, reason）
