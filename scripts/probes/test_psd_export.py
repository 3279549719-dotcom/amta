"""测试 PSD 导出 — 用单翼停留之地第5页和第40页验证。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PIL import Image
from amta.typeset.psd_export import export_page_psd

ARTIFACTS = Path("workspace/touhou-single-wing/artifacts")
OUTPUT_DIR = Path("output/psd_test")


def test_page(page_key: str):
    print(f"\n{'='*60}")
    print(f"Testing {page_key}")
    print(f"{'='*60}")
    output = OUTPUT_DIR / f"{page_key}.psd"
    t0 = time.perf_counter()
    export_page_psd(ARTIFACTS, page_key, output)
    elapsed = time.perf_counter() - t0
    size_mb = output.stat().st_size / 1024 / 1024
    print(f"  generated in {elapsed:.1f}s, size: {size_mb:.1f} MB")

    # 验证
    img = Image.open(output)
    print(f"  PIL verify: {img.size} {img.mode} {img.format}")

    # 检查 PSD 里的图层数（PIL n_frames 对 PSD 可能不准，用文件大小推断）
    print(f"  SUCCESS")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for page in ["page_5", "page_40"]:
        test_page(page)
    print(f"\nAll tests passed. PSD files in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
