"""竖排列末逗号消冗 —— 纯函数与断列行为（Task 2）。

问题样例（touhou-getten-shinchi 第4页，来自真实译文）：
- r03 '而且漫画家是一种职业，在幻想乡靠它谋生很难哦'
      → 列 '是一种职业，' 的逗号落在列末（非末列）
- r01 '没关系啦！就算画不好，月都的漫画家不也有很多画得很差的嘛！'
      → 列 '就算画不好，' 的逗号落在列末（非末列）

用户样例诉求：当逗号正好落在竖排列末时，换列边界已经表达了这次停顿，
再显示一个逗号是冗余的（例：仙人风范，/ 端庄贤淑 → 仙人风范 / 端庄贤淑）。

实现策略（经 supervisor 复核修正）：
- 只关掉**渲染**（column_end_pause_mask → hide_mask），绝不改写译文/lines 元数据。
  因此字格推进、列高、整组列的垂直居中都不变，不会出现"列变短后重新居中"的位移。
- 覆盖所有视觉列（含末列），列末逗号家族（，、,）一律不显示。
- 列中逗号、句末标点（。！？…；：）保留；这不是"删除所有竖排标点"。
"""
from amta.typeset.typeset_engine import break_lines, wrap_vertical
from amta.typeset.vertical_punct import column_end_pause_mask

# 第4页 typeset 产物实际使用的列宽（由 artifacts/typeset/page_4.json 的
# lines 逐字反推：'而且漫画家'/'是一种职业，'/... 对应 max_chars=6）。
PAGE4_R03 = "而且漫画家是一种职业，在幻想乡靠它谋生很难哦"
PAGE4_R01 = "没关系啦！就算画不好，月都的漫画家不也有很多画得很差的嘛！"
REAL_MAX_CHARS = 6


# === 纯函数：列末逗号掩码 ===

def _masked(columns):
    """把掩码压成"实际显示"的列文本，方便断言。"""
    return ["".join(c for c, h in zip(col, row) if not h)
            for col, row in zip(columns, column_end_pause_mask(columns))]


def test_column_end_comma_is_hidden():
    assert _masked(["仙人风范，", "端庄贤淑"]) == ["仙人风范", "端庄贤淑"]


def test_last_column_end_comma_is_hidden():
    """末列同属视觉列末，适用同一条列末显示策略（supervisor 明确要求覆盖）。"""
    assert _masked(["仙人风范", "端庄贤淑，"]) == ["仙人风范", "端庄贤淑"]


def test_all_columns_covered():
    assert _masked(["甲，", "乙，", "丙，"]) == ["甲", "乙", "丙"]


def test_enumeration_comma_same_policy():
    """顿号与逗号同族，列末同样不显示（不是单独特例）。"""
    assert _masked(["甲、", "乙"]) == ["甲", "乙"]


def test_ascii_comma_same_policy():
    """半角逗号同族。"""
    assert _masked(["甲乙,", "丙丁"]) == ["甲乙", "丙丁"]


def test_sentence_final_punctuation_is_kept():
    """句末标点承载"句子结束"语义，即使落在列末也必须显示。"""
    for mark in "。！？…；：":
        cols = [f"仙人风范{mark}", "端庄贤淑"]
        assert _masked(cols) == cols, f"{mark} 不应被隐藏"


def test_mid_column_comma_is_kept():
    """逗号在列中间时不是边界冗余，必须显示。"""
    cols = ["仙人，风范", "端庄贤淑"]
    assert _masked(cols) == cols


def test_single_column_untouched():
    assert _masked(["仙人风范，端庄贤淑"]) == ["仙人风范，端庄贤淑"]


def test_pure_punctuation_column_untouched():
    """只有逗号一列的退化情况不掩码（避免整列变空白）。"""
    assert _masked(["，", "乙"]) == ["，", "乙"]


def test_mask_shape_matches_columns():
    cols = ["甲乙丙", "丁"]
    mask = column_end_pause_mask(cols)
    assert [len(r) for r in mask] == [len(c) for c in cols]
    assert mask == [[False, False, False], [False]]


def test_input_not_mutated():
    cols = ["仙人风范，", "端庄贤淑"]
    column_end_pause_mask(cols)
    assert cols == ["仙人风范，", "端庄贤淑"]


def test_empty_input():
    assert column_end_pause_mask([]) == []


# === 与实际断列行为衔接 ===

def test_break_lines_no_longer_forces_comma_to_column_end():
    """2026-10-07：移除"标点后断列有奖励"后，DP 不再主动把逗号顶到列末。

    旧行为（已删）：DP 给 text[j-1] in strong_break 的断点 cost -= 50，
    导致"仙人风范，端庄贤淑"被切成 ["仙人风范，", "端庄贤淑"]。
    新行为：DP 只靠列长均衡定断点，逗号自然落进列中。
    """
    lines = wrap_vertical("仙人风范，端庄贤淑", 6)
    assert lines == ["仙人风", "范，端庄贤淑"], f"新断列: {lines}"
    # 逗号在第二列中间，不是列末
    assert not lines[0].endswith("，"), f"逗号不该在列末: {lines}"


def test_engine_output_plus_policy_matches_desired_effect():
    """端到端规则：断列结果经掩码后显示 = 用户期望的两列。"""
    lines = wrap_vertical("仙人风范，端庄贤淑", 6)
    # 逗号已在列中，掩码不触发；显示即原文
    assert _masked(lines) == ["仙人风", "范，端庄贤淑"]


def test_real_page4_r03_column_end_comma_is_masked():
    """真实样本 r03：'是一种职业，' 的列末逗号被掩码。"""
    columns = break_lines(PAGE4_R03, REAL_MAX_CHARS)
    assert columns == ["而且漫画家", "是一种职业，", "在幻想乡靠", "它谋生很难哦"], columns
    assert _masked(columns) == ["而且漫画家", "是一种职业", "在幻想乡靠", "它谋生很难哦"]


def test_real_page4_r01_column_end_comma_is_masked():
    """真实样本 r01：'就算画不好，' 的列末逗号被掩码，'！' 全部保留。"""
    columns = break_lines(PAGE4_R01, REAL_MAX_CHARS)
    assert columns == ["没关系啦！", "就算画不好，", "月都的漫画家",
                       "不也有很多画", "得很差的嘛！"], columns
    masked = _masked(columns)
    assert masked == ["没关系啦！", "就算画不好", "月都的漫画家",
                      "不也有很多画", "得很差的嘛！"]
    assert "".join(masked).count("！") == 2, "句末 ！ 必须保留"


def test_mask_is_render_only_break_lines_output_untouched():
    """掩码是渲染层关注点：断列函数本身绝不改标点。"""
    columns = break_lines(PAGE4_R03, REAL_MAX_CHARS)
    column_end_pause_mask(columns)
    assert columns == ["而且漫画家", "是一种职业，", "在幻想乡靠", "它谋生很难哦"]
