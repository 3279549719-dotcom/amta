"""typeset 工位适配器 — StationContext → typeset_station.run → StationResult。"""
from __future__ import annotations

import time

from amta.common.paths import read_json
from amta.stores import artifacts
from amta.typeset.typeset_station import run as typeset_run

from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行排版工位。

    上游依赖（consumes=["detect", "ocr", "translate", "inpaint"]）：
    - ctx.inputs["detect"] → detection.json
    - ctx.inputs["ocr"] → canon.json
    - ctx.inputs["translate"] → translation.json
    - ctx.inputs["inpaint"] → inpaint.json（从中读 clean_image 字段获取 clean 图路径）
    产出：{artifacts_dir}/{page}_typeset.json + {artifacts_dir}/final/{page}_final.png
    """
    t0 = time.perf_counter()
    try:
        det_path = ctx.inputs.get("detect")
        canon_path = ctx.inputs.get("ocr")
        trans_path = ctx.inputs.get("translate")
        inpaint_path = ctx.inputs.get("inpaint")

        if det_path is None:
            raise ValueError("上游 detect 产物路径缺失")
        if canon_path is None:
            raise ValueError("上游 ocr 产物路径缺失")
        if trans_path is None:
            raise ValueError("上游 translate 产物路径缺失")
        if inpaint_path is None:
            raise ValueError("上游 inpaint 产物路径缺失")

        # 从 inpaint.json 读取 clean 图路径
        inpaint_doc = read_json(inpaint_path)
        clean_image_name = inpaint_doc.get("clean_image", "")
        if not clean_image_name:
            raise ValueError("inpaint.json 中缺少 clean_image 字段，inpaint 阶段可能未生成 clean 图")
        clean_path = ctx.artifacts_dir / clean_image_name
        if not clean_path.exists():
            raise FileNotFoundError(f"clean 图不存在: {clean_path}")

        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["typeset"]
        final_dir = ctx.artifacts_dir / "final"
        final_path = final_dir / f"{ctx.page}_final.png"

        doc = typeset_run(
            work_id=ctx.work_id,
            canon_path=canon_path,
            trans_path=trans_path,
            det_path=det_path,
            clean_path=clean_path,
            out_path=out_path,
            final_path=final_path,
        )

        duration = time.perf_counter() - t0
        checks = doc.get("checks", {})
        return StationResult(
            page=ctx.page,
            stage="typeset",
            status="ok",
            output_artifact=out_path,
            duration_s=round(duration, 2),
            stats={
                "rendered": checks.get("rendered", 0),
                "translated": checks.get("translated", 0),
                "coverage_complete": checks.get("coverage_complete", False),
                "n_overflow": len(checks.get("overflow", [])),
                "n_skipped_no_bbox": len(checks.get("skipped_no_bbox", [])),
            },
        )
    except Exception as e:
        duration = time.perf_counter() - t0
        return StationResult(
            page=ctx.page,
            stage="typeset",
            status="failed",
            duration_s=round(duration, 2),
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )


