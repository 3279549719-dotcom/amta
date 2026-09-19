"""探针：用真实整页数据测——加纯标点条款后，省略号框会不会真的被跳过。"""
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


def run_page_test(canon_path: str, page_name: str, extra_clause: str = "") -> None:
    print(f"\n{'='*60}")
    print(f"=== {page_name} ===")
    print(f"{'='*60}")

    with open(canon_path, encoding="utf-8") as f:
        data = json.load(f)

    items = data["items"]
    print(f"共 {len(items)} 个框")

    system = _SYSTEM_PROMPT + (f"\n{extra_clause}" if extra_clause else "")
    user = build_content(items)

    cfg = get_chat_config()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
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
    for item, out in zip(items, parsed):
        rid = item["region_id"]
        src = (item.get("baberu_text") or item.get("text") or "")[:40]
        dst = out[:40]
        # 标记：纯标点/无实义的框
        is_ellipsis = all(c in ".．。・…" for c in src.strip()) and len(src.strip()) > 0
        marker = " ⚠️ 省略号" if is_ellipsis else ""
        print(f"  {rid}: {repr(src):50s} → {repr(dst):40s}{marker}")


def main() -> None:
    # 月天 p10（有长省略号 r02）
    canon_p10 = "workspace/touhou-getten-shinchi/artifacts/canon/page_10.json"

    # 1. 当前 prompt
    run_page_test(canon_p10, "月天 p10 — 当前 prompt")

    # 2. 加了纯标点条款
    new_clause = (
        "- 如果某条输入是纯标点符号（如省略号、句号堆叠）、拟声词、"
        "或没有实际语义的内容，不需要翻译，对应位置输出空字符串。"
    )
    run_page_test(canon_p10, "月天 p10 — 加纯标点条款", new_clause)


if __name__ == "__main__":
    main()
