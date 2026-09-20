"""p31-40 报告：每页 原图 | 成品图，共 20 张。"""
from __future__ import annotations
import base64
from pathlib import Path

ROOT = Path(r"E:\manga translator agent")
SRC = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")
WORK = ROOT/"workspace"/"touhou-getten-shinchi"
OUT = ROOT/"output"/"batch-31-40-report"
OUT.mkdir(exist_ok=True)

PAGES = list(range(31, 41))


def b64(p):
    return "data:image/jpeg;base64," + base64.b64encode(Path(p).read_bytes()).decode()


rows = []
for pg in PAGES:
    raw_p = SRC/f"{pg}.jpg"
    final_p = WORK/"artifacts"/"final"/f"page_{pg}_final.png"
    cells = []
    for label, p in [("原图", raw_p), ("成品", final_p)]:
        cells.append(f'<figure><img src="{b64(p)}"/><figcaption>p{pg} · {label}</figcaption></figure>')
    rows.append('<div class="row">' + "".join(cells) + "</div>")

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>p31-40 成品报告</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;background:#1a1a1a;color:#eee;margin:20px}}
h1{{font-size:22px}} .sub{{color:#999;margin-bottom:20px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:24px}}
figure{{margin:0;background:#2a2a2a;padding:8px;border-radius:6px}}
img{{width:100%;display:block;border-radius:4px}}
figcaption{{font-size:13px;margin-top:6px;text-align:center;color:#ccc}}
</style></head><body>
<h1>月天新地 p31-40 成品报告</h1>
<div class="sub">左：原图 ｜ 右：成品（中文排版后）</div>
{''.join(rows)}
</body></html>"""

outp = OUT/"report.html"
outp.write_text(html, encoding="utf-8")
print(outp)
