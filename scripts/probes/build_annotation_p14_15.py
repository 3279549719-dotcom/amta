"""一次性探针：为 p14/p15 生成「原图裁切 + OCR + 机翻 + 人工改译框」标注 HTML。

用途：导演人工标注翻译问题。输出自包含 HTML（图片 base64 内嵌），可直接 share_file 上传。
产出：output/annotation_p14_15.html
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(r"E:\manga translator agent")
WORK = ROOT / "workspace" / "touhou-p17-20-e2e"
PAGES = {
    14: ROOT / "output" / "data" / "ocr_compare_html" / "14.jpg",
    15: ROOT / "output" / "data" / "ocr_compare_html" / "15.jpg",
}
PAD = 20  # 裁切外扩像素
OUT = ROOT / "output" / "annotation_p14_15.html"


def b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def build_page(page_num: int, img_path: Path) -> str:
    canon = load_json(WORK / "artifacts" / "canon" / f"page_{page_num}.json")
    trans = load_json(WORK / "artifacts" / "translation" / f"page_{page_num}.json")
    mt = trans.get("translations", {})
    items = canon.get("items", [])

    img = Image.open(img_path).convert("RGB")
    W, H = img.size

    # 漫画阅读顺序：先按 y 分档（上下排），每排内从右到左
    rows = sorted(items, key=lambda it: (round(it["bbox"][1] / 500), -it["bbox"][0]))

    cards = []
    for it in rows:
        rid = it["region_id"]
        x1, y1, x2, y2 = [float(v) for v in it["bbox"]]
        cx1 = max(0, int(x1) - PAD)
        cy1 = max(0, int(y1) - PAD)
        cx2 = min(W, int(x2) + PAD)
        cy2 = min(H, int(y2) + PAD)
        crop = img.crop((cx1, cy1, cx2, cy2))
        # 大图缩到宽 360 以内
        if crop.width > 360:
            ratio = 360 / crop.width
            crop = crop.resize((360, int(crop.height * ratio)))
        img_b64 = b64(crop)
        ocr = it.get("baberu_text") or it.get("text") or ""
        machine = mt.get(rid, "")
        cards.append(f"""
        <div class="card">
          <div class="crop"><img src="data:image/jpeg;base64,{img_b64}" alt="{rid}"></div>
          <div class="body">
            <div class="rid">{rid}</div>
            <div class="row"><span class="tag">OCR</span><span class="ocr">{ocr}</span></div>
            <div class="row"><span class="tag">机翻</span><span class="mt">{machine}</span></div>
            <div class="row"><span class="tag">你的改译</span>
              <textarea data-page="{page_num}" data-rid="{rid}" placeholder="在这里写你认为通顺的中文，或写"问题类型"如：OCR错字/生硬/漏译/指代不清"></textarea>
            </div>
          </div>
        </div>""")

    full_b64 = b64(img)
    return f"""
    <h2>第 {page_num} 页 <a class="raw" href="data:image/jpeg;base64,{full_b64}" target="_blank">看整页原图</a></h2>
    <div class="cards">{''.join(cards)}</div>"""


def main() -> None:
    pages_html = "\n".join(build_page(n, p) for n, p in PAGES.items())
    html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>翻译人工标注 p14-15</title>
<style>
 body{{font-family:'Microsoft YaHei',sans-serif;background:#f5f5f5;margin:0;padding:20px;max-width:1100px;margin:auto}}
 h1{{font-size:20px}} h2{{margin-top:36px;border-bottom:2px solid #333;padding-bottom:6px}}
 .raw{{font-size:13px;font-weight:normal;color:#06c}}
 .cards{{display:grid;grid-template-columns:1fr;gap:12px;margin-top:12px}}
 .card{{display:flex;gap:14px;background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px}}
 .crop img{{max-height:220px;border:1px solid #ccc;border-radius:4px}}
 .crop{{flex:0 0 auto}}
 .body{{flex:1;display:flex;flex-direction:column;gap:6px}}
 .rid{{font-weight:bold;color:#a33;font-size:13px}}
 .row{{display:flex;gap:8px;align-items:flex-start;font-size:14px}}
 .tag{{flex:0 0 44px;color:#888;font-size:12px;padding-top:2px}}
 .ocr{{color:#555}} .mt{{color:#000}}
 textarea{{width:100%;min-height:48px;border:1px solid #bbb;border-radius:4px;padding:6px;font-size:14px;box-sizing:border-box}}
 #bar{{position:sticky;top:0;background:#333;color:#fff;padding:10px 16px;border-radius:8px;display:flex;gap:12px;align-items:center;margin-bottom:16px}}
 button{{padding:6px 16px;border:0;border-radius:4px;cursor:pointer;font-size:14px}}
 #export{{background:#0a0}} #count{{font-size:13px}}
</style></head>
<body>
<div id="bar">
  <b>翻译标注 p14-15</b>
  <span id="count">已标注 0 条</span>
  <button id="export" onclick="exportJSON()">导出标注 JSON</button>
</div>
<h1>逐气泡标注：左为原图裁切，中为 OCR 日文与当前机翻，右写你的改译/问题</h1>
{pages_html}
<script>
function collect(){{
  const out=[];
  document.querySelectorAll('textarea').forEach(t=>{{
    if(t.value.trim()) out.push({{page:+t.dataset.page, region_id:t.dataset.rid, note:t.value.trim()}});
  }});
  return out;
}}
document.querySelectorAll('textarea').forEach(t=>t.addEventListener('input',()=>{{
  document.getElementById('count').textContent='已标注 '+collect().length+' 条';
}}));
function exportJSON(){{
  const blob=new Blob([JSON.stringify(collect(),null,2)],{{type:'application/json'}});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='annotation_p14_15.json';a.click();
}}
</script>
</body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
