"""探针：用 VLM 读 p5/p40 detect 出的所有 block，输出 {page, region_id, bbox, vlm_text} JSON。

用途：替换 hayai 读崩的长段文本，验证 VLM fallback 后的最终成品。
"""
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


def main():
    key = get_vlm_api_key()
    if not key:
        print("[probe] no VLM key")
        return

    out = {}
    for page in [5, 40]:
        det = json.load(open(ART / "detection" / f"page_{page}.json", encoding="utf-8"))
        raw = Image.open(SRC / f"{page}.jpg").convert("RGB")
        blocks = det["blocks"]
        # crop 所有 block
        crops, metas = [], []
        for b in blocks:
            x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
            c = raw.crop((x1, y1, x2, y2))
            crops.append(c)
            metas.append({"region_id": b["region_id"], "bbox": b["bbox"]})
        print(f"[probe] page_{page}: {len(crops)} crops, calling VLM ...")
        result = vlm_verify_batch(crops, api_key=key, max_retries=1, timeout=90)
        print(f"[probe] status={result['status']} elapsed={result['elapsed']:.1f}s")
        texts = result.get("texts") or []
        out[f"page_{page}"] = [
            {**m, "vlm_text": texts[i] if i < len(texts) else None}
            for i, m in enumerate(metas)
        ]

    out_path = ROOT / "workspace" / "_verify_p5_p40" / "vlm_read_all.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[probe] saved -> {out_path}")
    # 打印长段
    for page, items in out.items():
        print(f"\n===== {page} =====")
        for it in items:
            t = (it["vlm_text"] or "")
            print(f"  [{it['region_id']}] len={len(t)} bbox={[int(v) for v in it['bbox']]}")
            print(f"    {t[:120]}")


if __name__ == "__main__":
    main()
