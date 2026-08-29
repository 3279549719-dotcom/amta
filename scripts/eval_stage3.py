"""eval_stage3 — Front3 Stage 3 端到端验证（纯文本语义翻译，DeepSeek）。

对已完成 Stage 2 的页跑 03_translate（双引擎文本 → 译文），汇总指标，
生成 HTML 报告（漫画原图 + crop 图 + baberu/vlm 原文 + 中文译文对照）。

用法: python scripts/eval_stage3.py [--pages 11 12 13 14 15]
输出: artifacts/page_{n}_translation.json + artifacts/eval_stage3_report.html
Refs ADR-023。
"""
from __future__ import annotations

import argparse
import base64
import difflib
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

WORKTREE = Path(__file__).resolve().parent.parent
ARTIFACTS = WORKTREE / "workspace" / "touhou-single-wing" / "artifacts"
STATE_DIR = WORKTREE / "workspace" / "touhou-single-wing" / "state"
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
REPORT = ARTIFACTS / "eval_stage3_report.html"
WORK_ID = "touhou-single-wing"


def b64_img(img: Image.Image, max_w: int = 480, quality: int = 70) -> str:
    """PIL 图 → base64 JPEG(缩放宽 max_w)。"""
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, max(1, int(img.height * ratio))), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def crop_b64(crop_path: Path, target_h: int = 150) -> str:
    """crop 图 → base64(统一高 target_h)。"""
    img = Image.open(crop_path)
    scale = target_h / img.height
    new_w = max(1, int(img.width * scale))
    img = img.resize((new_w, target_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=72)
    return base64.b64encode(buf.getvalue()).decode()


def sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def run_page(page: int) -> dict | None:
    """跑单页 03_translate，返回摘要 dict（translation 已存在则复用）。"""
    from _03_translate import run as translate_run  # type: ignore[import-not-found]

    canon_path = ARTIFACTS / f"page_{page}_canon.json"
    out_path = ARTIFACTS / f"page_{page}_translation.json"
    raw_path = RAW_DIR / f"{page}.jpg"
    crop_dir = ARTIFACTS / "crops" / f"page_{page}"
    if not canon_path.exists():
        print(f"  [SKIP] page {page}: canon 缺失（先跑 eval_stage2）")
        return None
    if out_path.exists():
        print(f"  [CACHE] page {page}: translation 已存在")
    else:
        t0 = time.time()
        translate_run(
            canon_path,
            out_path,
            work_id=WORK_ID,
            state_dir=STATE_DIR,
        )
        print(f"  [OK] page {page}: {time.time() - t0:.0f}s")

    canon = json.loads(canon_path.read_text(encoding="utf-8"))
    trans_doc = json.loads(out_path.read_text(encoding="utf-8"))
    translations = trans_doc.get("translations", {})
    trace_path = ARTIFACTS / f"{page}_03_translate_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8")) if trace_path.exists() else {}

    filled = [t for t in translations.values() if (t or "").strip()]
    empty_rids = [r["region_id"] for r in canon if not (translations.get(r["region_id"]) or "").strip()]
    diff_regions = []
    for r in canon:
        bab = (r.get("baberu_text") or "").strip()
        vlm = (r.get("vlm_text") or "").strip()
        if bab and vlm and bab != vlm and sim(bab, vlm) < 0.6:
            diff_regions.append(r["region_id"])
    return {
        "page": page,
        "n_regions": len(canon),
        "n_translated": len(filled),
        "n_empty": len(empty_rids),
        "empty_rids": empty_rids,
        "residue": trans_doc.get("residue", []),
        "glossary_violations": trans_doc.get("glossary_violations", []),
        "n_diff": len(diff_regions),
        "diff_rids": diff_regions,
        "elapsed": trace.get("translate_elapsed"),
        "model": trace.get("model", "?"),
        "canon": canon,
        "translations": translations,
        "crop_dir": crop_dir,
        "raw_path": raw_path,
    }


HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>AMTA Stage 3 纯文本语义翻译验证报告</title>
<style>
 body {{ font-family: "Microsoft YaHei", sans-serif; background:#f5f6fa; margin:0; padding:20px; color:#2d3436; }}
 h1 {{ font-size:20px; }} .sub {{ color:#636e72; font-size:13px; margin-bottom:16px; }}
 table {{ border-collapse: collapse; background:#fff; width:100%; font-size:13px; }}
 th, td {{ border:1px solid #dfe6e9; padding:5px 10px; text-align:left; }}
 th {{ background:#eaf4ff; }}
 .page {{ background:#fff; border-radius:10px; padding:14px 18px; margin:14px 0; box-shadow:0 1px 4px rgba(0,0,0,.08); }}
 .page h2 {{ font-size:15px; margin:0 0 10px; }}
 .orig {{ float:right; margin-left:14px; border:1px solid #dfe6e9; border-radius:6px; }}
 .cropgrid {{ display:flex; flex-wrap:wrap; gap:10px; clear:both; }}
 .crop {{ background:#f8f9fa; border:1px solid #dfe6e9; border-radius:8px; padding:8px; width:236px; }}
 .crop img {{ max-width:220px; max-height:170px; display:block; margin-bottom:6px; background:#fff; }}
 .rid {{ font-size:11px; color:#636e72; font-family:Consolas,monospace; }}
 .t {{ font-size:12px; line-height:1.6; margin:2px 0; }}
 .baberu {{ color:#0984e3; }} .vlm {{ color:#6c5ce7; }}
 .zh {{ color:#1e8449; font-weight:bold; background:#eafaf1; border-radius:4px; padding:2px 4px; margin-top:4px; }}
 .match {{ color:#1e8449; font-size:11px; }} .diff {{ color:#c0392b; font-size:11px; font-weight:bold; }}
 .empty {{ color:#b2bec3; font-style:italic; }}
 .meta {{ font-size:12px; color:#636e72; margin-bottom:8px; }}
 .ok {{ color:#1e8449; font-weight:bold; }} .bad {{ color:#c0392b; font-weight:bold; }}
 .nest {{ background:#fff3cd; color:#856404; font-size:11px; border-radius:4px; padding:1px 5px; }}
</style></head><body>
<h1>🦞 AMTA Stage 3 纯文本语义翻译验证报告</h1>
<div class="sub">{generated} · 页 {pages} · 双引擎 OCR(baberu+vlm) → DeepSeek({model}) 一次性裁决 · ADR-023</div>
<table><tr><th>页</th><th>框数</th><th>有译文</th><th>空译文</th><th>双引擎差异大</th><th>日文残留</th><th>术语违例</th><th>耗时(s)</th></tr>
{summary_rows}
</table>
{page_sections}
</body></html>"""


def page_section(r: dict) -> str:
    rows = []
    for i in r["canon"]:
        rid = i.get("region_id", "?")
        bab = (i.get("baberu_text") or "").strip()
        vlm = (i.get("vlm_text") or "").strip()
        zh = (r["translations"].get(rid) or "").strip()
        crop_path = r["crop_dir"] / f"{rid}.png"
        if crop_path.exists():
            img_html = f'<img src="data:image/jpeg;base64,{crop_b64(crop_path)}">'
        else:
            img_html = '<div class="empty">(crop 缺失)</div>'

        engine_flag = ""
        if bab and vlm:
            ratio = sim(bab, vlm)
            if bab == vlm:
                engine_flag = '<span class="match">✓ 引擎一致</span>'
            elif ratio >= 0.6:
                engine_flag = f'<span class="match">≈ 近似({ratio:.0%})</span>'
            else:
                engine_flag = f'<span class="diff">✗ 差异大({ratio:.0%})</span>'
        else:
            engine_flag = '<span class="empty">单边空</span>'

        nest = ""
        if i.get("contained_in"):
            nest = f' <span class="nest">嵌套于 {i["contained_in"]}</span>'

        bab_html = bab if bab else '<span class="empty">(空)</span>'
        vlm_html = vlm if vlm else '<span class="empty">(空)</span>'
        zh_html = f'<div class="t zh">译: {zh}</div>' if zh else '<div class="t zh">(空译文)</div>'
        rows.append(
            f'<div class="crop">{img_html}<div class="rid">{rid}{nest} {engine_flag}</div>'
            f'<div class="t baberu">B: {bab_html}</div>'
            f'<div class="t vlm">V: {vlm_html}</div>{zh_html}</div>'
        )
    orig = ""
    if Path(r["raw_path"]).exists():
        orig = f'<img class="orig" src="data:image/jpeg;base64,{b64_img(Image.open(r["raw_path"]))}">'
    warnings = ""
    if r["empty_rids"]:
        warnings += f' <span class="bad">空译文: {", ".join(r["empty_rids"])}</span>'
    if r["residue"]:
        warnings += f' <span class="bad">残留: {len(r["residue"])}</span>'
    if r["glossary_violations"]:
        warnings += f' <span class="bad">术语: {len(r["glossary_violations"])}</span>'
    return (
        f'<div class="page"><h2>Page {r["page"]} <span class="meta">'
        f'{r["n_regions"]} 框 · 译文 {r["n_translated"]} · 差异大 {r["n_diff"]} · {r["elapsed"]}s{warnings}</span></h2>'
        f'{orig}<div class="cropgrid">{"".join(rows)}</div><div style="clear:both"></div></div>'
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 3 纯文本翻译验证")
    ap.add_argument("--pages", type=int, nargs="+", default=[11, 12, 13, 14, 15])
    a = ap.parse_args()

    print(f"[eval_stage3] pages={a.pages}")
    results = []
    for p in a.pages:
        r = run_page(p)
        if r:
            results.append(r)

    total_regions = sum(r["n_regions"] for r in results)
    total_trans = sum(r["n_translated"] for r in results)
    total_diff = sum(r["n_diff"] for r in results)
    total_residue = sum(len(r["residue"]) for r in results)
    total_gloss = sum(len(r["glossary_violations"]) for r in results)
    print(f"[eval_stage3] 总框数={total_regions} 有译文={total_trans} 差异大={total_diff} "
          f"残留={total_residue} 术语违例={total_gloss}")

    rows = []
    for r in results:
        rows.append(
            f'<tr><td>{r["page"]}</td><td>{r["n_regions"]}</td><td>{r["n_translated"]}</td>'
            f'<td>{r["n_empty"] or ""}</td><td>{r["n_diff"]}</td>'
            f'<td>{len(r["residue"]) or ""}</td><td>{len(r["glossary_violations"]) or ""}</td>'
            f'<td>{r["elapsed"]}</td></tr>'
        )
    rows.append(
        f'<tr><td><b>总计</b></td><td><b>{total_regions}</b></td><td><b>{total_trans}</b></td>'
        f'<td><b>{total_regions - total_trans}</b></td><td><b>{total_diff}</b></td>'
        f'<td><b>{total_residue}</b></td><td><b>{total_gloss}</b></td><td></td></tr>'
    )

    model = results[0]["model"] if results else "?"
    html = HTML_TMPL.format(
        generated=time.strftime("%Y-%m-%d %H:%M"),
        pages=", ".join(str(p) for p in a.pages),
        model=model,
        summary_rows="\n".join(rows),
        page_sections="\n".join(page_section(r) for r in results),
    )
    REPORT.write_text(html, encoding="utf-8")
    print(f"[eval_stage3] 报告 -> {REPORT} ({REPORT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
