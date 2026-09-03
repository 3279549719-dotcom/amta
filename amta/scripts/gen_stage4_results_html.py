"""生成 Stage 4 框外字去除方案验证结果 HTML 页面。

把所有对比图转 base64 嵌入, 整合量化数据, 生成自包含 HTML。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(r"E:\manga translator agent\amta")
OUT_DIR = ROOT / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

REFINE_DIR = ROOT / "output" / "tmp" / "refine_mask_probe"
INPAINT_DIR = ROOT / "output" / "tmp" / "inpaint_mask_compare"
AOT_DIR = ROOT / "output" / "tmp" / "refined_aot_compare"


def img_to_base64(path: Path, max_width: int = 1200) -> str:
    """图片转 base64, 可选缩小。"""
    from PIL import Image
    import io
    img = Image.open(path)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    print("[gen_html] Loading data...")
    refine_summary = load_json(REFINE_DIR / "summary.json")
    inpaint_summary = load_json(INPAINT_DIR / "summary.json")

    print("[gen_html] Converting images to base64...")
    images = {
        "mask_p11": img_to_base64(REFINE_DIR / "page_11_comparison.png"),
        "mask_p12": img_to_base64(REFINE_DIR / "page_12_comparison.png"),
        "inpaint_p11": img_to_base64(INPAINT_DIR / "page_11_comparison.png"),
        "inpaint_p12": img_to_base64(INPAINT_DIR / "page_12_comparison.png"),
        "engine_p11": img_to_base64(AOT_DIR / "page_11_comparison.png"),
    }
    print(f"  images loaded: {len(images)}")

    # 计算 inpaint 改动减少比例
    for page in ["page_11", "page_12"]:
        s = inpaint_summary[page]
        s["diff_reduction_pct"] = round(
            (1 - s["refined_pixel_diff"] / s["rect_pixel_diff"]) * 100, 1)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stage 4 框外字去除方案验证结果</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; color: #1a1a2e; line-height: 1.6; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 28px; margin-bottom: 8px; color: #1a1a2e; }}
  .subtitle {{ color: #666; margin-bottom: 32px; font-size: 14px; }}
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-left: 8px; }}
  .badge-pass {{ background: #d4edda; color: #155724; }}
  .badge-skip {{ background: #fff3cd; color: #856404; }}
  .badge-fail {{ background: #f8d7da; color: #721c24; }}

  .section {{ background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .section h2 {{ font-size: 20px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 2px solid #e8ecf1; }}
  .section h3 {{ font-size: 16px; margin: 20px 0 12px; color: #2c3e50; }}

  /* 概览卡片 */
  .overview-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; border-radius: 10px; padding: 20px; }}
  .card.green {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }}
  .card.orange {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }}
  .card.blue {{ background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }}
  .card .label {{ font-size: 13px; opacity: 0.9; margin-bottom: 4px; }}
  .card .value {{ font-size: 32px; font-weight: 700; }}
  .card .unit {{ font-size: 14px; opacity: 0.8; }}

  /* 表格 */
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; }}
  th {{ background: #f0f2f5; padding: 10px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #d0d5dd; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #e8ecf1; }}
  tr:hover {{ background: #f8f9fb; }}
  .highlight {{ background: #e8f5e9; font-weight: 600; color: #1b5e20; }}
  .num {{ font-family: "SF Mono", "Consolas", monospace; }}

  /* 图片 */
  .img-container {{ margin: 16px 0; text-align: center; }}
  .img-container img {{ max-width: 100%; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  .img-caption {{ font-size: 13px; color: #666; margin-top: 8px; }}

  /* 方案状态 */
  .plan-status {{ display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }}
  .plan-item {{ flex: 1; min-width: 280px; border: 2px solid #e8ecf1; border-radius: 10px; padding: 16px; }}
  .plan-item.done {{ border-color: #38ef7d; background: #f0fdf4; }}
  .plan-item.assessed {{ border-color: #fbbf24; background: #fffbeb; }}
  .plan-item h4 {{ font-size: 15px; margin-bottom: 8px; }}
  .plan-item p {{ font-size: 13px; color: #555; }}

  /* 结论 */
  .conclusion {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; border-radius: 12px; padding: 28px; margin-top: 24px; }}
  .conclusion h2 {{ color: #fff; border-bottom-color: rgba(255,255,255,0.2); }}
  .conclusion li {{ margin-bottom: 8px; }}
  .conclusion strong {{ color: #38ef7d; }}

  .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 32px; padding: 16px; }}
</style>
</head>
<body>
<div class="container">

  <h1>Stage 4 框外字去除方案验证结果</h1>
  <p class="subtitle">分支: feat/stage4-outside-text-removal @ b0121e9 &nbsp;|&nbsp; 日期: 2026-09-03 &nbsp;|&nbsp; 样本: 东方Project 单翼停留之地 page_11 / page_12</p>

  <!-- 概览 -->
  <div class="overview-grid">
    <div class="card green">
      <div class="label">Mask 像素减少</div>
      <div class="value">74%<span class="unit">+</span></div>
    </div>
    <div class="card blue">
      <div class="label">Inpaint 背景改动减少</div>
      <div class="value">51-71<span class="unit">%</span></div>
    </div>
    <div class="card orange">
      <div class="label">精修 mask 计算耗时</div>
      <div class="value">&lt;0.1<span class="unit">s/框</span></div>
    </div>
    <div class="card">
      <div class="label">新模型依赖</div>
      <div class="value">0<span class="unit">个</span></div>
    </div>
  </div>

  <!-- 方案状态 -->
  <div class="section">
    <h2>方案执行状态</h2>
    <div class="plan-status">
      <div class="plan-item done">
        <h4>方案 A: 框内传统方法精修 mask <span class="badge badge-pass">已验证通过</span></h4>
        <p>移植 BallonsTranslator + comic-translate 生产级算法（Otsu + 颜色直方图 + 连通域过滤），在每个 text_free 框内精修像素级 mask。零新模型、零新依赖。</p>
      </div>
      <div class="plan-item assessed">
        <h4>方案 B: SAM 框提示分割 <span class="badge badge-skip">仅评估, 未执行</span></h4>
        <p>SAM 未安装、本地无模型权重（需下载 375MB-1.2GB），CPU 推理较慢。作为方案 A 处理不了极端 case 时的升级路径。</p>
      </div>
      <div class="plan-item assessed">
        <h4>方案 C: lama_large_512px 动漫 inpaint <span class="badge badge-skip">仅评估, 未执行</span></h4>
        <p>需从 HuggingFace 下载 ~800MB 模型 + 移植 BallonsTranslator 加载代码。方案 A 已证明 mask 精度比换 inpaint 引擎收益更大，作为长期优化方向。</p>
      </div>
    </div>
  </div>

  <!-- 方案 A: Mask 精度对比 -->
  <div class="section">
    <h2>方案 A: Mask 精度对比</h2>
    <p>矩形 mask（当前方案）把整个框都标记为"要修复"，包含 60-70% 的空白/背景。精修 mask 只圈出真正的文字像素。</p>

    <table>
      <thead>
        <tr>
          <th>页面</th>
          <th>text_free 框数</th>
          <th>矩形 mask 像素</th>
          <th>精修 mask 像素</th>
          <th>减少比例</th>
          <th>矩形覆盖率</th>
          <th>精修覆盖率</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>page_11</td>
          <td class="num">{refine_summary['page_11']['free_boxes']}</td>
          <td class="num">{refine_summary['page_11']['rect_pixels']:,}</td>
          <td class="num highlight">{refine_summary['page_11']['refined_pixels']:,}</td>
          <td class="num highlight">{refine_summary['page_11']['reduction_pct']}%</td>
          <td class="num">{refine_summary['page_11']['rect_ratio']}%</td>
          <td class="num highlight">{refine_summary['page_11']['refined_ratio']}%</td>
        </tr>
        <tr>
          <td>page_12</td>
          <td class="num">{refine_summary['page_12']['free_boxes']}</td>
          <td class="num">{refine_summary['page_12']['rect_pixels']:,}</td>
          <td class="num highlight">{refine_summary['page_12']['refined_pixels']:,}</td>
          <td class="num highlight">{refine_summary['page_12']['reduction_pct']}%</td>
          <td class="num">{refine_summary['page_12']['rect_ratio']}%</td>
          <td class="num highlight">{refine_summary['page_12']['refined_ratio']}%</td>
        </tr>
      </tbody>
    </table>

    <h3>page_11 Mask 对比（1 个 text_free 框，人物头顶文字）</h3>
    <div class="img-container">
      <img src="data:image/jpeg;base64,{images['mask_p11']}" alt="page_11 mask comparison">
      <p class="img-caption">2×2 对比: 原图 / 矩形 mask(红) / 精修 mask(蓝) / 差异图。精修 mask 只圈文字像素，完全不碰背景。</p>
    </div>

    <h3>page_12 Mask 对比（3 个 text_free 框，含竖排文字+SFX）</h3>
    <div class="img-container">
      <img src="data:image/jpeg;base64,{images['mask_p12']}" alt="page_12 mask comparison">
      <p class="img-caption">3 个框的精修效果：左上角框外字在人物头发上，精修 mask 精确圈出文字不碰头发。</p>
    </div>
  </div>

  <!-- 方案 A: Inpaint 效果对比 -->
  <div class="section">
    <h2>方案 A: Inpaint 实际效果对比（lama-manga 引擎）</h2>
    <p>pixel_diff = inpaint 后与原图的像素差异比例，越小说明背景改动越精确。</p>

    <table>
      <thead>
        <tr>
          <th>页面</th>
          <th>矩形 mask pixel_diff</th>
          <th>精修 mask pixel_diff</th>
          <th>背景改动减少</th>
          <th>矩形耗时</th>
          <th>精修耗时</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>page_11</td>
          <td class="num">{inpaint_summary['page_11']['rect_pixel_diff']*100:.2f}%</td>
          <td class="num highlight">{inpaint_summary['page_11']['refined_pixel_diff']*100:.2f}%</td>
          <td class="num highlight">{inpaint_summary['page_11']['diff_reduction_pct']}%</td>
          <td class="num">{inpaint_summary['page_11']['rect_time']:.1f}s</td>
          <td class="num">{inpaint_summary['page_11']['refined_time']:.1f}s</td>
        </tr>
        <tr>
          <td>page_12</td>
          <td class="num">{inpaint_summary['page_12']['rect_pixel_diff']*100:.2f}%</td>
          <td class="num highlight">{inpaint_summary['page_12']['refined_pixel_diff']*100:.2f}%</td>
          <td class="num highlight">{inpaint_summary['page_12']['diff_reduction_pct']}%</td>
          <td class="num">{inpaint_summary['page_12']['rect_time']:.1f}s</td>
          <td class="num">{inpaint_summary['page_12']['refined_time']:.1f}s</td>
        </tr>
      </tbody>
    </table>

    <h3>page_11 Inpaint 效果对比</h3>
    <div class="img-container">
      <img src="data:image/jpeg;base64,{images['inpaint_p11']}" alt="page_11 inpaint comparison">
      <p class="img-caption">1×3 对比: 原图 / 矩形 mask inpaint(留模糊斑) / 精修 mask inpaint(自然)。精修 mask 后实验台背景几乎看不到修复痕迹。</p>
    </div>

    <h3>page_12 Inpaint 效果对比（关键样本：文字在头发上）</h3>
    <div class="img-container">
      <img src="data:image/jpeg;base64,{images['inpaint_p12']}" alt="page_12 inpaint comparison">
      <p class="img-caption">左上角框外字在人物头发上：矩形 mask inpaint 后头发细节被破坏，留下模糊斑块；精修 mask inpaint 后头发细节完全保持，背景修复自然。</p>
    </div>
  </div>

  <!-- Inpaint 引擎对比 -->
  <div class="section">
    <h2>精修 mask 下 Inpaint 引擎对比（page_11）</h2>
    <p>关键洞察：<strong>mask 精度比 inpaint 引擎更重要</strong>。一旦 mask 精确了，lama-manga 和 aot-inpainting 都能给出不错的效果。</p>

    <table>
      <thead>
        <tr>
          <th>引擎</th>
          <th>耗时</th>
          <th>效果</th>
          <th>备注</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>lama-manga</td>
          <td class="num">30.7s</td>
          <td class="highlight">好</td>
          <td>当前默认引擎，动漫场景优化</td>
        </tr>
        <tr>
          <td>aot-inpainting</td>
          <td class="num">25.5s</td>
          <td class="highlight">好</td>
          <td>略快，AOT 算法对纹理修复好</td>
        </tr>
      </tbody>
    </table>

    <div class="img-container">
      <img src="data:image/jpeg;base64,{images['engine_p11']}" alt="engine comparison">
      <p class="img-caption">1×3 对比: 原图 / 精修 mask + lama-manga / 精修 mask + aot-inpainting。两者效果都不错，aot 略快。</p>
    </div>
  </div>

  <!-- 已验证做不通的方向 -->
  <div class="section">
    <h2>已验证做不通的方向（避免重复踩坑）</h2>
    <table>
      <thead>
        <tr>
          <th>方向</th>
          <th>结果</th>
          <th>原因</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>CTD DBNet 全页像素 mask</td>
          <td><span class="badge badge-fail">失败</span></td>
          <td>对框外字零响应（max=0.0005~0.0014），只训练了气泡内黑字白底</td>
        </tr>
        <tr>
          <td>comic-text-detector-seg</td>
          <td><span class="badge badge-fail">失败</span></td>
          <td>输出全黑，对框外字零响应</td>
        </tr>
        <tr>
          <td>矩形 mask + lama-manga</td>
          <td><span class="badge badge-fail">不理想</span></td>
          <td>矩形把 60-70% 空白/背景也标记为"要修复"，inpaint 负担过重，留模糊斑块</td>
        </tr>
        <tr>
          <td>矩形 mask + aot-inpainting</td>
          <td><span class="badge badge-fail">不理想</span></td>
          <td>同上，mask 精度问题不是引擎能解决的</td>
        </tr>
        <tr>
          <td>flux2-klein 整页扩散</td>
          <td><span class="badge badge-fail">太慢</span></td>
          <td>10 分钟未完成，CPU 模式下不可用</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- 结论 -->
  <div class="conclusion">
    <h2>核心结论与建议</h2>
    <ul>
      <li><strong>方向错误是最大的浪费</strong>：之前追求"全页像素级分割模型"是错的，所有专用模型都只训练了气泡内文字。检测框已经够用了。</li>
      <li><strong>方案 A 是立即可用的答案</strong>：框内传统方法精修 mask，零新模型、零风险，mask 像素减少 74%，inpaint 背景改动减少 51-71%，视觉效果显著提升。</li>
      <li><strong>mask 精度 > inpaint 引擎</strong>：一旦 mask 精确了，lama-manga 和 aot-inpainting 都能给出不错的效果。换引擎的收益远小于提升 mask 精度。</li>
      <li><strong>建议执行路径</strong>：① 把 --refine-mask 默认开启 → ② 跑 10-20 页端到端验证鲁棒性 → ③ 发现处理不了的 case 再上 SAM（方案 B）→ ④ 长期考虑换 lama_large_512px（方案 C）。</li>
    </ul>
  </div>

  <div class="footer">
    AMTA Stage 4 框外字去除方案验证 &nbsp;|&nbsp; 2026-09-03 &nbsp;|&nbsp; 分支 feat/stage4-outside-text-removal @ b0121e9
  </div>

</div>
</body>
</html>"""

    out_path = OUT_DIR / "stage4-outside-text-removal-results.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"[gen_html] Saved: {out_path}")
    print(f"  size: {out_path.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()