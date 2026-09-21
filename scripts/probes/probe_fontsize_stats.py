"""统计 typeset JSON 的字号分布：每页平均字号、最小字号、溢出数、横竖排比例。"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import amta  # noqa: F401  (UTF-8 stdout choke point)

base = Path("workspace/touhou-getten-shinchi/artifacts/typeset")
pages = sys.argv[1:] if len(sys.argv) > 1 else [f"page_{i}" for i in range(41, 68)]
# 允许传纯数字 41 或 page_41
pages = [p if p.startswith("page_") else f"page_{p}" for p in pages]

all_sizes = []
per_page = []
overflow_total = 0
h_count = v_count = 0

for pg in pages:
    f = base / f"{pg}.json"
    if not f.exists():
        continue
    doc = json.loads(f.read_text(encoding="utf-8"))
    items = doc.get("rendered_items", [])
    if not items:
        continue
    sizes = [it["font_size"] for it in items if it.get("lines")]
    if not sizes:
        continue
    checks = doc.get("checks", {})
    overflow = len(checks.get("overflow", []))
    overflow_total += overflow
    for it in items:
        if it.get("layout_direction") == "horizontal":
            h_count += 1
        else:
            v_count += 1
    avg = sum(sizes) / len(sizes)
    mn = min(sizes)
    per_page.append((pg, len(sizes), avg, mn, overflow))
    all_sizes.extend(sizes)

print(f"{'page':<10} {'n':>3} {'avg':>6} {'min':>5} {'ovf':>4}")
for pg, n, avg, mn, ovf in per_page:
    print(f"{pg:<10} {n:>3} {avg:>6.1f} {mn:>5} {ovf:>4}")

print()
print(f"总页数: {len(per_page)}")
print(f"总框数: {len(all_sizes)} (横{h_count} 竖{v_count})")
print(f"全页平均字号: {sum(all_sizes)/len(all_sizes):.1f}")
print(f"全页最小字号: {min(all_sizes)}")
print(f"<20px 的框数: {sum(1 for s in all_sizes if s < 20)}")
print(f"<25px 的框数: {sum(1 for s in all_sizes if s < 25)}")
print(f"总溢出数: {overflow_total}")
