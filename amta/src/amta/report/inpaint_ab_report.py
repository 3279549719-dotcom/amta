"""inpaint_ab_report — Inpainting 速度 A/B 对比报告（深接口模块）。

scripts/gen_inpaint_ab_report.py 是本模块的薄 CLI。
对比四组: baseline(整页Koharu) / p0(裁剪+Koharu) / p1_cpu(裁剪+本地big-lama) / p1_manga(裁剪+本地lama-manga)
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image

MODES = [
    ("baseline", "Baseline: 整页 Koharu lama-manga"),
    ("p0", "P0: 裁剪 + Koharu lama-manga"),
    ("p1_cpu", "P0+P1: 裁剪 + 本地 big-lama (CPU)"),
    ("p1_manga", "P0+P1: 裁剪 + 本地 lama-manga (CPU)"),
]
DEFAULT_PAGES = [11, 12, 13, 14, 15]


def _img_to_base64(path: Path, max_width: int = 800) -> str:
    img = Image.open(path)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def load_summary(exp_dir: Path, mode: str) -> dict[int, dict]:
    """加载某模式的 summary JSON，返回 {page: record}，过滤 error 条目。"""
    path = Path(exp_dir) / f"summary_{mode}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {r["page"]: r for r in data if "error" not in r}


def build_speed_table(summaries: dict[str, dict[int, dict]],
                      pages: list[int] | None = None) -> str:
    """构建速度对比表格 HTML。"""
    pages = pages or DEFAULT_PAGES
    rows = []
    for p in pages:
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

    avg_cells = ["<td><strong>平均</strong></td>"]
    for mode, _ in MODES:
        vals = [summaries[mode][p]["avg"] for p in pages
                if p in summaries.get(mode, {}) and summaries[mode][p].get("avg") is not None]
        frees = [summaries[mode][p]["n_free"] for p in pages
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


def build_speed_chart(summaries: dict[str, dict[int, dict]],
                      pages: list[int] | None = None) -> str:
    """纯 CSS 柱状图，不依赖外部库。"""
    pages = pages or DEFAULT_PAGES
    max_val = 0
    for mode, _ in MODES:
        for p in pages:
            r = summaries.get(mode, {}).get(p)
            if r and r.get("avg") is not None:
                max_val = max(max_val, r["avg"])
    if max_val == 0:
        max_val = 1

    colors = ["#EA6668", "#FAAD14", "#52C41A", "#1890FF"]
    bars = []
    for p in pages:
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


def _build_page_comparison(page: int, summaries: dict[str, dict[int, dict]],
                           exp_dir: Path, src_dir: Path) -> str:
    """每页四格对比: 原图 / Baseline / P0 / P1。"""
    labels = [("原图", Path(src_dir) / f"{page}.jpg")]
    for mode, label in MODES:
        if mode == "baseline":
            clean_path = Path(exp_dir) / mode / "clean" / f"page_{page}_run2_clean.png"
            if not clean_path.exists():
                clean_path = Path(exp_dir) / mode / "clean" / f"page_{page}_run0_clean.png"
        else:
            clean_path = Path(exp_dir) / mode / "clean" / f"page_{page}_clean.png"
        if clean_path.exists():
            labels.append((label.split(":")[0], clean_path))

    cells = []
    for label, path in labels:
        if path.exists():
            b64 = _img_to_base64(path, max_width=500)
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


_CSS = """
body { font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a2e; margin:0; padding:24px; line-height:1.6; }
.container { max-width:1400px; margin:0 auto; }
h1 { font-size:24px; margin-bottom:4px; }
.subtitle { color:#666; font-size:13px; margin-bottom:20px; }
.stats { display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }
.stat { background:#fff; border-radius:10px; padding:14px 20px; box-shadow:0 1px 4px rgba(0,0,0,.06); min-width:140px; }
.stat .num { font-size:28px; font-weight:700; color:#1e40af; }
.stat.ok .num { color:#16a34a; }
.stat.warn .num { color:#dc2626; }
.stat .lbl { font-size:12px; color:#666; }
.section { background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }
.section h2 { font-size:18px; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }
.page-section { background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }
.page-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }
.page-title { font-size:16px; font-weight:700; color:#1e40af; }
table { width:100%; border-collapse:collapse; font-size:13px; margin:12px 0; }
th { background:#f3f4f6; padding:8px 10px; text-align:left; border-bottom:2px solid #e5e7eb; }
td { padding:8px 10px; border-bottom:1px solid #f3f4f6; }
tr:hover { background:#f9fafb; }
.num { font-family:"SF Mono","Consolas",monospace; }
.highlight { background:#e8f5e9; font-weight:600; color:#1b5e20; }
.conclusion { background:linear-gradient(135deg,#1a1a2e,#16213e); color:#fff; border-radius:12px; padding:24px; margin-top:20px; }
.conclusion h2 { color:#fff; border-bottom-color:rgba(255,255,255,.2); }
.conclusion li { margin-bottom:8px; }
.conclusion strong { color:#38ef7d; }
.footer { text-align:center; color:#999; font-size:11px; margin-top:24px; padding:16px; }
"""


def render_inpaint_ab_report(
    exp_dir: Path,
    src_dir: Path,
    pages: list[int] | None = None,
    out_path: Path | None = None,
) -> str:
    """生成 Inpainting 速度 A/B 对比报告，返回 HTML 字符串。

    Args:
        exp_dir: 实验结果目录（含 summary_*.json + 各模式 clean/ 子目录）
        src_dir: 原图目录（N.jpg）
        pages: 页码列表，默认 [11,12,13,14,15]
        out_path: 可选，写入 HTML 文件
    """
    pages = pages or DEFAULT_PAGES
    exp_dir = Path(exp_dir)
    src_dir = Path(src_dir)

    print("[report] Loading summaries...")
    summaries = {mode: load_summary(exp_dir, mode) for mode, _ in MODES}

    print("[report] Building speed table...")
    speed_table = build_speed_table(summaries, pages)

    print("[report] Building speed chart...")
    speed_chart = build_speed_chart(summaries, pages)

    print("[report] Building page comparisons...")
    page_sections = "\n".join(
        _build_page_comparison(p, summaries, exp_dir, src_dir) for p in pages
    )

    def _avg(mode: str) -> float:
        vals = [r["avg"] for r in summaries[mode].values() if r.get("avg") is not None]
        return sum(vals) / len(vals) if vals else 0.0

    avg_baseline = _avg("baseline")
    avg_p0 = _avg("p0")
    avg_p1 = _avg("p1_cpu")
    avg_p1_manga = _avg("p1_manga")
    speedup_p0 = (1 - avg_p0 / avg_baseline) * 100 if avg_baseline > 0 else 0
    speedup_p1 = (1 - avg_p1 / avg_baseline) * 100 if avg_baseline > 0 else 0
    speedup_p1_manga = (1 - avg_p1_manga / avg_baseline) * 100 if avg_baseline > 0 else 0

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stage 4 Inpainting 速度 A/B 对比报告</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">

<h1>Stage 4 Inpainting 速度 A/B 对比报告 — lama-manga 本地推理验证</h1>
<p class="subtitle">四组对比: baseline / p0 / p1_cpu / p1_manga &nbsp;|&nbsp; 每页平均耗时</p>

<div class="stats">
  <div class="stat"><div class="num">{avg_baseline:.1f}s</div><div class="lbl">Baseline 平均/页</div></div>
  <div class="stat {'ok' if speedup_p0 > 0 else 'warn'}"><div class="num">{speedup_p0:+.0f}%</div><div class="lbl">P0 速度变化</div></div>
  <div class="stat ok"><div class="num">{speedup_p1:+.0f}%</div><div class="lbl">P0+P1 big-lama 提升</div></div>
  <div class="stat ok"><div class="num">{speedup_p1_manga:+.0f}%</div><div class="lbl">P0+P1 lama-manga 提升</div></div>
  <div class="stat ok"><div class="num">{avg_p1_manga:.1f}s</div><div class="lbl">lama-manga 平均/页</div></div>
</div>

<div class="section">
  <h2>速度对比（每页平均耗时）</h2>
  {speed_table}
</div>

<div class="section">
  <h2>速度柱状图</h2>
  {speed_chart}
</div>

<div class="section">
  <h2>每页效果对比</h2>
</div>
{page_sections}

<div class="conclusion">
  <h2>核心结论</h2>
  <ul>
    <li><strong>P0+P1 lama-manga 是最终方案</strong>：平均 {avg_p1_manga:.1f}s/页，比 Baseline 快 {speedup_p1_manga:.0f}%</li>
    <li><strong>瓶颈根因</strong>：Koharu 服务化开销（6次HTTP往返+project重建）是主要瓶颈</li>
    <li><strong>模型匹配是关键</strong>：lama-manga（漫画微调）vs big-lama（通用）质量差异显著</li>
    <li><strong>建议</strong>：合入 P0+P1 lama-manga 方案，本地推理替代 Koharu HTTP 调用</li>
  </ul>
</div>

<div class="footer">AMTA Stage 4 Inpainting Speed A/B Test &nbsp;|&nbsp; amta.report 深接口渲染</div>

</div>
</body>
</html>"""

    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        print(f"[report] Saved: {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")

    return html
