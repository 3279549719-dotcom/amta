"""translate 工位适配器 — StationContext → translate_station.translate_page → StationResult。

注意：translate_page 只返回 dict 不落盘，落盘逻辑在适配器里（与 03_translate.py 一致）。
canon 输入用 artifacts.load_canon 规范化（兼容旧裸 list 格式 + validate）。
pre_scan 自动接入：work_state.terms 为空时扫描已有 canon 锁定术语（纯机械，无 LLM 调用）。
"""
from __future__ import annotations

import time

from amta import artifacts, workstate
from amta.paths import write_json
from amta.translate_station import translate_page

from ..context import StationContext, StationResult


def _ensure_terms(work_id: str, artifacts_dir) -> int:
    """确保术语表存在：为空时自动跑 pre_scan 扫描已有 canon。返回锁定的术语数。

    pre_scan 是纯机械匹配（无 LLM 调用），失败不阻塞翻译（降级为无术语替换）。
    逐页流水线下增量生效：第一页只有第一页 canon，越往后扫描到的术语越多。
    """
    try:
        state = workstate.load_state(work_id)
        if state.get("terms"):
            return len(state["terms"])
        from amta.pre_scan import run_pre_scan
        matched = run_pre_scan(work_id, artifacts_dir)
        return len(matched)
    except Exception as e:  # noqa: BLE001 — pre_scan 失败降级，不阻塞翻译
        print(f"[translate] pre_scan skipped ({type(e).__name__}: {str(e)[:80]})")
        return 0


def run(ctx: StationContext) -> StationResult:
    """执行翻译工位。

    上游依赖：ctx.inputs["ocr"] → canon artifact
    从 ctx.config 读取：vlm_enabled
    产出：{artifacts_dir}/{page}_translation.json（适配器负责落盘）
    """
    t0 = time.perf_counter()
    try:
        canon_path = ctx.inputs.get("ocr")
        if canon_path is None:
            raise ValueError("上游 ocr 产物路径缺失，检查阶段依赖配置")

        # load_canon: normalize + validate + 兼容旧裸 list 格式（与 03_translate.py 一致）
        canon = artifacts.load_canon(canon_path)

        # pre_scan 自动接入：术语表为空时扫描已有 canon
        n_terms = _ensure_terms(ctx.work_id, ctx.artifacts_dir)

        # mode 参数已从 translate_page 移除（translate_station.py:18 注释），与 03_translate.py 一致不传
        doc = translate_page(
            work_id=ctx.work_id,
            canon=canon,
            state_dir=ctx.state_dir,
            page=ctx.page,
            raw_image_path=ctx.raw_image,
            vlm_enabled=ctx.config["vlm_enabled"],
        )

        # translate_page 不落盘，适配器负责落盘（与 03_translate.py 第36行一致）
        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["translation"]
        doc_to_save = dict(doc)
        doc_to_save.pop("_trace", None)  # trace 不落盘（与 03_translate.py 第35行一致）
        write_json(out_path, doc_to_save)

        duration = time.perf_counter() - t0
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
                "n_locked_terms": n_terms,
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
