"""生成 dashscope vs baberu 双引擎 OCR 对比 HTML（page_11-20）。
左：原图。中：dashscope 结果。右：baberu 结果。按 region_id 对齐。"""
import glob
import html
import json
import os
import shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(ROOT, 'output', 'data', 'ocr_compare_html')
IMG_SRC = r'D:\我的汉化\汉化作品\东方\单翼停留之地'
os.makedirs(OUT, exist_ok=True)

def load_canons(base):
    d = {}
    for f in sorted(glob.glob(os.path.join(base, 'page_*_canon.json'))):
        j = json.load(open(f, encoding='utf-8'))
        page = int(j['page'].split('_')[1])
        d[page] = j['items']
    return d

dash = load_canons(os.path.join(ROOT, 'output/data/stage3_full_canon'))
baberu = load_canons(os.path.join(ROOT, 'output/data/baberu_canon'))

pages_html = []
for p in range(11, 21):
    # 复制原图
    src_img = os.path.join(IMG_SRC, f'{p}.jpg')
    dst_img = os.path.join(OUT, f'{p}.jpg')
    if os.path.exists(src_img) and not os.path.exists(dst_img):
        shutil.copy2(src_img, dst_img)
    # 两份 items，按 region_id 对齐
    def by_rid(items):
        return {it['region_id']: it for it in items}
    dmap = by_rid(dash.get(p, []))
    bmap = by_rid(baberu.get(p, []))
    all_rids = list(dmap.keys())
    for rid in bmap:
        if rid not in all_rids:
            all_rids.append(rid)
    all_rids.sort()

    rows = []
    for rid in all_rids:
        di = dmap.get(rid, {})
        bi = bmap.get(rid, {})
        dtxt = di.get('baberu_text') or ''
        btxt = bi.get('baberu_text') or ''
        same = (dtxt == btxt)
        flag = '<span class="same">=</span>' if same else '<span class="diff">≠</span>'
        rows.append(
            f'<tr><td class="rid">{html.escape(rid)}</td>'
            f'<td class="fl"> {flag}</td>'
            f'<td class="txt dash">{html.escape(dtxt) if dtxt else "·"}</td>'
            f'<td class="txt bab">{html.escape(btxt) if btxt else "·"}</td></tr>'
        )
    nd = len(dash.get(p, []))
    nb = len(baberu.get(p, []))
    pages_html.append(f'''
    <div class="page">
      <div class="page-head"><h2>page_{p}</h2>
        <span class="meta">dashscope {nd} · baberu {nb}</span></div>
      <div class="page-body">
        <div class="img-wrap"><img loading="lazy" src="{p}.jpg" alt="page {p}"></div>
        <div class="cmp-wrap"><table>
          <thead><tr><th>region_id</th><th></th><th>dashscope (qwen-vl-ocr)</th><th>baberu (本地)</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table></div>
      </div>
    </div>''')

doc = '''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>OCR 双引擎对比 — page 11-20</title><style>
 body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:24px}
 h1{font-size:22px} h2{font-size:18px;margin:0;display:inline}
 .page{background:#1a1d24;border:1px solid #2a2e38;border-radius:10px;padding:18px;margin-bottom:28px}
 .page-head{margin-bottom:12px} .meta{color:#8a93a6;font-size:13px;margin-left:10px}
 .page-body{display:flex;gap:20px;align-items:flex-start}
 .img-wrap{flex:0 0 30%;max-width:320px}
 .img-wrap img{width:100%;border-radius:6px;border:1px solid #333}
 .cmp-wrap{flex:1;min-width:0}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th{text-align:left;color:#9aa3b5;font-weight:600;padding:6px 8px;border-bottom:1px solid #2c313c}
 td{padding:6px 8px;border-bottom:1px solid #22262e;vertical-align:top}
 .rid{color:#6ea8fe;font-family:monospace;white-space:nowrap}
 .txt{white-space:pre-wrap;word-break:break-word}
 .dash{color:#e6e6e6} .bab{color:#b8c4d8}
 .same{color:#3fb950;font-weight:700}.diff{color:#f85149;font-weight:700}
 tbody tr:hover{background:#20242d}
 @media(max-width:900px){.page-body{flex-direction:column}.img-wrap{max-width:none}}
</style></head><body>
<h1>OCR 双引擎对比报告 — canon 页 11-20</h1>
<p style="color:#8a93a6">左原图 · 中=dashscope(qwen-vl-ocr) · 右=baberu(本地 onnx)。<span class="same">=</span> 两引擎一致，<span class="diff">≠</span> 不一致。</p>
''' + ''.join(pages_html) + '''
</body></html>'''
out = os.path.join(OUT, 'index.html')
open(out, 'w', encoding='utf-8').write(doc)
print('生成:', out, f'({os.path.getsize(out)} bytes)')
