"""生成三版本对比报告：v1(二态) vs v2(三态) vs v3(三态+conf0.2)。

包含原图、OCR内容、翻译内容、过滤详情、三版本对比数据。
"""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")

# 三个版本的结果
V1_PATH = ROOT / "research" / "guardrails_exp_v1" / "03_translation_vlm-filter.json"
V2_PATH = ROOT / "research" / "guardrails_exp_v2" / "result_v2_tri-state.json"
V3_PATH = ROOT / "output" / "data" / "guardrails_exp_v3" / "result_v3_conf02_tri-state.json"
OUT_PATH = ROOT / "output" / "data" / "guardrails_comparison" / "full_comparison_v1v2v3.html"
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with open(V1_PATH, "r", encoding="utf-8") as f:
    v1 = json.load(f)
with open(V2_PATH, "r", encoding="utf-8") as f:
    v2 = json.load(f)
with open(V3_PATH, "r", encoding="utf-8") as f:
    v3 = json.load(f)

v1_pages = {p["page"]: p for p in v1["per_page"]}
v2_pages = {p["page"]: p for p in v2["per_page"]}
v3_pages = {p["page"]: p for p in v3["per_page"]}
sample_pages = sorted(v2_pages.keys())


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
        text = b.get("text", "")[:80]
        trans = b.get("translation", "")[:80]
        orig = b.get("original_text", "")
        vlm_state = b.get("vlm_state", "")
        state_tag = ""
        if vlm_state == "fixed":
            state_tag = '<span class="tag fix">FIX</span>'
        items += f"""
        <div class="block-item">
          <div class="block-header"><span class="block-idx">#{i+1}</span> {state_tag}</div>
          <div class="block-text"><span class="label">OCR:</span> {text}</div>
          {f'<div class="block-orig"><span class="label">原OCR:</span> {orig[:60]}</div>' if orig else ''}
          <div class="block-trans"><span class="label">翻译:</span> {trans}</div>
        </div>"""
    return f'<div class="col"><h4 style="color:{color}">{title} ({len(blocks)})</h4>{items}</div>'


def render_removed(removed: list, title: str, color: str) -> str:
    if not removed:
        return ""
    items = ""
    for b in removed:
        text = b.get("text", "")[:60]
        reason = b.get("reason", b.get("filter_reason", ""))
        items += f'<div class="removed-item"><span class="removed-text">"{text}"</span> <span class="removed-reason">— {reason}</span></div>'
    return f'<div class="removed-section" style="border-left:3px solid {color};"><h5 style="color:{color};margin:0 0 6px;">{title} ({len(removed)})</h5>{items}</div>'


def render_fixed(fixed: list, title: str, color: str) -> str:
    if not fixed:
        return ""
    items = ""
    for b in fixed:
        orig = b.get("original", b.get("original_text", ""))[:50]
        corr = b.get("corrected", b.get("text", ""))[:50]
        reason = b.get("reason", "")
        items += f'<div class="fixed-item"><span class="fixed-orig">"{orig}"</span> → <span class="fixed-corr">"{corr}"</span> <span class="fixed-reason">— {reason}</span></div>'
    return f'<div class="fixed-section" style="border-left:3px solid {color};"><h5 style="color:{color};margin:0 0 6px;">{title} ({len(fixed)})</h5>{items}</div>'


# 构建 HTML
html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>三版本对比报告 — v1(二态) vs v2(三态) vs v3(三态+conf0.2)</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background: #f0f2f5; color: #1a1a2e; line-height:1.6; }}
  .container {{ max-width: 1500px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .subtitle {{ color: #666; margin-bottom: 20px; font-size: 13px; }}
  .summary-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-bottom:24px; }}
  .sum-card {{ background:#fff; border-radius:10px; padding:14px; box-shadow:0 1px 4px rgba(0,0,0,0.06); }}
  .sum-card .label {{ font-size:11px; color:#888; text-transform:uppercase; }}
  .sum-card .value {{ font-size:20px; font-weight:700; margin-top:2px; }}
  .sum-card.v1 .value {{ color:#2563eb; }}
  .sum-card.v2 .value {{ color:#7c3aed; }}
  .sum-card.v3 .value {{ color:#059669; }}
  .sum-card.best .value {{ color:#dc2626; }}
  .page-section {{ background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,0.06); }}
  .page-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; padding-bottom:10px; border-bottom:2px solid #f0f0f0; }}
  .page-title {{ font-size:17px; font-weight:700; color:#1e40af; }}
  .page-stats {{ font-size:12px; color:#666; }}
  .page-body {{ display:grid; grid-template-columns: 300px 1fr; gap:20px; }}
  .page-image {{ text-align:center; }}
  .page-image img {{ max-width:100%; max-height:450px; border-radius:6px; border:1px solid #e5e7eb; }}
  .page-image .img-label {{ font-size:11px; color:#999; margin-top:6px; }}
  .versions {{ display:flex; flex-direction:column; gap:16px; }}
  .version-block {{ border:1px solid #e5e7eb; border-radius:8px; padding:12px; }}
  .version-title {{ font-size:14px; font-weight:700; margin-bottom:8px; padding-bottom:6px; border-bottom:1px solid #f0f0f0; }}
  .version-title.v1 {{ color:#2563eb; }}
  .version-title.v2 {{ color:#7c3aed; }}
  .version-title.v3 {{ color:#059669; }}
  .blocks-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  .col h4 {{ font-size:12px; margin-bottom:6px; padding-bottom:4px; border-bottom:1px solid #eee; }}
  .block-item {{ background:#fafafa; border-radius:6px; padding:6px 8px; margin-bottom:4px; border:1px solid #f0f0f0; }}
  .block-header {{ font-size:10px; color:#999; margin-bottom:2px; }}
  .block-text, .block-trans, .block-orig {{ font-size:11px; margin:1px 0; }}
  .block-text .label, .block-trans .label, .block-orig .label {{ color:#888; font-weight:600; margin-right:4px; }}
  .block-trans {{ color:#047857; }}
  .block-orig {{ color:#d97706; }}
  .tag {{ display:inline-block; padding:1px 5px; border-radius:3px; font-size:9px; font-weight:700; }}
  .tag.fix {{ background:#dcfce7; color:#166534; }}
  .removed-section, .fixed-section {{ padding:6px 10px; margin:6px 0; background:#fafafa; border-radius:4px; }}
  .removed-item, .fixed-item {{ font-size:11px; padding:2px 0; color:#666; }}
  .removed-text, .fixed-orig {{ font-family:monospace; color:#374151; }}
  .fixed-corr {{ color:#047857; font-weight:600; }}
  .removed-reason, .fixed-reason {{ color:#9ca3af; font-style:italic; }}
  .footer {{ text-align:center; color:#999; font-size:11px; margin-top:32px; padding:16px; }}
</style>
</head>
<body>
<div class="container">
<h1>三版本对比报告</h1>
<p class="subtitle">v1(二态VLM, conf=0.3) vs v2(三态VLM, conf=0.3) vs v3(三态VLM, conf=0.2) ｜ 10页样本 ｜ qwen3.5-omni-plus + deepseek-v4-flash</p>

<div class="summary-grid">
  <div class="sum-card v1"><div class="label">v1 最终翻译</div><div class="value">{v1['total_final']}</div></div>
  <div class="sum-card v2"><div class="label">v2 最终翻译</div><div class="value">{v2['total_final']}</div></div>
  <div class="sum-card v3"><div class="label">v3 最终翻译</div><div class="value">{v3['total_final']}</div></div>
  <div class="sum-card v1"><div class="label">v1 总过滤率</div><div class="value">{v1['overall_removal_rate']:.1%}</div></div>
  <div class="sum-card v2"><div class="label">v2 总过滤率</div><div class="value">{v2['overall_removal_rate']:.1%}</div></div>
  <div class="sum-card v3"><div class="label">v3 总过滤率</div><div class="value">{v3['overall_removal_rate']:.1%}</div></div>
  <div class="sum-card v2"><div class="label">v2 VLM修正</div><div class="value">{v2['total_vlm_fix']}</div></div>
  <div class="sum-card v3"><div class="label">v3 VLM修正</div><div class="value">{v3.get('total_vlm_fix', '?')}</div></div>
  <div class="sum-card best"><div class="label">v3 检测框数</div><div class="value">{v3['total_original']}</div></div>
</div>
"""

# 每页对比
for page in sample_pages:
    p1 = v1_pages.get(page, {})
    p2 = v2_pages.get(page, {})
    p3 = v3_pages.get(page, {})
    img_path = RAW_DIR / f"{page}.jpg"
    img_b64 = img_to_base64(img_path)

    html += f"""
<div class="page-section">
  <div class="page-header">
    <div class="page-title">page_{page:02d}</div>
    <div class="page-stats">
      v1: {p1.get('final_count','?')}框 ｜
      v2: {p2.get('final_count','?')}框 (fix={len(p2.get('vlm_fixed',[]))}) ｜
      v3: {p3.get('final_count','?')}框 (fix={len(p3.get('vlm_fixed',[]))})
    </div>
  </div>
  <div class="page-body">
    <div class="page-image">
      <img src="{img_b64}" alt="page_{page}" />
      <div class="img-label">原图 page_{page}.jpg</div>
    </div>
    <div class="versions">
"""

    # v1
    html += f"""
      <div class="version-block">
        <div class="version-title v1">v1 二态VLM (conf=0.3) — 最终翻译 {p1.get('final_count','?')} 框</div>
        <div class="blocks-grid">
          {render_blocks(p1.get('final_blocks', []), "最终翻译", "#2563eb")}
        </div>
        {render_removed(p1.get('vlm_removed', []), "VLM丢弃", "#dc2626")}
      </div>
"""

    # v2
    html += f"""
      <div class="version-block">
        <div class="version-title v2">v2 三态VLM (conf=0.3) — 最终翻译 {p2.get('final_count','?')} 框 (keep={p2.get('vlm_keep','?')}, fix={len(p2.get('vlm_fixed',[]))}, drop={len(p2.get('vlm_dropped',[]))})</div>
        <div class="blocks-grid">
          {render_blocks(p2.get('final_blocks', []), "最终翻译", "#7c3aed")}
        </div>
        {render_fixed(p2.get('vlm_fixed', []), "VLM修正 (OCR错误→正确文本)", "#059669")}
        {render_removed(p2.get('vlm_dropped', []), "VLM丢弃", "#dc2626")}
      </div>
"""

    # v3
    html += f"""
      <div class="version-block">
        <div class="version-title v3">v3 三态VLM (conf=0.2) — 最终翻译 {p3.get('final_count','?')} 框 (原始{p3.get('original_count','?')}框, keep={p3.get('vlm_keep','?')}, fix={len(p3.get('vlm_fixed',[]))}, drop={len(p3.get('vlm_dropped',[]))})</div>
        <div class="blocks-grid">
          {render_blocks(p3.get('final_blocks', []), "最终翻译", "#059669")}
        </div>
        {render_fixed(p3.get('vlm_fixed', []), "VLM修正 (OCR错误→正确文本)", "#059669")}
        {render_removed(p3.get('vlm_dropped', []), "VLM丢弃", "#dc2626")}
      </div>
"""

    html += """
    </div>
  </div>
</div>
"""

html += """
<div class="footer">
  AMTA Guardrails Experiment · v1(二态) vs v2(三态) vs v3(三态+conf0.2) · 10-page sample · qwen3.5-omni-plus + deepseek-v4-flash
</div>
</div>
</body>
</html>"""

OUT_PATH.write_text(html, encoding="utf-8")
print(f"[comparison] -> {OUT_PATH}")
print(f"[comparison] size: {OUT_PATH.stat().st_size / 1024 / 1024:.1f} MB")
