"""ocr 工位适配器 — StationContext → ocr_station.ocr_page → StationResult。"""
from __future__ import annotations

from amta.common.paths import read_json
from amta.stations.ocr_station import ocr_page
from amta.stores import artifacts

from .._guarded import guarded
from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行 OCR 工位。上游依赖：ctx.inputs["detect"] → detection artifact。"""
    def _do():
        det_path = ctx.inputs.get("detect")
        if det_path is None:
            raise ValueError("上游 detect 产物路径缺失，检查阶段依赖配置")
        det = read_json(det_path)

        doc = ocr_page(
            work_id=ctx.work_id,
            det=det,
            raw_page=ctx.raw_image,
            artifacts_dir=ctx.artifacts_dir,
            page_idx=ctx.page_idx,
            engine="vlm-paratext" if ctx.config.get("vlm_mode") else ctx.config["engine"],
            vlm_enabled=ctx.config["vlm_enabled"],
        )
        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["canon"]
        stats = {
            "n_regions": doc.get("n_regions", len(doc.get("items", []))),
            "vlm_status": doc.get("vlm_status", "unknown"),
        }
        return out_path, stats

    return guarded(ctx, "ocr", _do)
