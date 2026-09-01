"""从 results.json 生成 HTML 对比报告。"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "output" / "data" / "detect_ab" / "results.json"
OUT = ROOT / "output" / "data" / "detect_ab" / "report.html"

with open(RESULTS, "r", encoding="utf-8") as f:
    data = json.load(f)

agg = data.get("aggregate", {})
pages = [p for p in data["per_page"] if "error" not in p]

# 原图公网 URL
RAW_IMAGES = {
    11: "https://aka.doubaocdn.com/s/UotZDq81VE",
    13: "https://aka.doubaocdn.com/s/m9S1UfNy2d",
    14: "https://aka.doubaocdn.com/s/YsQN5ioVAT",
    17: "https://aka.doubaocdn.com/s/nxdVaVKiIc",
    18: "https://aka.doubaocdn.com/s/A7Vxng0Gun",
}

# 每页 HTML
page_sections = []
for p in pages:
    bl, rt = p["baseline"], p["rtdetr"]
    # OCR 结果列表
    def ocr_list(items):
        if not items:
            return '<div style="color:#999;font-size:13px;padding:8px;">无</div>'
        rows = "".join(
            f'<div class="ocr-item"><span class="bbox">[{int(i["bbox"][0])},{int(i["bbox"][1])},{int(i["bbox"][2])},{int(i["bbox"][3])}]</span>'
            f'<span class="text">{i["text"]}</span></div>'
            for i in items
        )
        return f'<div class="ocr-list">{rows}</div>'

    raw_url = RAW_IMAGES.get(p["page"], "")
    raw_img = f'<div style="margin-bottom:16px;"><img src="{raw_url}" style="max-width:100%;border-radius:8px;border:1px solid #eee;" alt="page_{p["page"]}"></div>' if raw_url else ""

    section = f"""
    <div class="page-section">
      <div class="page-title">第 {p['page']} 页 <span class="badge">{p['image_size'][0]}x{p['image_size'][1]}</span></div>
      {raw_img}
      <table class="compare-table">
        <thead><tr><th>指标</th><th>4引擎并集 (baseline)</th><th>RT-DETR-v2</th><th>变化</th></tr></thead>
        <tbody>
          <tr><td>检测框数</td><td>{bl['n_boxes']}</td><td><b>{rt['n_boxes']}</b></td><td class="delta up">+{rt['n_boxes'] - bl['n_boxes']}</td></tr>
          <tr><td>非空框率</td><td>{bl['non_empty_rate']*100:.1f}%</td><td>{rt['non_empty_rate']*100:.1f}%</td><td>—</td></tr>
          <tr><td>去重后 OCR 字符数</td><td>{bl['dedup_chars']}</td><td><b>{rt['dedup_chars']}</b></td><td class="delta up">+{rt['dedup_chars'] - bl['dedup_chars']} ({(rt['dedup_chars']/max(1,bl['dedup_chars'])-1)*100:.0f}%)</td></tr>
          <tr><td>平均每框字符数</td><td>{bl['avg_chars_per_nonempty']}</td><td>{rt['avg_chars_per_nonempty']}</td><td>—</td></tr>
          <tr><td>检测耗时</td><td>N/A (历史结果)</td><td>{rt['detect_time_sec']}s</td><td>—</td></tr>
          <tr><td>OCR 耗时</td><td>{bl['ocr_time_sec']}s</td><td>{rt['ocr_time_sec']}s</td><td>—</td></tr>
        </tbody>
      </table>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
        <div class="ocr-results"><h4>4引擎并集 OCR 结果（{len(bl['ocr_results'])} 条）</h4>{ocr_list(bl['ocr_results'])}</div>
        <div class="ocr-results"><h4>RT-DETR-v2 OCR 结果（{len(rt['ocr_results'])} 条）</h4>{ocr_list(rt['ocr_results'])}</div>
      </div>
    </div>
    """
    page_sections.append(section)

# 柱状图数据
max_chars = max(max(p["baseline"]["dedup_chars"], p["rtdetr"]["dedup_chars"]) for p in pages)
bar_groups = ""
for p in pages:
    bl_h = int(p["baseline"]["dedup_chars"] / max_chars * 100)
    rt_h = int(p["rtdetr"]["dedup_chars"] / max_chars * 100)
    bar_groups += f"""
    <div class="bar-group">
      <div class="bar baseline" style="height:{bl_h}px" title="baseline: {p['baseline']['dedup_chars']} chars"></div>
      <div class="bar rtdetr" style="height:{rt_h}px" title="rtdetr: {p['rtdetr']['dedup_chars']} chars"></div>
      <div class="bar-label">p{p['page']}</div>
    </div>"""

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>检测方案 A/B 对比报告 — 4引擎并集 vs RT-DETR-v2</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f5f7fa; color:#1a1a2e; line-height:1.6; }}
  .container {{ max-width:1200px; margin:0 auto; padding:24px; }}
  h1 {{ font-size:24px; margin-bottom:8px; }}
  .subtitle {{ color:#666; margin-bottom:24px; font-size:14px; }}
  .summary-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin-bottom:32px; }}
  .summary-card {{ background:#fff; border-radius:12px; padding:20px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
  .summary-card .label {{ font-size:12px; color:#888; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px; }}
  .summary-card .value {{ font-size:28px; font-weight:700; }}
  .summary-card .delta {{ font-size:13px; margin-top:4px; }}
  .delta.up {{ color:#16a34a; }}
  .delta.down {{ color:#dc2626; }}
  .chart-section {{ background:#fff; border-radius:12px; padding:24px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
  .chart-section h3 {{ font-size:16px; margin-bottom:16px; }}
  .bar-chart {{ display:flex; align-items:flex-end; gap:24px; height:160px; padding:0 8px; border-bottom:1px solid #eee; }}
  .bar-group {{ flex:1; display:flex; flex-direction:column; align-items:center; gap:4px; }}
  .bar-group .bar {{ width:32px; border-radius:4px 4px 0 0; }}
  .bar.baseline {{ background:#94a3b8; }}
  .bar.rtdetr {{ background:#4f46e5; }}
  .bar-label {{ font-size:11px; color:#666; margin-top:4px; }}
  .legend {{ display:flex; gap:16px; font-size:12px; color:#666; margin-bottom:12px; }}
  .legend span {{ display:flex; align-items:center; gap:4px; }}
  .legend .dot {{ width:10px; height:10px; border-radius:2px; }}
  .page-section {{ background:#fff; border-radius:12px; padding:24px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
  .page-title {{ font-size:18px; font-weight:600; margin-bottom:16px; display:flex; align-items:center; gap:8px; }}
  .page-title .badge {{ font-size:11px; padding:2px 8px; border-radius:10px; background:#eef2ff; color:#4f46e5; }}
  .compare-table {{ width:100%; border-collapse:collapse; margin-bottom:8px; }}
  .compare-table th,.compare-table td {{ padding:10px 14px; text-align:left; border-bottom:1px solid #eee; font-size:14px; }}
  .compare-table th {{ background:#f8fafc; font-weight:600; color:#555; font-size:12px; text-transform:uppercase; }}
  .compare-table tr:last-child td {{ border-bottom:none; }}
  .ocr-results h4 {{ font-size:14px; margin-bottom:8px; color:#555; }}
  .ocr-list {{ max-height:280px; overflow-y:auto; border:1px solid #eee; border-radius:8px; }}
  .ocr-item {{ padding:8px 12px; border-bottom:1px solid #f0f0f0; font-size:13px; display:flex; gap:12px; }}
  .ocr-item:last-child {{ border-bottom:none; }}
  .ocr-item .bbox {{ color:#888; font-family:monospace; font-size:11px; white-space:nowrap; flex-shrink:0; }}
  .ocr-item .text {{ flex:1; }}
  .footer {{ text-align:center; color:#999; font-size:12px; margin-top:32px; padding:16px; }}
</style>
</head>
<body>
<div class="container">
  <h1>检测方案 A/B 对比报告</h1>
  <p class="subtitle">现有4引擎并集（baseline） vs RT-DETR-v2 ｜ OCR 引擎：Baberu ONNX int4 ｜ 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

  <div class="summary-grid">
    <div class="summary-card">
      <div class="label">总检测框（5页合计）</div>
      <div class="value">{agg.get('rtdetr_total_boxes',0)}</div>
      <div class="delta up">vs baseline {agg.get('baseline_total_boxes',0)}（+{agg.get('rtdetr_total_boxes',0)-agg.get('baseline_total_boxes',0)}）</div>
    </div>
    <div class="summary-card">
      <div class="label">去重后 OCR 字符数（5页合计）</div>
      <div class="value">{agg.get('rtdetr_total_chars',0)}</div>
      <div class="delta up">vs baseline {agg.get('baseline_total_chars',0)}（+{agg.get('char_improvement_pct',0)}%）</div>
    </div>
    <div class="summary-card">
      <div class="label">平均非空框率</div>
      <div class="value">{agg.get('rtdetr_avg_nonempty',0)*100:.1f}%</div>
      <div class="delta">baseline: {agg.get('baseline_avg_nonempty',0)*100:.1f}%</div>
    </div>
    <div class="summary-card">
      <div class="label">RT-DETR-v2 平均检测耗时</div>
      <div class="value">{agg.get('rtdetr_avg_detect_time',0)}s</div>
      <div class="delta">CPU-only (i5-1135G7)</div>
    </div>
  </div>

  <div class="chart-section">
    <h3>各页 OCR 字符数对比</h3>
    <div class="legend">
      <span><span class="dot" style="background:#94a3b8"></span>4引擎并集</span>
      <span><span class="dot" style="background:#4f46e5"></span>RT-DETR-v2</span>
    </div>
    <div class="bar-chart">{bar_groups}</div>
  </div>

  {''.join(page_sections)}

  <div class="footer">
    AMTA detect A/B test · RT-DETR-v2 (ogkalu/comic-text-and-bubble-detector) · Baberu OCR (genshiai-daichi/baberu-ocr)
  </div>
</div>
</body>
</html>"""

OUT.write_text(html, encoding="utf-8")
print(f"[report] -> {OUT}")
print(f"[report] {len(pages)} pages, {agg.get('rtdetr_total_chars',0)} vs {agg.get('baseline_total_chars',0)} chars")
