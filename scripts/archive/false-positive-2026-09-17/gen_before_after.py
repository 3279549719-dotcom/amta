"""生成新旧对比报告：假阳性修复前后。"""
from __future__ import annotations

import base64
import os
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
import amta  # noqa: E402,F401  # UTF-8 stdout choke point


def img_to_b64(path: str, max_width: int = 800) -> str:
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
    manga = "touhou-getten-shinchi"
    ws = Path(f"workspace/{manga}/artifacts/final")

    # 新跑的覆盖了旧的，直接展示新的成品图
    pages = [3, 5, 10]
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>假阳性修复后成品图</title>
<style>
  body { font-family: -apple-system, sans-serif; background: #f5f5f7; padding: 20px; }
  h1 { text-align: center; margin-bottom: 8px; }
  .subtitle { text-align: center; color: #666; margin-bottom: 32px; }
  .case { max-width: 900px; margin: 0 auto 40px; background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
  .case-title { font-size: 18px; font-weight: 600; margin-bottom: 12px; }
  .case img { width: 100%; border-radius: 8px; }
  .note { background: #e8f5e9; border-left: 4px solid #4caf50; padding: 12px 16px; border-radius: 0 8px 8px 0; margin-top: 12px; font-size: 14px; line-height: 1.6; }
</style>
</head>
<body>
<h1>假阳性修复后成品图</h1>
<p class="subtitle">改动：1) translate prompt 加纯标点条款  2) inpaint 只擦有译文的框</p>
"""

    notes = {
        3: "中间那个大空白气泡：之前被 OCR 过滤了（conf 太低），但 inpaint 还是把它擦了。现在 inpaint 只擦 canon 里的框，这个大气泡不会再被误擦了。",
        5: "中间偏右黑色小气泡：之前是短省略号，被走了全流程。现在 LLM 输出空译文，inpaint 不擦了，typeset 不写了。",
        10: "右下角黑色大三角气泡：之前是 48 个点的长省略号，被走了全流程。现在 LLM 输出空译文，inpaint 不擦了，typeset 不写了。",
    }

    for p in pages:
        img_b64 = img_to_b64(str(ws / f"page_{p}_final.png"))
        html += f"""
<div class="case">
  <div class="case-title">Page {p}</div>
  <img src="data:image/png;base64,{img_b64}" alt="page_{p}">
  <div class="note">{notes[p]}</div>
</div>
"""

    html += "</body></html>"

    out = Path("output/false-positive-fixed.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    size = out.stat().st_size / 1024
    print(f"生成完成: {out} ({size:.0f} KB)")


if __name__ == "__main__":
    main()
