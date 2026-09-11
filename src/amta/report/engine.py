"""报告引擎 — 深接口渲染原语 + 薄封装入口。

渲染原语（可自由组合）：
  render_image_panel(img, label)       → 一张图 + 标签的 HTML 片段
  render_region_table(rows, stages)    → 区域×阶段表格的 HTML 片段
  render_page_section(page, granularity) → 一页的 HTML 片段（不含 <html> 外壳）
  render_compare_section(images, labels, page_idx) → 多图左右对比的 HTML 片段
  render_report_shell(sections, title) → 把多页片段装进完整 HTML

薄封装（向后兼容）：
  render_report(page) → ReportResult（单页完整 HTML，等价于旧行为）
"""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path
from typing import Any

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
td { padding:6px 8px; border-bottom:1px solid #f3f4f; vertical-align:top; }
tr:hover { background:#f9fafb; }
.rid { font-weight:600; color:#1e40af; white-space:nowrap; }
.compare-row { display:flex; gap:16px; flex-wrap:wrap; }
.compare-col { flex:1; min-width:280px; text-align:center; }
.compare-col .label { font-size:13px; color:#666; margin-bottom:8px; font-weight:600; }
.compare-col img { max-width:100%; height:auto; border-radius:8px; border:1px solid #e5e7eb; }
.footer { text-align:center; color:#999; font-size:11px; margin-top:24px; padding:16px; }
"""


# ---- 底层工具 ----

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
                pass
    return result


def _img_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _align_regions(page: PageReport) -> tuple[list[dict], list[str]]:
    """跨阶段对齐区域，返回 (行数据列表, warnings)。"""
    warnings: list[str] = []
    union = page.all_region_ids
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
        target_bbox = None
        for s in page.stages:
            d = s.cells.get(rid)
            if isinstance(d, dict) and "bbox" in d:
                target_bbox = d["bbox"]
                break
        for s in page.stages:
            matched = match_region(rid, target_bbox, list(s.cells.keys()),
                                   stage_bboxes.get(s.key, {}))
            if matched is not None:
                row["cells"][s.key] = s.cells[matched]
            else:
                row["cells"][s.key] = None
                warnings.append(f"区域 {rid} 在阶段 {s.key} 缺失")
        rows.append(row)
    return rows, warnings


def _compute_stats(page: PageReport, rows: list[dict]) -> list[dict]:
    """计算每页统计卡片数据。"""
    stats = []
    for s in page.stages:
        stats.append({"num": len(s.cells), "lbl": s.label, "cls": ""})
        if s.key == "translate":
            non_empty = sum(1 for d in s.cells.values()
                            if isinstance(d, dict) and d.get("translation", "").strip())
            stats.append({"num": non_empty, "lbl": "成功译文", "cls": "ok"})
            pa = s.page_artifact
            if isinstance(pa, dict):
                residue = pa.get("residue", [])
                glossary = pa.get("glossary_violations", [])
                if residue:
                    stats.append({"num": len(residue), "lbl": "日文残留", "cls": "warn"})
                if glossary:
                    stats.append({"num": len(glossary), "lbl": "术语违例", "cls": "warn"})
    return stats


# ---- 渲染原语（公开，可自由组合）----

def render_image_panel(img: Image.Image, label: str = "") -> str:
    """渲染一张图 + 可选标签的 HTML 片段。"""
    img_b64 = _img_to_base64(img)
    label_html = f'<div class="label">{label}</div>' if label else ""
    return f'<div class="img-panel">{label_html}<img src="data:image/jpeg;base64,{img_b64}" alt="{label}"></div>'


def render_region_table(rows: list[dict], stages: list[StageOutput]) -> str:
    """渲染区域×阶段表格的 HTML 片段。"""
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


def render_page_section(page: PageReport, granularity: str = "region") -> tuple[str, dict]:
    """渲染一页的 HTML 片段（不含 <html> 外壳）。

    granularity:
      - "region": 全图（叠加 overlay）+ 区域表格（详细调试用）
      - "page": 只渲染全图（叠加 overlay），不渲染表格（快速浏览用）

    返回 (html片段, 统计信息dict)
    """
    img = _load_image(page.raw_image)
    img = _composite_overlays(img, page.stages)

    stats_info: dict[str, Any] = {"stages_rendered": [s.key for s in page.stages]}

    if granularity == "page":
        # 页级：只放一张全图
        img_b64 = _img_to_base64(img)
        section = f"""
    <div class="page-section">
      <div class="page-header">
        <div class="page-title">page_{page.page_idx} — {page.page_idx}.jpg</div>
      </div>
      <div class="layout">
        <div class="img-panel"><img src="data:image/jpeg;base64,{img_b64}" alt="page {page.page_idx}"></div>
      </div>
    </div>"""
        stats_info["regions_total"] = 0
        stats_info["regions_aligned"] = 0
        stats_info["warnings"] = []
        return section, stats_info

    # region 级：全图 + 区域表格
    rows, warnings = _align_regions(page)
    stats = _compute_stats(page, rows)
    regions_aligned = sum(1 for row in rows
                          if all(row["cells"].get(s.key) is not None for s in page.stages))
    table_html = render_region_table(rows, page.stages)

    stats_html = "".join(
        f'<div class="stat {s["cls"]}"><div class="num">{s["num"]}</div><div class="lbl">{s["lbl"]}</div></div>'
        for s in stats
    )
    warn_html = ""
    if warnings:
        warn_html = f'<div class="page-warnings">⚠ {len(warnings)} 条警告: {"; ".join(warnings[:5])}</div>'

    img_b64 = _img_to_base64(img)
    section = f"""
    <div class="page-section">
      <div class="page-header">
        <div class="page-title">page_{page.page_idx} — {page.page_idx}.jpg</div>
        {warn_html}
      </div>
      <div class="stats">{stats_html}</div>
      <div class="layout">
        <div class="img-panel"><img src="data:image/jpeg;base64,{img_b64}" alt="page {page.page_idx}"></div>
        <div class="table-panel">{table_html}</div>
      </div>
    </div>"""

    stats_info["regions_total"] = len(rows)
    stats_info["regions_aligned"] = regions_aligned
    stats_info["regions_dropped"] = [row["rid"] for row in rows
                                     if any(row["cells"].get(s.key) is None for s in page.stages)]
    stats_info["warnings"] = warnings
    return section, stats_info


def render_compare_section(images: list[tuple[Image.Image, str]], page_idx: int) -> str:
    """渲染多图左右对比的 HTML 片段（页级粒度用）。

    images: [(PIL.Image, 标签), ...]
    """
    cols = []
    for img, label in images:
        img_b64 = _img_to_base64(img)
        cols.append(f"""
        <div class="compare-col">
          <div class="label">{label}</div>
          <img src="data:image/jpeg;base64,{img_b64}" alt="{label}">
        </div>""")
    return f"""
    <div class="page-section">
      <div class="page-header">
        <div class="page-title">page_{page_idx} — {page_idx}.jpg</div>
      </div>
      <div class="compare-row">{''.join(cols)}</div>
    </div>"""


def render_report_shell(sections: list[str], title: str, subtitle: str = "") -> str:
    """把多页 HTML 片段装进完整 HTML 外壳。"""
    subtitle_html = f'<div class="subtitle">{subtitle}</div>' if subtitle else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <h1>{title}</h1>
  {subtitle_html}
  {''.join(sections)}
  <div class="footer">amta report tool — 深接口渲染引擎 ｜ 阶段可插拔 ｜ 粒度可切换</div>
</div>
</body>
</html>"""


# ---- 薄封装（向后兼容）----

def render_report(page: PageReport) -> ReportResult:
    """深模块唯一入口：吃 PageReport，吐 ReportResult。纯函数。

    等价于 granularity="region" 的单页报告（旧行为）。
    """
    t0 = time.time()
    section, stats_info = render_page_section(page, granularity="region")
    stages_str = " → ".join(s.label for s in page.stages)
    html = render_report_shell(
        [section],
        title=f"管线报告 — page_{page.page_idx} ({page.page_idx}.jpg)",
        subtitle=f"阶段: {stages_str}",
    )
    return ReportResult(
        html=html,
        page_idx=page.page_idx,
        stages_rendered=stats_info["stages_rendered"],
        regions_total=stats_info.get("regions_total", 0),
        regions_aligned=stats_info.get("regions_aligned", 0),
        regions_dropped=stats_info.get("regions_dropped", []),
        warnings=stats_info.get("warnings", []),
        render_time_ms=(time.time() - t0) * 1000,
    )
