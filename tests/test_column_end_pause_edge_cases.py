"""竖排列末逗号消冗 —— High effort 边缘案例（Task 4）。

本文件是 `tests/test_column_end_pause.py` 的**边缘案例补充**，只覆盖纯函数
`column_end_pause_mask` 的边界行为，共 14 条：

| # | 边缘案例 | 期望 |
|---|---|---|
| 1 | 单列文本（无列边界可承接断句） | 不掩码 |
| 2 | 多列时末列仍按既定策略掩码（锁住上一轮决策） | 掩码 |
| 3 | 单字符列（整列只有一个逗号） | 不掩码，避免整列空白 |
| 4 | 连续逗号 "文字，，" 第二逗号在列末 | 只掩末位那一个 |
| 5 | 半角 "," 与全角 "，" | 都掩码 |
| 6 | 顿号 "、"（同族） | 掩码，不做单独特例 |
| 7 | 强终止符 "。！？" | 一律保留 |
| 8 | 省略号 "…" | 保留 |
| 9 | 分号 "；" / 冒号 "：" | 保留（当前实现更保守的一侧） |
| 10 | 竖排标点组合 "！？" 落在列末 | 保留 |
| 11 | 空列 / 空输入 | 形状正确、不炸 |
| 12 | 混合：只有部分列以逗号族结尾 | 掩码在正确的 (列, 字符) 下标 |
| 13 | verticalize_text 之后再取列末字符 | 结论不变（逗号码位不被竖排形式改写） |
| 14 | 输入列表不被就地修改 | 纯函数无副作用 |
"""
from amta.typeset.vertical_punct import (
    column_end_pause_mask,
    verticalize_text,
)

# 逗号族（列末消冗的对象）与必须保留的强/语气标点。
COMMA_FAMILY = "，、,"
KEEP_AT_COLUMN_END = "。！？…；："


def _masked(columns: list[str]) -> list[str]:
    """把掩码压成"实际显示"的列文本，方便断言。"""
    return ["".join(c for c, h in zip(col, row) if not h)
            for col, row in zip(columns, column_end_pause_mask(columns))]


# === 1. 单列文本：没有下一列承接断句 → 不消隐 ===

def test_single_column_trailing_comma_is_kept():
    """整条文本只占一列时，文本内部不存在列边界，逗号必须保留。"""
    assert _masked(["仙人风范，"]) == ["仙人风范，"]
    assert column_end_pause_mask(["仙人风范，"]) == [[False] * 5]


def test_single_column_kept_for_every_comma_family_member():
    """逗号族三个字符在单列列末都不该被动。"""
    for mark in COMMA_FAMILY:
        cols = [f"仙人风范{mark}"]
        assert _masked(cols) == cols, f"单列列末 {mark!r} 被误掩码"


# === 2. 多列时末列的既定策略不变（锁住上一轮决策，防止本次改动误伤） ===

def test_multi_column_last_column_still_masked():
    """≥2 列时末列仍属视觉列末 → 仍掩码（维持上一轮已固化的决策）。"""
    assert _masked(["仙人风范", "端庄贤淑，"]) == ["仙人风范", "端庄贤淑"]
    assert _masked(["甲，", "乙、"]) == ["甲", "乙"]


# === 3. 单字符列：整列只有一个逗号 → 不掩码 ===

def test_single_char_comma_column_is_not_blanked():
    """一列只有一个逗号时掩码会让整列变空白，必须保留。"""
    assert _masked(["，", "乙丙丁"]) == ["，", "乙丙丁"]
    assert _masked(["甲乙", "、"]) == ["甲乙", "、"]


# === 4. 连续逗号：只掩列末那一个 ===

def test_consecutive_commas_only_the_column_end_one_is_masked():
    """'文字，，' 只有列末（第二个）逗号是边界冗余，第一个照画。"""
    cols = ["文字，，", "后续内容"]
    mask = column_end_pause_mask(cols)
    assert mask[0] == [False, False, False, True], mask[0]
    assert _masked(cols) == ["文字，", "后续内容"]


def test_triple_consecutive_commas_only_last_masked():
    cols = ["甲乙，，，", "丙"]
    assert column_end_pause_mask(cols)[0] == [False, False, False, False, True]
    assert _masked(cols) == ["甲乙，，", "丙"]


# === 5. 半角/全角逗号都要掩码 ===

def test_halfwidth_and_fullwidth_comma_both_masked():
    assert _masked(["甲乙，", "丙丁"]) == ["甲乙", "丙丁"]
    assert _masked(["甲乙,", "丙丁"]) == ["甲乙", "丙丁"]
    assert _masked(["甲乙，", "丙丁,"]) == ["甲乙", "丙丁"]


# === 6. 顿号同族 ===

def test_ideographic_comma_same_policy_as_comma():
    cols = ["苹果、", "香蕉、", "橘子"]
    assert _masked(cols) == ["苹果", "香蕉", "橘子"]


# === 7/8/9. 强终止符、省略号、分号冒号一律保留 ===

def test_strong_terminators_kept_at_column_end():
    for mark in "。！？":
        cols = [f"仙人风范{mark}", "端庄贤淑"]
        assert _masked(cols) == cols, f"强终止符 {mark!r} 被误掩码"


def test_ellipsis_kept_at_column_end():
    # 横排省略号与竖排形式 ︙ 都应保留。
    for mark in ("…", "\uFE19"):
        cols = [f"仙人风范{mark}", "端庄贤淑"]
        assert _masked(cols) == cols, f"省略号 {mark!r} 被误掩码"


def test_semicolon_and_colon_kept_at_column_end():
    """；：当前实现保留（比计划更保守的一侧）；本测试固化该行为。"""
    for mark in "；：":
        cols = [f"仙人风范{mark}", "端庄贤淑"]
        assert _masked(cols) == cols, f"{mark!r} 被误掩码"


# === 10. 竖排标点组合（！？）落在列末 ===

def test_combined_vertical_punct_group_at_column_end_kept():
    """'！？' 作为一个组合行落在列末时，两个字符都不能被掩码。"""
    cols = ["太好了！？", "我们走吧"]
    assert _masked(cols) == cols


# === 11. 退化输入 ===

def test_empty_input_and_empty_columns():
    assert column_end_pause_mask([]) == []
    assert column_end_pause_mask(["", "甲乙"]) == [[], [False, False]]


# === 12. 混合列：掩码落在正确的 (列, 字符) 下标 ===

def test_mask_targets_exact_indices():
    cols = ["逗号在末，", "逗号在中间，的", "顿号在末、"]
    mask = column_end_pause_mask(cols)
    assert mask == [
        [False, False, False, False, True],
        [False] * 7,
        [False, False, False, False, True],
    ], mask


# === 13. verticalize_text 不改逗号码位 ===

def test_verticalize_text_does_not_change_mask_decision():
    """掩码按横排原文算，verticalize 后取列末字符结论必须一致。"""
    cols = ["（仙人风范，", "端庄贤淑）"]
    mask = column_end_pause_mask(cols)
    vertical = [verticalize_text(c) for c in cols]
    assert mask[0][-1] is True
    # 竖排形式换算只动括号/省略号，列末逗号码位不变。
    assert vertical[0][-1] == "，"
    assert _masked(vertical) == ["\uFE35仙人风范", "端庄贤淑\uFE36"]


# === 14. 纯函数：输入不被就地修改 ===

def test_input_columns_not_mutated():
    cols = ["仙人风范，", "端庄贤淑、"]
    snapshot = list(cols)
    column_end_pause_mask(cols)
    assert cols == snapshot
