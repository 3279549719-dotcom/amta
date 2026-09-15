"""探针：用 DeepSeek vision 直接读那个被 hayai 读崩的长 crop。

验证"VLM fallback"路线是否可行——hayai 幻觉时，VLM 能不能读对长段无框线文字。
"""
from __future__ import annotations

import base64
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image
from amta.common.config import get_vlm_api_key
from amta.backends.vlm_verify import vlm_verify_batch

CROP = ROOT / "workspace" / "touhou-single-wing" / "artifacts" / "crops" / "r00.png"


def main():
    key = get_vlm_api_key()
    if not key:
        print("[probe] no VLM_API_KEY / CHAT_API_KEY in .env")
        return
    img = Image.open(CROP).convert("RGB")
    print(f"[probe] crop size: {img.size}")
    print(f"[probe] calling DeepSeek vision ...")
    result = vlm_verify_batch([img], api_key=key, max_retries=1, timeout=60)
    print(f"[probe] status: {result['status']}, elapsed: {result['elapsed']:.1f}s")
    if result.get("texts"):
        for i, t in enumerate(result["texts"]):
            print(f"\n===== VLM text [{i}] =====")
            print(t)
    else:
        print("[probe] raw_output:", result.get("raw_output", "")[:500])


if __name__ == "__main__":
    main()
