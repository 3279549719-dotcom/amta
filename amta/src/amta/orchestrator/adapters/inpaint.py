"""inpaint 工位适配器 — StationContext → inpaint_station.run → StationResult。

使用本地 lama-manga 推理（ADR-029），不依赖 Koharu HTTP 服务。
"""
from __future__ import annotations

import time

from amta import artifacts
from amta.inpaint_station import run as inpaint_run

from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行 inpaint 工位。

    上游依赖：ctx.inputs["detect"] → detection.json
    从 ctx.config 读取：refine_mask（默认 False）, inpaint_engine（默认 "lama-manga"）
    产出：{artifacts_dir}/{page}_inpaint.json + {artifacts_dir}/clean/{page}_clean.png
    """
    t0 = time.perf_counter()
    try:
        det_path = ctx.inputs.get("detect")
        if det_path is None:
            raise ValueError("上游 detect 产物路径缺失，检查阶段依赖配置")

        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["inpaint"]
        clean_dir = ctx.artifacts_dir / "clean"

        doc = inpaint_run(
            work_id=ctx.work_id,
            det_path=det_path,
            raw_page=ctx.raw_image,
            out_path=out_path,
            clean_dir=clean_dir,
            refine_mask=ctx.config.get("refine_mask", False),
            inpaint_engine=ctx.config.get("inpaint_engine", "lama-manga"),
        )

        duration = time.perf_counter() - t0
        checks = doc.get("checks", {})
        return StationResult(
            page=ctx.page,
            stage="inpaint",
            status="ok",
            output_artifact=out_path,
            duration_s=round(duration, 2),
            stats={
                "filled": checks.get("filled", 0),
                "inpainted": checks.get("inpainted", 0),
                "skipped": checks.get("skipped", 0),
                "pixel_diff_ratio": checks.get("pixel_diff_ratio", 0),
                "refine_mask": checks.get("refine_mask", False),
            },
        )
    except Exception as e:
        duration = time.perf_counter() - t0
        return StationResult(
            page=ctx.page,
            stage="inpaint",
            status="failed",
            duration_s=round(duration, 2),
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )

