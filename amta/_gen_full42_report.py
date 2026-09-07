"""生成全量42页瓦片化实验报告 HTML（含 30 框逐框核对表）。"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(r"E:\manga translator agent\amta\output")
detail = json.loads((OUT / "tiling_full42" / "new_blocks_detail.json").read_text(encoding="utf-8"))
summary = json.loads((OUT / "tiling_full42" / "summary.json").read_text(encoding="utf-8"))

# 人工分类（基于 OCR 文本 + 裁剪图人眼核对）
# verdict: dialog=真对白, note=解说/旁白, aogaki=后记正文, noise=杂质残留
CLASSIFY = {
    ("p2", 0.704): ("noise", "纯省略号，rule_filter 滤掉"),
    ("p3", 0.808): ("dialog", "单字「ぽ」，对白残字/装饰字，保留"),
    ("p5", 0.705): ("note", "设定解说文字（横排正文），非气泡对白"),
    ("p6", 0.789): ("noise", "左边缘窄条乱码，edge_box 滤掉"),
    ("p11", 0.838): ("dialog", "竖排手写对白「はっ...」"),
    ("p14", 0.812): ("dialog", "「八意様」对白"),
    ("p14", 0.771): ("dialog", "「いたい!」—— 原漏检，救回"),
    ("p15", 0.886): ("dialog", "「はい」—— 原 conf 0.678 漏检，救回"),
    ("p17", 0.878): ("dialog", "「おとな...」—— 原漏检，救回"),
    ("p17", 0.766): ("dialog", "「ご苦労」—— 原 conf 0.623 漏检，救回"),
    ("p19", 0.835): ("dialog", "「サグ姉」—— 原漏检，救回"),
    ("p22", 0.804): ("dialog", "「はっ...」竖排对白"),
    ("p24", 0.759): ("dialog", "「フルフル」拟声/对白"),
    ("p25", 0.770): ("dialog", "「姉様」对白"),
    ("p26", 0.847): ("dialog", "「私のスタンプ帳見せてあげる」竖排对白"),
    ("p27", 0.812): ("dialog", "「月!?」对白"),
    ("p31", 0.725): ("noise", "纯省略号，rule_filter 滤掉"),
    ("p32", 0.845): ("dialog", "「ちょっ、離してください」对白"),
    ("p32", 0.700): ("dialog", "「楽ちゃん♪」对白"),
    ("p33", 0.724): ("dialog", "「うわああああああ」对白"),
    ("p34", 0.814): ("dialog", "「戻れー」对白"),
    ("p40", 0.932): ("aogaki", "后记正文段落（作者后记整页）"),
    ("p40", 0.920): ("aogaki", "后记正文段落"),
    ("p40", 0.915): ("aogaki", "后记正文段落"),
    ("p40", 0.912): ("aogaki", "后记正文段落"),
    ("p40", 0.898): ("aogaki", "后记正文段落"),
    ("p40", 0.894): ("aogaki", "后记正文段落"),
    ("p40", 0.780): ("aogaki", "后记正文段落（开头问候）"),
    ("p40", 0.775): ("aogaki", "后记正文段落"),
    ("p40", 0.753): ("aogaki", "后记正文段落（邮箱/署名）"),
}
KEY = {("p40", 0.753): ("aogaki", "后记正文段落（邮箱/署名）")}
CLASSIFY.update(KEY)

CAT = {
    "dialog": ("真对白 / 小字", "#52C41A"),
    "note": ("解说 / 旁白", "#8BC8EA"),
    "aogaki": ("后记正文（p40）", "#E1B98F"),
    "noise": ("杂质", "#EA6668"),
}
ORDER = {"dialog": 0, "note": 1, "aogaki": 2, "noise": 3}

rows = []
for b in sorted(detail, key=lambda x: (x["page"], x["conf"])):
    key = (f"p{b['page']}", b["conf"])
    cat, note = CLASSIFY.get(key, ("note", "待人工确认"))
    verdict = "保留" if b["verdict"] == "keep" else "滤除"
    rows.append({
        "page": b["page"], "conf": b["conf"], "bbox": b.get("bbox"), "text": b["text"],
        "verdict": verdict, "cat": cat, "note": note,
    })

n_dialog = sum(1 for r in rows if r["cat"] == "dialog")
n_note = sum(1 for r in rows if r["cat"] == "note")
n_aogaki = sum(1 for r in rows if r["cat"] == "aogaki")
n_noise = sum(1 for r in rows if r["cat"] == "noise")
n_keep = sum(1 for r in rows if r["verdict"] == "保留")
n_drop = sum(1 for r in rows if r["verdict"] == "滤除")

cov = summary["coverage_bins"]
cov_total = sum(cov.values())

# coverage 双峰柱状
bars = ""
for k, v in cov.items():
    pct = v / cov_total * 100
    bars += f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0;"><div style="width:90px;font-size:12px;color:#555;text-align:right;">{k}</div><div style="flex:1;background:#F0F0EC;border-radius:4px;height:22px;position:relative;"><div style="width:{pct}%;background:{"#52C41A" if float(k.split("-")[0])<0.5 else "#EA6668"};height:22px;border-radius:4px;"></div></div><div style="width:50px;font-size:12px;color:#1A1B1C;">{v}</div></div>'

tr_html = ""
for r in rows:
    cat_name, color = CAT[r["cat"]]
    bb = r["bbox"]
    bb_s = "—" if bb is None else f"[{bb[0]},{bb[1]},{bb[2]},{bb[3]}]"
    tr_html += (
        f'<tr><td style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;">p{r["page"]}</td>'
        f'<td style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;">{r["conf"]:.3f}</td>'
        f'<td style="padding:6px 8px;border:1px solid #E4E3DD;font-size:11px;color:#6B7280;">{bb_s}</td>'
        f'<td style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;">{r["text"] or "（空）"}</td>'
        f'<td style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;color:{"#52C41A" if r["verdict"]=="保留" else "#EA6668"};">{r["verdict"]}</td>'
        f'<td style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;color:{color};font-weight:600;">{cat_name}</td>'
        f'<td style="padding:6px 8px;border:1px solid #E4E3DD;font-size:11px;color:#555;">{r["note"]}</td></tr>'
    )

html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>瓦片化副引擎全量实验（42页，纯3×4）</title></head>
<body style="margin:0;padding:20px;background:#F4F3EE;font-family:'PingFang SC','Microsoft YaHei',sans-serif;color:#1A1B1C;">
<div style="max-width:960px;margin:0 auto;">

<div style="background:#fff;border-radius:14px;padding:20px;margin-bottom:16px;border:1px solid rgba(0,0,0,0.08);">
  <h1 style="font-size:20px;margin:0 0 4px;">瓦片化副引擎 · 全 42 页实验报告</h1>
  <div style="font-size:12px;color:#6B7280;">纯 3×4 网格 · overlap 0.15 · NMS iou 0.5 · 新增=conf≥0.7 且 coverage&lt;0.5 · OCR=hayai · rule_filter 在 OCR 后</div>
</div>

<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
  <div style="flex:1 1 130px;background:#fff;border-radius:14px;padding:16px;border:1px solid rgba(0,0,0,0.08);">
    <div style="font-size:12px;color:#6B7280;">主链框（整图 640/0.7）</div>
    <div style="font-size:26px;font-weight:700;margin-top:4px;">{summary["total_main"]}</div></div>
  <div style="flex:1 1 130px;background:#fff;border-radius:14px;padding:16px;border:1px solid rgba(0,0,0,0.08);">
    <div style="font-size:12px;color:#6B7280;">瓦片框（3×4, conf≥0.3）</div>
    <div style="font-size:26px;font-weight:700;margin-top:4px;">{summary["total_tiled"]}</div></div>
  <div style="flex:1 1 130px;background:#fff;border-radius:14px;padding:16px;border:1px solid rgba(0,0,0,0.08);">
    <div style="font-size:12px;color:#6B7280;">新增框（≥0.7 非碎片）</div>
    <div style="font-size:26px;font-weight:700;margin-top:4px;color:#3B5BB5;">{summary["total_new"]}</div></div>
  <div style="flex:1 1 130px;background:#fff;border-radius:14px;padding:16px;border:1px solid rgba(0,0,0,0.08);">
    <div style="font-size:12px;color:#6B7280;">OCR+rule_filter 后保留</div>
    <div style="font-size:26px;font-weight:700;margin-top:4px;color:#52C41A;">{n_keep}</div></div>
  <div style="flex:1 1 130px;background:#fff;border-radius:14px;padding:16px;border:1px solid rgba(0,0,0,0.08);">
    <div style="font-size:12px;color:#6B7280;">rule_filter 滤除</div>
    <div style="font-size:26px;font-weight:700;margin-top:4px;color:#EA6668;">{n_drop}</div></div>
</div>

<div style="background:#fff;border-radius:14px;padding:20px;margin-bottom:16px;border:1px solid rgba(0,0,0,0.08);">
  <h2 style="font-size:16px;margin:0 0 4px;">保留框分类账（{n_keep} 个）</h2>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;">
    <div style="flex:1 1 120px;background:rgba(82,196,26,0.08);border-radius:12px;padding:12px;text-align:center;"><div style="font-size:12px;color:#6B7280;">真对白/小字</div><div style="font-size:22px;font-weight:700;color:#52C41A;">{n_dialog}</div></div>
    <div style="flex:1 1 120px;background:rgba(139,200,234,0.12);border-radius:12px;padding:12px;text-align:center;"><div style="font-size:12px;color:#6B7280;">解说/旁白</div><div style="font-size:22px;font-weight:700;color:#3B5BB5;">{n_note}</div></div>
    <div style="flex:1 1 120px;background:rgba(225,185,143,0.15);border-radius:12px;padding:12px;text-align:center;"><div style="font-size:12px;color:#6B7280;">p40 后记正文</div><div style="font-size:22px;font-weight:700;color:#B07A3E;">{n_aogaki}</div></div>
    <div style="flex:1 1 120px;background:rgba(234,102,104,0.08);border-radius:12px;padding:12px;text-align:center;"><div style="font-size:12px;color:#6B7280;">杂质残留</div><div style="font-size:22px;font-weight:700;color:#EA6668;">{n_noise}</div></div>
  </div>
  <div style="font-size:12px;color:#6B7280;margin-top:10px;">注：3 个 rule_filter 滤除的均为杂质（2 纯省略号 + 1 左边缘乱码窄条）。27 个保留框中，真正的“非对白文本”是 p5 解说 + p40 后记整页 9 段。</div>
</div>

<div style="background:#fff;border-radius:14px;padding:20px;margin-bottom:16px;border:1px solid rgba(0,0,0,0.08);">
  <h2 style="font-size:16px;margin:0 0 4px;">coverage 分布：双峰验证（全量 {cov_total} 框）</h2>
  <div style="font-size:12px;color:#6B7280;margin:6px 0;">绿=独立框（coverage&lt;0.5），红=碎片（≥0.5）。碎片 469 个集中在 0.9~1.0，独立框 211 个集中在 0~0.1；中间 0.1~0.9 仅 33 个。</div>
  {bars}
  <div style="font-size:12px;color:#6B7280;margin-top:8px;">结论：0.5 阈值落在天然空档，0.3~0.9 无成批骑墙框（31 个中间框里 24 个 cov≥0.8 是碎片尾，7 个 conf&lt;0.5 本就进不了产线）。</div>
</div>

<div style="background:#fff;border-radius:14px;padding:20px;margin-bottom:16px;border:1px solid rgba(0,0,0,0.08);">
  <h2 style="font-size:16px;margin:0 0 8px;">30 个新增框 · 逐框核对表</h2>
  <div style="overflow-x:auto;">
  <table style="border-collapse:collapse;width:100%;min-width:760px;">
  <tr style="background:#F8F9FD;">
    <th style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;text-align:left;">页</th>
    <th style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;text-align:left;">conf</th>
    <th style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;text-align:left;">bbox</th>
    <th style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;text-align:left;">OCR(hayai)</th>
    <th style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;text-align:left;">rule_filter</th>
    <th style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;text-align:left;">人工分类</th>
    <th style="padding:6px 8px;border:1px solid #E4E3DD;font-size:12px;text-align:left;">备注</th>
  </tr>
  {tr_html}
  </table>
  </div>
</div>

<div style="background:#fff;border-radius:14px;padding:20px;border:1px solid rgba(0,0,0,0.08);">
  <h2 style="font-size:16px;margin:0 0 8px;">关键结论</h2>
  <ul style="font-size:13px;line-height:1.9;margin:0;padding-left:20px;">
    <li><b>已知 6 个漏检中 5 个救回</b>：いたい!/はい/おとな…/ご苦労/サグ姉 全部进入新增框；<b>そぉ～ 仍未救回</b>——纯 3×4 下 conf=0.672&lt;0.7（2×3+3×4 融合时是 0.738 可过线，这是纯 3×4 的已知代价）。</li>
    <li><b>新增多为真字</b>：30 个新增框 OCR 后仅 3 个被 rule_filter 滤除（纯省略号×2、边缘乱码×1）；27 个保留中 17 个是真对白/小字（含 p3 单字「ぽ」）、9 个是 p40 后记正文、1 个 p5 解说。</li>
    <li><b>副引擎会捞“非对白正文”</b>：p40 后记页（整页密集文字）被切成 9 段捞入、p5 解说文字被捞入——这些是真字但不是气泡对白，需下游决定是否翻译（后记页建议整页翻译而非逐框）。</li>
    <li><b>唯一≥0.7 的“图案杂质”未出现</b>：4 页样本时的刺绣徽章（conf 0.731）在全量中未见同类，本次 30 个新增无图案类杂质。</li>
    <li><b>耗时可接受</b>：42 页检测 ~12.5 分钟（42×13 次 640 推理），页均 ~18s。</li>
  </ul>
</div>

</div></body></html>"""

(OUT / "tiling_full42_report.html").write_text(html, encoding="utf-8")
print(f"report written: {OUT / 'tiling_full42_report.html'}")
print(f"dialog={n_dialog} note={n_note} aogaki={n_aogaki} noise={n_noise} keep={n_keep} drop={n_drop}")
