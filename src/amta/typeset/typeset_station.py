"""typeset 工位路由 — 根据 canon 的 ocr_engine 选择渲染路径。

VLM paratext 页 → vlm_render.render_page
普通页           → mits_render.render_page

本文件只做路由和产物信封组装，不做渲染。
"""
from __future__ import annotations

from pathlib import Path

from amta.common.paths import read_json


def run(work_id: str, canon_path: Path, trans_path: Path, det_path: Path,
        clean_path: Path, out_path: Path, final_path: Path) -> dict:
    """单页排版路由：看 canon 的 ocr_engine 字段，调对应渲染器。"""
    raw_canon = read_json(canon_path)
    is_vlm = isinstance(raw_canon, dict) and raw_canon.get("ocr_engine") == "vlm-paratext"

    if is_vlm:
        from amta.typeset.vlm_render import render_page as vlm_render_page
        return vlm_render_page(work_id, canon_path, trans_path, clean_path,
                               out_path, final_path)

    from amta.typeset.mits_render import render_page as mits_render_page
    return mits_render_page(work_id, canon_path, trans_path, det_path, clean_path,
                            out_path, final_path)
