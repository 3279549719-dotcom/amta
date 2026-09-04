"""生成 Stage 4 端到端验证 HTML 报告。

核心发现:
1. 框内字(text_bubble): 直接涂白即可
2. 框外字(text_free): 矩形mask + koharu inpaint 效果很好, 不需要像素级mask
3. 04_inpaint.py 有两个bug: mask黑白约定反了 + 分类映射断了
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output" / "tmp" / "e2e_inpaint"
OUT_HTML = OUT_DIR / "stage4_e2e_report.html"


def img_to_base64(path: Path, max_side: int = 1400, quality: int = 82) -> str:
    im = Image.open(path)
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def img_tag(name: str, alt: str = "", max_side: int = 1400) -> str:
    p = OUT_DIR / name
    if not p.exists():
        return f"<p style='color:#999'>(missing: {name})</p>"
    return f'<img src="{img_to_base64(p, max_side)}" alt="{alt}" style="max-width:100%;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.15);margin:12px 0">'


def build_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stage 4 端到端验证报告 - 框内字涂白 + 框外字 Inpaint</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif; max-width: 1400px; margin: 0 auto; padding: 24px; background: #fafafa; color: #333; line-height: 1.7; }}
  h1 {{ color: #1a1a2e; border-bottom: 3px solid #e94560; padding-bottom: 12px; font-size: 26px; }}
  h2 {{ color: #16213e; margin-top: 48px; border-left: 5px solid #e94560; padding-left: 14px; font-size: 21px; }}
  h3 {{ color: #0f3460; margin-top: 28px; font-size: 17px; }}
  .meta {{ color: #888; font-size: 14px; margin-bottom: 20px; }}
  .key-insight {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; padding: 22px 28px; border-radius: 14px; margin: 24px 0; box-shadow: 0 4px 20px rgba(245,87,108,.3); }}
  .key-insight h2 {{ color: white; border: none; margin: 0 0 10px 0; padding: 0; font-size: 19px; }}
  .key-insight p {{ margin: 6px 0; }}
  .key-insight code {{ background: rgba(255,255,255,.25); color: white; padding: 2px 8px; border-radius: 4px; }}
  .bug-box {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 16px 20px; margin: 20px 0; border-radius: 0 10px 10px 0; }}
  .bug-box h3 {{ color: #856404; margin-top: 0; }}
  .good {{ background: #d4edda; border-left: 4px solid #28a745; padding: 16px 20px; margin: 20px 0; border-radius: 0 10px 10px 0; }}
  .bad {{ background: #f8d7da; border-left: 4px solid #dc3545; padding: 16px 20px; margin: 20px 0; border-radius: 0 10px 10px 0; }}
  .conclusion {{ background: #f0f7ff; border-left: 4px solid #0f3460; padding: 16px 20px; margin: 20px 0; border-radius: 0 10px 10px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; background: white; box-shadow: 0 1px 6px rgba(0,0,0,.08); border-radius: 8px; overflow: hidden; }}
  th, td {{ border: 1px solid #e8e8e8; padding: 10px 14px; text-align: left; font-size: 14px; }}
  th {{ background: #16213e; color: white; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}
  .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin: 24px 0; }}
  .metric-card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,.08); text-align: center; }}
  .metric-card .value {{ font-size: 30px; font-weight: bold; color: #e94560; }}
  .metric-card .label {{ font-size: 13px; color: #666; margin-top: 6px; }}
  .img-caption {{ font-size: 13px; color: #777; text-align: center; margin-top: -4px; margin-bottom: 24px; font-style: italic; }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  pre {{ background: #1a1a2e; color: #e0e0e0; padding: 18px; border-radius: 10px; overflow-x: auto; font-size: 13px; line-height: 1.5; font-family: "Cascadia Code", Consolas, monospace; }}
  code {{ background: #e9ecef; padding: 2px 7px; border-radius: 4px; font-size: 13px; color: #c7254e; }}
  .footer {{ color: #aaa; text-align: center; font-size: 12px; margin-top: 40px; }}
</style>
</head>
<body>

<h1>Stage 4 端到端验证报告</h1>
<div class="meta">框内字涂白 + 框外字 Inpaint &nbsp;|&nbsp; 2026-09-03 &nbsp;|&nbsp; 分支: feat/stage4-ctd-mask-probe</div>

<div class="key-insight">
<h2>核心结论</h2>
<p><strong>1. 框内字 (text_bubble)：</strong>直接矩形涂白即可，气泡本来就是白的，零副作用。</p>
<p><strong>2. 框外字 (text_free)：</strong>矩形 mask + koharu lama-manga inpaint 效果很好，文字完全擦掉，背景被修复。<strong>不需要 CTD 像素级 mask</strong>——CTD 对框外字零响应，且矩形 mask + inpaint 已经够用。</p>
<p><strong>3. 发现两个 bug：</strong><code>04_inpaint.py</code> 的 mask 黑白约定搞反了 + 分类映射断了，导致之前的 inpaint 从来没真正生效过。</p>
</div>

<h2>一、第一性原理：框内字 vs 框外字</h2>

<div class="conclusion">
<strong>框内字</strong>：文字在白色气泡内 → 涂白 = 把气泡重新涂白 → 零副作用。<br>
<strong>框外字</strong>：文字直接画在画面上（网点、衣服、天空）→ 涂白会破坏背景 → 需要 inpaint 修复背景。
</div>

<p>之前的探针错误地用了全是框内字的页面（21、22页），导致过度研究 CTD 像素级 mask。本次用 page_13（4个框外字）验证真正的痛点场景。</p>

<h2>二、发现的 Bug</h2>

<div class="bug-box">
<h3>Bug 1: mask 黑白约定搞反了</h3>
<p><code>04_inpaint.py</code> 的 <code>_build_mask()</code>：</p>
<pre>mask = Image.new("L", img.size, 255)  # 全白
d.rectangle([...], fill=0)  # 文字区域涂黑</pre>
<p>但 koharu 的约定是：<strong>要修复的区域 = 白色(255)，其余 = 黑色(0)</strong>。代码里搞反了，导致 mask 全白（没有要修复的区域），inpaint 什么都不做。</p>
<p><strong>验证：</strong>用反色 mask 测试，changed pixels 从 0 变成 186,204，inpaint 正常工作。</p>
</div>

<div class="bug-box">
<h3>Bug 2: 分类映射断了</h3>
<p><code>inpaint_strategy.py</code> 读 <code>category</code> 字段：</p>
<pre>cat = r.get("category") or "dialogue_bubble"  # 没有就默认涂白</pre>
<p>但 <code>01_detect.py</code> 输出的 detection.json 里只有 <code>bubble_type</code>（text_bubble/text_free），没有 <code>category</code> 字段。所以<strong>所有框都被默认成 dialogue_bubble 涂白了</strong>，框外字根本没走 inpaint。</p>
</div>

<h2>三、修复后端到端效果</h2>

<h3>全页对比：原图 vs 修复后</h3>
{img_tag("_success_white_target.png", "inpainted result", max_side=1200)}
<div class="img-caption">修复后：框内字涂白 + 框外字 inpaint（注意：此图只做了框外字 inpaint，框内字还没涂白）</div>

<h3>框外字修复细节 1：网点背景</h3>
{img_tag("_detail_free0.png", "free0 detail", max_side=1000)}
<div class="img-caption">左: 原图（网点背景上的竖排字） &nbsp;|&nbsp; 右: inpaint 后（文字消失，网点背景被修复）</div>

<h3>框外字修复细节 2：人物衣服/翅膀</h3>
{img_tag("_detail_free1.png", "free1 detail", max_side=800)}
<div class="img-caption">左: 原图（衣服上的竖排字） &nbsp;|&nbsp; 右: inpaint 后（文字消失，衣服纹理被修复）</div>

<div class="good">
<strong>效果评估：</strong>
<ul>
<li>文字完全擦掉，无残留</li>
<li>背景修复自然，网点纹理和衣服线条都恢复了</li>
<li>矩形 mask 比文字大，但 inpaint 模型能很好地修复额外区域</li>
<li>不需要像素级 mask，矩形 mask 已经够用</li>
</ul>
</div>

<h2>四、CTD 像素级 mask 的结论</h2>

<div class="bad">
<strong>CTD DBNet 对框外字零响应：</strong>
<ul>
<li>框外字区域的 shrink_map 最大值仅 0.0005~0.0014（几乎为0）</li>
<li>CTD 主要训练气泡内黑字白底，对网点背景、黑底白字、衣服上的字无泛化能力</li>
<li>CTD 检测框对框外字召回率 0/8</li>
</ul>
</div>

<div class="conclusion">
<strong>CTD 的定位：</strong>可以用于气泡内文字的像素级 mask（如果未来需要），但对框外字无效。当前阶段<strong>不需要引入 CTD</strong>，矩形 mask + koharu inpaint 已经满足需求。
</div>

<h2>五、最终架构（修正版）</h2>

<pre>Stage 1 (detect):   RT-DETR-v2 → bbox + bubble_type (text_bubble/text_free)
Stage 2 (OCR):      逐框识别
Stage 3 (translate): 术语预扫描 + LLM 翻译
Stage 4 (inpaint):   按 bubble_type 分流:
  ├─ text_bubble → 矩形涂白（气泡本来就是白的）
  └─ text_free → 矩形mask(要修复区域=白色) + koharu lama-manga inpaint
Stage 5 (typeset):   现有 PIL 二分字号 + 贪心折行</pre>

<div class="metric-grid">
  <div class="metric-card"><div class="value">2</div><div class="label">发现的 Bug 数</div></div>
  <div class="metric-card"><div class="value">186K</div><div class="label">修复后 inpaint 变化像素</div></div>
  <div class="metric-card"><div class="value">0</div><div class="label">需要的新模型/新依赖</div></div>
  <div class="metric-card"><div class="value">~6s</div><div class="label">koharu inpaint 耗时/页</div></div>
</div>

<h2>六、下一步</h2>
<ol>
<li><strong>修复 04_inpaint.py：</strong>
  <ul>
  <li>修正 <code>_build_mask()</code> 的黑白约定（要修复区域=白色）</li>
  <li>修正分类映射：用 <code>bubble_type</code> 字段，text_bubble→fill_white，text_free→inpaint</li>
  </ul>
</li>
<li>跑 5-10 页（含框外字）验证端到端效果</li>
<li>写 ADR-021 记录决策：Stage 4 策略 + mask 约定 + 分类映射</li>
<li>删除/归档 CTD 相关探针脚本（本分支验证后不需要）</li>
</ol>

<h3>已知风险</h3>
<ul>
<li>复杂背景（渐变、特效）上的框外字，inpaint 修复质量可能下降</li>
<li>超大框外字区域（整页 SFX）可能需要分段处理</li>
<li>koharu inpaint 是单并发，多页时是瓶颈</li>
</ul>

<div class="footer">AMTA Stage 4 端到端验证 &nbsp;|&nbsp; 2026-09-03 &nbsp;|&nbsp; 探针: scripts/probe_e2e_inpaint.py &nbsp;|&nbsp; 报告: scripts/gen_e2e_report.py</div>

</body>
</html>"""


def main() -> None:
    html = build_html()
    OUT_HTML.write_text(html, encoding="utf-8")
    size_mb = OUT_HTML.stat().st_size / 1024 / 1024
    print(f"[gen_e2e_report] HTML: {OUT_HTML}")
    print(f"[gen_e2e_report] Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
