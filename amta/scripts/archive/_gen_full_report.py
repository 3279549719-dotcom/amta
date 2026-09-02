"""生成完整的护栏方案对比 HTML 报告，包含原图、OCR、翻译、过滤详情。"""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT_DIR = ROOT / "output" / "data" / "guardrails_exp"

with open(OUT_DIR / "result_rule-only.json", "r", encoding="utf-8") as f:
    rule = json.load(f)
with open(OUT_DIR / "result_vlm-filter.json", "r", encoding="utf-8") as f:
    vlm = json.load(f)

rule_pages = {p["page"]: p for p in rule["per_page"]}
vlm_pages = {p["page"]: p for p in vlm["per_page"]}
sample_pages = sorted(rule_pages.keys())


def img_to_base64(path: Path) -> str:
    if not path.exists():
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


def render_blocks(blocks: list, title: str, color: str) -> str:
    if not blocks:
        return f'<div class="col"><h4 style="color:{color}">{title} (0)</h4><p style="color:#999;font-size:12px;">无</p></div>'
    items = ""
    for i, b in enumerate(blocks):
        text = b.get("text", "")[:100]
        trans = b.get("translation", "")[:100]
        bbox = b.get("bbox", [])
        bbox_str = f"[{int(bbox[0])},{int(bbox[1])},{int(bbox[2])},{int(bbox[3])}]" if len(bbox) == 4 else ""
        items += f"""
        <div class="block-item">
          <div class="block-header"><span class="block-idx">#{i+1}</span> <span class="block-bbox">{bbox_str}</span></div>
          <div class="block-text"><span class="label">OCR:</span> {text}</div>
          <div class="block-trans"><span class="label">翻译:</span> {trans}</div>
        </div>"""
    return f'<div class="col"><h4 style="color:{color}">{title} ({len(blocks)})</h4>{items}</div>'


def render_removed(removed: list, title: str, color: str) -> str:
    if not removed:
        return ""
    items = ""
    for b in removed:
        text = b.get("text", "")[:80]
        reason = b.get("reason", "")
        items += f'<div class="removed-item"><span class="removed-text">"{text}"</span> <span class="removed-reason">— {reason}</span></div>'
    return f'<div class="removed-section" style="border-left:3px solid {color};"><h5 style="color:{color};margin:0 0 6px;">{title} ({len(removed)})</h5>{items}</div>'


# 构建 HTML
html_parts = []
html_parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>护栏方案完整对比报告 — rule-only vs vlm-filter</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background: #f0f2f5; color: #1a1a2e; line-height:1.6; }
  .container { max-width: 1400px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 24px; margin-bottom: 4px; }
  .subtitle { color: #666; margin-bottom: 20px; font-size: 13px; }
  .summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-bottom:24px; }
  .sum-card { background:#fff; border-radius:10px; padding:14px; box-shadow:0 1px 4px rgba(0,0,0,0.06); }
  .sum-card .label { font-size:11px; color:#888; text-transform:uppercase; }
  .sum-card .value { font-size:22px; font-weight:700; margin-top:2px; }
  .sum-card.rule .value { color:#2563eb; }
  .sum-card.vlm .value { color:#7c3aed; }
  .sum-card.diff .value { color:#dc2626; }
  .page-section { background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,0.06); }
  .page-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; padding-bottom:10px; border-bottom:2px solid #f0f0f0; }
  .page-title { font-size:17px; font-weight:700; color:#1e40af; }
  .page-stats { font-size:12px; color:#666; }
  .page-body { display:grid; grid-template-columns: 340px 1fr; gap:20px; }
  .page-image { text-align:center; }
  .page-image img { max-width:100%; max-height:500px; border-radius:6px; border:1px solid #e5e7eb; }
  .page-image .img-label { font-size:11px; color:#999; margin-top:6px; }
  .blocks-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  .col h4 { font-size:13px; margin-bottom:8px; padding-bottom:4px; border-bottom:1px solid #eee; }
  .block-item { background:#fafafa; border-radius:6px; padding:8px 10px; margin-bottom:6px; border:1px solid #f0f0f0; }
  .block-header { font-size:10px; color:#999; margin-bottom:3px; }
  .block-idx { font-weight:700; color:#666; }
  .block-bbox { font-family:monospace; margin-left:6px; }
  .block-text, .block-trans { font-size:12px; margin:2px 0; }
  .block-text .label, .block-trans .label { color:#888; font-weight:600; margin-right:4px; }
  .block-trans { color:#047857; }
  .removed-section { padding:6px 10px; margin:8px 0; background:#fafafa; border-radius:4px; }
  .removed-item { font-size:11px; padding:2px 0; color:#666; }
  .removed-text { font-family:monospace; color:#374151; }
  .removed-reason { color:#9ca3af; font-style:italic; }
  .diff-section { margin-top:12px; padding:10px; background:#fef3c7; border-radius:6px; border:1px solid #fde68a; }
  .diff-section h5 { color:#92400e; margin-bottom:6px; font-size:12px; }
  .diff-item { font-size:11px; padding:2px 0; color:#78350f; }
  .footer { text-align:center; color:#999; font-size:11px; margin-top:32px; padding:16px; }
</style>
</head>
<body>
<div class="container">
<h1>护栏方案完整对比报告</h1>
<p class="subtitle">rule-only（纯规则过滤）vs vlm-filter（规则过滤 + VLM 全页筛选）｜ 10 页样本 ｜ qwen3.5-omni-plus + deepseek-v4-flash ｜ 2026-09-01</p>
""")

# 汇总卡片
html_parts.append(f"""
<div class="summary-grid">
  <div class="sum-card rule"><div class="label">rule-only 最终翻译</div><div class="value">{rule['total_final']}</div></div>
  <div class="sum-card vlm"><div class="label">vlm-filter 最终翻译</div><div class="value">{vlm['total_final']}</div></div>
  <div class="sum-card diff"><div class="label">VLM 额外过滤</div><div class="value">{vlm['total_vlm_removed']}</div></div>
  <div class="sum-card rule"><div class="label">rule-only 过滤率</div><div class="value">{rule['overall_removal_rate']:.1%}</div></div>
  <div class="sum-card vlm"><div class="label">vlm-filter 过滤率</div><div class="value">{vlm['overall_removal_rate']:.1%}</div></div>
  <div class="sum-card"><div class="label">原始框数</div><div class="value">{rule['total_original']}</div></div>
  <div class="sum-card"><div class="label">规则过滤</div><div class="value">{rule['total_rule_removed']}</div></div>
  <div class="sum-card diff"><div class="label">过滤率提升</div><div class="value">+{(vlm['overall_removal_rate']-rule['overall_removal_rate'])*100:.1f}%</div></div>
</div>
""")

# 每页详情
for page in sample_pages:
    rp = rule_pages[page]
    vp = vlm_pages.get(page, {})
    img_path = RAW_DIR / f"{page}.jpg"
    img_b64 = img_to_base64(img_path)

    # 找出两个方案的差异（rule-only 翻译了但 vlm-filter 过滤了的）
    rule_texts = {b["text"] for b in rp["final_blocks"]}
    vlm_texts = {b["text"] for b in vp.get("final_blocks", [])}
    only_in_rule = sorted(rule_texts - vlm_texts)
    diff_html = ""
    if only_in_rule:
        diff_items = "".join(f'<div class="diff-item">"{t[:60]}"</div>' for t in only_in_rule)
        diff_html = f'<div class="diff-section"><h5>⚠️ rule-only翻译了但vlm-filter过滤了（{len(only_in_rule)}个）</h5>{diff_items}</div>'

    html_parts.append(f"""
<div class="page-section">
  <div class="page-header">
    <div class="page-title">page_{page:02d}</div>
    <div class="page-stats">
      原始 {rp['original_count']} 框 ｜
      rule-only: {rp['final_count']} 框 ｜
      vlm-filter: {vp.get('final_count','?')} 框
      (规则过滤 {len(vp.get('rule_removed',[]))} + VLM过滤 {len(vp.get('vlm_removed',[]))})
    </div>
  </div>
  <div class="page-body">
    <div class="page-image">
      <img src="{img_b64}" alt="page_{page}" />
      <div class="img-label">原图 page_{page}.jpg ({rp.get('image_size',['?','?'])[0]}x{rp.get('image_size',['?','?'])[1]})</div>
    </div>
    <div>
      <div class="blocks-grid">
        {render_blocks(rp["final_blocks"], "rule-only 最终翻译", "#2563eb")}
        {render_blocks(vp.get("final_blocks", []), "vlm-filter 最终翻译", "#7c3aed")}
      </div>
      {render_removed(rp.get("rule_removed", []), "规则过滤（两方案相同）", "#f59e0b")}
      {render_removed(vp.get("vlm_removed", []), "VLM 额外过滤（仅 vlm-filter）", "#7c3aed")}
      {diff_html}
    </div>
  </div>
</div>
""")

html_parts.append("""
<div class="footer">
  AMTA Guardrails Experiment · rule-only vs vlm-filter · 10-page sample · qwen3.5-omni-plus + deepseek-v4-flash
</div>
</div>
</body>
</html>""")

out_path = OUT_DIR / "full_comparison_report.html"
out_path.write_text("".join(html_parts), encoding="utf-8")
print(f"[full-report] -> {out_path}")
print(f"[full-report] size: {out_path.stat().st_size / 1024 / 1024:.1f} MB")
