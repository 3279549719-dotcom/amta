"""一次性探针：用新 prompt 重翻 p14/p15，写回 artifacts/translation。

只动 translate（新 _SYSTEM_PROMPT），不碰 detect/ocr/inpaint。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"E:\manga translator agent")
sys.path.insert(0, str(ROOT / "src"))

from amta.stores import artifacts
from amta.translation.stage3_minimal import translate_page_minimal

ROOT = Path(r"E:\manga translator agent")
WORK = "touhou-p17-20-e2e"
WORKSPACE = ROOT / "workspace" / WORK
ART = WORKSPACE / "artifacts"
PAGES = [16, 17, 18, 19, 20]


def main() -> None:
    for page in PAGES:
        canon_path = ART / "canon" / f"page_{page}.json"
        canon = json.loads(canon_path.read_text(encoding="utf-8"))
        out = translate_page_minimal(
            WORK, canon,
            state_dir=WORKSPACE,
            page=f"page_{page}",
        )
        trans_path = ART / "translation" / f"page_{page}.json"
        trans_path.write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"--- page {page} ---")
        for rid, t in out["translations"].items():
            print(f"  {rid}: {t}")


if __name__ == "__main__":
    main()
