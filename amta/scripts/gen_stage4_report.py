"""生成 Stage4 11-20页验证报告（深接口 StageOutput + 自定义HTML布局）。

每页 section：
  - 顶部2图并列：原图 | inpaint后clean图
  - 下方表格：行=text_free文字框，列=像素精修mask | inpaint修复后（缩略图）

深接口适配：
  - mask stage: src/amta/report/stages/mask.py
  - inpaint stage: src/amta/report/stages/inpaint.py
"""
from __future__ import annotations

import base64
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))

from amta.report.stages.mask import from_mask as build_mask_stage  # noqa: E402
from amta.report.stages.inpaint import from_inpaint as build_inpaint_stage  # noqa: E402
from amta.text_mask_refiner import refine_text_mask  # noqa: E402

SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
RESULT_DIR = ROOT / "output" / "tmp" / "stage4_e2e_11_20"
CLEAN_DIR = RESULT_DIR / "clean"
OUT_HTML = ROOT / "output" / "stage4-e2e-11-20-report.html"

PAGE_RANGE = range(11, 21)


def img_to_b64(img: Image.Image, max_side: int = 900) -> str:
    im = img.copy()
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def extract_text_free_boxes(inpaint_json: dict) -> dict[str, list[float]]:
    """从 inpaint.json 提取 text_free 框的 {region_id: bbox}。"""
    actions = inpaint_json.get("actions", [])
    boxes = {}
    for i, a in enumerate(actions):
        if a.get("action") == "inpaint":
            rid = a.get("region_id") or f"r{i:02d}"
            bb = a.get("bbox")
            if bb and len(bb) == 4:
                boxes[rid] = bb
    return boxes


def render_page_section(page_num: int, raw_img: Image.Image, clean_img: Image.Image,
                        mask_stage, inpaint_stage) -> str:
    """渲染单页 section：2图并列 + 表格。"""
    raw_b64 = img_to_b64(raw_img)
    clean_b64 = img_to_b64(clean_img)

    # 区域对齐（取两个stage的region并集）
    all_rids = []
    for rid in mask_stage.cells:
        if rid not in all_rids:
            all_rids.append(rid)
    for rid in inpaint_stage.cells:
        if rid not in all_rids:
            all_rids.append(rid)

    # 表格行
    rows_html = ""
    for rid in all_rids:
        mask_cell = mask_stage.render_cell(mask_stage.cells.get(rid))
        inpaint_cell = inpaint_stage.render_cell(inpaint_stage.cells.get(rid))
        # bbox 显示
        bbox = mask_stage.cells.get(rid, {}).get("bbox") or inpaint_stage.cells.get(rid, {}).get("bbox", [])
        bbox_str = f"[{int(bbox[0])},{int(bbox[1])},{int(bbox[2])},{int(bbox[3])}]" if bbox else ""
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
        <div class="page-stats">text_free 框: {n_free} ｜ mask: 方案A精修 ｜ inpaint: lama-manga</div>
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


def render_no_free_section(page_num: int, raw_img: Image.Image) -> str:
    """没有 text_free 框的页：只显示原图 + 提示。"""
    raw_b64 = img_to_b64(raw_img)
    return f"""
    <div class="page-section no-free">
      <div class="page-header">
        <div class="page-title">第 {page_num} 页 — {page_num}.jpg</div>
        <div class="page-stats" style="color:#999">本页无 text_free 框（全部为 text_bubble 涂白）</div>
      </div>
      <div class="compare-row">
        <div class="compare-cell">
          <img src="data:image/jpeg;base64,{raw_b64}" alt="原图 {page_num}.jpg">
          <div class="img-label">原图</div>
        </div>
      </div>
    </div>"""


CSS = """
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


def main():
    t0 = time.time()
    sections = []
    total_free = 0
    pages_with_free = 0
    pages_no_free = 0

    for n in PAGE_RANGE:
        raw_path = SRC_DIR / f"{n}.jpg"
        inpaint_path = RESULT_DIR / f"page_{n}_inpaint.json"
        clean_path = CLEAN_DIR / f"page_{n}_clean.png"

        if not raw_path.exists():
            print(f"[skip] page_{n}: raw not found")
            continue
        if not inpaint_path.exists():
            print(f"[skip] page_{n}: inpaint.json not found (may have failed)")
            continue

        raw_img = Image.open(raw_path).convert("RGB")
        inpaint_data = json.loads(inpaint_path.read_text(encoding="utf-8"))
        text_free_boxes = extract_text_free_boxes(inpaint_data)

        if not text_free_boxes:
            sections.append(render_no_free_section(n, raw_img))
            pages_no_free += 1
            print(f"[page {n}] no text_free boxes")
            continue

        # 加载 clean 图
        if clean_path.exists():
            clean_img = Image.open(clean_path).convert("RGB")
        else:
            print(f"[warn] page_{n}: clean image not found, using raw as fallback")
            clean_img = raw_img

        # 生成精修mask（和04_inpaint相同参数 pad=4）
        img_rgb = np.array(raw_img)
        bbox_list = list(text_free_boxes.values())
        mask_np = refine_text_mask(img_rgb, bbox_list, pad=4)

        # 构建深接口 StageOutput
        mask_stage = build_mask_stage(raw_img, mask_np, text_free_boxes)
        inpaint_stage = build_inpaint_stage(clean_img, text_free_boxes)

        # 渲染 section
        sections.append(render_page_section(n, raw_img, clean_img, mask_stage, inpaint_stage))
        total_free += len(text_free_boxes)
        pages_with_free += 1
        print(f"[page {n}] {len(text_free_boxes)} text_free boxes, rendered")

    # 统计卡片
    stats_html = f"""
    <div class="stats">
      <div class="stat"><div class="num">{pages_with_free + pages_no_free}</div><div class="lbl">总页数</div></div>
      <div class="stat ok"><div class="num">{pages_with_free}</div><div class="lbl">有text_free框</div></div>
      <div class="stat warn"><div class="num">{pages_no_free}</div><div class="lbl">无text_free框</div></div>
      <div class="stat"><div class="num">{total_free}</div><div class="lbl">text_free框总数</div></div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Stage4 验证报告 — 像素精修mask + inpaint（11-20页）</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <h1>Stage4 验证报告 — 像素精修mask + inpaint</h1>
  <div class="subtitle">
    方案A精修mask（Otsu + 颜色直方图 + 连通域）｜ inpaint引擎: lama-manga ｜
    范围: 11-20页 ｜ 生成时间: {time.strftime("%Y-%m-%d %H:%M:%S")}
  </div>
  {stats_html}
  {''.join(sections)}
  <div class="footer">
    amta Stage4 验证 ｜ 深接口 StageOutput (mask/inpaint) ｜
    页码1基（page_N ↔ N.jpg）｜ 分支: feat/stage4-outside-text-removal
  </div>
</div>
</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    elapsed = time.time() - t0
    print("\n=== 报告生成完成 ===")
    print(f"输出: {OUT_HTML}")
    print(f"大小: {OUT_HTML.stat().st_size / 1024:.0f} KB")
    print(f"页数: {pages_with_free + pages_no_free} (有框: {pages_with_free}, 无框: {pages_no_free})")
    print(f"text_free框总数: {total_free}")
    print(f"耗时: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
