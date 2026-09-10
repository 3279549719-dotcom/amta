"""Q6 A/B 报告：有前缀(main) vs 无前缀(实验分支) 翻译质量对比。

读取两个 workspace 的 translation JSON + final 成品图，生成 HTML 对比报告。
用法: uv run python scripts/probes/gen_q6_ab_report.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # amta/
WS_A = ROOT / "workspace" / "ab-prefix-a"
WS_B = ROOT / "workspace" / "ab-no-prefix-b"
PAGES = [10, 11, 12, 13, 14, 15]
OUT = ROOT / "workspace" / "q6-ab-report.html"


def load_translations(ws: Path, page: int) -> dict[str, str]:
    p = ws / "artifacts" / "translation" / f"page_{page}.json"
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return doc.get("translations", {})


def load_canon(ws: Path, page: int) -> list[dict]:
    p = ws / "artifacts" / "canon" / f"page_{page}.json"
    if not p.exists():
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    return doc.get("items", doc.get("regions", []))


def final_image(ws: Path, page: int) -> Path | None:
    p = ws / "artifacts" / "final" / f"page_{page}_final.png"
    return p if p.exists() else None


def main():
    rows = []
    stats = {"total": 0, "same": 0, "diff": 0, "a_empty": 0, "b_empty": 0, "both_empty": 0}

    for page in PAGES:
        ta = load_translations(WS_A, page)
        tb = load_translations(WS_B, page)
        canon = load_canon(WS_A, page)
        all_ids = list(dict.fromkeys(list(ta.keys()) + list(tb.keys())))

        page_diffs = []
        for rid in all_ids:
            a = ta.get(rid, "")
            b = tb.get(rid, "")
            stats["total"] += 1
            if a == b:
                stats["same"] += 1
            else:
                stats["diff"] += 1
                page_diffs.append((rid, a, b))
            if not a and not b:
                stats["both_empty"] += 1
            elif not a:
                stats["a_empty"] += 1
            elif not b:
                stats["b_empty"] += 1

        # OCR text lookup
        ocr_map = {}
        for item in canon:
            rid = item.get("region_id", "")
            text = item.get("baberu_text") or item.get("text") or item.get("ocr") or ""
            if rid:
                ocr_map[rid] = text

        fa = final_image(WS_A, page)
        fb = final_image(WS_B, page)

        diff_html = ""
        if page_diffs:
            diff_rows = ""
            for rid, a, b in page_diffs:
                ocr = ocr_map.get(rid, "")
                diff_rows += f"""<tr>
                    <td style="font-family:monospace;font-size:11px;color:#6B7280;">{rid}</td>
                    <td style="font-size:12px;">{ocr}</td>
                    <td style="font-size:12px;background:#EFF6FF;">{a or '<em style="color:#9CA3AF;">(空)</em>'}</td>
                    <td style="font-size:12px;background:#F0FDF4;">{b or '<em style="color:#9CA3AF;">(空)</em>'}</td>
                </tr>"""
            diff_html = f"""
            <div style="margin-top:12px;">
                <div style="font-size:12px;font-weight:600;color:#DC2626;margin-bottom:6px;">翻译差异 ({len(page_diffs)} 条)</div>
                <table style="width:100%;border-collapse:collapse;font-size:12px;">
                    <thead><tr style="background:#F3F4F6;">
                        <th style="text-align:left;padding:4px 8px;">region</th>
                        <th style="text-align:left;padding:4px 8px;">OCR原文</th>
                        <th style="text-align:left;padding:4px 8px;background:#DBEAFE;">A 有前缀</th>
                        <th style="text-align:left;padding:4px 8px;background:#D1FAE5;">B 无前缀</th>
                    </tr></thead>
                    <tbody>{diff_rows}</tbody>
                </table>
            </div>"""

        img_a = f'<img src="file:///{fa.as_posix()}" style="width:100%;border:1px solid #E5E7EB;border-radius:4px;">' if fa else '<div style="color:#9CA3AF;font-size:12px;padding:20px;text-align:center;">(无成品图)</div>'
        img_b = f'<img src="file:///{fb.as_posix()}" style="width:100%;border:1px solid #E5E7EB;border-radius:4px;">' if fb else '<div style="color:#9CA3AF;font-size:12px;padding:20px;text-align:center;">(无成品图)</div>'

        rows.append(f"""
        <div style="background:#fff;border:1px solid #E5E7EB;border-radius:8px;padding:16px;margin-bottom:20px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <h3 style="margin:0;font-size:16px;color:#1F2937;">Page {page}</h3>
                <span style="font-size:11px;color:#6B7280;">翻译 {len(ta)} 条 / 差异 {len(page_diffs)} 条</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                <div><div style="font-size:11px;font-weight:600;color:#2563EB;margin-bottom:4px;">A — 有前缀 (main)</div>{img_a}</div>
                <div><div style="font-size:11px;font-weight:600;color:#059669;margin-bottom:4px;">B — 无前缀 (实验)</div>{img_b}</div>
            </div>
            {diff_html}
        </div>""")

    pct_same = (stats["same"] / stats["total"] * 100) if stats["total"] else 0
    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>Q6 A/B 报告 — 翻译输入前缀移除</title>
<style>body{{margin:0;padding:20px;background:#F9FAFB;font-family:"PingFang SC","Segoe UI",Arial,sans-serif;}}</style>
</head><body>
<div style="max-width:1100px;margin:0 auto;">
    <h1 style="font-size:22px;color:#111827;margin-bottom:4px;">Q6 A/B 实验 — 翻译输入 region_id 前缀移除</h1>
    <p style="font-size:13px;color:#6B7280;margin-bottom:20px;">
        A 组 (main): 输入格式 <code style="background:#E5E7EB;padding:1px 4px;border-radius:3px;">r01|日文</code> + 前缀剥离后处理<br>
        B 组 (实验分支): 输入格式纯日文逐行 + 无前缀剥离<br>
        页面: {PAGES[0]}-{PAGES[-1]} (共 {len(PAGES)} 页) · detect/OCR 两组完全一致，仅翻译层输入格式不同
    </p>
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:24px;">
        <div style="background:#fff;border:1px solid #E5E7EB;border-radius:8px;padding:12px;text-align:center;">
            <div style="font-size:24px;font-weight:700;color:#1F2937;">{stats['total']}</div>
            <div style="font-size:11px;color:#6B7280;">总翻译条</div>
        </div>
        <div style="background:#fff;border:1px solid #E5E7EB;border-radius:8px;padding:12px;text-align:center;">
            <div style="font-size:24px;font-weight:700;color:#059669;">{stats['same']}</div>
            <div style="font-size:11px;color:#6B7280;">完全相同 ({pct_same:.1f}%)</div>
        </div>
        <div style="background:#fff;border:1px solid #E5E7EB;border-radius:8px;padding:12px;text-align:center;">
            <div style="font-size:24px;font-weight:700;color:#DC2626;">{stats['diff']}</div>
            <div style="font-size:11px;color:#6B7280;">翻译差异</div>
        </div>
        <div style="background:#fff;border:1px solid #E5E7EB;border-radius:8px;padding:12px;text-align:center;">
            <div style="font-size:24px;font-weight:700;color:#2563EB;">{stats['a_empty']}</div>
            <div style="font-size:11px;color:#6B7280;">仅A为空</div>
        </div>
        <div style="background:#fff;border:1px solid #E5E7EB;border-radius:8px;padding:12px;text-align:center;">
            <div style="font-size:24px;font-weight:700;color:#059669;">{stats['b_empty']}</div>
            <div style="font-size:11px;color:#6B7280;">仅B为空</div>
        </div>
    </div>
    {''.join(rows)}
</div></body></html>"""

    OUT.write_text(html, encoding="utf-8")
    print(f"Report -> {OUT}")
    print(f"Stats: {stats}")


if __name__ == "__main__":
    main()
