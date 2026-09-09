"""ocr 工位适配器 — StationContext → ocr_station.ocr_page → StationResult。"""
from __future__ import annotations

import time

from amta.stores import artifacts
from amta.stations.ocr_station import ocr_page
from amta.common.paths import read_json

from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行 OCR 工位。

    上游依赖：ctx.inputs["detect"] → detection artifact
    从 ctx.config 读取：engine, vlm_enabled（已由 registry default_config + 覆盖合并）
    产出：{artifacts_dir}/{page}_canon.json
    """
    t0 = time.perf_counter()
    try:
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
            engine=ctx.config["engine"],
            vlm_enabled=ctx.config["vlm_enabled"],
            rule_filter_enabled=ctx.config.get("rule_filter_enabled", False),
        )
        duration = time.perf_counter() - t0
        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["canon"]
        return StationResult(
            page=ctx.page,
            stage="ocr",
            status="ok",
            output_artifact=out_path,
            duration_s=round(duration, 2),
            stats={
                "n_regions": doc.get("n_regions", len(doc.get("items", []))),
                "vlm_status": doc.get("vlm_status", "unknown"),
            },
        )
    except Exception as e:
        duration = time.perf_counter() - t0
        return StationResult(
            page=ctx.page,
            stage="ocr",
            status="failed",
            duration_s=round(duration, 2),
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )

