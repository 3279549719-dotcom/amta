"""detect 工位适配器 — StationContext → detect_station.detect_page → StationResult。"""
from __future__ import annotations

import time

from amta import artifacts
from amta.detect_station import detect_page

from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行检测工位。

    无上游依赖（consumes=[]）。
    从 ctx.config 读取：conf_threshold（默认 0.7）
    产出：{artifacts_dir}/{page}_detection.json
    """
    t0 = time.perf_counter()
    try:
        doc = detect_page(
            work_id=ctx.work_id,
            raw_page=ctx.raw_image,
            out_dir=ctx.artifacts_dir,
            page_idx=ctx.page_idx,
            conf_threshold=ctx.config["conf_threshold"],
        )
        duration = time.perf_counter() - t0
        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["detection"]
        return StationResult(
            page=ctx.page,
            stage="detect",
            status="ok",
            output_artifact=out_path,
            duration_s=round(duration, 2),
            stats={
                "n_boxes": doc.get("n_boxes", 0),
                "conf_threshold": doc.get("conf_threshold", 0.7),
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
