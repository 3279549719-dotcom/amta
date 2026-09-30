"""inpaint 工位适配器 — StationContext → inpaint_station.run → StationResult。

使用本地 lama-manga 推理（ADR-029），不依赖 Koharu HTTP 服务。
"""
from __future__ import annotations

from amta.inpaint.inpaint_station import run as inpaint_run
from amta.stores import artifacts

from .._guarded import guarded
from ..context import StationContext, StationResult


def run(ctx: StationContext) -> StationResult:
    """执行 inpaint 工位。上游：detect + translate。"""
    def _do():
        det_path = ctx.inputs.get("detect")
        if det_path is None:
            raise ValueError("上游 detect 产物路径缺失，检查阶段依赖配置")
        trans_path = ctx.inputs.get("translate")

        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["inpaint"]
        clean_dir = ctx.artifacts_dir / "clean"

        doc = inpaint_run(
            work_id=ctx.work_id,
            det_path=det_path,
            raw_page=ctx.raw_image,
            out_path=out_path,
            clean_dir=clean_dir,
            inpaint_engine=ctx.config["inpaint_engine"],
            trans_path=trans_path,
        )

        checks = doc.get("checks", {})
        stats = {
            "filled": checks.get("filled", 0),
            "inpainted": checks.get("inpainted", 0),
            "skipped": checks.get("skipped", 0),
            "pixel_diff_ratio": checks.get("pixel_diff_ratio", 0),
        }
        return out_path, stats

    return guarded(ctx, "inpaint", _do)
