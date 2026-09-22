"""集成验证：直接调用 typeset adapter，确认 export_psd 开关能生成 PSD。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.orchestrator.adapters.typeset import run as typeset_adapter_run
from amta.orchestrator.context import StationContext

ARTIFACTS = Path("workspace/touhou-single-wing/artifacts")
PAGE = "page_40"


def main():
    ctx = StationContext(
        work_id="touhou-single-wing",
        page=PAGE,
        page_idx=40,
        raw_image=Path("dummy.jpg"),
        artifacts_dir=ARTIFACTS,
        state_dir=ARTIFACTS.parent / "state",
        inputs={
            "detect": ARTIFACTS / "detection" / f"{PAGE}.json",
            "ocr": ARTIFACTS / "canon" / f"{PAGE}.json",
            "translate": ARTIFACTS / "translation" / f"{PAGE}.json",
            "inpaint": ARTIFACTS / "inpaint" / f"{PAGE}.json",
        },
        config={"export_psd": True},
    )

    print(f"Running typeset adapter with export_psd=True on {PAGE}...")
    result = typeset_adapter_run(ctx)
    print(f"status: {result.status}")
    print(f"duration: {result.duration_s}s")
    print(f"stats: {result.stats}")

    psd_path = ARTIFACTS / "psd" / f"{PAGE}.psd"
    if psd_path.exists():
        size_mb = psd_path.stat().st_size / 1024 / 1024
        print(f"\nPSD generated: {psd_path} ({size_mb:.1f} MB)")
        from PIL import Image
        img = Image.open(psd_path)
        print(f"PIL verify: {img.size} {img.mode} {img.format}")
        print("INTEGRATION TEST PASSED")
    else:
        print(f"PSD NOT found at {psd_path}")
        print("INTEGRATION TEST FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
