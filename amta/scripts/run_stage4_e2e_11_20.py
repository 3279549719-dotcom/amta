"""批量跑 11-20 页 04_inpaint（精修mask + lama-manga）。

输入映射（已有0基detection.json → 1基输出）：
  N.jpg ← page_{N-1}_detection.json（已有，0基命名）
  输出: page_N_inpaint.json + page_N_clean.png（1基命名）
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
DET_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "stage4_e2e_11_20"
CLEAN_DIR = OUT_DIR / "clean"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CLEAN_DIR.mkdir(parents=True, exist_ok=True)

WORK_ID = "stage4-e2e-11-20"
PAGE_RANGE = range(11, 21)  # 11-20
INPAINT_SCRIPT = str(SCRIPT_DIR / "04_inpaint.py")

results = []
for n in PAGE_RANGE:
    raw = SRC_DIR / f"{n}.jpg"
    det = DET_DIR / f"page_{n-1}_detection.json"  # 0基已有文件
    out = OUT_DIR / f"page_{n}_inpaint.json"       # 1基输出

    if not raw.exists():
        print(f"[skip] page_{n}: raw not found {raw}")
        continue
    if not det.exists():
        print(f"[skip] page_{n}: detection not found {det}")
        continue
    if out.exists():
        print(f"[skip] page_{n}: already exists {out.name}")
        continue

    t0 = time.time()
    print(f"[run ] page_{n}: {raw.name} + {det.name} (refine-mask, lama-manga)")
    cmd = [
        sys.executable, INPAINT_SCRIPT,
        "--work-id", WORK_ID,
        "--det", str(det),
        "--raw", str(raw),
        "--out", str(out),
        "--clean-dir", str(CLEAN_DIR),
        "--refine-mask",
        "--engine", "lama-manga",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    elapsed = time.time() - t0
    if proc.returncode == 0:
        print(f"[ok  ] page_{n} ({elapsed:.1f}s) {proc.stdout.strip()[-120:]}")
        results.append({"page": n, "status": "ok", "elapsed": elapsed})
    else:
        print(f"[fail] page_{n} ({elapsed:.1f}s) rc={proc.returncode}")
        print(f"       stderr: {proc.stderr[-300:]}")
        results.append({"page": n, "status": "fail", "error": proc.stderr[-200:], "elapsed": elapsed})

ok_count = len([r for r in results if r["status"] == "ok"])
print(f"\n=== DONE: {ok_count}/{len(results)} pages ok ===")
for r in results:
    if r["status"] == "fail":
        print(f"  FAIL page_{r['page']}: {r.get('error','')[:100]}")
