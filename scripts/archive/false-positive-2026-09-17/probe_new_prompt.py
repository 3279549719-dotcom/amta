"""测试新 prompt 在真实整页数据上的效果。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.translation.translate import (
    _SYSTEM_PROMPT,
    get_chat_config,
    text_chat,
    parse_translation_array,
)


def build_content(batch: list[dict]) -> str:
    instr = ("将以下日文漫画内容翻译成中文。"
             "输出JSON数组，长度和顺序与输入一致。"
             "漫画口语化表达，句末尽量不要句号。\n")
    blocks = [r.get("baberu_text") or r.get("text") or "" for r in batch]
    return instr + "\n".join(blocks)


def test_page(canon_path: str, page_name: str) -> None:
    print(f"\n{'='*60}")
    print(f"=== {page_name} ===")
    print(f"{'='*60}")

    with open(canon_path, encoding="utf-8") as f:
        data = json.load(f)

    items = data["items"]
    print(f"共 {len(items)} 个框")

    cfg = get_chat_config()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": build_content(items)},
    ]

    raw = text_chat(
        base_url=cfg["base_url"],
        model=cfg["model"],
        messages=messages,
        api_key=cfg.get("api_key"),
    )

    parsed = parse_translation_array(raw, len(items))
    if parsed is None:
        print("解析失败！")
        return

    print("\n逐框结果：")
    empty_count = 0
    for item, out in zip(items, parsed):
        rid = item["region_id"]
        src = (item.get("baberu_text") or item.get("text") or "")[:40]
        dst = out[:40]
        is_empty = not out.strip()
        if is_empty:
            empty_count += 1
        marker = " ← 输出空" if is_empty else ""
        print(f"  {rid}: {repr(src):50s} → {repr(dst):40s}{marker}")

    print(f"\n空译文框数：{empty_count}/{len(items)}")


def main() -> None:
    # 月天 p3
    test_page(
        "workspace/touhou-getten-shinchi/artifacts/canon/page_3.json",
        "月天 p3（新 prompt）"
    )
    # 月天 p10
    test_page(
        "workspace/touhou-getten-shinchi/artifacts/canon/page_10.json",
        "月天 p10（新 prompt）"
    )


if __name__ == "__main__":
    main()
