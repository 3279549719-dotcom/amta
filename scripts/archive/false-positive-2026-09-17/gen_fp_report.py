"""生成假阳性案例对比报告 HTML。"""
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
    ws = Path("workspace")

    cases = [
        {
            "title": "案例1：背景大字「蓬莱」被当对话翻译",
            "manga": "单翼停留之地 touhou-single-wing",
            "page": "Page 12",
            "clean": img_to_b64(str(ws / "touhou-single-wing/artifacts/clean/page_12_clean.png")),
            "final": img_to_b64(str(ws / "touhou-single-wing/artifacts/final/page_12_final.png")),
            "note": "左下角竖框：本来是背景门牌/招牌字「蓬莱」，不该翻译。结果 detect 框进来 → OCR 读出来 → LLM 翻译成中文 → inpaint 擦掉原文 → typeset 写上中文「蓬莱」。avg_conf 0.97，OCR 读得很准——问题不在 OCR，在 detect 多管闲事。",
        },
        {
            "title": "案例2：长省略号（48个点）被走全流程",
            "manga": "月天新地 touhou-getten-shinchi",
            "page": "Page 10",
            "clean": img_to_b64(str(ws / "touhou-getten-shinchi/artifacts/clean/page_10_clean.png")),
            "final": img_to_b64(str(ws / "touhou-getten-shinchi/artifacts/final/page_10_final.png")),
            "note": "右下角黑色气泡：一排省略号表示沉默，不是台词。结果 detect 框了它 → OCR 读成48个句点 → LLM 原样吐回 → inpaint 擦了原文 → typeset 画了48个点。读者看到一排点被换了位置。",
        },
        {
            "title": "案例3：短省略号（12个点）被走全流程",
            "manga": "月天新地 touhou-getten-shinchi",
            "page": "Page 5",
            "clean": img_to_b64(str(ws / "touhou-getten-shinchi/artifacts/clean/page_5_clean.png")),
            "final": img_to_b64(str(ws / "touhou-getten-shinchi/artifacts/final/page_5_final.png")),
            "note": "中间偏右黑色小气泡：短省略号。LLM 还算聪明转成了中文省略号，但这个框本来就不该进翻译流程。",
        },
    ]

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>AMTA 假阳性案例对比报告</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f7; color: #1d1d1f; padding: 24px; }
  .header { max-width: 1400px; margin: 0 auto 32px; text-align: center; }
  .header h1 { font-size: 28px; margin-bottom: 8px; }
  .header p { color: #6e6e73; font-size: 15px; }
  .case { max-width: 1400px; margin: 0 auto 48px; background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
  .case-title { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
  .case-meta { font-size: 13px; color: #6e6e73; margin-bottom: 16px; }
  .compare { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  .col { text-align: center; }
  .col-label { font-size: 13px; font-weight: 600; margin-bottom: 8px; padding: 4px 12px; border-radius: 6px; display: inline-block; }
  .col-clean .col-label { background: #e8f0fe; color: #1a73e8; }
  .col-final .col-label { background: #fce8e6; color: #d93025; }
  .col img { width: 100%; border-radius: 8px; border: 1px solid #e5e5ea; }
  .note { background: #fff8e1; border-left: 4px solid #ffc107; padding: 12px 16px; border-radius: 0 8px 8px 0; font-size: 14px; line-height: 1.6; }
  .note strong { color: #e65100; }
</style>
</head>
<body>
<div class="header">
  <h1>AMTA 假阳性案例对比报告</h1>
  <p>False Positive：图本来没问题，不该动，结果流水线多管闲事给改了</p>
</div>
"""

    for c in cases:
        html += f"""
<div class="case">
  <div class="case-title">{c['title']}</div>
  <div class="case-meta">{c['manga']} ｜ {c['page']}</div>
  <div class="compare">
    <div class="col col-clean">
      <div class="col-label">Clean（擦字后 / 底图）</div>
      <img src="data:image/png;base64,{c['clean']}" alt="clean">
    </div>
    <div class="col col-final">
      <div class="col-label">Final（成品图 / 写了中文）</div>
      <img src="data:image/png;base64,{c['final']}" alt="final">
    </div>
  </div>
  <div class="note"><strong>问题：</strong>{c['note']}</div>
</div>
"""

    html += """
<div class="header" style="margin-top: 48px;">
  <p>对比维度：左图 = 擦完字的干净底图，右图 = 最终成品图（写了中文）<br>
  如果右图里多出来的中文，在漫画语境里不该出现——那就是假阳性。</p>
</div>
</body>
</html>"""

    out = Path("output/false-positive-compare.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    size = out.stat().st_size / 1024
    print(f"报告生成完成: {out} ({size:.0f} KB)")


if __name__ == "__main__":
    main()
