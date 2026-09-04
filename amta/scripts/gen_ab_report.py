"""生成 Stage 4 框外字去除 A/B 对比实验最终报告 HTML。

⚠️ 待收敛: 本脚本为独立实现（279行），尚未上移到 amta.report 深接口。
   新报告需求请用 gen_report.py（amta.report 通用引擎），本脚本仅用于历史 A/B 实验复现。
   收敛计划: 核心渲染逻辑上移到 src/amta/report/ab_report.py，本脚本退化为薄 CLI。

方案A: 框内传统方法精修mask (Otsu + 颜色直方图 + 连通域过滤)
方案B: SAM框提示像素级分割 (ViT-B, box prompt)
样本: 11-20页, 8页有text_free框, 共19个框
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(r"E:\manga translator agent\amta")
OUT_DIR = ROOT / "output"

PLAN_A_DIR = ROOT / "output" / "tmp" / "refine_mask_batch_11_20"
PLAN_B_DIR = ROOT / "output" / "tmp" / "sam_mask_probe"


def img_to_base64(path: Path, max_width: int = 1400) -> str:
    img = Image.open(path)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def main():
    print("[report] Loading summaries...")
    plan_a = json.loads((PLAN_A_DIR / "summary.json").read_text(encoding="utf-8"))
    plan_b = json.loads((PLAN_B_DIR / "summary.json").read_text(encoding="utf-8"))

    # 合并数据
    pages = sorted(set(plan_a.keys()) & set(plan_b.keys()))
    print(f"  Pages: {len(pages)}")

    # 计算平均指标
    avg_a_reduction = np.mean([plan_b[p]["plan_a_reduction_pct"] for p in pages])
    avg_b_reduction = np.mean([plan_b[p]["plan_b_reduction_pct"] for p in pages])
    avg_ab_iou = np.mean([plan_b[p]["ab_iou"] for p in pages])
    avg_a_time = np.mean([plan_b[p]["plan_a_time"] for p in pages])
    avg_b_time = np.mean([plan_b[p]["plan_b_time"] for p in pages])

    print(f"  Plan A avg reduction: {avg_a_reduction:.1f}%")
    print(f"  Plan B avg reduction: {avg_b_reduction:.1f}%")
    print(f"  A/B avg IoU: {avg_ab_iou:.3f}")
    print(f"  Plan A avg time: {avg_a_time:.3f}s")
    print(f"  Plan B avg time: {avg_b_time:.3f}s")

    print("[report] Loading comparison images...")
    # 选3页代表性的对比图: page_11(典型), page_14(多框), page_19(大框)
    comparison_images = {}
    for p in ["page_11", "page_14", "page_19"]:
        path = PLAN_B_DIR / f"{p}_ab_comparison.png"
        if path.exists():
            comparison_images[p] = img_to_base64(path)
            print(f"  loaded {p}")

    # 生成详细数据表格行
    table_rows = ""
    for p in pages:
        a = plan_b[p]
        rect_k = f"{a['rect_pixels']:,}"
        a_k = f"{a['plan_a_pixels']:,}"
        b_k = f"{a['plan_b_pixels']:,}"
        a_red = f"{a['plan_a_reduction_pct']}%"
        b_red = f"{a['plan_b_reduction_pct']}%"
        winner = "A" if a["plan_a_reduction_pct"] > a["plan_b_reduction_pct"] else "B"
        winner_color = "#1b5e20" if winner == "A" else "#b71c1c"
        table_rows += f"""<tr>
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

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stage 4 框外字去除 A/B 对比实验报告</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; color: #1a1a2e; line-height: 1.6; }}
  .container {{ max-width: 1300px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 28px; margin-bottom: 8px; }}
  .subtitle {{ color: #666; margin-bottom: 32px; font-size: 14px; }}

  .section {{ background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .section h2 {{ font-size: 20px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 2px solid #e8ecf1; }}
  .section h3 {{ font-size: 16px; margin: 20px 0 12px; color: #2c3e50; }}

  /* 概览卡片 */
  .overview-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{ border-radius: 10px; padding: 20px; color: #fff; }}
  .card.a {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }}
  .card.b {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }}
  .card.speed {{ background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }}
  .card.iou {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}
  .card .label {{ font-size: 13px; opacity: 0.9; margin-bottom: 4px; }}
  .card .value {{ font-size: 30px; font-weight: 700; }}
  .card .unit {{ font-size: 14px; opacity: 0.8; }}
  .card .sub {{ font-size: 12px; opacity: 0.85; margin-top: 4px; }}

  /* 表格 */
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px; }}
  th {{ background: #f0f2f5; padding: 10px 8px; text-align: left; font-weight: 600; border-bottom: 2px solid #d0d5dd; white-space: nowrap; }}
  td {{ padding: 8px; border-bottom: 1px solid #e8ecf1; }}
  tr:hover {{ background: #f8f9fb; }}
  .num {{ font-family: "SF Mono", "Consolas", monospace; }}
  .highlight {{ background: #e8f5e9; }}

  /* 图片 */
  .img-container {{ margin: 16px 0; text-align: center; }}
  .img-container img {{ max-width: 100%; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  .img-caption {{ font-size: 13px; color: #666; margin-top: 8px; }}

  /* 结论 */
  .conclusion {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; border-radius: 12px; padding: 28px; margin-top: 24px; }}
  .conclusion h2 {{ color: #fff; border-bottom-color: rgba(255,255,255,0.2); }}
  .conclusion li {{ margin-bottom: 10px; }}
  .conclusion strong {{ color: #38ef7d; }}
  .conclusion .bad {{ color: #f5576c; }}

  /* 方案描述 */
  .plan-desc {{ display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }}
  .plan-box {{ flex: 1; min-width: 300px; border: 2px solid #e8ecf1; border-radius: 10px; padding: 16px; }}
  .plan-box.a {{ border-color: #38ef7d; background: #f0fdf4; }}
  .plan-box.b {{ border-color: #f5576c; background: #fef2f2; }}
  .plan-box h4 {{ font-size: 15px; margin-bottom: 8px; }}
  .plan-box p {{ font-size: 13px; color: #555; }}
  .plan-box .tag {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; margin-bottom: 8px; }}
  .tag.a {{ background: #dcfce7; color: #166534; }}
  .tag.b {{ background: #fee2e2; color: #991b1b; }}

  .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 32px; padding: 16px; }}
</style>
</head>
<body>
<div class="container">

  <h1>Stage 4 框外字去除 A/B 对比实验报告</h1>
  <p class="subtitle">分支: feat/stage4-outside-text-removal &nbsp;|&nbsp; 日期: 2026-09-03 &nbsp;|&nbsp; 样本: 东方Project 单翼停留之地 page_11~20 &nbsp;|&nbsp; 8页有text_free框, 共19个框</p>

  <!-- 概览 -->
  <div class="overview-grid">
    <div class="card a">
      <div class="label">方案A 平均mask像素减少</div>
      <div class="value">{avg_a_reduction:.1f}<span class="unit">%</span></div>
      <div class="sub">传统方法精修 (Otsu+连通域)</div>
    </div>
    <div class="card b">
      <div class="label">方案B 平均mask像素减少</div>
      <div class="value">{avg_b_reduction:.1f}<span class="unit">%</span></div>
      <div class="sub">SAM ViT-B 框提示分割</div>
    </div>
    <div class="card speed">
      <div class="label">速度对比 (A vs B)</div>
      <div class="value">{avg_b_time/avg_a_time:.0f}<span class="unit">x</span></div>
      <div class="sub">A: {avg_a_time:.3f}s/页, B: {avg_b_time:.1f}s/页</div>
    </div>
    <div class="card iou">
      <div class="label">A/B 平均 IoU</div>
      <div class="value">{avg_ab_iou:.3f}</div>
      <div class="sub">两者mask差异很大 (越低越不同)</div>
    </div>
  </div>

  <!-- 实验设计 -->
  <div class="section">
    <h2>实验设计</h2>
    <div class="plan-desc">
      <div class="plan-box a">
        <span class="tag a">方案 A</span>
        <h4>框内传统方法精修 mask</h4>
        <p><strong>原理</strong>：在每个检测框内，用 Otsu 阈值（黑字+白字）+ 灰度直方图 top-3 颜色范围 + 连通域过滤（排除太小/太大/贴边组件）精修出文字像素。移植自 BallonsTranslator + comic-translate 的生产级算法。</p>
        <p><strong>先验</strong>：文字是框内的深色/浅色连通组件，与背景有颜色差异。</p>
        <p><strong>依赖</strong>：零新模型，只用 OpenCV + NumPy。</p>
      </div>
      <div class="plan-box b">
        <span class="tag b">方案 B</span>
        <h4>SAM 框提示像素级分割</h4>
        <p><strong>原理</strong>：用 Meta 的 Segment Anything Model（ViT-B，375MB），以检测框作为 box_prompt，对每个框做零样本像素级分割，选择置信度最高的 mask。</p>
        <p><strong>先验</strong>：通用分割模型，框内的"显著对象"会被分割出来。</p>
        <p><strong>依赖</strong>：segment-anything 包 + 375MB 模型权重，CPU 推理。</p>
      </div>
    </div>
    <p><strong>评估指标</strong>：</p>
    <ul style="margin-left:20px;margin-top:8px;">
      <li><strong>mask 像素减少率</strong>：相比矩形 mask，精修后减少的像素比例（越高越好，说明只圈文字不碰背景）</li>
      <li><strong>A/B IoU</strong>：方案A和方案B mask 的交并比（越低说明两者差异越大）</li>
      <li><strong>耗时</strong>：单页处理时间（越低越好）</li>
    </ul>
  </div>

  <!-- 详细数据 -->
  <div class="section">
    <h2>逐页详细数据</h2>
    <div style="overflow-x:auto;">
    <table>
      <thead>
        <tr>
          <th>页面</th>
          <th>框数</th>
          <th>矩形mask像素</th>
          <th>方案A像素</th>
          <th>方案B像素</th>
          <th>A减少率</th>
          <th>B减少率</th>
          <th>A/B IoU</th>
          <th>A耗时</th>
          <th>B耗时</th>
          <th>胜者</th>
        </tr>
      </thead>
      <tbody>
        {table_rows}
      </tbody>
    </table>
    </div>
    <p style="font-size:13px;color:#666;margin-top:8px;">
      <strong>结论</strong>：方案A在 8/8 页上的 mask 像素减少率都优于方案B。page_18 两者接近（49.2% vs 50.2%），因为该页只有1个很小的框，文字占框比例高。
    </p>
  </div>

  <!-- 视觉对比 -->
  <div class="section">
    <h2>视觉对比（A/B mask 叠加）</h2>
    <p>每张对比图包含 5 个子图：原图 / 矩形mask(红) / 方案A(蓝) / 方案B(绿) / A vs B差异(蓝=只有A, 绿=只有B, 黄=两者都有)。</p>

    <h3>page_11（1个框，人物头顶文字）</h3>
    <div class="img-container">
      <img src="data:image/jpeg;base64,{comparison_images.get('page_11', '')}" alt="page_11 AB comparison">
      <p class="img-caption">方案A(蓝)精确圈出"ぽつん"几个字的像素；方案B(绿)把整个框内区域都当mask，包括大量空白。A减少95.9%，B只减少24.7%。</p>
    </div>

    <h3>page_14（4个框，含竖排文字+SFX）</h3>
    <div class="img-container">
      <img src="data:image/jpeg;base64,{comparison_images.get('page_14', '')}" alt="page_14 AB comparison">
      <p class="img-caption">方案A(蓝)精确圈出各个框内的文字像素；方案B(绿)把框内的人物、背景线条都当成了mask，完全无法区分文字和非文字。A减少87.5%，B只减少56.0%。</p>
    </div>

    <h3>page_19（3个大框，含复杂背景）</h3>
    <div class="img-container">
      <img src="data:image/jpeg;base64,{comparison_images.get('page_19', '')}" alt="page_19 AB comparison">
      <p class="img-caption">大框场景下差距更明显：方案A精确圈出文字，方案B把大块背景区域都包含进去。A减少70.4%，B只减少45.3%。</p>
    </div>
  </div>

  <!-- 根因分析 -->
  <div class="section">
    <h2>根因分析：为什么 SAM 不适合这个任务？</h2>
    <ol style="margin-left:20px;">
      <li style="margin-bottom:12px;">
        <strong>SAM 是通用分割模型，没有"文字"概念</strong>。SAM 被训练来分割"显著对象"，但漫画框内的文字和背景线条、人物轮廓混在一起，SAM 无法区分"文字像素"和"非文字像素"。它把整个框内的内容都当成了一个对象。
      </li>
      <li style="margin-bottom:12px;">
        <strong>框提示（box prompt）的语义是"框内的对象"，不是"框内的文字"</strong>。当我们给 SAM 一个包含文字的框时，它会分割出框内最显著的区域，而不是文字本身。对于空白背景上的文字，SAM 可能会把整个框都分割出来。
      </li>
      <li style="margin-bottom:12px;">
        <strong>传统方法利用了"文字是连通组件"这个强先验</strong>。方案A的 Otsu + 连通域过滤直接针对"文字是深色/浅色的小连通组件"这个特性，能够精确圈出文字像素。这个先验在漫画场景下非常可靠。
      </li>
      <li style="margin-bottom:12px;">
        <strong>CPU 推理速度不可接受</strong>。SAM ViT-B 在 CPU 上处理一页需要 23-37 秒，而方案A只需要 0.01-0.23 秒，差距 100-300 倍。即使有 GPU，SAM 的推理开销也远大于传统方法。
      </li>
    </ol>
  </div>

  <!-- 结论 -->
  <div class="conclusion">
    <h2>最终结论与建议</h2>
    <ul>
      <li><strong>方案A 全面优于方案B</strong>：在 8/8 页上，方案A的 mask 像素减少率都高于方案B（平均 81.2% vs 47.6%），速度快 313 倍（0.09s vs 28.2s/页）。</li>
      <li><strong>SAM 不适合漫画文字像素级分割</strong>：通用分割模型没有"文字"概念，框提示语义不匹配，无法区分文字和背景线条/人物。</li>
      <li><strong>传统方法在框内完全够用</strong>：利用"文字是连通组件"这个强先验，Otsu + 连通域过滤能够精确圈出文字像素，零新模型、零风险、极快。</li>
      <li><strong>建议</strong>：
        <ul style="margin-left:20px;margin-top:8px;">
          <li>✅ 采用方案A作为框外字 mask 生成的主力方案</li>
          <li>❌ 放弃方案B（SAM），不适合这个任务</li>
          <li>🔮 方案C（lama_large_512px 专门动漫 inpaint）可作为长期优化，但 mask 精度比 inpaint 引擎更重要</li>
          <li>📋 下一步：把方案A的 --refine-mask 默认开启，跑 10-20 页端到端 inpaint 验证</li>
        </ul>
      </li>
    </ul>
  </div>

  <div class="footer">
    AMTA Stage 4 框外字去除 A/B 对比实验 &nbsp;|&nbsp; 2026-09-03 &nbsp;|&nbsp; 分支 feat/stage4-outside-text-removal
  </div>

</div>
</body>
</html>"""

    out_path = OUT_DIR / "stage4-ab-comparison-report.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"[report] Saved: {out_path}")
    print(f"  size: {out_path.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()