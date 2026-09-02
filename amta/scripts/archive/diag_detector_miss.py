"""detector 漏检诊断探针 — 对指定页面跑 4-detector，保存 per-engine 原始框（未去重），
并对已知漏检区域做逐 detector 覆盖检查。

用途：定位"大小字混合气泡漏检"的根因——是上游 detector 根本没检出，还是后处理误杀。

用法:
  python scripts/diag_detector_miss.py --raw "D:\\...\\15.jpg" --out output/tmp/diag_p15.json
  python scripts/diag_detector_miss.py --raw "D:\\...\\14.jpg" --out output/tmp/diag_p14.json

输出:
  {
    "source": "...",
    "image_meta": {width, height},
    "engines": {
      "pp-doclayout-v3": [{node_id, bbox, bubble_type, ocr, confidence, transform}],
      "comic-text-detector": [...],
      "anime-text": [...],
      "comic-text-bubble-detector": [...]
    },
    "union": [...],
    "per_engine_count": {...},
    "union_count": N,
    "miss_regions": [
      {
        "label": "弟子だからね (大字主台词)",
        "expected_bbox": [x1,y1,x2,y2],
        "coverage": {engine: [{node_id, bbox, iou_with_expected}], ...},
        "covered_by": ["anime-text", ...],
        "missed_by": ["pp-doclayout-v3", ...]
      }
    ]
  }

前置: koharu v0.59.1 headless 运行在 127.0.0.1:4000。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.koharu_client import KoharuClient  # noqa: E402
from amta.paths import write_json  # noqa: E402
from amta.pipeline import DETECTOR_STEPS  # noqa: E402
from amta.runner import run_all_pages  # noqa: E402
from amta.geometry import union_blocks, iou, bbox_from_block  # noqa: E402
from PIL import Image  # noqa: E402

# 已知漏检区域（手工标注，用于逐 detector 覆盖检查）
# 格式: {label, file_keyword, expected_bbox:[x1,y1,x2,y2]}
MISS_REGIONS = [
    {
        "label": "15.jpg 左下 弟子だからね (大字主台词)",
        "file_keyword": "15.jpg",
        "expected_bbox": [50, 2430, 210, 2870],
    },
    {
        "label": "15.jpg 左下 落ち着きなさい (小字注释)",
        "file_keyword": "15.jpg",
        "expected_bbox": [140, 2390, 200, 2700],
    },
    {
        "label": "14.jpg 右下 では豊ちゃん… (大字长句)",
        "file_keyword": "14.jpg",
        "expected_bbox": [1600, 2630, 1870, 3150],
    },
]


def run_diag(raw_page: Path, out_path: Path,
             host: str = "127.0.0.1", port: int = 4000) -> dict:
    client = KoharuClient(host=host, port=port)
    client.wait_server(timeout=60)

    print(f"[diag] running 4 detectors on {raw_page.name} ...", flush=True)
    results = run_all_pages(client, [raw_page], DETECTOR_STEPS,
                            prefix="amta-diag", timeout=1200, label="diag")
    per_engine = next(iter(results.values()))["engines"]

    # 保留每个 engine 的完整原始框（含 transform/ocr/confidence，不 compact）
    engines_raw = {}
    for eng, blocks in per_engine.items():
        engines_raw[eng] = [
            {
                "node_id": b.get("node_id"),
                "bbox": bbox_from_block(b),
                "bubble_type": b.get("bubble_type"),
                "ocr": b.get("ocr", ""),
                "confidence": b.get("confidence"),
                "transform": b.get("transform", {}),
            }
            for b in blocks
        ]

    # 并集（和 01_detect 同逻辑）
    comp = {eng: [{"node_id": b["node_id"], "bbox": b["bbox"],
                    "bubble_type": b["bubble_type"], "ocr": b["ocr"]}
                   for b in blocks]
            for eng, blocks in engines_raw.items()}
    union = union_blocks(comp)

    # 漏检区域覆盖检查
    miss_regions = []
    for mr in MISS_REGIONS:
        if mr["file_keyword"] not in raw_page.name:
            continue
        exp = mr["expected_bbox"]
        coverage = {}
        covered_by = []
        missed_by = []
        for eng, blocks in engines_raw.items():
            hits = []
            for b in blocks:
                sc = iou(b["bbox"], exp)
                # 也检查中心点是否在预期区域内（detector 框可能偏大或偏小）
                cx = (b["bbox"][0] + b["bbox"][2]) / 2
                cy = (b["bbox"][1] + b["bbox"][3]) / 2
                center_in = exp[0] <= cx <= exp[2] and exp[1] <= cy <= exp[3]
                if sc > 0.1 or center_in:
                    hits.append({"node_id": b["node_id"], "bbox": b["bbox"],
                                 "iou": round(sc, 3), "center_in": center_in,
                                 "ocr": b.get("ocr", "")})
            coverage[eng] = hits
            if hits:
                covered_by.append(eng)
            else:
                missed_by.append(eng)
        miss_regions.append({
            "label": mr["label"],
            "expected_bbox": exp,
            "coverage": coverage,
            "covered_by": covered_by,
            "missed_by": missed_by,
        })

    img = Image.open(raw_page)
    doc = {
        "source": str(raw_page),
        "image_meta": {"width": img.width, "height": img.height},
        "engines": engines_raw,
        "union": [{"node_id": b.get("node_id"), "bbox": b["bbox"],
                    "bubble_type": b.get("bubble_type")} for b in union],
        "per_engine_count": {eng: len(blocks) for eng, blocks in engines_raw.items()},
        "union_count": len(union),
        "miss_regions": miss_regions,
        "detectors": list(DETECTOR_STEPS.keys()),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(out_path, doc)

    # 控制台摘要
    print(f"\n[diag] {raw_page.name}: union={len(union)} boxes")
    for eng, n in doc["per_engine_count"].items():
        print(f"  {eng}: {n} boxes")
    if miss_regions:
        print("\n[diag] 漏检区域覆盖检查:")
        for mr in miss_regions:
            print(f"  {mr['label']}")
            print(f"    检出: {mr['covered_by'] or 'NONE'}")
            print(f"    漏检: {mr['missed_by']}")
            for eng, hits in mr["coverage"].items():
                for h in hits:
                    print(f"      {eng}: bbox={h['bbox']} iou={h['iou']} center_in={h['center_in']} ocr={h['ocr']!r}")
    print(f"\n[diag] saved -> {out_path}")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="detector 漏检诊断探针")
    ap.add_argument("--raw", required=True, type=Path, help="源页图路径")
    ap.add_argument("--out", required=True, type=Path, help="输出 JSON 路径")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4000)
    a = ap.parse_args()
    run_diag(a.raw, a.out, a.host, a.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
