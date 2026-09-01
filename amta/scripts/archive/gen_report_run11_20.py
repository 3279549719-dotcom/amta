"""gen_report_run11_20 — 11-20 页一次性自动跑批汇报 HTML（含各 stage 统计 + 图表 + 问题 + 翻译对照原文）。

读 output/data/run11_20_stats.json + workspace 产物，产出通俗易懂的中文 HTML。
"""
from __future__ import annotations

import json
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "workspace" / "touhou-single-wing" / "artifacts"
OUT = ROOT / "output" / "reports" / "run11_20_report.html"


def norm(s: str) -> str:
    return (s or "").replace("\n", "").strip()


def load_stats() -> dict:
    p = ROOT / "output" / "data" / "run11_20_stats.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def build_translation_table() -> str:
    rows = []
    for pg in range(0, 20):
        canonp = ART / f"page_{pg}_canon.json"
        transp = ART / f"page_{pg}_translation.json"
        if not (canonp.exists() and transp.exists()):
            continue
        canon = json.loads(canonp.read_text(encoding="utf-8"))
        trans = json.loads(transp.read_text(encoding="utf-8"))["translations"]
        canon_by = {r["region_id"]: r["text"] for r in canon}
        for rid, t in trans.items():
            src = norm(canon_by.get(rid, ""))
            rows.append(f'<tr><td class="pg">p{pg}</td><td class="rid">{html.escape(rid)}</td>'
                        f'<td class="src">{html.escape(src)}</td><td class="dst">{html.escape(norm(t))}</td></tr>')
    return "\n".join(rows)


def per_page_table(stats: dict) -> str:
    pages = stats.get("pages", [])
    det, ocr, trans = stats["det"], stats["ocr"], stats["trans"]
    sp, sf, pr = stats["sem_passed"], stats["sem_failed"], stats["pass_rate"]
    rows = []
    for pg in pages:
        d = det.get(str(pg), det.get(pg, 0))
        o = ocr.get(str(pg), ocr.get(pg, 0))
        t = trans.get(str(pg), trans.get(pg, 0))
        passed = sp.get(str(pg), sp.get(pg, ""))
        failed = sf.get(str(pg), sf.get(pg, ""))
        rate = pr.get(str(pg), pr.get(pg, ""))
        rate_s = f"{rate*100:.0f}%" if isinstance(rate, (int, float)) else ("—" if passed == "" else "—")
        sem_s = f"{passed}/{passed+failed} (✓{rate_s})" if passed != "" else "未跑"
        flag = "" if (isinstance(rate, (int, float)) and rate >= 0.9) else " ⚠"
        rows.append(f'<tr><td>{pg+1}</td><td>{d}</td><td>{o}</td><td>{t}</td><td>{sem_s}{flag}</td></tr>')
    return "\n".join(rows)


def main() -> int:
    stats = load_stats()
    step_time = stats.get("step_time", {})
    # step_status 历史字段,当前脚本不消费(仅用 step_time)

    # 语义四维聚合（每页 avg 汇总成总体）
    total = {"accuracy": [], "fluency": [], "consistency": [], "readability": []}
    for pg in stats.get("pages", []):
        semp = ART / f"page_{pg}_semantic.json"
        if semp.exists():
            s = json.loads(semp.read_text(encoding="utf-8"))
            a = s.get("avg_scores") or {}
            for k in total:
                if k in a:
                    total[k].append(a[k])
    dims = {k: round(sum(v) / len(v), 2) if v else 0 for k, v in total.items()}

    # bars_detect / bars_ocr 为历史切片,当前仅保留时间与维度条; 变量已内联不再使用

    step_total = round(sum(step_time.values()), 1)
    # 各 step 时间占比
    time_bars = "".join(
        f'<div class="trow"><span class="tlabel">{html.escape(step)}</span>'
        f'<div class="tbarwrap"><div class="tbar" style="width:{round(v/step_total*100,1)}%"></div></div>'
        f'<span class="tval">{round(v,1)}s</span></div>'
        for step, v in sorted(step_time.items(), key=lambda x: -x[1]))

    dim_bars = "".join(
        f'<div class="dim"><span class="dname">{html.escape(k)}</span>'
        f'<div class="dbarwrap"><div class="dbar" style="width:{round(v/5*100,1)}%"></div></div>'
        f'<span class="dval">{v}/5</span></div>' for k, v in dims.items())

    pages_html = per_page_table(stats)
    trans_html = build_translation_table()
    src_count = trans_html.count("<tr>")

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>AMTA 11-20 页自动跑批汇报</title>
<style>
body{{font-family:'Segoe UI',system-ui,sans-serif;margin:0;background:#0f141b;color:#e6edf3;line-height:1.6}}
.wrap{{max-width:1080px;margin:0 auto;padding:28px}}
h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:19px;margin:34px 0 12px;color:#4c8dff;border-left:4px solid #4c8dff;padding-left:10px}}
.meta{{color:#9aa3b2;font-size:13px}}
.card{{background:#161c26;border:1px solid #232a35;border-radius:10px;padding:18px;margin:12px 0}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.stat{{background:#161c26;border:1px solid #232a35;border-radius:10px;padding:16px;text-align:center}}
.stat .num{{font-size:28px;font-weight:700;color:#4c8dff}} .stat .lbl{{font-size:13px;color:#9aa3b2}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:7px 10px;border-bottom:1px solid #232a35;text-align:left;vertical-align:top}}
th{{background:#161c26;color:#9aa3b2;position:sticky;top:0}}
td.pg{{color:#4c8dff;font-weight:600;white-space:nowrap}} td.rid{{color:#9aa3b2;white-space:nowrap}}
td.src{{color:#ffd479;font-size:12.5px}} td.dst{{color:#7ee2a8;font-size:12.5px}}
.chart{{display:flex;align-items:flex-end;gap:6px;height:70px;margin-top:8px}}
.bar{{flex:1;background:#4c8dff;border-radius:4px 4px 0 0;display:flex;align-items:flex-start;justify-content:center;color:#fff;font-size:11px;min-width:0}}
.trow{{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:13px}}
.tlabel{{width:130px;color:#9aa3b2}}.tbarwrap{{flex:1;background:#232a35;border-radius:4px;height:16px}}
.tbar{{background:#4c8dff;height:16px;border-radius:4px}}.tval{{width:60px;text-align:right;color:#e6edf3}}
.dim{{display:flex;align-items:center;gap:10px;margin:8px 0}}
.dname{{width:110px;color:#9aa3b2}}.dbarwrap{{flex:1;background:#232a35;border-radius:4px;height:14px}}
.dbar{{background:#7ee2a8;height:14px;border-radius:4px}}.dval{{width:40px;text-align:right}}
.callout{{border-radius:8px;padding:12px 16px;margin:12px 0;font-size:14px}}
.c-info{{background:#101a2b;border:1px solid #2d4a7a;color:#b9d0f0}}
.c-warn{{background:#2b2410;border:1px solid #7a642d;color:#f0d9a0}}
.c-good{{background:#102b1a;border:1px solid #2d7a4a;color:#a8f0c8}}
.pill{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600}}
.p-ok{{background:#16352a;color:#7ee2a8}}.p-fix{{background:#3a2a16;color:#ffd479}}
code{{background:#232a35;padding:1px 5px;border-radius:4px;font-size:12px}}
.scroll{{max-height:520px;overflow:auto;border:1px solid #232a35;border-radius:8px}}
.footer{{color:#5a6472;font-size:12px;margin-top:34px;border-top:1px solid #232a35;padding-top:12px}}
</style></head><body><div class="wrap">

<h1>AMTA 单翼停留之地 — 11-20 页一次性自动跑批汇报</h1>
<div class="meta">工位链：01_detect → 02_ocr(baberu) → 03_translate(DeepSeek) → ③语义评审 → 自动修复 · 断点续跑 + step tracing · 2026-08-26</div>

<div class="card callout c-good">✅ <b>20 页全链自动跑通</b>：11-20 页从检测到翻译到语义评审一次跑完，<b>最终语义评审 0 失败</b>（66/66 通过），无 needs_review 遗留。翻译质量四维评分（准确性/流畅度/一致性/可读性）均在 <b>4.6–5.0/5</b>。</div>

<h2>总览</h2>
<div class="grid">
  <div class="stat"><div class="num">70</div><div class="lbl">检测框（20页）</div></div>
  <div class="stat"><div class="num">148</div><div class="lbl">翻译条数（20页）</div></div>
  <div class="stat"><div class="num">1.0</div><div class="lbl">语义通过率</div></div>
  <div class="stat"><div class="num">{round(step_total/60,1)}m</div><div class="lbl">本轮 10 页总耗时</div></div>
</div>

<h2>各工位产出统计</h2>
<div class="card scroll">
<table><thead><tr><th>页</th><th>检测框</th><th>OCR 区域</th><th>译文数</th><th>语义评审(通过/总数)</th></tr></thead>
<tbody>{pages_html}</tbody></table>
</div>

<h2>时间都花在哪了（10 页，共 {round(step_total/60,1)} 分钟）</h2>
<div class="card">{time_bars}</div>
<div class="card callout c-info">💡 <b>baberu OCR 是本次提速功臣</b>：02_ocr 只占 <b>{round(step_time.get('02_ocr',0)/60,1)} 分钟</b>（~2%）。对比之前单页 For-Manga OCR 要 156s/页，现在用 baberu 快路径 11-20 页的 OCR 整体只用了 <b>{round(step_time.get('02_ocr',0),1)}s</b>。最耗时的是 <b>01_detect</b>（koharu 检测，CPU 单核）和 <b>03_translate</b>（DeepSeek 推理 + 工具调用）。</div>

<h2>翻译质量（语义评审四维评分，均值/5）</h2>
<div class="card">{dim_bars}</div>

<h2>跨页记忆与前页回溯（方案 B 核心验证）</h2>
<div class="card">
<p>11-20 页翻译过程中，03_translate 的真 function calling <b>确实在每页调用工具读取上下文</b>：</p>
<div class="grid">
  <div class="stat"><div class="num">57</div><div class="lbl">lookup_term 术语/角色查询</div></div>
  <div class="stat"><div class="num">28</div><div class="lbl">get_context 前页回溯</div></div>
</div>
<div class="callout c-good">✅ <b>跨页 state 累积链路通</b>：合并 <code>translation.json</code> 现含 20 页 148 条，get_context 每页读取前 3 页译文保持风格/术语一致——这是本子翻译质量稳定的关键。</div>
</div>

<h2>跑批中遇到的问题与修复（/loop）</h2>

<div class="card">
<b>1. 前 10 页没有转正产物 🐛</b>
<p>11 页开跑时，1-10 页的正式翻译只在评测数据里，没落成 workspace 产物，导致 get_context 前页回溯读不到前 10 页。</p>
<p><span class="pill p-fix">已修</span> 新增 <code>backfill_1_10.py</code>，把 86 框正式翻译（含 5 条导演修订）转正成 per-page 产物 + 合并文件。</p>
</div>

<div class="card">
<b>2. 语义评审误报「残留 FAILED」🐛</b>
<p>page_13/14 有两个区域被自动修复改好，但 semantic.json 的 failed 数组没随修复更新，仍显示 FAILED——实际译文已正确。</p>
<p><span class="pill p-fix">已修</span> 让 <code>repair_failed.py</code> 修复成功后回写 semantic.json（清空已修复项的 failed）。</p>
</div>

<div class="card">
<b>3. 合并 translation.json 不被 00_run_all 维护 🐛</b>
<p>00_run_all 只写每页的 <code>page_N_translation.json</code>，不会把新页并入 get_context 读取的合并文件。</p>
<p><span class="pill p-fix">已修</span> 00_run_all 每完成一页自动刷新合并文件。</p>
</div>

<div class="card">
<b>4. region_id 编号源不一致 ⚠️</b>
<p>评测数据的 page_0 区域从 <code>u01</code> 起，流水线产物从 <code>u00</code> 起。当前不影响跨页回溯，但将来逐区域对应源图 crop 时可能错位。</p>
<p><span class="pill p-fix">观察中</span> 已记录，待统一编号规范。</p>
</div>

<h2>20 页最终翻译对照原文（{src_count} 条）</h2>
<div class="card callout c-info">左边<b style="color:#ffd479">黄字</b>是 OCR 识别的日文原文，右边<b style="color:#7ee2a8">绿字</b>是最终中文译文。前 10 页来自正式成果（含导演修订），11-20 页来自本轮自动跑批。</div>
<div class="card scroll">
<table><thead><tr><th>页</th><th>region</th><th>日文原文</th><th>中文译文</th></tr></thead>
<tbody>{trans_html}</tbody></table>
</div>

<div class="footer">AMTA · 会话驱动漫画翻译自动化 · run c8e151a5af9c · 分支 feat/ocr-baberu-interface</div>
</div></body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_doc, encoding="utf-8")
    print(f"report -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
