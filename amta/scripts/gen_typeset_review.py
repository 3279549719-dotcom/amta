"""gen_typeset_review — typeset 成品图看图报告生成器。

把指定目录下的 final 渲染图内嵌进自包含 HTML，方便在线查看。
用法: python scripts/gen_typeset_review.py --input-dir <dir> --pattern "page_*_final.png" --out <output.html> --title "标题"
"""
from __future__ import annotations

import argparse
import base64
from pathlib import Path


def img_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def main() -> int:
    ap = argparse.ArgumentParser(description="typeset 成品图看图报告")
    ap.add_argument("--input-dir", required=True, type=Path, help="成品图目录")
    ap.add_argument("--pattern", default="page_*_final.png", help="文件名匹配模式")
    ap.add_argument("--out", required=True, type=Path, help="输出 HTML 路径")
    ap.add_argument("--title", default="Typeset 成品图审查", help="报告标题")
    a = ap.parse_args()

    images = sorted(a.input_dir.glob(a.pattern))
    if not images:
        print(f"[gen_typeset_review] 未找到匹配 {a.pattern} 的图片")
        return 1

    print(f"[gen_typeset_review] 找到 {len(images)} 张图片")

    img_sections = []
    for img_path in images:
        b64 = img_to_base64(img_path)
        size_kb = img_path.stat().st_size // 1024
        img_sections.append(f"""
    <div class="page-section">
      <div class="page-header">
        <div class="page-title">{img_path.name}</div>
        <div class="page-meta">{size_kb} KB</div>
      </div>
      <div class="img-full">
        <img src="data:image/png;base64,{b64}" alt="{img_path.name}" />
      </div>
    </div>""")
        print(f"  - {img_path.name} ({size_kb} KB)")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{a.title}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a2e; margin:0; padding:24px; line-height:1.6; }}
.container {{ max-width:1200px; margin:0 auto; }}
h1 {{ font-size:22px; margin-bottom:4px; }}
.subtitle {{ color:#666; font-size:13px; margin-bottom:20px; }}
.page-section {{ background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }}
.page-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }}
.page-title {{ font-size:16px; font-weight:700; color:#1e40af; }}
.page-meta {{ font-size:12px; color:#999; }}
.img-full {{ text-align:center; }}
.img-full img {{ max-width:100%; border-radius:8px; border:1px solid #e5e7eb; }}
.footer {{ text-align:center; color:#999; font-size:11px; margin-top:24px; padding:16px; }}
</style>
</head>
<body>
<div class="container">
  <h1>{a.title}</h1>
  <div class="subtitle">共 {len(images)} 张图片 ｜ 来源: {a.input_dir}</div>
  {''.join(img_sections)}
  <div class="footer">amta gen_typeset_review — 自包含 HTML，图片 base64 内嵌</div>
</div>
</body>
</html>"""

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(html, encoding="utf-8")
    print(f"[gen_typeset_review] 报告 -> {a.out} ({a.out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
