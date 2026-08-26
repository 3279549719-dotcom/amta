"""Generate a benchmark report for For-Manga ONLY, in the same style as
benchmark_b_paddle_manga.html (Summary by type + Rows worst-first).
Input: output/data/benchmark86_for_manga.json
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.paths import DATA, REPORTS, ensure_utf8_stdio, read_json  # noqa: E402

ensure_utf8_stdio()

SRC = DATA / "benchmark86_for_manga.json"
OUT = REPORTS / "ocr_benchmark_for_manga.html"


def h(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    data = read_json(SRC)
    summary = data["summary"]
    rows = list(data["rows"])
    # worst-first by CER, tiebreak by page
    rows.sort(key=lambda r: (-r["cer"], r["page"]))

    L = ['<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">',
         "<title>OCR Benchmark — For-Manga (86 aligned frames)</title>",
         "<style>body{font-family:system-ui;margin:24px}table{border-collapse:collapse;width:100%;font-size:13px}",
         "td,th{border:1px solid #ddd;padding:4px 8px;text-align:left}tr.bad td{background:#fff0f0}",
         ".ok td{background:#f0fff0}h2{margin-top:28px}</style></head><body>",
         "<h1>OCR Benchmark — PaddleOCR-VL-For-Manga (llama-server local)</h1>",
         "<p>86 detector-aligned GT frames, unified norm. 2 other engines excluded.</p>",
         "<h2>Summary</h2><table><tr><th>type</th><th>n</th><th>CER</th><th>EM</th></tr>"]
    for t in ["dialogue_in", "dialogue_out", "sfx", "bg_text", "ALL"]:
        s = summary[t]
        L.append(f"<tr><td>{t}</td><td>{s['n']}</td><td>{s['cer']:.3f}</td><td>{s['em']:.3f}</td></tr>")
    L.append("</table>")

    L.append("<h2>Rows (worst first)</h2>"
             "<table><tr><th>page</th><th>crop</th><th>type</th><th>GT</th><th>pred</th><th>CER</th><th>EM</th></tr>")
    for r in rows:
        cls = "bad" if r["cer"] >= 0.3 else "ok"
        L.append(f"<tr class='{cls}'><td>{r['page']}</td><td>{h(r['crop'])}</td><td>{r['type']}</td>"
                 f"<td>{h(r['gt'])}</td><td>{h(r['pred'])}</td>"
                 f"<td>{r['cer']:.3f}</td><td>{r['em']}</td></tr>")
    L.append("</table></body></html>")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"[gen_report_for_manga] -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
