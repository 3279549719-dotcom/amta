"""单独 VLM 读 p5 r00（底部大段设定解说）。不拼 contact sheet，原图直接送。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image
from amta.common.config import get_vlm_api_key
from amta.backends.vlm_verify import vlm_verify_batch

SRC = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ART = ROOT / "workspace" / "touhou-single-wing" / "artifacts"

# p5 r00 bbox: [128, 2664, 1962, 3253]
# p40 r00 bbox: [250, 655, 2003, 2254]
TARGETS = {
    "page_5": {"region_id": "r00", "bbox": [128, 2664, 1962, 3253]},
    "page_40": {"region_id": "r00", "bbox": [250, 655, 2003, 2254]},
}


def main():
    key = get_vlm_api_key()
    out = {}
    for page_name, meta in TARGETS.items():
        page = int(page_name.split("_")[1])
        raw = Image.open(SRC / f"{page}.jpg").convert("RGB")
        x1, y1, x2, y2 = [int(v) for v in meta["bbox"]]
        crop = raw.crop((x1, y1, x2, y2))
        print(f"[{page_name}] crop size: {crop.size}")
        result = vlm_verify_batch([crop], api_key=key, max_retries=1, timeout=90)
        print(f"  status={result['status']} elapsed={result['elapsed']:.1f}s")
        texts = result.get("texts") or []
        out[page_name] = texts[0] if texts else result.get("raw_output", "")
        print(f"  text ({len(out[page_name])} chars):")
        print(out[page_name])
        print()

    out_path = ROOT / "workspace" / "_verify_p5_p40" / "vlm_long_texts.json"
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"saved -> {out_path}")


if __name__ == "__main__":
    main()
