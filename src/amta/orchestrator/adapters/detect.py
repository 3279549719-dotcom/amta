"""detect 工位适配器 — StationContext → detect_station.detect_page → StationResult。"""
from __future__ import annotations

import time

from amta.stations.detect_station import detect_page
from amta.stores import artifacts

from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行检测工位。

    无上游依赖（consumes=[]）。
    从 ctx.config 读取：conf_threshold（默认 0.5，ADR-Q1 甜点）
    产出：{artifacts_dir}/{stage}/page_N.json（目录即索引，C1 布局）
    """
    t0 = time.perf_counter()
    try:
        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["detection"]
        doc = detect_page(
            work_id=ctx.work_id,
            raw_page=ctx.raw_image,
            out_dir=ctx.artifacts_dir,
            page_idx=ctx.page_idx,
            conf_threshold=ctx.config["conf_threshold"],
            tiling_enabled=ctx.config.get("tiling_enabled", False),
            tiling_cols=ctx.config.get("tiling_cols", 3),
            tiling_rows=ctx.config.get("tiling_rows", 4),
            tiling_conf=ctx.config.get("tiling_conf", 0.3),
            tiling_nms_iou=ctx.config.get("tiling_nms_iou", 0.5),
            coverage_thresh=ctx.config.get("coverage_thresh", 0.5),
            out_path=out_path,
        )
        duration = time.perf_counter() - t0
        return StationResult(
            page=ctx.page,
            stage="detect",
            status="ok",
            output_artifact=out_path,
            duration_s=round(duration, 2),
            stats={
                "n_boxes": doc.get("n_boxes", 0),
                "conf_threshold": doc.get("conf_threshold", 0.5),
            },
        )
    except Exception as e:
        duration = time.perf_counter() - t0
        return StationResult(
            page=ctx.page,
            stage="detect",
            status="failed",
            duration_s=round(duration, 2),
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )
