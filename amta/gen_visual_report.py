"""生成 conf=0.3/0.5/0.7 三档阈值下"原图 + 检测框标注 + 每框识别情况"对比可视化。

修复：跨 conf 用 bbox IoU 物理匹配同一框，不再依赖 region_id 字符串（编号会错位）。
每页 = 三档并排（每档原图 + 绿框保留/红框砍掉）+ 明细表（按物理框对齐，含每框在三档的保留状态）。
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "compare_conf"
RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")

CONFS = ["0.3", "0.5", "0.7"]
COLOR_KEEP = (34, 197, 94)     # 绿 - 该档保留
COLOR_CUT = (239, 68, 68)      # 红 - 该档被砍
COLOR_FONT = (255, 255, 255)

# 3.jpg 人工核实的真假（按物理位置描述，下面用 bbox 匹配）
P2_GROUND_TRUTH = {
    # bbox: (label)
    (1804, 1134, 1978, 1989): "真",
    (60, 269, 632, 476): "假",       # 窗帘
    (60, 689, 946, 818): "假",       # 装饰条
    (1629, 329, 1792, 812): "真",
    (847, 1720, 1013, 2071): "真",
    (877, 1131, 1002, 1484): "真",
    (1087, 2534, 1175, 2877): "真",
    (494, 842, 681, 979): "真(音效)",
    (174, 2958, 317, 3064): "假",    # 网点
}


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def get_font(size: int) -> ImageFont.ImageFont:
    for name in ["msyh.ttc", "simhei.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def iou(b1: list, b2: list) -> float:
    x1, y1, x2, y2 = b1
    a1, c1, a2, c2 = b2
    ix1, iy1 = max(x1, a1), max(y1, c1)
    ix2, iy2 = min(x2, a2), min(y2, c2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    area1 = (x2 - x1) * (y2 - y1)
    area2 = (a2 - a1) * (c2 - c1)
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0


def match_physical(base_bbox: list, conf_blocks: list[dict], thr: float = 0.5) -> dict | None:
    """在 conf_blocks 里找与 base_bbox IoU>thr 的物理框。"""
    best, best_iou = None, 0.0
    for b in conf_blocks:
        v = iou(base_bbox, b["bbox"])
        if v > best_iou:
            best, best_iou = b, v
    return best if best_iou > thr else None


def draw_page(draw: ImageDraw.ImageDraw, base_blocks: list[dict], scale: float, offset: int,
              keep_phys: set[int], font: ImageFont.ImageFont, img_w: int):
    """在单档图上画检测框。keep_phys = 该档保留的 base block 索引集合。"""
    for idx, b in enumerate(base_blocks):
        x1, y1, x2, y2 = [int(v * scale) for v in b["bbox"]]
        y1 += offset
        y2 += offset
        conf = b.get("confidence", 0)
        rid = b.get("region_id", "")
        color = COLOR_KEEP if idx in keep_phys else COLOR_CUT
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        label = f"{rid} conf={conf:.3f} {b.get('bubble_type','')}"
        gt = get_gt(b["bbox"])
        if gt:
            label += f" [{gt}]"
        font_l = get_font(11)
        label_w = draw.textlength(label, font=font_l)
        lx = min(x1, img_w - label_w - 4)
        ly = max(0, y1 - 18)
        draw.rectangle([lx, ly, lx + label_w + 6, ly + 16], fill=(0, 0, 0))
        draw.text((lx + 3, ly + 1), label, fill=COLOR_FONT, font=font_l)


def get_gt(bbox: list) -> str:
    key = tuple(int(v) for v in bbox)
    for gt_key, label in P2_GROUND_TRUTH.items():
        if iou(list(key), list(gt_key)) > 0.7:
            return label
    return ""


def render_page_row(page_idx: int) -> dict:
    page = f"page_{page_idx}"
    raw_path = RAW / f"{page_idx + 1}.jpg"
    img = Image.open(raw_path)
    w, h = img.size

    # 读三档检测
    det_all = {}
    canon_all = {}
    for conf in CONFS:
        det_all[conf] = load_json(OUT / f"{page}_conf{conf}_det.json")["blocks"]
        canon_all[conf] = {it["region_id"]: it for it in load_json(OUT / f"{page}_conf{conf}_canon.json")["items"]}

    # 基准 = conf=0.3 全集的框（最全）
    base_blocks = det_all["0.3"]

    # OCR 文本：从 conf=0.3 canon 按 region_id 取
    ocr_text = {}
    for it in canon_all["0.3"].values():
        ocr_text[it["region_id"]] = it.get("text", "")

    # 物理匹配：每个 base 框在各 conf 里是否保留
    keep_phys = {}  # conf -> set(base_idx)
    for conf in CONFS:
        conf_blocks = det_all[conf]
        keep = set()
        for idx, b in enumerate(base_blocks):
            m = match_physical(b["bbox"], conf_blocks)
            if m is not None:
                keep.add(idx)
        keep_phys[conf] = keep

    # 画三档并排
    thumb_h = 460
    panel_w = int(w * thumb_h / h)
    canvas_w = panel_w * 3 + 60
    canvas_h = thumb_h + 20
    canvas = Image.new("RGB", (canvas_w, canvas_h), (245, 247, 250))
    draw = ImageDraw.Draw(canvas)

    for ci, conf in enumerate(CONFS):
        ox = ci * (panel_w + 30)
        title = f"conf={conf}"
        if conf == "0.7":
            title += "  (推荐)"
        draw.text((ox + 8, 2), title, fill=(30, 64, 175), font=get_font(20))
        scale = thumb_h / h
        thumb = img.resize((panel_w, thumb_h))
        canvas.paste(thumb, (ox, 18))
        draw_page(draw, base_blocks, scale, 18, keep_phys[conf], get_font(11), panel_w)
        n_keep = len(keep_phys[conf])
        n_cut = len(base_blocks) - n_keep
        stat = f"保留 {n_keep} / 砍掉 {n_cut}"
        draw.text((ox + 8, thumb_h + 20), stat, fill=(37, 99, 235) if n_cut == 0 else (220, 38, 38), font=get_font(13))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    # 明细表（物理对齐）
    table_rows = []
    for idx, b in enumerate(base_blocks):
        table_rows.append({
            "region": b["region_id"],
            "conf": round(b.get("confidence", 0), 3),
            "type": b.get("bubble_type", ""),
            "text": ocr_text.get(b["region_id"], ""),
            "kept": {conf: (idx in keep_phys[conf]) for conf in CONFS},
            "gt": get_gt(b["bbox"]),
        })

    return {"img_b64": img_b64, "page": page, "file": f"{page_idx + 1}.jpg", "rows": table_rows}


def main():
    all_pages = []
    for i in range(10):
        print(f"rendering page_{i}...")
        all_pages.append(render_page_row(i))

    html_parts = []
    html_parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>检测置信度阈值对比 — conf=0.3 vs 0.5 vs 0.7（含原图与检测框）</title>
<style>
  body { font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a2e; margin:0; padding:24px; line-height:1.6; }
  .container { max-width:1200px; margin:0 auto; }
  h1 { font-size:24px; margin-bottom:4px; }
  .subtitle { color:#666; font-size:13px; margin-bottom:20px; }
  .page-section { background:#fff; border-radius:12px; padding:20px; margin-bottom:24px; box-shadow:0 1px 4px rgba(0,0,0,0.06); }
  .page-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }
  .page-title { font-size:17px; font-weight:700; color:#1e40af; }
  .page-stats { font-size:12px; color:#666; }
  .panel-img { width:100%; border-radius:8px; border:1px solid #e5e7eb; margin-bottom:12px; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th { background:#f3f4f6; padding:6px; text-align:left; border-bottom:2px solid #e5e7eb; }
  td { padding:6px; border-bottom:1px solid #f3f4f6; }
  .keep { color:#16a34a; font-weight:700; }
  .cut { color:#dc2626; font-weight:700; }
  .gt-real { color:#16a34a; }
  .gt-fake { color:#dc2626; }
  .legend { display:inline-block; width:12px; height:12px; border-radius:2px; margin-right:4px; vertical-align:middle; }
  .footer { text-align:center; color:#999; font-size:11px; margin-top:32px; padding:16px; }
</style>
</head>
<body>
<div class="container">
  <h1>检测置信度阈值对比 — conf=0.3 vs 0.5 vs 0.7</h1>
  <div class="subtitle">
    连续 1–10.jpg ｜ 每档 = 原图 + 检测框（<span class="legend" style="background:#22c55e"></span>保留 / <span class="legend" style="background:#ef4444"></span>砍掉）
    ｜ 跨档按物理位置(bbox)对齐，同一框在三档的保留状态逐格对比 ｜ 3.jpg 标注人工核实真假 ｜ 2026-09-02
  </div>""")

    for p in all_pages:
        rows_html = ""
        for r in p["rows"]:
            kept_cells = "".join(
                f'<td class="{"keep" if r["kept"][c] else "cut"}">{"✓" if r["kept"][c] else "✗"}</td>'
                for c in CONFS)
            gt_cls = "gt-real" if r["gt"] == "真" else ("gt-fake" if r["gt"] == "假" else "")
            rows_html += f"""<tr>
              <td><strong>{r["region"]}</strong></td>
              <td>{r["conf"]:.3f}</td>
              <td>{r["type"]}</td>
              <td style="font-family:monospace">{r["text"]}</td>
              {kept_cells}
              <td class="{gt_cls}">{r["gt"]}</td>
            </tr>"""
        html_parts.append(f"""
  <div class="page-section">
    <div class="page-header">
      <div class="page-title">{p["page"]} — {p["file"]}</div>
      <div class="page-stats">检测框：conf0.3={sum(1 for r in p["rows"] if r["kept"]["0.3"])}, conf0.5={sum(1 for r in p["rows"] if r["kept"]["0.5"])}, conf0.7={sum(1 for r in p["rows"] if r["kept"]["0.7"])}</div>
    </div>
    <img class="panel-img" src="data:image/png;base64,{p["img_b64"]}">
    <table>
      <thead><tr><th>region</th><th>conf</th><th>类型</th><th>OCR 文本</th><th>conf=0.3</th><th>conf=0.5</th><th>conf=0.7</th><th>真假(3.jpg)</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>""")

    html_parts.append("""
  <div class="footer">
    检测: RT-DETR-v2 ｜ OCR: baberu ｜ 规则: pure_punct/pure_number/extreme_aspect/edge_box ｜
    分支: feat/deepseek-vision-compare ｜ 修复: 跨档按 bbox 物理对齐（不再用 region_id 字符串）
  </div>
</div>
</body>
</html>""")

    out_html = OUT / "conf_threshold_visual_report.html"
    out_html.write_text("\n".join(html_parts), encoding="utf-8")
    print(f"报告 -> {out_html} ({out_html.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
