"""从 detect_multi results.json 生成多检测器对比 HTML 报告。"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "output" / "data" / "detect_multi" / "results.json"
OUT = ROOT / "output" / "data" / "detect_multi" / "report.html"

RAW_IMAGES = {
    11: "https://aka.doubaocdn.com/s/UotZDq81VE",
    13: "https://aka.doubaocdn.com/s/m9S1UfNy2d",
    14: "https://aka.doubaocdn.com/s/YsQN5ioVAT",
    17: "https://aka.doubaocdn.com/s/nxdVaVKiIc",
    18: "https://aka.doubaocdn.com/s/A7Vxng0Gun",
}

DETECTOR_LABELS = {
    "baseline": "4引擎并集 (baseline)",
    "rtdetr-v2": "RT-DETR-v2 (方案C)",
    "koharu-ctd": "koharu CTD单引擎 (方案A)",
    "ctd-onnx": "CTD ONNX直接推理 (方案B)",
}

DETECTOR_COLORS = {
    "baseline": "#94a3b8",
    "rtdetr-v2": "#4f46e5",
    "koharu-ctd": "#16a34a",
    "ctd-onnx": "#f59e0b",
}

with open(RESULTS, "r", encoding="utf-8") as f:
    data = json.load(f)

pages = [p for p in data["per_page"] if "error" not in p]
det_names = list(pages[0]["detectors"].keys()) if pages else []
agg = data.get("aggregate", {})

# 汇总卡片
cards = ""
for dn in det_names:
    m = agg.get(dn, {})
    label = DETECTOR_LABELS.get(dn, dn)
    color = DETECTOR_COLORS.get(dn, "#666")
    cards += f"""
    <div class="summary-card">
      <div class="label">{label}</div>
      <div class="value" style="color:{color}">{m.get('total_chars',0)}</div>
      <div class="delta">{m.get('total_boxes',0)} 框 · 非空率 {m.get('avg_nonempty_rate',0)*100:.0f}% · {m.get('avg_detect_time',0)}s/页</div>
    </div>"""

# 柱状图
max_chars = max(max(p["detectors"][dn]["dedup_chars"] for dn in det_names) for p in pages) if pages else 1
bar_groups = ""
for p in pages:
    bars = ""
    for dn in det_names:
        h = int(p["detectors"][dn]["dedup_chars"] / max_chars * 120)
        color = DETECTOR_COLORS.get(dn, "#666")
        bars += f'<div class="bar" style="height:{h}px;background:{color}" title="{dn}: {p["detectors"][dn]["dedup_chars"]} chars"></div>'
    bar_groups += f'<div class="bar-group">{bars}<div class="bar-label">p{p["page"]}</div></div>'

legend = "".join(
    f'<span><span class="dot" style="background:{DETECTOR_COLORS.get(dn,"#666")}"></span>{DETECTOR_LABELS.get(dn,dn)}</span>'
    for dn in det_names
)

# 每页详情
page_sections = []
for p in pages:
    raw_url = RAW_IMAGES.get(p["page"], "")
    raw_img = f'<div style="margin-bottom:16px;"><img src="{raw_url}" style="max-width:100%;border-radius:8px;border:1px solid #eee;"></div>' if raw_url else ""

    # 对比表
    rows = ""
    metrics = [
        ("检测框数", "n_boxes", ""),
        ("非空框率", "non_empty_rate", "%"),
        ("去重后字符数", "dedup_chars", ""),
        ("平均每框字符", "avg_chars_per_nonempty", ""),
        ("检测耗时", "detect_time_sec", "s"),
        ("OCR耗时", "ocr_time_sec", "s"),
    ]
    for label, key, unit in metrics:
        cells = ""
        for dn in det_names:
            v = p["detectors"][dn].get(key)
            if v is None:
                cells += "<td>N/A</td>"
            elif key == "non_empty_rate":
                cells += f"<td>{v*100:.1f}%</td>"
            else:
                cells += f"<td>{v}{unit}</td>"
        rows += f"<tr><td><b>{label}</b></td>{cells}</tr>"

    header = "".join(f"<th>{DETECTOR_LABELS.get(dn,dn)}</th>" for dn in det_names)

    # OCR 结果
    ocr_cols = ""
    for dn in det_names:
        items = p["detectors"][dn].get("ocr_results", [])
        if not items:
            list_html = '<div style="color:#999;font-size:13px;padding:8px;">无</div>'
        else:
            rows_html = "".join(
                f'<div class="ocr-item"><span class="bbox">[{int(i["bbox"][0])},{int(i["bbox"][1])}]</span><span class="text">{i["text"]}</span></div>'
                for i in items
            )
            list_html = f'<div class="ocr-list">{rows_html}</div>'
        ocr_cols += f'<div class="ocr-results"><h4>{DETECTOR_LABELS.get(dn,dn)}（{len(items)}条）</h4>{list_html}</div>'

    section = f"""
    <div class="page-section">
      <div class="page-title">第 {p['page']} 页 <span class="badge">{p['image_size'][0]}x{p['image_size'][1]}</span></div>
      {raw_img}
      <table class="compare-table">
        <thead><tr><th>指标</th>{header}</tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <div style="display:grid;grid-template-columns:repeat({len(det_names)},1fr);gap:12px;margin-top:16px;">
        {ocr_cols}
      </div>
    </div>
    """
    page_sections.append(section)

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>检测方案对比报告 — baseline / RT-DETR-v2 / koharu-CTD</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f5f7fa; color:#1a1a2e; line-height:1.6; }}
  .container {{ max-width:1400px; margin:0 auto; padding:24px; }}
  h1 {{ font-size:24px; margin-bottom:8px; }}
  .subtitle {{ color:#666; margin-bottom:24px; font-size:14px; }}
  .summary-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin-bottom:32px; }}
  .summary-card {{ background:#fff; border-radius:12px; padding:20px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
  .summary-card .label {{ font-size:12px; color:#888; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px; }}
  .summary-card .value {{ font-size:28px; font-weight:700; }}
  .summary-card .delta {{ font-size:13px; margin-top:4px; color:#666; }}
  .chart-section {{ background:#fff; border-radius:12px; padding:24px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
  .chart-section h3 {{ font-size:16px; margin-bottom:16px; }}
  .bar-chart {{ display:flex; align-items:flex-end; gap:20px; height:160px; padding:0 8px; border-bottom:1px solid #eee; }}
  .bar-group {{ flex:1; display:flex; flex-direction:row; align-items:flex-end; justify-content:center; gap:4px; }}
  .bar {{ width:28px; border-radius:4px 4px 0 0; }}
  .bar-label {{ font-size:11px; color:#666; margin-top:4px; position:absolute; }}
  .legend {{ display:flex; gap:16px; font-size:12px; color:#666; margin-bottom:12px; flex-wrap:wrap; }}
  .legend span {{ display:flex; align-items:center; gap:4px; }}
  .legend .dot {{ width:10px; height:10px; border-radius:2px; }}
  .page-section {{ background:#fff; border-radius:12px; padding:24px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
  .page-title {{ font-size:18px; font-weight:600; margin-bottom:16px; display:flex; align-items:center; gap:8px; }}
  .page-title .badge {{ font-size:11px; padding:2px 8px; border-radius:10px; background:#eef2ff; color:#4f46e5; }}
  .compare-table {{ width:100%; border-collapse:collapse; margin-bottom:8px; }}
  .compare-table th,.compare-table td {{ padding:10px 14px; text-align:left; border-bottom:1px solid #eee; font-size:14px; }}
  .compare-table th {{ background:#f8fafc; font-weight:600; color:#555; font-size:12px; }}
  .ocr-results h4 {{ font-size:14px; margin-bottom:8px; color:#555; }}
  .ocr-list {{ max-height:280px; overflow-y:auto; border:1px solid #eee; border-radius:8px; }}
  .ocr-item {{ padding:8px 12px; border-bottom:1px solid #f0f0f0; font-size:13px; display:flex; gap:10px; }}
  .ocr-item:last-child {{ border-bottom:none; }}
  .ocr-item .bbox {{ color:#888; font-family:monospace; font-size:11px; white-space:nowrap; flex-shrink:0; }}
  .ocr-item .text {{ flex:1; }}
  .footer {{ text-align:center; color:#999; font-size:12px; margin-top:32px; padding:16px; }}
  .note {{ background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:12px 16px; margin-bottom:24px; font-size:13px; color:#92400e; }}
</style>
</head>
<body>
<div class="container">
  <h1>检测方案对比报告</h1>
  <p class="subtitle">4引擎并集 vs RT-DETR-v2 vs koharu-CTD单引擎 ｜ OCR：Baberu ONNX int4 ｜ {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

  <div class="note">
    <b>说明：</b>方案A（koharu-CTD单引擎）本质就是 manga-image-translator 的 CTD 模型，通过 koharu REST API 调用。
    方案B（CTD ONNX直接推理）因模型文件国内下载困难暂未跑通，检测质量应与 koharu-CTD 一致，优势是速度更快（避免 koharu 41.8s/页开销）。
  </div>

  <div class="summary-grid">{cards}</div>

  <div class="chart-section">
    <h3>各页 OCR 字符数对比</h3>
    <div class="legend">{legend}</div>
    <div class="bar-chart">{bar_groups}</div>
  </div>

  {''.join(page_sections)}

  <div class="footer">
    AMTA detect A/B/C test · RT-DETR-v2 (ogkalu) · CTD (manga-image-translator) · Baberu OCR (genshiai-daichi)
  </div>
</div>
</body>
</html>"""

OUT.write_text(html, encoding="utf-8")
print(f"[report] -> {OUT}")
print(f"[report] {len(pages)} pages, detectors: {det_names}")
