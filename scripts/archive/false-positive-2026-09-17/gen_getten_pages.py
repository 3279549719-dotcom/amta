"""生成月天 p2-p5 成品图对比页面。"""
from __future__ import annotations

import base64
import os
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
import amta  # noqa: E402,F401  # UTF-8 stdout choke point


def img_to_b64(path: str, max_width: int = 900) -> str:
    img = Image.open(path)
    w, h = img.size
    if w > max_width:
        ratio = max_width / w
        new_h = int(h * ratio)
        img = img.resize((max_width, new_h), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def main() -> None:
    pages = [2, 3, 4, 5]
    ws = Path("workspace/touhou-getten-shinchi/artifacts/final")

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>月天新地 p2-p5 成品图</title>
<style>
  body { font-family: -apple-system, sans-serif; background: #f5f5f7; padding: 20px; }
  h1 { text-align: center; margin-bottom: 24px; }
  .page { max-width: 900px; margin: 0 auto 40px; background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
  .page-title { font-size: 18px; font-weight: 600; margin-bottom: 12px; }
  .page img { width: 100%; border-radius: 8px; }
</style>
</head>
<body>
<h1>月天新地 成品图 p2-p5</h1>
"""

    for p in pages:
        img_b64 = img_to_b64(str(ws / f"page_{p}_final.png"))
        html += f"""
<div class="page">
  <div class="page-title">Page {p}</div>
  <img src="data:image/png;base64,{img_b64}" alt="page_{p}">
</div>
"""

    html += "</body></html>"

    out = Path("output/getten-p2-p5.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    size = out.stat().st_size / 1024
    print(f"生成完成: {out} ({size:.0f} KB)")


if __name__ == "__main__":
    main()
