"""eval_stage2 — Front3 Stage 2 端到端验证(Baberu + VLM 双引擎会诊)。

跑 11-20 页: 02_ocr(detection.json → canon.json 双引擎文本),汇总指标,
生成 HTML 报告(漫画原图 + crop 图 + baberu/vlm OCR 文本对照)。

用法: python scripts/eval_stage2.py [--pages 11 12 ...] [--engine baberu]
输出: artifacts/page_{n}_canon.json + artifacts/eval_stage2_report.html
Refs ADR-023。
"""
from __future__ import annotations

import argparse
import base64
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402
from amta.artifacts import load_canon  # noqa: E402

WORKTREE = Path(__file__).resolve().parent.parent
ARTIFACTS = WORKTREE / "workspace" / "touhou-single-wing" / "artifacts"
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
REPORT = ARTIFACTS / "eval_stage2_report.html"


def b64_img(img: Image.Image, max_w: int = 480, quality: int = 70) -> str:
    """PIL 图 → base64 JPEG(缩放宽 max_w)。"""
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, max(1, int(img.height * ratio))), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def crop_b64(crop_path: Path, target_h: int = 150) -> str:
    """crop 图 → base64(统一高 target_h,过小放大)。"""
    img = Image.open(crop_path)
    scale = target_h / img.height
    new_w = max(1, int(img.width * scale))
    img = img.resize((new_w, target_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=72)
    return base64.b64encode(buf.getvalue()).decode()


def run_page(page: int, engine: str) -> dict | None:
    """跑单页 02_ocr,返回摘要 dict。"""
    from _02_ocr import run as ocr_run  # type: ignore[import-not-found]

    det_path = ARTIFACTS / f"page_{page}_detection.json"
    raw_path = RAW_DIR / f"{page}.jpg"
    out_path = ARTIFACTS / f"page_{page}_canon.json"
    crop_dir = ARTIFACTS / "crops" / f"page_{page}"
    if not det_path.exists() or not raw_path.exists():
        print(f"  [SKIP] page {page}: det/raw 缺失")
        return None
    if out_path.exists():
        print(f"  [CACHE] page {page}: canon 已存在")
    else:
        t0 = time.time()
        ocr_run(
            work_id="touhou-single-wing",
            det_path=det_path,
            raw_page=raw_path,
            out_path=out_path,
            page_idx=page,
            crop_dir=crop_dir,
            engine=engine,
            vlm_enabled=True,
        )
        print(f"  [OK] page {page}: {time.time() - t0:.0f}s")
    items = load_canon(out_path)["items"]  # 契约层读取（doc 化，修 F2）；删除双形状防御

    import difflib

    def sim(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio()

    both = [i for i in items if (i.get("baberu_text") or "").strip() and (i.get("vlm_text") or "").strip()]
    exact = [i for i in both if (i.get("baberu_text") or "").strip() == (i.get("vlm_text") or "").strip()]
    similar = [i for i in both if sim((i.get("baberu_text") or "").strip(), (i.get("vlm_text") or "").strip()) >= 0.6]
    return {
        "page": page,
        "n_regions": len(items),
        "baberu_nonempty": sum(1 for i in items if (i.get("baberu_text") or "").strip()),
        "vlm_nonempty": sum(1 for i in items if (i.get("vlm_text") or "").strip()),
        "both_nonempty": len(both),
        "match": len(similar),
        "match_exact": len(exact),
        "match_rate": round(len(similar) / len(both), 3) if both else None,
        "vlm_status": items[0].get("vlm_status") if items else "?",
        "items": items,
        "crop_dir": crop_dir,
        "raw_path": raw_path,
    }


HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>AMTA Stage 2 双引擎 OCR 验证报告</title>
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
 .match {{ color:#1e8449; font-size:11px; }} .diff {{ color:#c0392b; font-size:11px; font-weight:bold; }}
 .empty {{ color:#b2bec3; font-style:italic; }}
 .meta {{ font-size:12px; color:#636e72; margin-bottom:8px; }}
 .ok {{ color:#1e8449; font-weight:bold; }} .bad {{ color:#c0392b; font-weight:bold; }}
</style></head><body>
<h1>🦞 AMTA Stage 2 双引擎 OCR 验证报告</h1>
<div class="sub">{generated} · 页 {pages} · Baberu(本地 ONNX) vs DeepSeek VLM(contact sheet) · ADR-023</div>
<table><tr><th>页</th><th>框数</th><th>Baberu 非空</th><th>VLM 非空</th><th>可比对</th><th>近似一致(≥0.6)</th><th>一致率</th><th>VLM 状态</th></tr>
{summary_rows}
</table>
{page_sections}
</body></html>"""


def page_section(r: dict) -> str:
    rows = []
    for i in r["items"]:
        rid = i.get("region_id", "?")
        bab = (i.get("baberu_text") or "").strip()
        vlm = (i.get("vlm_text") or "").strip()
        crop_path = r["crop_dir"] / f"{rid}.png"
        img_html = ""
        if crop_path.exists():
            img_html = f'<img src="data:image/jpeg;base64,{crop_b64(crop_path)}">'
        else:
            img_html = '<div class="empty">(crop 缺失)</div>'
        if bab and vlm:
            import difflib

            ratio = difflib.SequenceMatcher(None, bab, vlm).ratio()
            if bab == vlm:
                flag = '<span class="match">✓ 完全一致</span>'
            elif ratio >= 0.6:
                flag = f'<span class="match">≈ 近似一致({ratio:.0%})</span>'
            else:
                flag = f'<span class="diff">✗ 差异大({ratio:.0%})</span>'
        else:
            flag = '<span class="empty">单边空</span>'
        bab_html = bab if bab else '<span class="empty">(空)</span>'
        vlm_html = vlm if vlm else '<span class="empty">(空)</span>'
        rows.append(
            f'<div class="crop">{img_html}<div class="rid">{rid} contained_in={i.get("contained_in")}</div>'
            f'<div class="t baberu">Baberu: {bab_html}</div>'
            f'<div class="t vlm">VLM: {vlm_html}</div><div>{flag}</div></div>'
        )
    orig = ""
    if Path(r["raw_path"]).exists():
        orig = f'<img class="orig" src="data:image/jpeg;base64,{b64_img(Image.open(r["raw_path"]))}">'
    rate = f'{r["match_rate"]:.0%}' if r["match_rate"] is not None else "-"
    return (
        f'<div class="page"><h2>Page {r["page"]} <span class="meta">'
        f'{r["n_regions"]} 框 · 一致率 {rate} · vlm={r["vlm_status"]}</span></h2>'
        f'{orig}<div class="cropgrid">{"".join(rows)}</div><div style="clear:both"></div></div>'
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 2 双引擎验证")
    ap.add_argument("--pages", type=int, nargs="+", default=list(range(11, 21)))
    ap.add_argument("--engine", default="baberu", choices=["baberu", "auto", "local"])
    a = ap.parse_args()

    print(f"[eval_stage2] pages={a.pages} engine={a.engine}")
    results = []
    for p in a.pages:
        r = run_page(p, a.engine)
        if r:
            results.append(r)

    total_regions = sum(r["n_regions"] for r in results)
    total_both = sum(r["both_nonempty"] for r in results)
    total_match = sum(r["match"] for r in results)
    overall = round(total_match / total_both, 3) if total_both else None
    print(f"[eval_stage2] 总框数={total_regions} 可比对={total_both} 一致={total_match} 一致率={overall}")

    rows = []
    for r in results:
        rate = f'{r["match_rate"]:.0%}' if r["match_rate"] is not None else "-"
        vs = r["vlm_status"]
        vs_html = f'<span class="ok">{vs}</span>' if vs == "ok" else f'<span class="bad">{vs}</span>'
        rows.append(
            f'<tr><td>{r["page"]}</td><td>{r["n_regions"]}</td><td>{r["baberu_nonempty"]}</td>'
            f'<td>{r["vlm_nonempty"]}</td><td>{r["both_nonempty"]}</td><td>{r["match"]}</td>'
            f'<td>{rate}</td><td>{vs_html}</td></tr>'
        )
    rows.append(
        f'<tr><td><b>总计</b></td><td><b>{total_regions}</b></td><td></td><td></td>'
        f'<td><b>{total_both}</b></td><td><b>{total_match}</b></td>'
        f'<td><b>{overall:.0%}</b> </td><td></td></tr>'.replace(f"{overall:.0%}", f"{overall:.0%}" if overall else "-")
        if overall is not None else
        f'<tr><td><b>总计</b></td><td><b>{total_regions}</b></td><td></td><td></td>'
        f'<td><b>{total_both}</b></td><td><b>{total_match}</b></td><td>-</td><td></td></tr>'
    )

    html = HTML_TMPL.format(
        generated=time.strftime("%Y-%m-%d %H:%M"),
        pages=", ".join(str(p) for p in a.pages),
        summary_rows="\n".join(rows),
        page_sections="\n".join(page_section(r) for r in results),
    )
    REPORT.write_text(html, encoding="utf-8")
    print(f"[eval_stage2] 报告 -> {REPORT} ({REPORT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
