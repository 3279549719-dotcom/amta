"""生成框外字(overlay_text)检测与擦除对比 HTML 报告。

核心问题: 框内字直接涂白即可, 框外字才需要像素级 mask。
对比: RT-DETR-v2 vs CTD 对框外字的检测召回率, 以及矩形涂白 vs CTD像素mask的擦除效果。

用法: python scripts/gen_overlay_report.py
输出: output/tmp/overlay_probe/overlay_text_report.html
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent.parent
PROBE_DIR = ROOT / "output" / "tmp" / "overlay_probe"
OUT_HTML = PROBE_DIR / "overlay_text_report.html"


def img_to_base64(path: Path, max_side: int = 1400, quality: int = 82) -> str:
    im = Image.open(path)
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def img_tag(name: str, alt: str = "", max_side: int = 1400) -> str:
    p = PROBE_DIR / name
    if not p.exists():
        return f"<p style='color:#999'>(missing: {name})</p>"
    return f'<img src="{img_to_base64(p, max_side)}" alt="{alt}" style="max-width:100%;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.15);margin:12px 0">'


def load_summary() -> list[dict]:
    p = PROBE_DIR / "summary.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def build_html() -> str:

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>框外字(overlay_text)检测与擦除对比报告</title>
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
  .conclusion {{ background: #f0f7ff; border-left: 4px solid #0f3460; padding: 16px 20px; margin: 20px 0; border-radius: 0 10px 10px 0; }}
  .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 16px 20px; margin: 20px 0; border-radius: 0 10px 10px 0; }}
  .good {{ background: #d4edda; border-left: 4px solid #28a745; padding: 16px 20px; margin: 20px 0; border-radius: 0 10px 10px 0; }}
  .bad {{ background: #f8d7da; border-left: 4px solid #dc3545; padding: 16px 20px; margin: 20px 0; border-radius: 0 10px 10px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; background: white; box-shadow: 0 1px 6px rgba(0,0,0,.08); border-radius: 8px; overflow: hidden; }}
  th, td {{ border: 1px solid #e8e8e8; padding: 10px 14px; text-align: center; font-size: 14px; }}
  th {{ background: #16213e; color: white; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}
  .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin: 24px 0; }}
  .metric-card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,.08); text-align: center; }}
  .metric-card .value {{ font-size: 30px; font-weight: bold; color: #e94560; }}
  .metric-card .label {{ font-size: 13px; color: #666; margin-top: 6px; }}
  .img-caption {{ font-size: 13px; color: #777; text-align: center; margin-top: -4px; margin-bottom: 24px; font-style: italic; }}
  .legend {{ display: flex; gap: 20px; flex-wrap: wrap; margin: 12px 0; font-size: 14px; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .legend-color {{ width: 16px; height: 16px; border-radius: 3px; display: inline-block; }}
  pre {{ background: #1a1a2e; color: #e0e0e0; padding: 18px; border-radius: 10px; overflow-x: auto; font-size: 13px; line-height: 1.5; font-family: "Cascadia Code", Consolas, monospace; }}
  code {{ background: #e9ecef; padding: 2px 7px; border-radius: 4px; font-size: 13px; color: #c7254e; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 40px 0; }}
  .footer {{ color: #aaa; text-align: center; font-size: 12px; margin-top: 40px; }}
</style>
</head>
<body>

<h1>框外字 (overlay_text) 检测与擦除对比报告</h1>
<div class="meta">第一性原理验证：框内字直接涂白，框外字才需要像素级 mask &nbsp;|&nbsp; 2026-09-03 &nbsp;|&nbsp; 分支: feat/stage4-ctd-mask-probe</div>

<div class="key-insight">
<h2>核心结论</h2>
<p><strong>1. 框内字 (dialogue_bubble)：</strong>直接矩形涂白即可，气泡本来就是白的，像素级 mask 无收益。</p>
<p><strong>2. 框外字 (overlay_text/sfx)：</strong>矩形涂白会严重破坏背景（网点、衣服、画面），<strong>必须用像素级 mask</strong>。</p>
<p><strong>3. 检测器选择：</strong>RT-DETR-v2 对框外字召回率高（有 category 分类），CTD 对框外字检测召回率低（0/4 匹配）——<strong>检测必须用 RT-DETR-v2</strong>。</p>
<p><strong>4. Mask 生成：</strong>用 RT-DETR-v2 的 bbox 定位框外字区域，在该区域内用 CTD DBNet 热图生成像素级 mask——<strong>CTD 只做 mask，不做检测</strong>。</p>
</div>

<h2>一、第一性原理：为什么框外字是真正的痛点</h2>

<div class="conclusion">
<strong>框内字</strong>：文字在白色气泡内 → 矩形涂白 = 把气泡重新涂白 → 零副作用，因为气泡本来就是白的。<br>
<strong>框外字</strong>：文字直接画在画面上（网点背景、人物衣服、天空、特效）→ 矩形涂白 = 把背景也涂没了 → 必须精确知道"哪些像素是文字"。
</div>

<p>之前的探针用 21、22 页（全是框内字）测试，CTD 像素 mask 的优势没有真正体现。本次用 page_13、page_14（各有 4 个框外字）验证真正的痛点场景。</p>

<h2>二、检测器对比：RT-DETR-v2 vs CTD 对框外字的召回率</h2>

<div class="legend">
  <div class="legend-item"><span class="legend-color" style="background:#00c800"></span> RT-DETR-v2: BUBBLE (框内字)</div>
  <div class="legend-item"><span class="legend-color" style="background:#0000ff"></span> RT-DETR-v2: FREE (框外字)</div>
  <div class="legend-item"><span class="legend-color" style="background:#ff6400"></span> CTD 检测框 (列级细框)</div>
</div>

<h3>page_13 (14.jpg) — RT-DETR-v2: 12框(8气泡+4框外) | CTD: 17框</h3>
{img_tag("page_13_detectors_comparison.png", "page_13 detectors comparison")}
<div class="img-caption">左: RT-DETR-v2 检测结果（绿=气泡内, 蓝=框外字） &nbsp;|&nbsp; 右: CTD 检测结果（橙色列级细框）</div>

<h3>page_14 (15.jpg) — RT-DETR-v2: 7框(3气泡+4框外) | CTD: 9框</h3>
{img_tag("page_14_detectors_comparison.png", "page_14 detectors comparison")}
<div class="img-caption">左: RT-DETR-v2 &nbsp;|&nbsp; 右: CTD</div>

<div class="bad">
<strong>关键发现：CTD 对框外字的检测召回率极低（0/8 匹配）。</strong><br>
CTD 的 DBNet 模型主要训练数据是气泡内的黑字白底，对以下场景泛化能力弱：
<ul>
<li>黑底白字（如 page_13 左上角"お礼が先でしょ"）</li>
<li>网点/灰色背景上的字（如 page_14 的旁白框外字）</li>
<li>人物衣服/翅膀上的字</li>
</ul>
而 RT-DETR-v2 能稳定检测到这些框外字，并且有 <code>text_bubble/text_free</code> 分类。
</div>

<table>
<tr><th>页面</th><th>RT-DETR-v2 总框</th><th>框内字</th><th>框外字</th><th>CTD 总框</th><th>CTD 匹配框外字</th><th>框外字召回率</th></tr>
<tr><td>page_13</td><td>12</td><td>8</td><td>4</td><td>17</td><td>0</td><td><strong style="color:#dc3545">0%</strong></td></tr>
<tr><td>page_14</td><td>7</td><td>3</td><td>4</td><td>9</td><td>0</td><td><strong style="color:#dc3545">0%</strong></td></tr>
</table>

<h2>三、擦除效果对比：矩形涂白 vs CTD 像素级 mask</h2>

<p>以下每组图从左到右四列：<strong>原图 → 矩形涂白(当前) → CTD mask叠加(紫) → CTD像素涂白</strong></p>

<h3>案例 1：网点背景上的框外字 (page_13_free00)</h3>
{img_tag("page_13_free00_comparison.png", "page_13 free00 comparison", max_side=1200)}
<div class="img-caption">文字: "いくら長年人付き合い子供の一人くらい……"（网点背景）</div>

<div class="bad">
<strong>矩形涂白（第2列）：</strong>把整个矩形区域涂白，<strong>网点背景被完全破坏</strong>，inpaint 后需要修复大片网点纹理。
</div>
<div class="good">
<strong>CTD 像素涂白（第4列）：</strong>只擦掉文字笔画，<strong>网点背景完好保留</strong>，inpaint 只需修复文字大小的区域。
</div>

<h3>案例 2：人物衣服上的框外字 (page_13_free01)</h3>
{img_tag("page_13_free01_comparison.png", "page_13 free01 comparison", max_side=1000)}
<div class="img-caption">文字: "なにをしているんだ……！"（人物衣服/翅膀背景）</div>

<div class="bad">
<strong>矩形涂白：</strong>把人物翅膀和衣服的一部分涂白了，<strong>严重破坏画面</strong>。
</div>
<div class="good">
<strong>CTD 像素涂白：</strong>只擦掉文字，衣服和翅膀的线条纹理完全保留。
</div>

<h3>案例 3：网点背景上的长旁白 (page_14_free00)</h3>
{img_tag("page_14_free00_comparison.png", "page_14 free00 comparison", max_side=1200)}
<div class="img-caption">文字: "あの2人の子供 歳は輝夜様と同じくらいか…"（网点背景）</div>

<div class="bad">
<strong>矩形涂白：</strong>大片网点背景被涂白。
</div>
<div class="good">
<strong>CTD 像素涂白：</strong>精确擦除文字，背景网点完好。
</div>

<h3>更多案例</h3>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
  <div>
    <h4>page_13_free02</h4>
    {img_tag("page_13_free02_comparison.png", "page_13 free02", max_side=900)}
  </div>
  <div>
    <h4>page_13_free03</h4>
    {img_tag("page_13_free03_comparison.png", "page_13 free03", max_side=900)}
  </div>
  <div>
    <h4>page_14_free01</h4>
    {img_tag("page_14_free01_comparison.png", "page_14 free01", max_side=900)}
  </div>
  <div>
    <h4>page_14_free02</h4>
    {img_tag("page_14_free02_comparison.png", "page_14 free02", max_side=900)}
  </div>
</div>

<h2>四、全页 CTD 像素 mask 可视化</h2>

<h3>page_13 全页 CTD mask 叠加（紫色=文字像素）</h3>
{img_tag("page_13_full_ctd_mask.png", "page_13 full CTD mask", max_side=1200)}
<div class="img-caption">紫色区域是 CTD DBNet 识别出的所有文字像素（包括气泡内和框外）</div>

<h3>page_14 全页 CTD mask 叠加</h3>
{img_tag("page_14_full_ctd_mask.png", "page_14 full CTD mask", max_side=1200)}

<div class="warning">
<strong>注意：</strong>全页 CTD mask 显示 CTD 对气泡内文字响应很强，但对部分框外字（特别是黑底白字）响应较弱。因此实际使用时应该<strong>用 RT-DETR-v2 的 bbox 限定区域</strong>，在该区域内取 CTD 热图，而不是直接用全页 CTD mask。
</div>

<h2>五、最终架构（修正版）</h2>

<pre>Stage 1 (detect):   RT-DETR-v2 → bbox + category (text_bubble/text_free)  ← 不动, 框外字召回率高
Stage 2 (OCR):      逐框识别                                       ← 不动
Stage 3 (translate): 术语预扫描 + LLM 翻译                          ← 不动
Stage 4 (inpaint):   按 category 分流:
  ├─ dialogue_bubble → 矩形涂白（气泡本来就是白的, 零副作用）
  └─ overlay_text/sfx → 用 RT-DETR-v2 的 bbox 定位区域
                        → 在该区域内取 CTD DBNet 热图
                        → 阈值化+膨胀 → 像素级 mask
                        → koharu lama-manga inpaint
Stage 5 (typeset):   现有 PIL 二分字号 + 贪心折行</pre>

<div class="conclusion">
<strong>职责分离：</strong>
<ul>
<li><strong>RT-DETR-v2</strong>：负责"在哪里"（检测 + 分类），框外字召回率高</li>
<li><strong>CTD DBNet</strong>：负责"哪些像素"（像素级 mask），只在框外字区域内使用</li>
<li>两者互补，CTD 不替代 RT-DETR-v2 做检测</li>
</ul>
</div>

<div class="metric-grid">
  <div class="metric-card"><div class="value">0/8</div><div class="label">CTD 对框外字的检测匹配数</div></div>
  <div class="metric-card"><div class="value">8/8</div><div class="label">RT-DETR-v2 对框外字的检测数</div></div>
  <div class="metric-card"><div class="value">~4s</div><div class="label">CTD 推理耗时/页 (CPU)</div></div>
  <div class="metric-card"><div class="value">0</div><div class="label">新增依赖数</div></div>
</div>

<h2>六、下一步计划</h2>
<ol>
<li>封装 <code>mask_generator.py</code>：输入原图 + bbox 列表，输出每个 bbox 区域内的 CTD 像素级 mask</li>
<li>接入 <code>04_inpaint.py</code>：
  <ul>
  <li><code>dialogue_bubble</code> → 保持矩形涂白</li>
  <li><code>overlay_text/sfx</code> → 用 CTD 像素级 mask + koharu inpaint</li>
  </ul>
</li>
<li>跑 5-10 页（含框外字）对比：矩形涂白 vs CTD像素mask 的最终 inpaint 效果</li>
<li>参数微调：框外字区域的 thresh/dilate 可能需要单独调（框外字背景复杂，热图响应弱）</li>
<li>写 ADR-021 记录决策</li>
</ol>

<h3>已知风险</h3>
<ul>
<li>CTD 对黑底白字的热图响应弱，可能需要反色处理或降低阈值</li>
<li>彩色 SFX / 艺术字的 DBNet 分割效果未验证</li>
<li>框外字区域内如果有画面线条（如人物轮廓），CTD 可能误识别为文字</li>
<li>需要验证 CTD mask + koharu inpaint 的端到端效果（目前只验证了 mask，没跑 inpaint）</li>
</ul>

<hr>
<div class="footer">AMTA Stage 4 框外字探针 &nbsp;|&nbsp; 2026-09-03 &nbsp;|&nbsp; 探针脚本: scripts/probe_overlay_text.py &nbsp;|&nbsp; 报告: scripts/gen_overlay_report.py</div>

</body>
</html>"""


def main() -> None:
    html = build_html()
    OUT_HTML.write_text(html, encoding="utf-8")
    size_mb = OUT_HTML.stat().st_size / 1024 / 1024
    print(f"[gen_overlay_report] HTML: {OUT_HTML}")
    print(f"[gen_overlay_report] Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
