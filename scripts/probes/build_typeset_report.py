"""p31-40 新排版报告：只放新成品图，8 页（刨掉 38/39）。"""
from __future__ import annotations
import base64
from pathlib import Path

ROOT = Path(r"E:\manga translator agent")
WORK = ROOT/"workspace"/"touhou-getten-shinchi"
OUT = ROOT/"output"/"batch-31-40-typeset-report"
OUT.mkdir(exist_ok=True)

PAGES = [31, 32, 33, 34, 35, 36, 37, 40]


def b64(p):
    return "data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode()


rows = []
for pg in PAGES:
    final_p = WORK/"artifacts"/"final"/f"page_{pg}_final.png"
    rows.append(f'<figure><img src="{b64(final_p)}"/><figcaption>p{pg}</figcaption></figure>')

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>p31-40 新排版</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;background:#1a1a1a;color:#eee;margin:20px}}
h1{{font-size:22px}} .sub{{color:#999;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
figure{{margin:0;background:#2a2a2a;padding:8px;border-radius:6px}}
img{{width:100%;display:block;border-radius:4px}}
figcaption{{font-size:14px;margin-top:6px;text-align:center;color:#ccc}}
</style></head><body>
<h1>p31-40 新排版（统一断行）</h1>
<div class="sub">刨掉 38/39（已知待改进），共 8 页</div>
<div class="grid">{''.join(rows)}</div>
</body></html>"""

outp = OUT/"report.html"
outp.write_text(html, encoding="utf-8")
print(outp)
