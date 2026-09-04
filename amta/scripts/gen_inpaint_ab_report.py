"""生成 Inpainting 速度 A/B 对比 HTML 报告。

复用 amta.report 深接口的 CSS 风格和 base64 工具, 自定义 A/B 四组对比布局。
用法: python scripts/gen_inpaint_ab_report.py
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(r"E:\manga translator agent\amta")
EXP_DIR = ROOT / "output" / "tmp" / "inpaint_speed_exp"
OUT_HTML = EXP_DIR / "inpaint_speed_ab_report.html"
SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")

MODES = [
    ("baseline", "Baseline: 整页 Koharu lama-manga"),
    ("p0", "P0: 裁剪 + Koharu lama-manga"),
    ("p1_cpu", "P0+P1: 裁剪 + 本地 big-lama (CPU)"),
]
PAGES = [11, 12, 13, 14, 15]


def img_to_base64(path: Path, max_width: int = 800) -> str:
    img = Image.open(path)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def load_summary(mode: str) -> dict[int, dict]:
    path = EXP_DIR / f"summary_{mode}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {r["page"]: r for r in data if "error" not in r}


def build_speed_table(summaries: dict[str, dict[int, dict]]) -> str:
    rows = []
    for p in PAGES:
        cells = [f"<td>page_{p}</td>"]
        for mode, _ in MODES:
            r = summaries.get(mode, {}).get(p)
            if r and r.get("avg") is not None:
                cells.append(f'<td class="num">{r["avg"]:.1f}s</td>')
                cells.append(f'<td class="num">{r["n_free"]}</td>')
            elif r and r.get("note"):
                cells.append(f'<td class="num" style="color:#dc2626">{r["note"]}</td>')
                cells.append(f'<td class="num">{r["n_free"]}</td>')
            else:
                cells.append('<td class="num">-</td><td class="num">-</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")

    # 平均行
    avg_cells = ["<td><strong>平均</strong></td>"]
    for mode, _ in MODES:
        vals = [summaries[mode][p]["avg"] for p in PAGES
                if p in summaries.get(mode, {}) and summaries[mode][p].get("avg") is not None]
        frees = [summaries[mode][p]["n_free"] for p in PAGES
                 if p in summaries.get(mode, {}) and summaries[mode][p].get("avg") is not None]
        if vals:
            avg_cells.append(f'<td class="num highlight"><strong>{sum(vals)/len(vals):.1f}s</strong></td>')
            avg_cells.append(f'<td class="num">{sum(frees)/len(frees):.1f}</td>')
        else:
            avg_cells.append('<td class="num">-</td><td class="num">-</td>')
    rows.append(f"<tr>{''.join(avg_cells)}</tr>")

    headers = "<tr><th>页面</th>"
    for mode, label in MODES:
        headers += f"<th>{label.split(':')[0]}<br><span style='font-weight:400;font-size:11px'>耗时</span></th>"
        headers += "<th><span style='font-weight:400;font-size:11px'>free框</span></th>"
    headers += "</tr>"

    return f"<table><thead>{headers}</thead><tbody>{''.join(rows)}</tbody></table>"


def build_speed_chart(summaries: dict[str, dict[int, dict]]) -> str:
    """纯 CSS 柱状图, 不依赖外部库。"""
    max_val = 0
    for mode, _ in MODES:
        for p in PAGES:
            r = summaries.get(mode, {}).get(p)
            if r and r.get("avg") is not None:
                max_val = max(max_val, r["avg"])
    if max_val == 0:
        max_val = 1

    colors = ["#EA6668", "#FAAD14", "#52C41A"]
    bars = []
    for p in PAGES:
        page_bars = []
        for i, (mode, _) in enumerate(MODES):
            r = summaries.get(mode, {}).get(p)
            if r and r.get("avg") is not None:
                h = int(r["avg"] / max_val * 180)
                page_bars.append(
                    f'<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px">'
                    f'<div style="font-size:10px;color:#666">{r["avg"]:.0f}s</div>'
                    f'<div style="width:24px;height:{h}px;background:{colors[i]};border-radius:4px 4px 0 0;min-height:4px"></div>'
                    f'<div style="font-size:9px;color:#999">{mode.split("_")[0]}</div>'
                    f"</div>"
                )
        bars.append(
            f'<div style="flex:1;display:flex;align-items:flex-end;justify-content:center;gap:6px;border-bottom:1px solid #e5e7eb;padding-bottom:8px">'
            f'{"".join(page_bars)}</div>'
            f'<div style="text-align:center;font-size:12px;color:#666;margin-top:4px">page_{p}</div>'
        )

    legend = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:16px;font-size:12px">'
        f'<span style="width:12px;height:12px;background:{colors[i]};border-radius:2px;display:inline-block"></span>'
        f'{label.split(":")[0]}</span>'
        for i, (_, label) in enumerate(MODES)
    )

    return (
        f'<div style="display:flex;gap:8px;margin:16px 0">{"".join(bars)}</div>'
        f'<div style="margin-top:8px">{legend}</div>'
    )


def build_page_comparison(page: int, summaries: dict[str, dict[int, dict]]) -> str:
    """每页四格对比: 原图 / Baseline / P0 / P1。"""
    images_html = []
    labels = [("原图", SRC_DIR / f"{page}.jpg")]
    for mode, label in MODES:
        if mode == "baseline":
            clean_path = EXP_DIR / mode / "clean" / f"page_{page}_run2_clean.png"
            if not clean_path.exists():
                clean_path = EXP_DIR / mode / "clean" / f"page_{page}_run0_clean.png"
        else:
            clean_path = EXP_DIR / mode / "clean" / f"page_{page}_clean.png"
        if clean_path.exists():
            labels.append((label.split(":")[0], clean_path))

    cells = []
    for label, path in labels:
        if path.exists():
            b64 = img_to_base64(path, max_width=500)
            cells.append(
                f'<div style="flex:1;min-width:200px">'
                f'<div style="font-size:12px;font-weight:600;color:#1e40af;margin-bottom:4px">{label}</div>'
                f'<img src="data:image/jpeg;base64,{b64}" style="width:100%;border-radius:6px;border:1px solid #e5e7eb">'
                f"</div>"
            )

    speed_info = ""
    for mode, label in MODES:
        r = summaries.get(mode, {}).get(page)
        if r and r.get("avg") is not None:
            speed_info += f"<div>{label.split(':')[0]}: <strong>{r['avg']:.1f}s</strong> ({r['n_free']} free框)</div>"
        elif r and r.get("note"):
            speed_info += f"<div>{label.split(':')[0]}: <strong style='color:#dc2626'>{r['note']}</strong></div>"

    return (
        f'<div class="page-section">'
        f'<div class="page-header"><div class="page-title">page_{page} — {page}.jpg</div></div>'
        f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;font-size:13px">{speed_info}</div>'
        f'<div style="display:flex;gap:12px;flex-wrap:wrap">{"".join(cells)}</div>'
        f"</div>"
    )


def main():
    print("[report] Loading summaries...")
    summaries = {mode: load_summary(mode) for mode, _ in MODES}

    print("[report] Building speed table...")
    speed_table = build_speed_table(summaries)

    print("[report] Building speed chart...")
    speed_chart = build_speed_chart(summaries)

    print("[report] Building page comparisons...")
    page_sections = "\n".join(build_page_comparison(p, summaries) for p in PAGES)

    # 概览卡片
    avg_baseline = sum(r["avg"] for r in summaries["baseline"].values() if r.get("avg") is not None) / max(1, len([r for r in summaries["baseline"].values() if r.get("avg") is not None])) if summaries.get("baseline") else 0
    avg_p0 = sum(r["avg"] for r in summaries["p0"].values() if r.get("avg") is not None) / max(1, len([r for r in summaries["p0"].values() if r.get("avg") is not None])) if summaries.get("p0") else 0
    avg_p1 = sum(r["avg"] for r in summaries["p1_cpu"].values() if r.get("avg") is not None) / max(1, len([r for r in summaries["p1_cpu"].values() if r.get("avg") is not None])) if summaries.get("p1_cpu") else 0

    speedup_p0 = (1 - avg_p0 / avg_baseline) * 100 if avg_baseline > 0 else 0
    speedup_p1 = (1 - avg_p1 / avg_baseline) * 100 if avg_baseline > 0 else 0

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stage 4 Inpainting 速度 A/B 对比报告</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a2e; margin:0; padding:24px; line-height:1.6; }}
.container {{ max-width:1400px; margin:0 auto; }}
h1 {{ font-size:24px; margin-bottom:4px; }}
.subtitle {{ color:#666; font-size:13px; margin-bottom:20px; }}
.stats {{ display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }}
.stat {{ background:#fff; border-radius:10px; padding:14px 20px; box-shadow:0 1px 4px rgba(0,0,0,.06); min-width:140px; }}
.stat .num {{ font-size:28px; font-weight:700; color:#1e40af; }}
.stat.ok .num {{ color:#16a34a; }}
.stat.warn .num {{ color:#dc2626; }}
.stat .lbl {{ font-size:12px; color:#666; }}
.section {{ background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }}
.section h2 {{ font-size:18px; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }}
.page-section {{ background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }}
.page-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }}
.page-title {{ font-size:16px; font-weight:700; color:#1e40af; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; margin:12px 0; }}
th {{ background:#f3f4f6; padding:8px 10px; text-align:left; border-bottom:2px solid #e5e7eb; }}
td {{ padding:8px 10px; border-bottom:1px solid #f3f4f6; }}
tr:hover {{ background:#f9fafb; }}
.num {{ font-family:"SF Mono","Consolas",monospace; }}
.highlight {{ background:#e8f5e9; font-weight:600; color:#1b5e20; }}
.conclusion {{ background:linear-gradient(135deg,#1a1a2e,#16213e); color:#fff; border-radius:12px; padding:24px; margin-top:20px; }}
.conclusion h2 {{ color:#fff; border-bottom-color:rgba(255,255,255,.2); }}
.conclusion li {{ margin-bottom:8px; }}
.conclusion strong {{ color:#38ef7d; }}
.footer {{ text-align:center; color:#999; font-size:11px; margin-top:24px; padding:16px; }}
</style>
</head>
<body>
<div class="container">

<h1>Stage 4 Inpainting 速度 A/B 对比报告</h1>
<p class="subtitle">分支: feat/stage4-inpaint-speed-optimization &nbsp;|&nbsp; 样本: 东方Project 单翼停留之地 page_11~15 &nbsp;|&nbsp; 每组3次取平均</p>

<!-- 概览卡片 -->
<div class="stats">
  <div class="stat"><div class="num">{avg_baseline:.1f}s</div><div class="lbl">Baseline 平均/页</div></div>
  <div class="stat {'ok' if speedup_p0 > 0 else 'warn'}"><div class="num">{speedup_p0:+.0f}%</div><div class="lbl">P0 速度变化</div></div>
  <div class="stat ok"><div class="num">{speedup_p1:+.0f}%</div><div class="lbl">P0+P1 速度提升</div></div>
  <div class="stat ok"><div class="num">{avg_p1:.1f}s</div><div class="lbl">P0+P1 平均/页</div></div>
</div>

<!-- 速度对比表 -->
<div class="section">
  <h2>速度对比（每页平均耗时）</h2>
  {speed_table}
</div>

<!-- 速度柱状图 -->
<div class="section">
  <h2>速度柱状图</h2>
  {speed_chart}
</div>

<!-- 每页效果对比 -->
<div class="section">
  <h2>每页效果对比（原图 / Baseline / P0 / P0+P1）</h2>
</div>
{page_sections}

<!-- 结论 -->
<div class="conclusion">
  <h2>核心结论</h2>
  <ul>
    <li><strong>P0+P1（裁剪+本地 LaMa）是最大赢家</strong>：平均 {avg_p1:.1f}s/页，比 Baseline 快 {speedup_p1:.0f}%，且无 HTTP 开销、速度稳定。</li>
    <li><strong>P0（裁剪+Koharu）效果不稳定</strong>：框少时略快，框多时因每个框独立走 Koharu HTTP 流程（create_project→import→inpaint→fetch），开销叠加后反而比整页更慢。</li>
    <li><strong>瓶颈根因</strong>：Koharu 服务化开销（6次HTTP往返+project重建）是主要瓶颈，而非推理本身。本地推理消除 HTTP 后速度提升显著。</li>
    <li><strong>质量说明</strong>：P0+P1 用的是 big-lama（通用 LaMa），Baseline/P0 用的是 lama-manga（漫画微调），质量差异部分来自模型而非架构。需人工评分确认。</li>
    <li><strong>建议</strong>：合入 P0+P1 方案，用本地 big-lama 替代 Koharu；核显 DirectML 加速需 TorchScript→ONNX 转换，留作后续优化。</li>
  </ul>
</div>

<div class="footer">AMTA Stage 4 Inpainting Speed A/B Test &nbsp;|&nbsp; 生成时间: 2026-09-04 &nbsp;|&nbsp; amta.report 深接口渲染</div>

</div>
</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"[report] Saved: {OUT_HTML}")
    print(f"  size: {OUT_HTML.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
