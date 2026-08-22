"""裁剪 10 页 detector 并集框成 crop，供 VLM 内容识别 → 内容级 recall。"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.geometry import iou  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
DATA = OUT / "data"
SRC_BASE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")

d = json.loads((DATA / "recall_detections.json").read_text(encoding="utf-8"))
out = OUT / "recall_crops"
out.mkdir(exist_ok=True)
total = 0
manifest = {}
for pkey, pinfo in d.items():
    page_num = int(pkey.split("_")[1]) + 1
    src = SRC_BASE / f"{page_num}.jpg"
    im = Image.open(src)
    union = []
    for eng, blocks in pinfo["engines"].items():
        for b in blocks:
            if not any(iou(b["bbox"], u) > 0.5 for u in union):
                union.append(b["bbox"])
    manifest[pkey] = {"page": page_num, "path": str(src), "crops": []}
    for i, bb in enumerate(union):
        x0, y0, x1, y1 = (int(v) for v in bb)
        crop = im.crop((max(0, x0 - 8), max(0, y0 - 8), min(im.width, x1 + 8), min(im.height, y1 + 8)))
        fname = f"{pkey}_u{i:02d}.png"
        crop.save(out / fname)
        manifest[pkey]["crops"].append({"crop": str(out / fname), "bbox": bb})
        total += 1
(DATA / "recall_crop_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"saved {total} union crops -> {out}")
