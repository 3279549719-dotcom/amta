"""生成 inpaint 修复对比报告：3列横排（原图 | 旧版V1 | 新版textink），3页。"""
from __future__ import annotations
import base64, sys
from pathlib import Path
ROOT = Path(r"E:\manga translator agent")
SRC = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")
WORK = ROOT/"workspace"/"touhou-getten-shinchi"
V1 = ROOT/"output"/"inpaint-compare"/"V1_current"
OUT = ROOT/"output"/"inpaint-report"
OUT.mkdir(exist_ok=True)

PAGES = [16, 21, 29]


def b64(p):
    return "data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode()


rows = []
for pg in PAGES:
    raw_p = SRC/f"{pg}.jpg"
    v1_p = V1/f"page_{pg}_final.png"
    new_p = WORK/"artifacts"/"final"/f"page_{pg}_final.png"
    cells = []
    for label, p in [("原图 raw", raw_p), ("旧版 V1（黑发洗灰）", v1_p), ("新版 textink（黑发保住）", new_p)]:
        cells.append(f'<figure><img src="{b64(p)}"/><figcaption>p{pg} · {label}</figcaption></figure>')
    rows.append('<div class="row">' + "".join(cells) + "</div>")

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>inpaint 修复对比</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;background:#1a1a1a;color:#eee;margin:20px}}
h1{{font-size:22px}} .sub{{color:#999;margin-bottom:20px}}
.row{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:24px}}
figure{{margin:0;background:#2a2a2a;padding:8px;border-radius:6px}}
img{{width:100%;display:block;border-radius:4px}}
figcaption{{font-size:13px;margin-top:6px;text-align:center;color:#ccc}}
.bad{{border:2px solid #e74c3c}} .good{{border:2px solid #2ecc71}}
</style></head><body>
<h1>AMTA inpaint 修复对比报告</h1>
<div class="sub">左：原图 ｜ 中：旧版实心矩形 mask（纯黑发洗成灰）｜ 右：新版文字墨迹 mask（只擦文字像素，保住原画）</div>
{''.join(rows)}
</body></html>"""

outp = OUT/"report.html"
outp.write_text(html, encoding="utf-8")
print(outp)
