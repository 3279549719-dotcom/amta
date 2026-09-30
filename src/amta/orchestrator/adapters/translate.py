"""translate 工位适配器 — StationContext → translate_station.translate_page → StationResult。

注意：translate_page 只返回 dict 不落盘，落盘逻辑在适配器里。
pre_scan 自动接入：work_state.terms 为空时扫描已有 canon 锁定术语（纯机械，无 LLM 调用）。
"""
from __future__ import annotations

from amta.common import workstate
from amta.common.paths import write_json
from amta.stores import artifacts
from amta.translation.translate_station import translate_page

from .._guarded import guarded
from ..context import StationContext, StationResult


def _ensure_terms(work_id: str, artifacts_dir) -> int:
    """确保术语表存在：为空时自动跑 pre_scan。失败不阻塞翻译。"""
    try:
        state = workstate.load_state(work_id)
        if state.get("terms"):
            return len(state["terms"])
        from amta.guards.pre_scan import run_pre_scan
        matched = run_pre_scan(work_id, artifacts_dir)
        return len(matched)
    except Exception as e:
        print(f"[translate] pre_scan skipped ({type(e).__name__}: {str(e)[:80]})")
        return 0


def run(ctx: StationContext) -> StationResult:
    """执行翻译工位。上游依赖：ctx.inputs["ocr"] → canon artifact。"""
    def _do():
        canon_path = ctx.inputs.get("ocr")
        if canon_path is None:
            raise ValueError("上游 ocr 产物路径缺失，检查阶段依赖配置")

        canon = artifacts.load_canon(canon_path)
        n_terms = _ensure_terms(ctx.work_id, ctx.artifacts_dir)

        doc = translate_page(
            work_id=ctx.work_id,
            canon=canon,
            state_dir=ctx.state_dir,
            page=ctx.page,
            raw_image_path=ctx.raw_image,
        )

        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["translation"]
        doc_to_save = dict(doc)
        doc_to_save.pop("_trace", None)
        write_json(out_path, doc_to_save)

        translations = doc.get("translations", {})
        stats = {
            "n_translations": len(translations),
            "n_holes": sum(1 for v in translations.values() if not v.strip()),
            "n_residue": len(doc.get("residue", [])),
            "n_glossary_violations": len(doc.get("glossary_violations", [])),
            "n_locked_terms": n_terms,
        }
        return out_path, stats

    return guarded(ctx, "translate", _do)
