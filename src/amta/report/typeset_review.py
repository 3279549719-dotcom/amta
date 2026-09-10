"""typeset_review — typeset 成品图看图报告（深接口模块）。

`scripts/gen_typeset_review.py` 是本模块的薄 CLI。

2026-09-10 从 `scripts/gen_typeset_review.py` 迁入：该脚本原本把整套 HTML 模板
直接写在 `scripts/` 下，违反 CLAUDE.md「HTML 报告铁律：必须用 `src/amta/report/`
深接口，禁止 scripts/ 下新建独立 HTML 生成脚本」。迁入后 scripts/ 只剩参数解析。
守卫在 `tests/test_typeset_review.py::TestHtmlReportIronLaw`（机械可查，不靠自觉）。

职责边界：本模块**只管渲染**（给一组图片路径 → 写一份自包含 HTML）；
"去哪找图、找不到怎么办"是 CLI 的事。
"""
from __future__ import annotations

import base64
from pathlib import Path

_STYLE = """
body { font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a2e; margin:0; padding:24px; line-height:1.6; }
.container { max-width:1200px; margin:0 auto; }
h1 { font-size:22px; margin-bottom:4px; }
.subtitle { color:#666; font-size:13px; margin-bottom:20px; }
.page-section { background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }
.page-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }
.page-title { font-size:16px; font-weight:700; color:#1e40af; }
.page-meta { font-size:12px; color:#999; }
.img-full { text-align:center; }
.img-full img { max-width:100%; border-radius:8px; border:1px solid #e5e7eb; }
.footer { text-align:center; color:#999; font-size:11px; margin-top:24px; padding:16px; }
"""

_PAGE_TEMPLATE = """
    <div class="page-section">
      <div class="page-header">
        <div class="page-title">{name}</div>
        <div class="page-meta">{size_kb} KB</div>
      </div>
      <div class="img-full">
        <img src="data:image/png;base64,{b64}" alt="{name}" />
      </div>
    </div>"""

_DOC_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{style}</style>
</head>
<body>
<div class="container">
  <h1>{title}</h1>
  <div class="subtitle">{subtitle}</div>
  {sections}
  <div class="footer">amta typeset_review — 自包含 HTML，图片 base64 内嵌</div>
</div>
</body>
</html>"""


def img_to_base64(path: Path) -> str:
    """读图并 base64 编码（自包含 HTML 用）。"""
    return base64.b64encode(path.read_bytes()).decode("ascii")


def render_typeset_review(
    images: list[Path],
    *,
    title: str,
    out_path: Path,
    source: str = "",
) -> Path:
    """把成品图渲染成一份自包含 HTML。

    Args:
        images: 图片路径列表（顺序即显示顺序）。
        title: 报告标题。
        out_path: 输出 HTML 路径（父目录会自动创建）。
        source: 图片来源说明，用于副标题；空则不显示。

    Returns:
        Path: 实际写出的 HTML 路径。
    """
    sections = []
    for img_path in images:
        sections.append(_PAGE_TEMPLATE.format(
            name=img_path.name,
            size_kb=img_path.stat().st_size // 1024,
            b64=img_to_base64(img_path),
        ))

    subtitle = f"共 {len(images)} 张图片"
    if source:
        subtitle += f" ｜ 来源: {source}"

    html = _DOC_TEMPLATE.format(
        title=title,
        style=_STYLE,
        subtitle=subtitle,
        sections="".join(sections),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
