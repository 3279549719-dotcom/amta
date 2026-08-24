"""裁剪 N 页 detector 并集框成 crop，供 VLM 内容识别 → 内容级 recall。

输入: output/data/recall_detections.json（每引擎原始框）
输出: output/recall_crops/ + output/data/recall_crop_manifest.json
用法: python scripts/recall_crop.py <src_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.geometry import union_boxes  # noqa: E402
from amta.images import crop_with_pad  # noqa: E402
from amta.paths import DATA, OUTPUT, read_json, write_json  # noqa: E402

SRC_BASE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")


def main() -> int:
    d = read_json(DATA / "recall_detections.json")
    out = OUTPUT / "recall_crops"
    out.mkdir(exist_ok=True)
    total = 0
    manifest = {}
    for pkey, pinfo in d.items():
        page_num = int(pkey.split("_")[1]) + 1
        src = SRC_BASE / f"{page_num}.jpg"
        union = union_boxes(pinfo["engines"])
        manifest[pkey] = {"page": page_num, "path": str(src), "crops": []}
        for i, cand in enumerate(union):
            fname = f"{pkey}_u{i:02d}.png"
            if crop_with_pad(src, cand["bbox"], out / fname, pad=8):
                manifest[pkey]["crops"].append({"crop": str(out / fname), "bbox": cand["bbox"]})
                total += 1
    write_json(DATA / "recall_crop_manifest.json", manifest)
    print(f"saved {total} union crops -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
