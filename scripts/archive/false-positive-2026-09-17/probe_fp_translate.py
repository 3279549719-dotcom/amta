"""探针：测试 translate prompt 加"纯标点输出空"条款后，省略号框会不会被跳过。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.translation.translate import (
    _SYSTEM_PROMPT,
    get_chat_config,
    text_chat,
    parse_translation_array,
)


def run_test(system_prompt: str, texts: list[str], label: str) -> None:
    print(f"\n=== {label} ===")
    print(f"输入: {texts}")

    user_msg = "请翻译以下漫画台词，按数组顺序输出：\n"
    for i, t in enumerate(texts):
        user_msg += f"{i+1}. {t}\n"

    cfg = get_chat_config()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    raw = text_chat(
        base_url=cfg["base_url"],
        model=cfg["model"],
        messages=messages,
        api_key=cfg.get("api_key"),
    )
    print(f"原始输出: {raw[:200]}")

    parsed = parse_translation_array(raw, len(texts))
    if parsed is None:
        print("解析失败！")
        return

    for i, (inp, out) in enumerate(zip(texts, parsed)):
        print(f"  {i+1}. 输入={repr(inp[:40])} → 输出={repr(out)}")


def main() -> None:
    # 测试用例：真实数据 + 正常台词对比
    test_cases = [
        "................................................",  # r02 长省略号（48个点）
        "............",  # r13 短省略号（12个点）
        "蓬莱",  # 案例1 背景门牌
        "ごめんなさいね",  # 正常台词
    ]

    # 1. 用当前 prompt
    run_test(_SYSTEM_PROMPT, test_cases, "当前 prompt（只有乱码条款）")

    # 2. 加了"纯标点/无实义输出空"条款的 prompt
    new_prompt = _SYSTEM_PROMPT + (
        "\n- 如果某条输入是纯标点符号（如省略号、句号堆叠）、拟声词、"
        "或没有实际语义的内容，不需要翻译，对应位置输出空字符串。"
    )
    run_test(new_prompt, test_cases, "加了纯标点条款的 prompt")


if __name__ == "__main__":
    main()
