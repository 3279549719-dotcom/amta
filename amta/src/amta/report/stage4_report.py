"""stage4_report — Stage4 mask+inpaint 逐页验证报告（深接口模块）。

scripts/gen_stage4_report.py 是本模块的薄 CLI。
复用 amta.report.stages.mask / inpaint 适配器 + refine_text_mask。
"""
from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from amta.report.stages.inpaint import from_inpaint as build_inpaint_stage
from amta.report.stages.mask import from_mask as build_mask_stage


def _img_to_b64(img: Image.Image, max_side: int = 900) -> str:
    im = img.copy()
    im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def extract_inpaint_boxes(inpaint_json: dict) -> dict[str, list[float]]:
    """从 inpaint.json 提取所有 inpaint 框的 {region_id: bbox}。

    ADR-033 后所有框统一走 inpaint，函数名保留兼容。
    """
    actions = inpaint_json.get("actions", [])
    boxes: dict[str, list[float]] = {}
    for i, a in enumerate(actions):
        if a.get("action") == "inpaint":
            rid = a.get("region_id") or f"r{i:02d}"
            bb = a.get("bbox")
            if bb and len(bb) == 4:
                boxes[rid] = bb
    return boxes


# ADR-033 兼容别名：旧名 "text_free" 框已在统一 inpaint 路径上退化为普通 inpaint 框，
# 保留函数名供 report/__init__ 导出与旧引用（test_report_convergence）不再 ImportError。
extract_text_free_boxes = extract_inpaint_boxes


_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a2e; line-height:1.6; }
.container { max-width:1400px; margin:0 auto; padding:24px; }
h1 { font-size:24px; margin-bottom:4px; }
.subtitle { color:#666; margin-bottom:20px; font-size:13px; }
.stats { display:flex; gap:12px; margin-bottom:24px; flex-wrap:wrap; }
.stat { background:#fff; border-radius:10px; padding:12px 18px; box-shadow:0 1px 4px rgba(0,0,0,.06); min-width:100px; }
.stat .num { font-size:24px; font-weight:700; color:#1e40af; }
.stat .lbl { font-size:11px; color:#666; }
.stat.ok .num { color:#16a34a; }
.stat.warn .num { color:#d97706; }
.page-section { background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }
.page-section.no-free { opacity:0.7; }
.page-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; padding-bottom:10px; border-bottom:2px solid #f0f0f0; }
.page-title { font-size:17px; font-weight:700; color:#1e40af; }
.page-stats { font-size:12px; color:#666; }
.compare-row { display:flex; gap:16px; margin-bottom:16px; }
.compare-cell { flex:1; text-align:center; }
.compare-cell img { width:100%; max-height:600px; object-fit:contain; border-radius:8px; border:1px solid #e5e7eb; }
.img-label { font-size:11px; color:#999; margin-top:6px; }
.table-wrap { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:12px; }
th { background:#f3f4f6; padding:8px 10px; text-align:left; border-bottom:2px solid #e5e7eb; font-size:12px; }
td { padding:10px; border-bottom:1px solid #f3f4f6; vertical-align:top; }
tr:hover { background:#f9fafb; }
.rid { font-weight:600; color:#1e40af; white-space:nowrap; font-size:12px; }
.rid .bbox { font-family:monospace; font-size:10px; color:#999; font-weight:400; }
.footer { text-align:center; color:#999; font-size:11px; margin-top:32px; padding:16px; }
"""


def _render_page_section(page_num: int, raw_img: Image.Image, clean_img: Image.Image,
                         mask_stage, inpaint_stage) -> str:
    """渲染单页 section：2图并列 + 表格。"""
    raw_b64 = _img_to_b64(raw_img)
    clean_b64 = _img_to_b64(clean_img)

    all_rids: list[str] = []
    for rid in mask_stage.cells:
        if rid not in all_rids:
            all_rids.append(rid)
    for rid in inpaint_stage.cells:
        if rid not in all_rids:
            all_rids.append(rid)

    rows_html = ""
    for rid in all_rids:
        mask_cell = mask_stage.render_cell(mask_stage.cells.get(rid))
        inpaint_cell = inpaint_stage.render_cell(inpaint_stage.cells.get(rid))
        bbox = (mask_stage.cells.get(rid, {}).get("bbox")
                or inpaint_stage.cells.get(rid, {}).get("bbox", []))
        bbox_str = (f"[{int(bbox[0])},{int(bbox[1])},{int(bbox[2])},{int(bbox[3])}]"
                    if bbox else "")
        rows_html += f"""
        <tr>
          <td class="rid">{rid}<br><span class="bbox">{bbox_str}</span></td>
          <td>{mask_cell}</td>
          <td>{inpaint_cell}</td>
        </tr>"""

    n_free = len(all_rids)
    return f"""
    <div class="page-section">
      <div class="page-header">
        <div class="page-title">第 {page_num} 页 — {page_num}.jpg</div>
        <div class="page-stats">inpaint 框: {n_free} ｜ mask: 矩形 ｜ inpaint: lama-manga</div>
      </div>
      <div class="compare-row">
        <div class="compare-cell">
          <img src="data:image/jpeg;base64,{raw_b64}" alt="原图 {page_num}.jpg">
          <div class="img-label">原图</div>
        </div>
        <div class="compare-cell">
          <img src="data:image/jpeg;base64,{clean_b64}" alt="修复后 {page_num}.jpg">
          <div class="img-label">完整修复后（clean）</div>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th style="width:120px">文字框</th><th>像素精修mask</th><th>inpaint修复后</th></tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
    </div>"""


def _render_no_free_section(page_num: int, raw_img: Image.Image) -> str:
    """没有 inpaint 框的页：只显示原图 + 提示。"""
    raw_b64 = _img_to_b64(raw_img)
    return f"""
    <div class="page-section no-free">
      <div class="page-header">
        <div class="page-title">第 {page_num} 页 — {page_num}.jpg</div>
        <div class="page-stats" style="color:#999">本页无 inpaint 框</div>
      </div>
      <div class="compare-row">
        <div class="compare-cell">
          <img src="data:image/jpeg;base64,{raw_b64}" alt="原图 {page_num}.jpg">
          <div class="img-label">原图</div>
        </div>
      </div>
    </div>"""


def render_stage4_report(
    src_dir: Path,
    result_dir: Path,
    pages: list[int],
    out_path: Path | None = None,
) -> str:
    """生成 Stage4 验证报告，返回 HTML 字符串。

    Args:
        src_dir: 原图目录（N.jpg）
        result_dir: stage4 结果目录，含 page_N_inpaint.json + clean/page_N_clean.png
        pages: 页码列表
        out_path: 可选，写入 HTML 文件
    """
    src_dir = Path(src_dir)
    result_dir = Path(result_dir)
    clean_dir = result_dir / "clean"

    t0 = time.time()
    sections: list[str] = []
    total_free = 0
    pages_with_free = 0
    pages_no_free = 0

    for n in pages:
        raw_path = src_dir / f"{n}.jpg"
        inpaint_path = result_dir / f"page_{n}_inpaint.json"
        clean_path = clean_dir / f"page_{n}_clean.png"

        if not raw_path.exists():
            print(f"[skip] page_{n}: raw not found")
            continue
        if not inpaint_path.exists():
            print(f"[skip] page_{n}: inpaint.json not found (may have failed)")
            continue

        raw_img = Image.open(raw_path).convert("RGB")
        inpaint_data = json.loads(inpaint_path.read_text(encoding="utf-8"))
        inpaint_boxes = extract_inpaint_boxes(inpaint_data)

        if not inpaint_boxes:
            sections.append(_render_no_free_section(n, raw_img))
            pages_no_free += 1
            print(f"[page {n}] no inpaint boxes")
            continue

        if clean_path.exists():
            clean_img = Image.open(clean_path).convert("RGB")
        else:
            print(f"[warn] page_{n}: clean image not found, using raw as fallback")
            clean_img = raw_img

        # 生成矩形 mask（和04_inpaint相同参数 pad=4，ADR-033 统一矩形 mask）
        w, h = raw_img.size
        mask_np = np.zeros((h, w), dtype=np.uint8)
        for bbox in inpaint_boxes.values():
            x1, y1, x2, y2 = [int(v) for v in bbox]
            x1 = max(0, x1 - 4); y1 = max(0, y1 - 4)
            x2 = min(w, x2 + 4); y2 = min(h, y2 + 4)
            mask_np[y1:y2, x1:x2] = 255

        # 构建深接口 StageOutput
        mask_stage = build_mask_stage(raw_img, mask_np, inpaint_boxes)
        inpaint_stage = build_inpaint_stage(clean_img, inpaint_boxes)

        sections.append(_render_page_section(n, raw_img, clean_img, mask_stage, inpaint_stage))
        total_free += len(inpaint_boxes)
        pages_with_free += 1
        print(f"[page {n}] {len(inpaint_boxes)} text_free boxes, rendered")

    stats_html = f"""
    <div class="stats">
      <div class="stat"><div class="num">{pages_with_free + pages_no_free}</div><div class="lbl">总页数</div></div>
      <div class="stat ok"><div class="num">{pages_with_free}</div><div class="lbl">有inpaint框</div></div>
      <div class="stat warn"><div class="num">{pages_no_free}</div><div class="lbl">无inpaint框</div></div>
      <div class="stat"><div class="num">{total_free}</div><div class="lbl">inpaint框总数</div></div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Stage4 验证报告 — 像素精修mask + inpaint</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <h1>Stage4 验证报告 — 像素精修mask + inpaint</h1>
  <div class="subtitle">
    方案A精修mask（Otsu + 颜色直方图 + 连通域）｜ inpaint引擎: lama-manga ｜
    范围: {pages[0]}-{pages[-1]}页 ｜ 生成时间: {time.strftime("%Y-%m-%d %H:%M:%S")}
  </div>
  {stats_html}
  {''.join(sections)}
  <div class="footer">
    amta Stage4 验证 ｜ 深接口 StageOutput (mask/inpaint) ｜
    页码1基（page_N ↔ N.jpg）
  </div>
</div>
</body>
</html>"""

    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        print("\n=== 报告生成完成 ===")
        print(f"输出: {out_path}")
        print(f"大小: {out_path.stat().st_size / 1024:.0f} KB")
        print(f"页数: {pages_with_free + pages_no_free} (有框: {pages_with_free}, 无框: {pages_no_free})")
        print(f"inpaint框总数: {total_free}")
        print(f"耗时: {time.time() - t0:.1f}s")

    return html
