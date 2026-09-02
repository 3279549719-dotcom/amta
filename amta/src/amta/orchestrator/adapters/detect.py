"""detect 工位适配器 — StationContext → detect_station.detect_page → StationResult。"""
from __future__ import annotations

import time

from amta import artifacts
from amta.detect_station import detect_page

from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行检测工位。

    从 ctx.config 读取：host, port（Koharu 服务地址）
    产出：{artifacts_dir}/{page}_detection.json
    """
    t0 = time.perf_counter()
    try:
        doc = detect_page(
            work_id=ctx.work_id,
            raw_page=ctx.raw_image,
            artifacts_dir=ctx.artifacts_dir,
            page_idx=ctx.page_idx,
            host=ctx.config.get("host", "127.0.0.1"),
            port=ctx.config.get("port", 4000),
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
                "n_boxes": doc.get("n_boxes", len(doc.get("blocks", []))),
                "per_engine_boxes": doc.get("per_engine_boxes", {}),
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
