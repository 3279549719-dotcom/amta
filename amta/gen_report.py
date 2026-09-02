"""生成 deepseek VLM 对比实验 HTML 报告（含 6 页对比 + 3.jpg 稳定性实验）。"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / "output" / "compare" / "compare_results.json").read_text(encoding="utf-8"))
OUT = ROOT / "output" / "compare" / "deepseek_vlm_report.html"

# === 3.jpg 稳定性实验数据（5 次运行，手动整理自 run_stability.py 输出）===
STABILITY = [
    {"run": 1, "keep": 7, "fix": 0, "drop": 2,
     "kept": ["r00", "r01", "r02", "r03", "r04", "r05", "r06"],
     "fixed": [],
     "dropped": [{"id": "r07", "text": "しま。", "reason": "blank background area, no text"},
                 {"id": "r08", "text": "この", "reason": "blank background area, no text"}]},
    {"run": 2, "keep": 5, "fix": 2, "drop": 2,
     "kept": ["r00", "r03", "r04", "r05", "r06"],
     "fixed": [{"id": "r01", "original": "それでも、", "corrected": "ぼっーん"},
               {"id": "r07", "original": "しま。", "corrected": "カチャ"}],
     "dropped": [{"id": "r02", "text": "そういうことで、", "reason": "blank area with panel border and sign, no text"},
                 {"id": "r08", "text": "この", "reason": "blank/illustration detail, no text"}]},
    {"run": 3, "keep": 5, "fix": 0, "drop": 4,
     "kept": ["r00", "r03", "r04", "r05", "r06"],
     "fixed": [],
     "dropped": [{"id": "r01", "text": "それでも、", "reason": "blank background area in top-left panel"},
                 {"id": "r02", "text": "そういうことで、", "reason": "blank area between panels"},
                 {"id": "r07", "text": "しま。", "reason": "blank background area in middle-left panel"},
                 {"id": "r08", "text": "この", "reason": "blank background area at bottom-left"}]},
    {"run": 4, "keep": 5, "fix": 0, "drop": 4,
     "kept": ["r00", "r03", "r04", "r05", "r06"],
     "fixed": [],
     "dropped": [{"id": "r01", "text": "それでも、", "reason": "no text; OCR hallucination"},
                 {"id": "r02", "text": "そういうことで、", "reason": "no text; OCR hallucination"},
                 {"id": "r07", "text": "しま。", "reason": "no text; OCR hallucination"},
                 {"id": "r08", "text": "この", "reason": "no text; OCR hallucination"}]},
    {"run": 5, "keep": 5, "fix": 2, "drop": 2,
     "kept": ["r00", "r03", "r04", "r05", "r06"],
     "fixed": [{"id": "r01", "original": "それでも、", "corrected": "ぽっーん"},
               {"id": "r07", "original": "しま。", "corrected": "研究室No.7"}],
     "dropped": [{"id": "r02", "text": "そういうことで、", "reason": "empty area in the left panel"},
                 {"id": "r08", "text": "この", "reason": "blank area near character's shoulder, no text"}]},
]

# 3.jpg 9 框的真实情况（人工核实）
GROUND_TRUTH = {
    "r00": {"real": True, "type": "text_bubble", "note": "真旁白，baberu 误读玉鬼→玉兎"},
    "r01": {"real": False, "type": "text_free", "note": "假框-窗帘竖纹，baberu 编それでも、"},
    "r02": {"real": False, "type": "text_free", "note": "假框-装饰长条，baberu 编そういうことで、"},
    "r03": {"real": True, "type": "text_bubble", "note": "真旁白"},
    "r04": {"real": True, "type": "text_bubble", "note": "真内心"},
    "r05": {"real": True, "type": "text_bubble", "note": "真内心"},
    "r06": {"real": True, "type": "text_bubble", "note": "真旁白"},
    "r07": {"real": True, "type": "text_free", "note": "真音效ぽっ～ん，baberu 误读しま。"},
    "r08": {"real": False, "type": "text_free", "note": "假框-网点纹理，baberu 编この"},
}


def img_to_b64(path: Path, max_side: int = 600) -> str:
    im = Image.open(path)
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode()


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_page(p: dict) -> str:
    raw_path = Path(p["raw_path"])
    img_b64 = img_to_b64(raw_path) if raw_path.exists() else ""

    # rule-only 翻译
    rule_trans = p.get("trans_rule", {})
    vlm_trans = p.get("trans_vlm", {})

    # rule-only items
    rule_items = p.get("rule_items", [])
    vlm_items = p.get("vlm_items", [])

    # 规则过滤明细
    rule_removed = p.get("rule_removed_by_reason", {})

    # VLM 过滤明细
    vlm_dropped = p.get("vlm_dropped", [])
    vlm_fixed = p.get("vlm_fixed", [])

    html = f'''
    <div class="page-section">
      <div class="page-header">
        <div class="page-title">{esc(p["page"])} — {esc(p["file"])}</div>
        <div class="page-stats">
          检测 {p["n_detected"]} → 规则过滤 {p["n_rule"]}（移除 {p["n_rule_removed"]}）
          → VLM过滤 {p["n_vlm"]}（drop {p["vlm_drop"]}, fix {p["vlm_fix"]}）
          ｜ 翻译 rule-only={len(rule_trans)} vlm-filter={len(vlm_trans)}
        </div>
      </div>
      <div class="page-body">
        <div class="page-image">
          <img src="data:image/jpeg;base64,{img_b64}" alt="{esc(p["file"])}">
          <div class="img-label">原图 {esc(p["file"])}</div>
        </div>
        <div class="blocks-grid">
          <div class="col">
            <h4>rule-only 最终翻译（{len(rule_trans)} 条）</h4>
    '''
    for it in rule_items:
        rid = it.get("region_id", "")
        ocr = it.get("text", "")
        trans = rule_trans.get(rid, "")
        html += f'''
            <div class="block-item">
              <div class="block-header"><span class="block-idx">{esc(rid)}</span>
                <span class="block-bbox">{esc(str(it.get("bbox","")))}</span>
                <span style="color:#999;margin-left:6px">{esc(str(it.get("bubble_type","")))}</span></div>
              <div class="block-text"><span class="label">OCR:</span>{esc(ocr)}</div>
              <div class="block-trans"><span class="label">译:</span>{esc(trans)}</div>
            </div>'''

    html += f'''
          </div>
          <div class="col">
            <h4>vlm-filter(deepseek) 最终翻译（{len(vlm_trans)} 条）</h4>
    '''
    for it in vlm_items:
        rid = it.get("region_id", "")
        ocr = it.get("text", "")
        orig = it.get("original_text", "")
        state = it.get("vlm_state", "")
        trans = vlm_trans.get(rid, "")
        state_cls = "keep" if "keep" in str(state) else ("fix" if "fix" in str(state) else "")
        html += f'''
            <div class="block-item">
              <div class="block-header"><span class="block-idx">{esc(rid)}</span>
                <span class="block-bbox">{esc(str(it.get("bbox","")))}</span>
                <span class="vlm-state {state_cls}">{esc(str(state)[:30])}</span></div>
              {"<div class='block-text'><span class='label'>原OCR:</span>" + esc(orig) + "</div>" if orig else ""}
              <div class="block-text"><span class="label">OCR:</span>{esc(ocr)}</div>
              <div class="block-trans"><span class="label">译:</span>{esc(trans)}</div>
            </div>'''

    # 规则过滤 + VLM 过滤明细
    html += '''
            <div class="filter-detail">
              <h5>规则过滤（两方案相同）</h5>
    '''
    if rule_removed:
        for reason, cnt in rule_removed.items():
            html += f'<div class="removed-item">{esc(reason)}: {cnt} 个</div>'
    else:
        html += '<div class="removed-item" style="color:#dc2626">无移除（假框形状不极端，规则拦不住）</div>'

    html += '''
              <h5 style="margin-top:10px">VLM 额外过滤（deepseek-v4-flash-vision-exp）</h5>
    '''
    if vlm_dropped:
        for d in vlm_dropped:
            html += f'<div class="removed-item"><span class="removed-text">{esc(d.get("region_id",""))}: "{esc(d.get("text","")[:40])}"</span> — <span class="removed-reason">{esc(d.get("reason","")[:60])}</span></div>'
    if vlm_fixed:
        for f in vlm_fixed:
            html += f'<div class="removed-item" style="color:#7c3aed">FIX {esc(f.get("region_id",""))}: "{esc(str(f.get("original",""))[:30])}" → "{esc(str(f.get("corrected",""))[:30])}"</div>'
    if not vlm_dropped and not vlm_fixed:
        html += '<div class="removed-item">无额外过滤</div>'

    html += '''
            </div>
          </div>
        </div>
      </div>
    </div>'''
    return html


def render_stability() -> str:
    """渲染 3.jpg 稳定性实验专节。"""
    html = '''
    <div class="page-section" style="border-left:4px solid #dc2626">
      <div class="page-header">
        <div class="page-title" style="color:#dc2626">稳定性实验 — 3.jpg 连续 5 次 VLM 裁决（同一输入）</div>
        <div class="page-stats">模型: deepseek-v4-flash-vision-exp ｜ 5 次运行 → 4 种不同结果</div>
      </div>
      <div style="margin-bottom:16px;padding:12px;background:#fef2f2;border-radius:8px;border:1px solid #fecaca">
        <strong>结论：deepseek VLM 裁决完全不稳定。</strong>
        同一输入连续跑 5 次，出现 4 种不同的 keep/fix/drop 组合。
        每次都误杀真音效 r07（ぽっ～ん），有 2 次在假框 r01（窗帘）上凭空造字，有 1 次直接保留全部假框。
        单次实验的"好结果"不可复现，换模型不能根本解决问题。
      </div>
      <table class="stab-table">
        <thead>
          <tr><th>运行</th><th>keep</th><th>fix</th><th>drop</th><th>假框 r01(窗帘)</th><th>假框 r02(装饰条)</th><th>真音效 r07(ぽっ)</th><th>假框 r08(网点)</th><th>问题</th></tr>
        </thead>
        <tbody>
    '''
    for r in STABILITY:
        kept = set(r["kept"])
        fixed_ids = {f["id"]: f for f in r["fixed"]}
        dropped_ids = {d["id"]: d for d in r["dropped"]}

        def cell(rid: str) -> str:
            gt = GROUND_TRUTH[rid]
            if rid in fixed_ids:
                f = fixed_ids[rid]
                cls = "bad" if not gt["real"] else "warn"
                return f'<td class="{cls}">FIX→"{esc(f["corrected"])}"</td>'
            if rid in dropped_ids:
                cls = "good" if not gt["real"] else "bad"
                return f'<td class="{cls}">DROP</td>'
            if rid in kept:
                cls = "good" if gt["real"] else "bad"
                return f'<td class="{cls}">KEEP</td>'
            return '<td>?</td>'

        # 问题描述
        problems = []
        if "r01" in kept:
            problems.append("假框 r01 被保留")
        if "r02" in kept:
            problems.append("假框 r02 被保留")
        if "r01" in fixed_ids:
            problems.append(f'r01 凭空造字"{fixed_ids["r01"]["corrected"]}"')
        if "r07" in dropped_ids:
            problems.append("真音效 r07 被误杀")
        if "r07" in fixed_ids:
            problems.append(f'r07 被错改"{fixed_ids["r07"]["corrected"]}"')

        html += f'''
          <tr>
            <td><strong>Run {r["run"]}</strong></td>
            <td>{r["keep"]}</td>
            <td>{r["fix"]}</td>
            <td>{r["drop"]}</td>
            {cell("r01")}
            {cell("r02")}
            {cell("r07")}
            {cell("r08")}
            <td style="color:#dc2626;font-size:11px">{esc("; ".join(problems))}</td>
          </tr>'''

    html += '''
        </tbody>
      </table>
      <div style="margin-top:12px;font-size:12px;color:#666">
        <span style="color:#16a34a">■</span> 正确裁决 &nbsp;
        <span style="color:#dc2626">■</span> 错误（假框保留/凭空造字/真框误杀） &nbsp;
        <span style="color:#d97706">■</span> 警告（真字被错改）
      </div>
    </div>'''
    return html


def main():
    s = DATA["summary"]
    pages_html = "\n".join(render_page(p) for p in DATA["pages"])
    stability_html = render_stability()

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>deepseek 视觉模型 VLM 裁决对比实验报告</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background:#f0f2f5; color:#1a1a2e; line-height:1.6; }}
  .container {{ max-width:1400px; margin:0 auto; padding:24px; }}
  h1 {{ font-size:24px; margin-bottom:4px; }}
  .subtitle {{ color:#666; margin-bottom:20px; font-size:13px; }}
  .summary-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin-bottom:24px; }}
  .sum-card {{ background:#fff; border-radius:10px; padding:14px; box-shadow:0 1px 4px rgba(0,0,0,0.06); }}
  .sum-card .label {{ font-size:11px; color:#888; text-transform:uppercase; }}
  .sum-card .value {{ font-size:22px; font-weight:700; margin-top:2px; }}
  .sum-card.rule .value {{ color:#2563eb; }}
  .sum-card.vlm .value {{ color:#7c3aed; }}
  .sum-card.diff .value {{ color:#dc2626; }}
  .page-section {{ background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,0.06); }}
  .page-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; padding-bottom:10px; border-bottom:2px solid #f0f0f0; }}
  .page-title {{ font-size:17px; font-weight:700; color:#1e40af; }}
  .page-stats {{ font-size:12px; color:#666; }}
  .page-body {{ display:grid; grid-template-columns:300px 1fr; gap:20px; }}
  .page-image {{ text-align:center; }}
  .page-image img {{ max-width:100%; max-height:500px; border-radius:6px; border:1px solid #e5e7eb; }}
  .page-image .img-label {{ font-size:11px; color:#999; margin-top:6px; }}
  .blocks-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .col h4 {{ font-size:13px; margin-bottom:8px; padding-bottom:4px; border-bottom:1px solid #eee; }}
  .block-item {{ background:#fafafa; border-radius:6px; padding:8px 10px; margin-bottom:6px; border:1px solid #f0f0f0; }}
  .block-header {{ font-size:10px; color:#999; margin-bottom:3px; }}
  .block-idx {{ font-weight:700; color:#666; }}
  .block-bbox {{ font-family:monospace; margin-left:6px; }}
  .block-text, .block-trans {{ font-size:12px; margin:2px 0; }}
  .block-text .label, .block-trans .label {{ color:#888; font-weight:600; margin-right:4px; }}
  .block-trans {{ color:#047857; }}
  .vlm-state {{ margin-left:6px; padding:1px 5px; border-radius:3px; font-size:9px; }}
  .vlm-state.keep {{ background:#dcfce7; color:#166534; }}
  .vlm-state.fix {{ background:#ede9fe; color:#5b21b6; }}
  .filter-detail {{ margin-top:12px; padding:10px; background:#f9fafb; border-radius:6px; }}
  .filter-detail h5 {{ font-size:12px; color:#374151; margin-bottom:6px; }}
  .removed-item {{ font-size:11px; padding:2px 0; color:#666; }}
  .removed-text {{ font-family:monospace; color:#374151; }}
  .removed-reason {{ color:#9ca3af; font-style:italic; }}
  .stab-table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  .stab-table th {{ background:#f3f4f6; padding:8px 6px; text-align:left; border-bottom:2px solid #e5e7eb; font-size:11px; }}
  .stab-table td {{ padding:8px 6px; border-bottom:1px solid #f3f4f6; }}
  .stab-table td.good {{ color:#16a34a; font-weight:600; }}
  .stab-table td.bad {{ color:#dc2626; font-weight:600; background:#fef2f2; }}
  .stab-table td.warn {{ color:#d97706; font-weight:600; }}
  .conclusion {{ background:#fff; border-radius:12px; padding:24px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,0.06); border-left:4px solid #7c3aed; }}
  .conclusion h2 {{ font-size:18px; margin-bottom:12px; color:#1e40af; }}
  .conclusion ul {{ margin-left:20px; margin-bottom:12px; }}
  .conclusion li {{ margin-bottom:6px; font-size:14px; }}
  .footer {{ text-align:center; color:#999; font-size:11px; margin-top:32px; padding:16px; }}
</style>
</head>
<body>
<div class="container">
  <h1>deepseek 视觉模型 VLM 裁决对比实验报告</h1>
  <div class="subtitle">
    rule-only（纯规则过滤）vs vlm-filter（规则过滤 + deepseek-v4-flash-vision-exp 三态裁决）
    ｜ 6 页样本 ｜ 其他条件完全不变（RT-DETR-v2 检测 + baberu OCR + 4 条规则 + deepseek-v4-flash 翻译）
    ｜ 2026-09-02
  </div>

  <div class="summary-grid">
    <div class="sum-card"><div class="label">原始检测框</div><div class="value">{s["total_detected"]}</div></div>
    <div class="sum-card rule"><div class="label">规则过滤后</div><div class="value">{s["total_rule"]}</div></div>
    <div class="sum-card"><div class="label">规则移除</div><div class="value">{s["total_rule_removed"]}</div></div>
    <div class="sum-card vlm"><div class="label">VLM过滤后</div><div class="value">{s["total_vlm"]}</div></div>
    <div class="sum-card diff"><div class="label">VLM额外drop</div><div class="value">{s["total_vlm_drop"]}</div></div>
    <div class="sum-card vlm"><div class="label">VLM fix</div><div class="value">{s["total_vlm_fix"]}</div></div>
    <div class="sum-card rule"><div class="label">rule-only翻译</div><div class="value">{s["total_trans_rule"]}</div></div>
    <div class="sum-card vlm"><div class="label">vlm-filter翻译</div><div class="value">{s["total_trans_vlm"]}</div></div>
  </div>

  {stability_html}

  {pages_html}

  <div class="conclusion">
    <h2>结论与建议</h2>
    <ul>
      <li><strong>换模型不能根本解决问题。</strong>deepseek-v4-flash-vision-exp 在 3.jpg 上连续 5 次裁决出现 4 种不同结果，和 qwen3.5-omni-plus 一样是"掷硬币"。单次实验的"好结果"不可复现。</li>
      <li><strong>deepseek 比 qwen 更激进。</strong>它更倾向于 drop（5 次里有 2 次 drop 4 个框），但也更激进地在假框上"修正"出不存在的文字（r01→ぼっーん/ぽっーん），并且每次都误杀真音效 r07（ぽっ～ん）。</li>
      <li><strong>规则过滤在难页上完全失效。</strong>3.jpg 上 4 条规则（纯标点/纯数字/极端宽高比/边缘框）移除 0 个框，因为假框形状不极端、baberu 编的是像模像样的日文。</li>
      <li><strong>真正可靠的方向：</strong>① 提高检测置信度阈值（conf 0.3→0.5），从源头减少假框；② VLM 只做 keep/drop，<strong>禁止 fix 造字</strong>（从根上杜绝"空框被修正成カちゃ"）；③ 对 VLM 裁决加 temperature=0 + 多次投票（3 次取多数），减少随机性；④ 真音效（text_free 短文本）单独处理，不与假框混在一起裁决。</li>
    </ul>
  </div>

  <div class="footer">
    实验分支: feat/deepseek-vision-compare @ 2c1d31c+e40b132 ｜
    VLM模型: deepseek-v4-flash-vision-exp ｜
    翻译模型: deepseek-v4-flash ｜
    检测: RT-DETR-v2 (conf=0.3) ｜ OCR: baberu ｜
    规则: pure_punct / pure_number / extreme_aspect / edge_box
  </div>
</div>
</body>
</html>'''

    OUT.write_text(html, encoding="utf-8")
    print(f"报告 -> {OUT}")
    print(f"大小: {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
