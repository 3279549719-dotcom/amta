"""从 detect_full results.json 生成快速 HTML 检测报告。"""
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "output" / "data" / "detect_full" / "results.json"
OUT = ROOT / "output" / "data" / "detect_full" / "report.html"

with open(RESULTS, "r", encoding="utf-8") as f:
    data = json.load(f)

agg = data["aggregate"]
pages = data["per_page"]

# 每页表格行
rows = ""
for p in pages:
    if "error" in p:
        rows += f'<tr><td>{p["page"]}</td><td colspan="8" style="color:#999;">ERROR: {p["error"]}</td></tr>'
        continue
    short_pct = round(p["short_boxes_le3"] / p["n_boxes"] * 100, 1) if p["n_boxes"] else 0
    punct_pct = round(p["punct_only_boxes"] / p["n_boxes"] * 100, 1) if p["n_boxes"] else 0
    # 高误报页标红
    row_class = ' class="warn"' if punct_pct >= 15 or short_pct >= 30 else ""
    rows += f"""<tr{row_class}>
      <td><b>{p['page']:02d}</b></td>
      <td>{p['n_boxes']}</td>
      <td>{p['raw_chars']}</td>
      <td>{p['avg_chars_per_box']}</td>
      <td>{p['non_empty_rate']*100:.0f}%</td>
      <td>{p['short_boxes_le3']} ({short_pct}%)</td>
      <td>{p['punct_only_boxes']} ({punct_pct}%)</td>
      <td>{p['detect_time_sec']}s</td>
      <td>{p['ocr_time_sec']}s</td>
    </tr>"""

# 柱状图数据（每页字符数）
max_chars = max(p.get("raw_chars", 0) for p in pages if "error" not in p)
bars = ""
for p in pages:
    if "error" in p:
        continue
    h = int(p["raw_chars"] / max_chars * 120)
    color = "#4f46e5"
    if p["punct_only_boxes"] / max(1, p["n_boxes"]) >= 0.15:
        color = "#ef4444"
    bars += f'<div class="bar" style="height:{h}px;background:{color}" title="page {p["page"]}: {p["raw_chars"]} chars, {p["n_boxes"]} boxes"></div>'
bar_labels = "".join(f'<div class="bar-label">{p["page"]:02d}</div>' for p in pages if "error" not in p)

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>全量检测报告 — RT-DETR-v2 + Baberu OCR (42页)</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f5f7fa; color:#1a1a2e; line-height:1.6; }}
  .container {{ max-width:1400px; margin:0 auto; padding:24px; }}
  h1 {{ font-size:24px; margin-bottom:4px; }}
  .subtitle {{ color:#666; margin-bottom:24px; font-size:14px; }}
  .summary-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin-bottom:28px; }}
  .card {{ background:#fff; border-radius:12px; padding:18px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
  .card .label {{ font-size:11px; color:#888; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px; }}
  .card .value {{ font-size:26px; font-weight:700; }}
  .card .delta {{ font-size:12px; margin-top:4px; color:#666; }}
  .card.warn .value {{ color:#ef4444; }}
  .card.good .value {{ color:#16a34a; }}
  .section {{ background:#fff; border-radius:12px; padding:22px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
  .section h3 {{ font-size:16px; margin-bottom:14px; }}
  .bar-chart {{ display:flex; align-items:flex-end; gap:3px; height:140px; padding:0 4px; border-bottom:1px solid #eee; overflow-x:auto; }}
  .bar {{ width:18px; border-radius:3px 3px 0 0; flex-shrink:0; }}
  .bar-labels {{ display:flex; gap:3px; padding:4px 4px 0; font-size:9px; color:#999; overflow-x:auto; }}
  .bar-label {{ width:18px; text-align:center; flex-shrink:0; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ padding:8px 10px; text-align:left; border-bottom:1px solid #f0f0f0; }}
  th {{ background:#f8fafc; font-weight:600; color:#555; font-size:11px; text-transform:uppercase; letter-spacing:0.3px; position:sticky; top:0; }}
  tr.warn {{ background:#fef2f2; }}
  tr:hover {{ background:#f8fafc; }}
  .note {{ background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:12px 16px; margin-bottom:20px; font-size:13px; color:#1e40af; }}
  .footer {{ text-align:center; color:#999; font-size:12px; margin-top:32px; padding:16px; }}
</style>
</head>
<body>
<div class="container">
  <h1>全量检测报告 — RT-DETR-v2 + Baberu OCR</h1>
  <p class="subtitle">《单翼停留之地》全 42 页 ｜ conf_threshold=0.3 ｜ {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

  <div class="note">
    <b>关键发现：</b>全本 415 框 / 6003 字符，平均 9.9 框/页。
    <b>8.4%（35框）为纯标点误报</b>（`．．．`/`～` 等），可通过 <code>has_translatable_content()</code> 过滤；
    <b>17.8%（74框）为 ≤3 字符短框</b>，其中部分是合法 SFX，部分是误报，需 VLM 上下文判断。
  </div>

  <div class="summary-grid">
    <div class="card good"><div class="label">检测页数</div><div class="value">{agg['pages_ok']}/{agg['pages_total']}</div><div class="delta">全部成功</div></div>
    <div class="card"><div class="label">总检测框</div><div class="value">{agg['total_boxes']}</div><div class="delta">平均 {agg['avg_boxes_per_page']} 框/页</div></div>
    <div class="card"><div class="label">总字符数</div><div class="value">{agg['total_chars']}</div><div class="delta">平均 {agg['avg_chars_per_page']} 字/页</div></div>
    <div class="card"><div class="label">非空率</div><div class="value">{agg['avg_nonempty_rate']*100:.0f}%</div><div class="delta">所有框均有 OCR 输出</div></div>
    <div class="card warn"><div class="label">纯标点框</div><div class="value">{agg['total_punct_boxes']}</div><div class="delta">{agg['total_punct_boxes']/agg['total_boxes']*100:.1f}% — 可直接过滤</div></div>
    <div class="card warn"><div class="label">短框(≤3字)</div><div class="value">{agg['total_short_boxes']}</div><div class="delta">{agg['total_short_boxes']/agg['total_boxes']*100:.1f}% — 需 VLM 判断</div></div>
    <div class="card"><div class="label">检测耗时</div><div class="value">{agg['total_detect_time']}s</div><div class="delta">平均 {agg['total_detect_time']/agg['pages_ok']:.2f}s/页</div></div>
    <div class="card"><div class="label">OCR耗时</div><div class="value">{agg['total_ocr_time']}s</div><div class="delta">平均 {agg['total_ocr_time']/agg['pages_ok']:.1f}s/页</div></div>
  </div>

  <div class="section">
    <h3>各页字符数分布（红色=纯标点框占比≥15%）</h3>
    <div class="bar-chart">{bars}</div>
    <div class="bar-labels">{bar_labels}</div>
  </div>

  <div class="section">
    <h3>每页详细数据</h3>
    <div style="overflow-x:auto;max-height:600px;overflow-y:auto;">
    <table>
      <thead><tr>
        <th>页</th><th>框数</th><th>字符</th><th>均字/框</th><th>非空率</th>
        <th>短框≤3字</th><th>纯标点框</th><th>检测</th><th>OCR</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    </div>
  </div>

  <div class="footer">
    AMTA full-run detection report · RT-DETR-v2 (ogkalu) · Baberu OCR (genshiai-daichi) · Total {agg['elapsed_sec']}s
  </div>
</div>
</body>
</html>"""

OUT.write_text(html, encoding="utf-8")
print(f"[report] -> {OUT}")
print(f"[report] {agg['pages_ok']} pages, {agg['total_boxes']} boxes, {agg['total_chars']} chars")
