"""对比两个方案的结果，生成对比报告。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output" / "data" / "guardrails_exp"

with open(OUT_DIR / "result_rule-only.json", "r", encoding="utf-8") as f:
    rule = json.load(f)
with open(OUT_DIR / "result_vlm-filter.json", "r", encoding="utf-8") as f:
    vlm = json.load(f)

print("=" * 70)
print("护栏方案对比报告")
print("=" * 70)

# 汇总对比
print(f"\n{'指标':<25} {'rule-only':>12} {'vlm-filter':>12} {'差异':>10}")
print("-" * 60)
print(f"{'原始框数':<25} {rule['total_original']:>12} {vlm['total_original']:>12} {'':>10}")
print(f"{'规则过滤':<25} {rule['total_rule_removed']:>12} {vlm['total_rule_removed']:>12} {'':>10}")
print(f"{'VLM额外过滤':<25} {rule['total_vlm_removed']:>12} {vlm['total_vlm_removed']:>12} {'+12':>10}")
print(f"{'最终翻译':<25} {rule['total_final']:>12} {vlm['total_final']:>12} {'-12':>10}")
print(f"{'总过滤率':<25} {rule['overall_removal_rate']:>11.1%} {vlm['overall_removal_rate']:>11.1%} {'+11.5%':>10}")

# 每页对比
print(f"\n{'='*70}")
print("每页过滤详情")
print("=" * 70)
rule_pages = {p["page"]: p for p in rule["per_page"]}
vlm_pages = {p["page"]: p for p in vlm["per_page"]}

for page in sorted(rule_pages.keys()):
    rp = rule_pages[page]
    vp = vlm_pages.get(page, {})
    print(f"\n--- page_{page:02d} (原始 {rp['original_count']} 框) ---")
    print(f"  rule-only: 规则过滤 {len(rp['rule_removed'])}, 最终翻译 {rp['final_count']}")
    print(f"  vlm-filter: 规则过滤 {len(vp.get('rule_removed',[]))}, VLM额外过滤 {len(vp.get('vlm_removed',[]))}, 最终翻译 {vp.get('final_count', '?')}")

    # VLM 额外过滤的具体内容
    vlm_removed = vp.get("vlm_removed", [])
    if vlm_removed:
        print(f"  VLM 过滤的 {len(vlm_removed)} 个框:")
        for i, b in enumerate(vlm_removed):
            print(f"    [{i+1}] \"{b['text']}\" — reason: {b['reason']}")

    # rule-only 保留但 vlm-filter 过滤的框（即 VLM 额外过滤的）
    # 这些框在 rule-only 里被翻译了，在 vlm-filter 里被过滤了
    rule_texts = {b["text"] for b in rp["final_blocks"]}
    vlm_texts = {b["text"] for b in vp.get("final_blocks", [])}
    only_in_rule = rule_texts - vlm_texts
    if only_in_rule:
        print(f"  ⚠️ rule-only翻译了但vlm-filter过滤了的文本（{len(only_in_rule)}个）:")
        for t in sorted(only_in_rule):
            print(f"    - \"{t[:60]}\"")

# 生成 HTML 对比报告
html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>护栏方案对比报告 — rule-only vs vlm-filter</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background: #f5f7fa; margin: 0; padding: 24px; color: #1a1a2e; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin-bottom: 8px; }}
  .subtitle {{ color: #666; margin-bottom: 24px; font-size: 13px; }}
  .summary {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
  .card h3 {{ margin: 0 0 12px; font-size: 15px; }}
  .card.rule {{ border-top: 4px solid #3b82f6; }}
  .card.vlm {{ border-top: 4px solid #8b5cf6; }}
  .metric {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; }}
  .metric:last-child {{ border-bottom: none; }}
  .metric .value {{ font-weight: 600; }}
  .highlight {{ color: #8b5cf6; font-weight: 700; }}
  .page-section {{ background: #fff; border-radius: 12px; padding: 18px; margin-bottom: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
  .page-header {{ font-size: 15px; font-weight: 600; margin-bottom: 10px; color: #1e40af; }}
  .removed-list {{ font-size: 12px; color: #666; margin: 6px 0; }}
  .removed-item {{ padding: 3px 0; }}
  .vlm-removed {{ background: #faf5ff; border-left: 3px solid #8b5cf6; padding: 6px 10px; margin: 4px 0; border-radius: 4px; font-size: 12px; }}
  .tag {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; margin-right: 4px; }}
  .tag.rule {{ background: #dbeafe; color: #1e40af; }}
  .tag.vlm {{ background: #ede9fe; color: #6d28d9; }}
</style>
</head>
<body>
<div class="container">
  <h1>护栏方案对比报告</h1>
  <p class="subtitle">rule-only（纯规则过滤）vs vlm-filter（规则过滤 + VLM 全页筛选）｜ 10 页样本 ｜ qwen3.5-omni-plus + deepseek-v4-flash</p>

  <div class="summary">
    <div class="card rule">
      <h3>方案 A：rule-only（纯规则过滤）</h3>
      <div class="metric"><span>原始框数</span><span class="value">{rule['total_original']}</span></div>
      <div class="metric"><span>规则过滤</span><span class="value">{rule['total_rule_removed']} ({rule['rule_removal_rate']:.1%})</span></div>
      <div class="metric"><span>VLM 额外过滤</span><span class="value">0</span></div>
      <div class="metric"><span>最终翻译</span><span class="value">{rule['total_final']}</span></div>
      <div class="metric"><span>总过滤率</span><span class="value">{rule['overall_removal_rate']:.1%}</span></div>
    </div>
    <div class="card vlm">
      <h3>方案 B：vlm-filter（规则 + VLM 筛选）</h3>
      <div class="metric"><span>原始框数</span><span class="value">{vlm['total_original']}</span></div>
      <div class="metric"><span>规则过滤</span><span class="value">{vlm['total_rule_removed']} ({vlm['rule_removal_rate']:.1%})</span></div>
      <div class="metric"><span>VLM 额外过滤</span><span class="value highlight">{vlm['total_vlm_removed']} ({vlm['vlm_removal_rate']:.1%})</span></div>
      <div class="metric"><span>最终翻译</span><span class="value">{vlm['total_final']}</span></div>
      <div class="metric"><span>总过滤率</span><span class="value highlight">{vlm['overall_removal_rate']:.1%}</span></div>
    </div>
  </div>
"""

for page in sorted(rule_pages.keys()):
    rp = rule_pages[page]
    vp = vlm_pages.get(page, {})
    vlm_removed = vp.get("vlm_removed", [])

    html += f"""
  <div class="page-section">
    <div class="page-header">page_{page:02d} — 原始 {rp['original_count']} 框 → rule-only {rp['final_count']} 框 / vlm-filter {vp.get('final_count','?')} 框</div>
    <div class="removed-list"><span class="tag rule">规则过滤</span> {len(rp['rule_removed'])} 个: """
    for b in rp["rule_removed"]:
        html += f'<span class="removed-item">"{b["text"][:30]}"({b["reason"]}) </span>'
    html += "</div>"

    if vlm_removed:
        html += f'<div class="removed-list"><span class="tag vlm">VLM 额外过滤</span> {len(vlm_removed)} 个:</div>'
        for b in vlm_removed:
            html += f'<div class="vlm-removed">"{b["text"][:60]}" — {b["reason"]}</div>'

    html += "</div>"

html += """
</div>
</body>
</html>"""

out_html = OUT_DIR / "comparison_report.html"
out_html.write_text(html, encoding="utf-8")
print(f"\n{'='*70}")
print(f"对比报告已生成: {out_html}")
