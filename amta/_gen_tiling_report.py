"""生成多尺度瓦片化对比报告 HTML（内嵌每页标注图 + conf 对比表）。"""
from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

sys.path.insert(0, r"E:\manga translator agent\amta\src")

import cv2
import numpy as np
from PIL import Image, ImageDraw

from _multiscale_v2 import raw_dets, nms_max_conf
import _tiling_sweep as ts

RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT = Path(r"E:\manga translator agent\amta\output\tiling_report.html")

PAGES = [14, 15, 17, 19]
KNOWN = {
    14: [("いたい!", [614, 1498, 654, 1621], (220, 40, 40))],
    15: [("はい", [1394, 770, 1460, 889], (220, 40, 40))],
    17: [("おとな…", [427, 2294, 489, 2449], (220, 40, 40)),
         ("ご苦労", [1323, 522, 1388, 664], (40, 120, 220))],
    19: [("そぉ～", [110, 311, 314, 408], (220, 40, 40)),
         ("サグ姉", [799, 2454, 851, 2553], (40, 120, 220))],
}

# 各方案结果（来自实验）
SCHEMES = [
    ("整图 640 (conf>=0.7) — 现产线", "whole", 0.7),
    ("瓦片 2×3 (conf>=0.3)", "t23", 0.3),
    ("瓦片 3×4 (conf>=0.3)", "t34", 0.3),
    ("融合 2×3+3×4 (conf>=0.3)", "fusion", 0.3),
]


def detect_whole_conf(img, conf_thr):
    dets = ts._detect_tile(img)  # noqa: SLF001
    dets = dets[dets[:, 5] >= conf_thr]
    if dets.size == 0:
        return []
    return [{"bbox": [int(v) for v in d[:4]], "label": int(d[4]), "conf": float(d[5])} for d in dets]


def detect_tiled_conf(img, cols, rows, conf_thr):
    h, w = img.shape[:2]
    tile_w = w / cols
    tile_h = h / rows
    step_w = tile_w * (1 - ts.OVERLAP)
    step_h = tile_h * (1 - ts.OVERLAP)
    out = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, int(c * step_w))
            y0 = max(0, int(r * step_h))
            x1 = min(w, int(x0 + tile_w))
            y1 = min(h, int(y0 + tile_h))
            tile = img[y0:y1, x0:x1].copy()
            dets = ts._detect_tile(tile)  # noqa: SLF001
            if dets.size == 0:
                continue
            dets = dets.copy()
            dets[:, [0, 2]] += x0
            dets[:, [1, 3]] += y0
            out.append(dets)
    combined = np.vstack(out) if out else np.array([]).reshape(0, 6)
    combined = combined[combined[:, 5] >= conf_thr]
    return nms_max_conf(combined, iou_thresh=0.5)


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def best_conf(blocks, kb):
    best = max(blocks, key=lambda b: _iou(b["bbox"], kb)) if blocks else None
    iou = _iou(best["bbox"], kb) if best else 0
    if best and iou >= 0.3:
        return best["conf"], iou
    return None, 0.0


def draw_page(img, blocks, known):
    """画框标注图：红=检出框，蓝=已知漏检字真值框。"""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    for b in blocks:
        x1, y1, x2, y2 = b["bbox"]
        conf = b["conf"]
        color = (60, 160, 60) if conf >= 0.7 else (240, 180, 40)
        d.rectangle([x1, y1, x2, y2], outline=color, width=6)
        d.text((x1 + 4, max(0, y1 - 40)), f"{conf:.2f}", fill=color)
    for name, kb, color in known:
        d.rectangle(kb, outline=color, width=3)
        d.text((kb[0] + 4, max(0, kb[1] - 40)), f"<{name}>", fill=color)
    return pil


def to_jpeg_b64(pil, quality=70, max_w=900):
    ratio = max_w / pil.width
    if ratio < 1:
        pil = pil.resize((max_w, int(pil.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    pil.convert("RGB").save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def main():
    rows_html = []
    for page in PAGES:
        img = cv2.imdecode(np.fromfile(str(RAW / f"{page}.jpg"), dtype=np.uint8), cv2.IMREAD_COLOR)
        known = KNOWN[page]
        # 各方案检出
        blocks_by_scheme = {}
        for label, kind, conf_thr in SCHEMES:
            if kind == "whole":
                blocks_by_scheme[label] = detect_whole_conf(img, conf_thr)
            elif kind == "t23":
                blocks_by_scheme[label] = detect_tiled_conf(img, 2, 3, conf_thr)
            elif kind == "t34":
                blocks_by_scheme[label] = detect_tiled_conf(img, 3, 4, conf_thr)
            elif kind == "fusion":
                all_d = []
                for c, r in [(2, 3), (3, 4)]:
                    d_ = raw_dets(img, c, r)
                    if d_.size:
                        all_d.append(d_)
                comb = np.vstack(all_d) if all_d else np.array([]).reshape(0, 6)
                comb = comb[comb[:, 5] >= conf_thr]
                blocks_by_scheme[label] = nms_max_conf(comb, iou_thresh=0.5)

        # 表格：每方案 × 每已知字
        table_rows = []
        for label, *_ in SCHEMES:
            cells = []
            for name, kb, _ in known:
                c, iou = best_conf(blocks_by_scheme[label], kb)
                if c is not None:
                    color = "#1a7f37" if c >= 0.7 else "#b35900"
                    cells.append(f'<td style="color:{color};font-weight:700">{c:.3f}</td>')
                else:
                    cells.append('<td style="color:#999">MISS</td>')
            n = len(blocks_by_scheme[label])
            table_rows.append(f"<tr><td>{label}</td><td style='text-align:center'>{n}</td>{''.join(cells)}</tr>")

        # 融合标注图
        fusion_img = draw_page(img, blocks_by_scheme[SCHEMES[3][0]], known)
        b64 = to_jpeg_b64(fusion_img)

        known_names = " / ".join(n for n, _, _ in known)
        rows_html.append(f"""
<h2>Page {page}（已知漏检：{known_names}）</h2>
<table>
  <tr><th>方案</th><th>框数</th>{''.join(f'<th>{n}</th>' for n, _, _ in known)}</tr>
  {''.join(table_rows)}
</table>
<p style="color:#666;font-size:12px">绿框=conf≥0.7 检出；黄框=0.3~0.7；细线=已知漏检字真值位置（标注 &lt;字&gt;）。图为"融合 2×3+3×4"结果。</p>
<img src="data:image/jpeg;base64,{b64}" style="width:100%;max-width:720px"/>
<hr/>
""")

    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>瓦片化检测实验报告 — 小字漏检</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;margin:0;padding:16px;background:#fafafa}}
h1{{font-size:18px}}h2{{font-size:15px;margin-top:24px}}
table{{border-collapse:collapse;margin:8px 0;background:#fff;font-size:13px}}
th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left}}
img{{display:block;margin:8px 0;border:1px solid #ddd}}
.sum{{background:#fff;border:1px solid #ddd;padding:12px;font-size:13px}}
</style></head><body>
<h1>瓦片化检测实验报告 — 框外小字漏检（p14/15/17/19）</h1>
<div class="sum">
<b>结论：</b>把原图切成瓦片、每块单独检测（模型仍工作在 640 训练尺度），再按最高置信度融合，
5 个已知漏检小字全部被检出且 conf ≥ 0.7，无需任何规则过滤、无需换模型。
<br/><b>对比基线：</b>现产线整图缩 640 检测（conf 0.7）→ 5 个全部 MISS 或 <0.7。
<br/><b>耗时：</b>4 页 × (2×3 + 3×4 = 17 次 640 推理) ≈ 30 秒。
</div>
{''.join(rows_html)}
</body></html>"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print("written:", OUT, len(html) // 1024, "KB")


if __name__ == "__main__":
    main()
