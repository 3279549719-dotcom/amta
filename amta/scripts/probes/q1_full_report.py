"""Q1 完整报告：原图 + 检测框标注 + OCR + 翻译。

用法：uv run python scripts/probes/q1_full_report.py
输出：workspace/exp-q1-tiling-garbled/q1_full_report.html
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 清除代理
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
DET_DIR = PROJECT_ROOT / "workspace" / "exp-q1-tiling-garbled" / "artifacts" / "detection"
AUDIT_DIR = PROJECT_ROOT / "workspace" / "exp-q1-tiling-garbled" / "q1_target_audit"
OUT_DIR = PROJECT_ROOT / "workspace" / "exp-q1-tiling-garbled"
ANNOT_DIR = OUT_DIR / "annotated"


def load_target_boxes():
    """加载目标框数据（OCR+翻译）。"""
    data = json.loads((AUDIT_DIR / "q1_target_boxes.json").read_text(encoding="utf-8"))
    return data


def load_detection(page):
    """加载某页的 detection 数据。"""
    f = DET_DIR / f"page_{page}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def annotate_page(page, target_boxes):
    """在原图上画检测框，返回标注后图片路径。"""
    ANNOT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{page}.jpg"
    if not raw_path.exists():
        return None

    img = Image.open(raw_path).convert("RGB")
    # 缩小到宽度 800，方便 HTML 显示
    scale = 800 / img.width
    new_w, new_h = 800, int(img.height * scale)
    img_small = img.resize((new_w, new_h), Image.LANCZOS)
    draw = ImageDraw.Draw(img_small)

    # 画所有检测框（灰色），目标框用红色
    det = load_detection(page)
    if det:
        for b in det["blocks"]:
            x1, y1, x2, y2 = [int(v * scale) for v in b["bbox"]]
            is_target = any(tb["region_id"] == b["region_id"] for tb in target_boxes)
            color = (220, 50, 50) if is_target else (180, 180, 180)
            width = 3 if is_target else 1
            draw.rectangle([x1, y1, x2, y2], outline=color, width=width)
            if is_target:
                draw.text((x1 + 2, y1 + 2), b["region_id"], fill=color)

    out_path = ANNOT_DIR / f"page_{page}_annotated.jpg"
    img_small.save(out_path, quality=85)
    return out_path


def generate_html(target_boxes):
    """生成完整 HTML 报告。"""
    pages = sorted(set(b["page"] for b in target_boxes))
    by_page = {p: [b for b in target_boxes if b["page"] == p] for p in pages}

    # 统计
    total = len(target_boxes)
    empty = sum(1 for b in target_boxes if not b.get("translation"))
    tiled = sum(1 for b in target_boxes if "tiled_new" in b["reasons"])
    ea_rescued = sum(1 for b in target_boxes if "extreme_aspect_rescued" in b["reasons"])
    eb_rescued = sum(1 for b in target_boxes if "edge_box_rescued" in b["reasons"])

    sections = ""
    for page in pages:
        boxes = by_page[page]
        annot_path = annotate_page(page, boxes)
        annot_rel = f"annotated/page_{page}_annotated.jpg" if annot_path else ""

        rows = ""
        for b in boxes:
            ocr = b.get("ocr_text", "").replace("\n", "<br>") or "<em>(空)</em>"
            trans = b.get("translation", "").replace("\n", "<br>") or '<span style="color:#EA6668;font-weight:600;">(空)</span>'
            reasons = ", ".join(b["reasons"])
            is_empty = not b.get("translation")
            row_bg = 'style="background:#FFF5F5;"' if is_empty else ""
            rows += f'''
            <tr {row_bg}>
              <td class="rid">{b["region_id"]}</td>
              <td>{b["bubble_type"]}</td>
              <td>{b["confidence"]:.3f}</td>
              <td style="font-size:11px;color:#888;">{reasons}</td>
              <td>{ocr}</td>
              <td class="trans">{trans}</td>
            </tr>'''

        sections += f'''
        <div class="page-section">
          <div class="page-header">
            <span class="page-title">第 {page} 页</span>
            <span class="page-meta">{len(boxes)} 个目标框</span>
          </div>
          <div class="layout">
            <div class="img-panel">
              {"<img src='" + annot_rel + "' alt='page " + str(page) + "' />" if annot_rel else "<em>原图不可用</em>"}
              <div class="legend">
                <span class="legend-item"><span class="legend-box red"></span>目标框</span>
                <span class="legend-item"><span class="legend-box gray"></span>其他框</span>
              </div>
            </div>
            <div class="table-panel">
              <table>
                <thead><tr><th>ID</th><th>类型</th><th>Conf</th><th>救回原因</th><th>OCR 原文</th><th>翻译</th></tr></thead>
                <tbody>{rows}</tbody>
              </table>
            </div>
          </div>
        </div>'''

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Q1 目标框完整审计报告</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a2e; margin:0; padding:24px; line-height:1.6; }}
.container {{ max-width:1400px; margin:0 auto; }}
h1 {{ font-size:22px; margin-bottom:4px; }}
.subtitle {{ color:#666; font-size:13px; margin-bottom:20px; }}
.stats {{ display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }}
.stat {{ background:#fff; border-radius:10px; padding:12px 18px; box-shadow:0 1px 4px rgba(0,0,0,.06); min-width:100px; }}
.stat .num {{ font-size:24px; font-weight:700; color:#1e40af; }}
.stat .num.red {{ color:#EA6668; }}
.stat .num.green {{ color:#52C41A; }}
.stat .lbl {{ font-size:11px; color:#666; }}
.page-section {{ background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }}
.page-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }}
.page-title {{ font-size:16px; font-weight:700; color:#1e40af; }}
.page-meta {{ font-size:12px; color:#888; }}
.layout {{ display:flex; gap:20px; align-items:flex-start; }}
.img-panel {{ flex:0 0 45%; }}
.img-panel img {{ width:100%; border-radius:8px; border:1px solid #e5e7eb; }}
.legend {{ display:flex; gap:16px; margin-top:8px; font-size:11px; color:#666; }}
.legend-item {{ display:flex; align-items:center; gap:4px; }}
.legend-box {{ display:inline-block; width:12px; height:12px; border-radius:2px; }}
.legend-box.red {{ background:#dc3545; }}
.legend-box.gray {{ background:#b4b4b4; }}
.table-panel {{ flex:1; overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th {{ background:#f3f4f6; padding:6px 8px; text-align:left; border-bottom:2px solid #e5e7eb; }}
td {{ padding:6px 8px; border-bottom:1px solid #f3f4f6; vertical-align:top; }}
tr:hover {{ background:#f9fafb; }}
.rid {{ font-weight:600; color:#1e40af; white-space:nowrap; }}
.trans {{ font-weight:500; }}
.footer {{ text-align:center; color:#999; font-size:11px; margin-top:24px; padding:16px; }}
</style>
</head>
<body>
<div class="container">
  <h1>Q1 目标框完整审计报告</h1>
  <div class="subtitle">瓦片化新增框 + 被旧几何规则救回的真框 · 翻译加"乱码→空"条款 · 无重试/无二分/无长度比护栏</div>
  <div class="stats">
    <div class="stat"><div class="num">{total}</div><div class="lbl">目标框总数</div></div>
    <div class="stat"><div class="num green">{total - empty}</div><div class="lbl">正常翻译</div></div>
    <div class="stat"><div class="num red">{empty}</div><div class="lbl">翻译为空</div></div>
    <div class="stat"><div class="num">{tiled}</div><div class="lbl">瓦片化新增</div></div>
    <div class="stat"><div class="num">{ea_rescued}</div><div class="lbl">extreme_aspect 救回</div></div>
    <div class="stat"><div class="num">{eb_rescued}</div><div class="lbl">edge_box 救回</div></div>
    <div class="stat"><div class="num">{len(pages)}</div><div class="lbl">分布页数</div></div>
  </div>
  {sections}
  <div class="footer">Q1 audit — 原图 + 检测框标注 + OCR + 翻译</div>
</div>
</body>
</html>"""

    out_path = OUT_DIR / "q1_full_report.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def main():
    print("加载目标框数据...")
    target_boxes = load_target_boxes()
    print(f"  目标框: {len(target_boxes)} 个")

    print("生成标注图和 HTML 报告...")
    out_path = generate_html(target_boxes)
    print(f"  报告已生成: {out_path}")
    print(f"  标注图目录: {ANNOT_DIR}")


if __name__ == "__main__":
    main()
