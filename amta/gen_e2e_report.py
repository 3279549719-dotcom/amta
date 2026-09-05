"""生成多页合并 HTML 报告（pages 11-15, 全5阶段）。

每页布局：
  三图并列：原图 | inpaint后(clean) | typeset后(final)
  下方：跨阶段处理步骤表格 + 统计卡片
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from amta.paths import ROOT  # noqa: E402
from amta.report.assembler import load_from_workspace  # noqa: E402
from amta.report.engine import render_report  # noqa: E402

WORK_ID = "touhou-e2e-orchestrator"
SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
PAGES = list(range(11, 16))
OUT = Path(__file__).resolve().parent / "output" / "e2e-orchestrator-report.html"
ART_DIR = ROOT / "workspace" / WORK_ID / "artifacts"


def img_to_base64(path: Path) -> str:
    if not path.exists():
        return ""
    return base64.b64encode(path.read_bytes()).decode("ascii")


def extract_parts(html: str) -> tuple[str, str]:
    """从单页 HTML 提取 <style> 和 <body> 内容。"""
    style_m = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    body_m = re.search(r"<body>(.*?)</body>", html, re.DOTALL)
    style = style_m.group(1) if style_m else ""
    body = body_m.group(1) if body_m else ""
    return style, body


def build_triple_image(idx: int) -> str:
    """三图并列：原图 | clean | final。"""
    raw_b64 = img_to_base64(SRC_DIR / f"{idx}.jpg")
    clean_b64 = img_to_base64(ART_DIR / "clean" / f"page_{idx}_clean.png")
    final_b64 = img_to_base64(ART_DIR / "final" / f"page_{idx}_final.png")

    def panel(label: str, b64: str, note: str = "") -> str:
        if not b64:
            return f'<div class="img-panel-slot"><div class="img-label">{label}</div><div class="img-missing">（无图）</div></div>'
        return f'''<div class="img-panel-slot">
      <div class="img-label">{label}</div>
      <img src="data:image/jpeg;base64,{b64}" alt="{label}" loading="lazy">
      {f'<div class="img-note">{note}</div>' if note else ''}
    </div>'''

    return f'''<div class="triple-image">
    {panel("原图 (raw)", raw_b64)}
    {panel("Inpaint 后 (clean)", clean_b64, "日文已擦除，背景已修补")}
    {panel("Typeset 后 (final)", final_b64, "中文译文已嵌入")}
  </div>'''


def main() -> None:
    pages_html = []
    css = ""
    summary = []

    for idx in PAGES:
        print(f"Rendering page {idx}...")
        page_report = load_from_workspace(WORK_ID, idx, SRC_DIR)
        result = render_report(page_report)
        style, body = extract_parts(result.html)
        if not css:
            css = style

        triple = build_triple_image(idx)

        # 在原有 body 内容前插入三图对比
        page_html = f'''<section id="page-{idx}" class="page-section-wrapper">
    <h2 class="page-title-h2">第 {idx} 页</h2>
    {triple}
    <div class="detail-section">
      <h3 class="detail-title">跨阶段处理详情</h3>
      {body}
    </div>
  </section>'''

        pages_html.append(page_html)
        summary.append({
            "page": idx,
            "stages": result.stages_rendered,
            "regions": result.regions_total,
            "aligned": result.regions_aligned,
            "warnings": len(result.warnings),
        })
        print(f"  stages={result.stages_rendered} regions={result.regions_total} "
              f"aligned={result.regions_aligned} warnings={len(result.warnings)}")

    nav = " ".join(
        f'<a href="#page-{s["page"]}" class="nav-link">第{s["page"]}页 '
        f'({s["aligned"]}/{s["regions"]}对齐)</a>'
        for s in summary
    )

    summary_rows = "".join(
        f"<tr><td>第{s['page']}页</td><td>{', '.join(s['stages'])}</td>"
        f"<td>{s['regions']}</td><td>{s['aligned']}</td><td>{s['warnings']}</td></tr>"
        for s in summary
    )

    extra_css = """
.nav-bar { position: sticky; top: 0; background: #1a1a2e; padding: 12px 20px; z-index: 100; display: flex; gap: 16px; flex-wrap: wrap; }
.nav-link { color: #e0e0e0; text-decoration: none; font-size: 14px; padding: 4px 10px; border-radius: 4px; background: #16213e; }
.nav-link:hover { background: #0f3460; }
.summary-table { width: 100%; border-collapse: collapse; margin: 20px 0; }
.summary-table th, .summary-table td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
.summary-table th { background: #f0f0f0; }
.page-section-wrapper { margin-bottom: 50px; border-bottom: 3px solid #eee; padding-bottom: 30px; }
.page-title-h2 { font-size: 22px; color: #1a1a2e; margin: 30px 0 16px; border-left: 4px solid #0f3460; padding-left: 12px; }
.triple-image { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.img-panel-slot { flex: 1; min-width: 280px; background: #f8f9fa; border-radius: 8px; padding: 12px; text-align: center; }
.img-label { font-weight: 600; font-size: 14px; color: #333; margin-bottom: 8px; }
.img-panel-slot img { max-width: 100%; height: auto; border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.img-note { font-size: 12px; color: #666; margin-top: 6px; }
.img-missing { color: #999; font-size: 13px; padding: 40px 0; }
.detail-section { background: #fafbfc; border-radius: 8px; padding: 16px; }
.detail-title { font-size: 16px; color: #444; margin: 0 0 12px; }
"""

    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Orchestrator 端到端验证报告 — pages 11-15</title>
<style>
{css}
{extra_css}
</style>
</head>
<body>
<div class="nav-bar">
  <strong style="color:#fff;">Orchestrator 端到端验证 (11-15)</strong>
  {nav}
</div>
<div class="container" style="max-width:1600px;margin:0 auto;padding:20px;">
  <h1>Orchestrator 全阶段端到端验证报告</h1>
  <p>工作区: <code>{WORK_ID}</code> | 页面: 11-15 | 阶段: detect → ocr → translate → inpaint → typeset</p>
  <p style="color:#666;font-size:14px;">每页上方为三图对比（原图 / inpaint擦除后 / typeset嵌入后），下方为跨阶段处理步骤表格。</p>
  <table class="summary-table">
    <thead><tr><th>页面</th><th>渲染阶段</th><th>区域总数</th><th>全阶段对齐</th><th>警告数</th></tr></thead>
    <tbody>{summary_rows}</tbody>
  </table>
  {''.join(pages_html)}
</div>
</body>
</html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(full_html, encoding="utf-8")
    print(f"\nReport written to: {OUT}")
    print(f"Size: {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
