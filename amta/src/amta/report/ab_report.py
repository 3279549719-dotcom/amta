"""ab_report — Stage4 框外字去除 A/B 对比实验报告（深接口模块）。

scripts/gen_ab_report.py 是本模块的薄 CLI。
方案A: 框内传统方法精修mask (Otsu + 颜色直方图 + 连通域过滤)
方案B: SAM框提示像素级分割 (ViT-B, box prompt)
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image


def _img_to_base64(path: Path, max_width: int = 1400) -> str:
    img = Image.open(path)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def _compute_averages(plan_b: dict, pages: list[str]) -> dict:
    """从 plan_b summary 计算各指标的页均值。"""
    return {
        "avg_a_reduction": float(np.mean([plan_b[p]["plan_a_reduction_pct"] for p in pages])),
        "avg_b_reduction": float(np.mean([plan_b[p]["plan_b_reduction_pct"] for p in pages])),
        "avg_ab_iou": float(np.mean([plan_b[p]["ab_iou"] for p in pages])),
        "avg_a_time": float(np.mean([plan_b[p]["plan_a_time"] for p in pages])),
        "avg_b_time": float(np.mean([plan_b[p]["plan_b_time"] for p in pages])),
    }


def _build_table_rows(plan_b: dict, pages: list[str]) -> str:
    rows = ""
    for p in pages:
        a = plan_b[p]
        rect_k = f"{a['rect_pixels']:,}"
        a_k = f"{a['plan_a_pixels']:,}"
        b_k = f"{a['plan_b_pixels']:,}"
        a_red = f"{a['plan_a_reduction_pct']}%"
        b_red = f"{a['plan_b_reduction_pct']}%"
        winner = "A" if a["plan_a_reduction_pct"] > a["plan_b_reduction_pct"] else "B"
        winner_color = "#1b5e20" if winner == "A" else "#b71c1c"
        rows += f"""<tr>
          <td>{p}</td>
          <td class="num">{a['free_boxes']}</td>
          <td class="num">{rect_k}</td>
          <td class="num">{a_k}</td>
          <td class="num">{b_k}</td>
          <td class="num" style="color:#1b5e20;font-weight:600">{a_red}</td>
          <td class="num" style="color:#b71c1c">{b_red}</td>
          <td class="num">{a['ab_iou']}</td>
          <td class="num">{a['plan_a_time']:.3f}s</td>
          <td class="num">{a['plan_b_time']:.1f}s</td>
          <td class="num" style="font-weight:700;color:{winner_color}">{winner}</td>
        </tr>"""
    return rows


_CSS = """
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; color: #1a1a2e; line-height: 1.6; }
  .container { max-width: 1300px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 28px; margin-bottom: 8px; }
  .subtitle { color: #666; margin-bottom: 32px; font-size: 14px; }
  .section { background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .section h2 { font-size: 20px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 2px solid #e8ecf1; }
  .section h3 { font-size: 16px; margin: 20px 0 12px; color: #2c3e50; }
  .overview-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { border-radius: 10px; padding: 20px; color: #fff; }
  .card.a { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
  .card.b { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
  .card.speed { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
  .card.iou { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
  .card .label { font-size: 13px; opacity: 0.9; margin-bottom: 4px; }
  .card .value { font-size: 30px; font-weight: 700; }
  .card .unit { font-size: 14px; opacity: 0.8; }
  .card .sub { font-size: 12px; opacity: 0.85; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px; }
  th { background: #f0f2f5; padding: 10px 8px; text-align: left; font-weight: 600; border-bottom: 2px solid #d0d5dd; white-space: nowrap; }
  td { padding: 8px; border-bottom: 1px solid #e8ecf1; }
  tr:hover { background: #f8f9fb; }
  .num { font-family: "SF Mono", "Consolas", monospace; }
  .img-container { margin: 16px 0; text-align: center; }
  .img-container img { max-width: 100%; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
  .img-caption { font-size: 13px; color: #666; margin-top: 8px; }
  .conclusion { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; border-radius: 12px; padding: 28px; margin-top: 24px; }
  .conclusion h2 { color: #fff; border-bottom-color: rgba(255,255,255,0.2); }
  .conclusion li { margin-bottom: 10px; }
  .conclusion strong { color: #38ef7d; }
  .plan-desc { display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }
  .plan-box { flex: 1; min-width: 300px; border: 2px solid #e8ecf1; border-radius: 10px; padding: 16px; }
  .plan-box.a { border-color: #38ef7d; background: #f0fdf4; }
  .plan-box.b { border-color: #f5576c; background: #fef2f2; }
  .plan-box h4 { font-size: 15px; margin-bottom: 8px; }
  .plan-box p { font-size: 13px; color: #555; }
  .plan-box .tag { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; margin-bottom: 8px; }
  .tag.a { background: #dcfce7; color: #166534; }
  .tag.b { background: #fee2e2; color: #991b1b; }
  .footer { text-align: center; color: #999; font-size: 12px; margin-top: 32px; padding: 16px; }
"""


def render_ab_report(
    plan_a_dir: Path,
    plan_b_dir: Path,
    out_path: Path | None = None,
) -> str:
    """生成 Stage4 框外字去除 A/B 对比报告，返回 HTML 字符串。

    Args:
        plan_a_dir: 方案A结果目录（含 summary.json）
        plan_b_dir: 方案B结果目录（含 summary.json + page_*_ab_comparison.png）
        out_path: 可选，写入 HTML 文件
    """
    plan_a_dir = Path(plan_a_dir)
    plan_b_dir = Path(plan_b_dir)

    print("[report] Loading summaries...")
    plan_a = json.loads((plan_a_dir / "summary.json").read_text(encoding="utf-8"))
    plan_b = json.loads((plan_b_dir / "summary.json").read_text(encoding="utf-8"))

    pages = sorted(set(plan_a.keys()) & set(plan_b.keys()))
    print(f"  Pages: {len(pages)}")

    avg = _compute_averages(plan_b, pages)
    print(f"  Plan A avg reduction: {avg['avg_a_reduction']:.1f}%")
    print(f"  Plan B avg reduction: {avg['avg_b_reduction']:.1f}%")
    print(f"  A/B avg IoU: {avg['avg_ab_iou']:.3f}")

    print("[report] Loading comparison images...")
    comparison_images = {}
    for p in ["page_11", "page_14", "page_19"]:
        path = plan_b_dir / f"{p}_ab_comparison.png"
        if path.exists():
            comparison_images[p] = _img_to_base64(path)
            print(f"  loaded {p}")

    table_rows = _build_table_rows(plan_b, pages)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stage 4 框外字去除 A/B 对比实验报告</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">

  <h1>Stage 4 框外字去除 A/B 对比实验报告</h1>
  <p class="subtitle">方案A: 框内传统方法精修mask &nbsp;|&nbsp; 方案B: SAM框提示像素级分割 &nbsp;|&nbsp; {len(pages)} 页有inpaint框</p>

  <div class="overview-grid">
    <div class="card a">
      <div class="label">方案A 平均mask像素减少</div>
      <div class="value">{avg['avg_a_reduction']:.1f}<span class="unit">%</span></div>
      <div class="sub">传统方法精修 (Otsu+连通域)</div>
    </div>
    <div class="card b">
      <div class="label">方案B 平均mask像素减少</div>
      <div class="value">{avg['avg_b_reduction']:.1f}<span class="unit">%</span></div>
      <div class="sub">SAM ViT-B 框提示分割</div>
    </div>
    <div class="card speed">
      <div class="label">速度对比 (A vs B)</div>
      <div class="value">{avg['avg_b_time']/avg['avg_a_time']:.0f}<span class="unit">x</span></div>
      <div class="sub">A: {avg['avg_a_time']:.3f}s/页, B: {avg['avg_b_time']:.1f}s/页</div>
    </div>
    <div class="card iou">
      <div class="label">A/B 平均 IoU</div>
      <div class="value">{avg['avg_ab_iou']:.3f}</div>
      <div class="sub">两者mask差异 (越低越不同)</div>
    </div>
  </div>

  <div class="section">
    <h2>逐页详细数据</h2>
    <div style="overflow-x:auto;">
    <table>
      <thead>
        <tr>
          <th>页面</th><th>框数</th><th>矩形mask像素</th><th>方案A像素</th><th>方案B像素</th>
          <th>A减少率</th><th>B减少率</th><th>A/B IoU</th><th>A耗时</th><th>B耗时</th><th>胜者</th>
        </tr>
      </thead>
      <tbody>{table_rows}</tbody>
    </table>
    </div>
  </div>

  <div class="section">
    <h2>视觉对比（A/B mask 叠加）</h2>
    <h3>page_11</h3>
    <div class="img-container">
      <img src="data:image/jpeg;base64,{comparison_images.get('page_11', '')}" alt="page_11 AB comparison">
    </div>
    <h3>page_14</h3>
    <div class="img-container">
      <img src="data:image/jpeg;base64,{comparison_images.get('page_14', '')}" alt="page_14 AB comparison">
    </div>
    <h3>page_19</h3>
    <div class="img-container">
      <img src="data:image/jpeg;base64,{comparison_images.get('page_19', '')}" alt="page_19 AB comparison">
    </div>
  </div>

  <div class="conclusion">
    <h2>结论</h2>
    <ul>
      <li><strong>方案A 平均减少 {avg['avg_a_reduction']:.1f}%</strong>，方案B 平均减少 {avg['avg_b_reduction']:.1f}%</li>
      <li>方案A 速度快 {avg['avg_b_time']/avg['avg_a_time']:.0f} 倍（{avg['avg_a_time']:.3f}s vs {avg['avg_b_time']:.1f}s/页）</li>
      <li>A/B IoU={avg['avg_ab_iou']:.3f}，两者 mask 差异显著</li>
      <li><strong>建议采用方案A</strong>（零新模型、极快、精确圈出文字像素）</li>
    </ul>
  </div>

  <div class="footer">AMTA Stage 4 框外字去除 A/B 对比实验</div>

</div>
</body>
</html>"""

    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        print(f"[report] Saved: {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")

    return html
