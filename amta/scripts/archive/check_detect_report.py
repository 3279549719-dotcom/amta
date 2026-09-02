"""check_detect_report — 逐框核对报告：把检测框(regions/blocks)可视化 + 对照用户手工真值。

用于 detect 修复的 eyeballing：每页列出框坐标/类型/sub_tier，标出疑似假阳性(面积过小/
type 不可靠)，裁剪图内嵌 HTML，对照用户手工真值标注 Δ。

读: output/data/detect_contract_p*.json 或 detect_union_11_20/p*.json (含 blocks)
写: output/reports/detect_check_11_20.html
用法: python scripts/check_detect_report.py [--src output/data/detect_contract] [--pattern p*.json]
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# 用户手工真值(Grill 定案): p11=8,p12=5,p13=11,p14=16,p15=10,p16=10,p17=10/11,p18=10,p19=7,p20=10
MANUAL = {11: 8, 12: 5, 13: 11, 14: 16, 15: 10, 16: 10, 17: 11, 18: 10, 19: 7, 20: 10}

# 假阳性启发式: 面积过小的框(极可能网点/花纹噪点)
MIN_AREA = 1500  # px², 低于此疑似假阳性(可调)


def _is_suspicious(bbox: list) -> bool:
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    return (w * h) < MIN_AREA


def _crop_b64(raw: Path, bbox: list, pad: int = 8) -> str:
    """把框裁剪成 base64 PNG(内嵌 HTML)。"""
    from io import BytesIO
    from PIL import Image
    try:
        img = Image.open(raw)
        x0 = max(0, int(bbox[0]) - pad)
        y0 = max(0, int(bbox[1]) - pad)
        x1 = min(img.width, int(bbox[2]) + pad)
        y1 = min(img.height, int(bbox[3]) + pad)
        crop = img.crop((x0, y0, x1, y1))
        buf = BytesIO()
        crop.save(buf, format="PNG")
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception:  # noqa: BLE001
        return ""


def _blocks_of(doc: dict) -> list[dict]:
    """优先取 regions 展平(容器自身+child_lines), 回退 blocks。"""
    if doc.get("regions"):
        out = []
        for r in doc["regions"]:
            if r.get("child_lines"):
                for line in r["child_lines"]:
                    it = dict(line)
                    it.setdefault("container", r.get("bbox"))
                    out.append(it)
            else:
                out.append(dict(r))
        return out
    return doc.get("blocks", [])


def build_report(det_dir: Path, raw_dir: Path, pattern: str) -> str:
    rows = []
    for f in sorted(glob.glob(str(det_dir / pattern))):
        doc = json.loads(Path(f).read_text(encoding="utf-8"))
        page = int(Path(f).stem.lstrip("p"))  # p11.json -> 11
        raw = raw_dir / f"{page}.jpg"
        if not raw.exists():
            raw = raw_dir / f"{page}.png"
        blocks = _blocks_of(doc)
        manual = MANUAL.get(page, "?")
        n = len(blocks)
        delta = f"{n - manual:+d}" if isinstance(manual, int) else ""
        susp = [b for b in blocks if _is_suspicious(b["bbox"])]
        rows.append(
            f'<tr><td class="pg">p{page}</td><td>{manual}</td><td>{n}</td>'
            f'<td class="{("danger" if isinstance(delta,str) and delta.startswith("-") else "")}">{delta}</td>'
            f'<td>{len(susp)}</td><td class="rows">{"<br>".join(_block_cell(b, raw) for b in blocks)}</td></tr>'
        )
    return rows


def _block_cell(b: dict, raw: Path) -> str:
    bb = b.get("bbox")
    if not bb:
        return ""
    flag = " ⚠️" if _is_suspicious(bb) else ""
    st = f' <span class="st">{b.get("sub_tier","")}</span>' if b.get("sub_tier") else ""
    img = _crop_b64(raw, bb)
    return (
        f'<div class="bcell"><img src="{img}"/>'
        f'<div class="binfo">[{int(bb[0])},{int(bb[1])},{int(bb[2])},{int(bb[3])}] '
        f'{b.get("bubble_type","")}{st}{flag}</div></div>'
    )


def render(det_dir: Path, raw_dir: Path, pattern: str, out: Path) -> None:
    rows = build_report(det_dir, raw_dir, pattern)
    out.parent.mkdir(parents=True, exist_ok=True)
    body_rows = "\n".join(rows)
    html_doc = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Detect 逐框核对报告</title><style>
body{{font-family:system-ui;margin:24px;background:#0f141b;color:#e6edf3}}
h1{{font-size:22px}} table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #334;padding:8px;vertical-align:top;text-align:left;font-size:12px}}
th{{background:#1a2230}} .pg{{color:#4c8dff;font-weight:700;white-space:nowrap}}
.danger{{color:#ff6b6b}} .rows{{min-width:420px}}
.bcell{{display:inline-block;margin:2px;border:1px solid #445;padding:2px;width:96px;vertical-align:top}}
.bcell img{{width:88px;height:auto;display:block}}
.binfo{{font-size:9px;color:#9aa3b2;word-break:break-all}} .st{{color:#5fe3b3}}
</style></head><body><h1>Detect 逐框核对报告</h1>
<p>手工真值 vs 检出框数 vs 疑似假阳性(面积<{MIN_AREA}px²)。<b>⚠️</b>=疑似假阳性。</p>
<table><tr><th>页</th><th>你真值</th><th>检出</th><th>Δ</th><th>⚠️疑似</th><th>框明细(裁剪图)</th></tr>
{body_rows}</table></body></html>"""
    out.write_text(html_doc, encoding="utf-8")
    print(f"[check_detect_report] -> {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--det", type=Path,
                    default=Path(__file__).resolve().parent.parent / "output" / "data" / "detect_contract")
    ap.add_argument("--raw", type=Path, default=Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地"))
    ap.add_argument("--pattern", default="p*.json")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent.parent / "output" / "reports" / "detect_check_11_20.html")
    a = ap.parse_args()
    render(a.det, a.raw, a.pattern, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
