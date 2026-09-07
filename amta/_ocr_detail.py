"""对 30 个新增框裁剪图重跑 hayai OCR，落盘逐框明细 + 与 rule_filter 判定对齐。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, r"E:\manga translator agent\amta\src")

OUT = Path(r"E:\manga translator agent\amta\output\tiling_full42")
CROP_NEW = OUT / "crops_new"


def main():
    from amta.ocr_engines import ocr_batch
    from amta.rule_filter import rule_filter

    # 读取 summary 中的新增框（含 conf、page）
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))

    # 从 crops_new 目录重建新增框列表（文件名含 page/conf）
    crops = sorted(CROP_NEW.glob("*.png"))
    new_blocks = []
    for p in crops:
        # p14_r000_c0.771.png
        page = int(p.name.split("_")[0][1:])
        conf = float(p.name.split("c")[1][:-4])
        new_blocks.append({"page": page, "conf": conf, "crop": p.name})

    print(f"[OCR] 共 {len(crops)} 个裁剪图，hayai 识别中...")
    ocr_rows = ocr_batch([str(p) for p in crops], engine="hayai")
    ocr_by_crop = {Path(r["crop"]).name: (r.get("ocr") or "").strip() for r in ocr_rows}

    for b in new_blocks:
        b["text"] = ocr_by_crop.get(b["crop"], "")

    # rule_filter（与全量脚本同一口径：原图 2243x3465）
    kept, removed = rule_filter(new_blocks, 2243, 3465)

    for b in kept:
        b["verdict"] = "keep"
    for b in removed:
        b["verdict"] = "drop"
        b.setdefault("filter_reason", b.get("filter_reason", "?"))

    # 落盘
    (OUT / "new_blocks_detail.json").write_text(
        json.dumps(new_blocks, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n=== 逐框明细（{len(new_blocks)}）===")
    for b in sorted(new_blocks, key=lambda x: (x["page"], x["conf"])):
        print(f"p{b['page']:>2} conf={b['conf']:.3f} [{b['verdict']:<4}] {b.get('filter_reason','')}  {b['text'][:30]!r}")


if __name__ == "__main__":
    main()
