"""translate 工位适配器 — StationContext → translate_station.translate_page → StationResult。"""
from __future__ import annotations

import time

from amta import artifacts
from amta.paths import read_json
from amta.translate_station import translate_page

from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行翻译工位。

    上游依赖：ctx.inputs["ocr"] → canon artifact
    从 ctx.config 读取：mode, vlm_enabled
    产出：{artifacts_dir}/{page}_translation.json
    """
    t0 = time.perf_counter()
    try:
        canon_path = ctx.inputs.get("ocr")
        if canon_path is None:
            raise ValueError("上游 ocr 产物路径缺失，检查阶段依赖配置")
        canon = read_json(canon_path)

        doc = translate_page(
            work_id=ctx.work_id,
            canon=canon,
            state_dir=ctx.state_dir,
            page=ctx.page,
            mode=ctx.config.get("mode", "minimal"),
            raw_image_path=ctx.raw_image,
            vlm_enabled=ctx.config.get("vlm_enabled", True),
        )
        duration = time.perf_counter() - t0
        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["translation"]

        translations = doc.get("translations", {})
        return StationResult(
            page=ctx.page,
            stage="translate",
            status="ok",
            output_artifact=out_path,
            duration_s=round(duration, 2),
            stats={
                "n_translations": len(translations),
                "n_holes": sum(1 for v in translations.values() if not v.strip()),
                "n_residue": len(doc.get("residue", [])),
                "n_glossary_violations": len(doc.get("glossary_violations", [])),
                "vlm_refine_count": (doc.get("vlm_refine") or {}).get("refinement_count", 0),
            },
        )
    except Exception as e:
        duration = time.perf_counter() - t0
        return StationResult(
            page=ctx.page,
            stage="translate",
            status="failed",
            duration_s=round(duration, 2),
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )
