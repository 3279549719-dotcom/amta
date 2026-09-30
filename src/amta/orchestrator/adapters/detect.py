"""detect 工位适配器 — StationContext → detect_station.detect_page → StationResult。"""
from __future__ import annotations

from amta.stations.detect_station import detect_page
from amta.stores import artifacts

from .._guarded import guarded
from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行检测工位。无上游依赖（consumes=[]）。"""
    def _do():
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
        stats = {
            "n_boxes": doc.get("n_boxes", 0),
            "conf_threshold": doc.get("conf_threshold", 0.5),
        }
        return out_path, stats

    return guarded(ctx, "detect", _do)
