"""报告引擎 — render_report 核心实现（纯函数，零 IO，零副作用）。

职责：区域对齐 → 图层叠加 → HTML 生成 → 可观测返回。
不读文件、不调 API、不写磁盘。
"""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path

from PIL import Image, ImageDraw

from .align import match_region
from .model import PageReport, ReportResult, StageOutput

_CSS = """
body { font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a2e; margin:0; padding:24px; line-height:1.6; }
.container { max-width:1400px; margin:0 auto; }
h1 { font-size:22px; margin-bottom:4px; }
.subtitle { color:#666; font-size:13px; margin-bottom:20px; }
.stats { display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }
.stat { background:#fff; border-radius:10px; padding:12px 18px; box-shadow:0 1px 4px rgba(0,0,0,.06); min-width:100px; }
.stat .num { font-size:24px; font-weight:700; color:#1e40af; }
.stat .lbl { font-size:11px; color:#666; }
.stat.ok .num { color:#16a34a; }
.stat.warn .num { color:#dc2626; }
.page-section { background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }
.page-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }
.page-title { font-size:16px; font-weight:700; color:#1e40af; }
.page-warnings { font-size:11px; color:#d97706; }
.layout { display:flex; gap:20px; align-items:flex-start; }
.img-panel { flex:0 0 45%; }
.img-panel img { width:100%; border-radius:8px; border:1px solid #e5e7eb; }
.table-panel { flex:1; overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:12px; }
th { background:#f3f4f6; padding:6px 8px; text-align:left; border-bottom:2px solid #e5e7eb; position:sticky; top:0; }
td { padding:6px 8px; border-bottom:1px solid #f3f4f6; vertical-align:top; }
tr:hover { background:#f9fafb; }
.rid { font-weight:600; color:#1e40af; white-space:nowrap; }
.footer { text-align:center; color:#999; font-size:11px; margin-top:24px; padding:16px; }
"""


def _load_image(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def _composite_overlays(img: Image.Image, stages: list[StageOutput]) -> Image.Image:
    """把所有有 render_overlay 的阶段图层叠加到原图上。"""
    result = img.copy()
    draw = ImageDraw.Draw(result)
    for s in stages:
        if s.render_overlay is not None:
            try:
                s.render_overlay(draw, s.cells, scale=1.0)
            except Exception:
                pass  # 单个阶段叠图失败不影响整体报告
    return result


def _img_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _align_regions(page: PageReport) -> tuple[list[dict], list[str]]:
    """跨阶段对齐区域，返回 (行数据列表, warnings)。

    每行: {"rid": 统一region_id, "cells": {stage_key: data_or_None}}
    """
    warnings: list[str] = []
    union = page.all_region_ids

    # 收集每个阶段的 bbox 映射（用于 IoU 回退）
    stage_bboxes: dict[str, dict[str, list[float]]] = {}
    for s in page.stages:
        bboxes = {}
        for rid, data in s.cells.items():
            if isinstance(data, dict) and "bbox" in data:
                bboxes[rid] = data["bbox"]
        stage_bboxes[s.key] = bboxes

    rows = []
    for rid in union:
        row = {"rid": rid, "cells": {}}
        # 取该区域的 bbox（从有 bbox 的阶段）
        target_bbox = None
        for s in page.stages:
            d = s.cells.get(rid)
            if isinstance(d, dict) and "bbox" in d:
                target_bbox = d["bbox"]
                break

        for s in page.stages:
            matched = match_region(
                rid, target_bbox,
                list(s.cells.keys()),
                stage_bboxes.get(s.key, {}),
            )
            if matched is not None:
                row["cells"][s.key] = s.cells[matched]
            else:
                row["cells"][s.key] = None
                warnings.append(f"区域 {rid} 在阶段 {s.key} 缺失")
        rows.append(row)

    return rows, warnings


def _render_table(rows: list[dict], stages: list[StageOutput]) -> str:
    headers = "".join(f"<th>{s.label}</th>" for s in stages)
    body_rows = []
    for row in rows:
        rid_cell = f'<td class="rid">{row["rid"]}</td>'
        data_cells = []
        for s in stages:
            data = row["cells"].get(s.key)
            data_cells.append(f"<td>{s.render_cell(data)}</td>")
        body_rows.append(f"<tr>{rid_cell}{''.join(data_cells)}</tr>")
    return f"""<table>
<thead><tr><th>region</th>{headers}</tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>"""


def _compute_stats(page: PageReport, rows: list[dict]) -> list[dict]:
    """计算每页统计卡片数据。"""
    stats = []
    detect_stage = next((s for s in page.stages if s.key == "detect"), None)
    ocr_stage = next((s for s in page.stages if s.key == "ocr"), None)
    trans_stage = next((s for s in page.stages if s.key == "translate"), None)

    if detect_stage:
        stats.append({"num": len(detect_stage.cells), "lbl": "检测框", "cls": ""})
    if ocr_stage:
        stats.append({"num": len(ocr_stage.cells), "lbl": "OCR 区域", "cls": ""})
    if trans_stage:
        non_empty = sum(1 for d in trans_stage.cells.values()
                        if isinstance(d, dict) and d.get("translation", "").strip())
        stats.append({"num": non_empty, "lbl": "成功译文", "cls": "ok"})
        pa = trans_stage.page_artifact
        if isinstance(pa, dict):
            residue = pa.get("residue", [])
            glossary = pa.get("glossary_violations", [])
            stats.append({"num": len(residue), "lbl": "日文残留", "cls": "ok" if not residue else "warn"})
            stats.append({"num": len(glossary), "lbl": "术语违例", "cls": "ok" if not glossary else "warn"})
    return stats


def render_report(page: PageReport) -> ReportResult:
    """深模块唯一入口：吃 PageReport，吐 ReportResult。纯函数。"""
    t0 = time.time()
    warnings: list[str] = []

    # 1. 加载原图 + 叠加图层
    img = _load_image(page.raw_image)
    img = _composite_overlays(img, page.stages)
    img_b64 = _img_to_base64(img)

    # 2. 跨阶段区域对齐
    rows, align_warnings = _align_regions(page)
    warnings.extend(align_warnings)

    # 3. 统计
    stats = _compute_stats(page, rows)
    regions_aligned = sum(
        1 for row in rows
        if all(row["cells"].get(s.key) is not None for s in page.stages)
    )
    regions_dropped = [
        row["rid"] for row in rows
        if any(row["cells"].get(s.key) is None for s in page.stages)
    ]

    # 4. 渲染表格
    table_html = _render_table(rows, page.stages)

    # 5. 统计卡片
    stats_html = "".join(
        f'<div class="stat {s["cls"]}"><div class="num">{s["num"]}</div><div class="lbl">{s["lbl"]}</div></div>'
        for s in stats
    )

    # 6. 警告栏
    warn_html = ""
    if warnings:
        warn_html = f'<div class="page-warnings">⚠ {len(warnings)} 条警告: {"; ".join(warnings[:5])}</div>'

    # 7. 组装 HTML
    page_num = page.page_idx + 1
    stages_str = " → ".join(s.label for s in page.stages)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>管线报告 — page_{page.page_idx} ({page_num}.jpg)</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <h1>管线报告 — page_{page.page_idx} ({page_num}.jpg)</h1>
  <div class="subtitle">阶段: {stages_str}</div>
  <div class="stats">{stats_html}</div>
  <div class="page-section">
    <div class="page-header">
      <div class="page-title">page_{page.page_idx} — {page_num}.jpg</div>
      {warn_html}
    </div>
    <div class="layout">
      <div class="img-panel">
        <img src="data:image/jpeg;base64,{img_b64}" alt="page {page_num}">
      </div>
      <div class="table-panel">
        {table_html}
      </div>
    </div>
  </div>
  <div class="footer">amta report tool — 深接口渲染引擎 ｜ 阶段可插拔 ｜ 区域 bbox IoU 对齐</div>
</div>
</body>
</html>"""

    return ReportResult(
        html=html,
        page_idx=page.page_idx,
        stages_rendered=[s.key for s in page.stages],
        regions_total=len(rows),
        regions_aligned=regions_aligned,
        regions_dropped=regions_dropped,
        warnings=warnings,
        render_time_ms=(time.time() - t0) * 1000,
    )
