"""批量对已有 translation.json 应用机械标点对齐（P2）。

不需要重新调用 LLM，直接对已有译文做后处理。
用法：cd "E:\manga translator agent" && python apply_punctuation_align.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "amta" / "src"))

from amta.punctuation_align import align_punctuation

ART = Path("amta/workspace/touhou-e2e-orchestrator/artifacts")


def main():
    total_removed = 0
    for page in range(11, 16):
        page_key = f"page_{page}"
        canon_path = ART / f"{page_key}_canon.json"
        trans_path = ART / f"{page_key}_translation.json"

        if not canon_path.exists() or not trans_path.exists():
            print(f"  SKIP {page_key}")
            continue

        canon = json.loads(canon_path.read_text(encoding="utf-8"))
        trans = json.loads(trans_path.read_text(encoding="utf-8"))

        canon_items = canon.get("items", [])
        translations = trans.get("translations", {})

        page_removed = 0
        for item in canon_items:
            rid = item["region_id"]
            src = item.get("text", "")
            dst = translations.get(rid, "")
            if not dst:
                continue
            new_dst = align_punctuation(src, dst)
            if new_dst != dst:
                removed = len(dst) - len(new_dst)
                page_removed += removed
                translations[rid] = new_dst
                print(f"  {page_key} {rid}: -{removed}字  {dst[:30]}... → {new_dst[:30]}...")

        trans["translations"] = translations
        trans_path.write_text(json.dumps(trans, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {page_key}: 共删除 {page_removed} 字符")
        total_removed += page_removed

    print(f"\n=== 完成，共删除 {total_removed} 字符 ===")


if __name__ == "__main__":
    main()
