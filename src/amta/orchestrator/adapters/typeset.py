"""typeset 工位适配器 — StationContext → typeset_station.run → StationResult。

上游：detect + ocr + translate + inpaint。
可选产出（config.export_psd=True）：psd/{page}.psd。
"""
from __future__ import annotations

from amta.common.paths import read_json
from amta.stores import artifacts
from amta.typeset.typeset_station import run as typeset_run

from .._guarded import guarded
from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行排版工位。"""
    def _do():
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

        inpaint_doc = read_json(inpaint_path)
        clean_image_name = inpaint_doc.get("clean_image", "")
        if not clean_image_name:
            raise ValueError("inpaint.json 中缺少 clean_image 字段")
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

        # 可选：分层 PSD（人工兜底）
        if ctx.config.get("export_psd", False):
            from amta.typeset.psd_jsx_export import export_page_psd
            psd_dir = ctx.artifacts_dir / "psd"
            psd_path = psd_dir / f"{ctx.page}.psd"
            exported = export_page_psd(ctx.artifacts_dir, ctx.page, psd_path)
            if not exported or not psd_path.is_file() or psd_path.stat().st_size == 0:
                raise RuntimeError("PSD export failed; PNG remains available, check Photoshop logs")

        checks = doc.get("checks", {})
        stats = {
            "rendered": checks.get("rendered", 0),
            "translated": checks.get("translated", 0),
            "coverage_complete": checks.get("coverage_complete", False),
            "n_overflow": len(checks.get("overflow", [])),
            "n_skipped_no_bbox": len(checks.get("skipped_no_bbox", [])),
        }
        if ctx.config.get("export_psd", False):
            stats["psd"] = str((ctx.artifacts_dir / "psd" / f"{ctx.page}.psd").relative_to(ctx.artifacts_dir.parent))
        return out_path, stats

    return guarded(ctx, "typeset", _do)
