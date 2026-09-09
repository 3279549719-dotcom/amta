"""typeset_engine 字体大小第一性原理测试（ADR-031 决策C）。

探针测试：窄长框应选竖排且字号显著大于旧实现的横排19px。
核心验证：fit_font_size 双方向计算选最优，零人为阈值。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

FONT_PATH = Path("C:/Windows/Fonts/msyh.ttc")


def test_narrow_tall_box_prefers_vertical_with_large_font():
    """探针：窄长框（宽207高954，47字）应选竖排，字号应>=30（旧实现横排仅19px）。"""
    from amta.typeset.typeset_engine import fit_font_size
    bbox = [0, 0, 207, 954]
    text = "在那之后我的研究可能是因为八意大人开始插嘴的缘故进展得很顺利虽然很烦人但我忍耐了"
    font_size, direction, lines = fit_font_size(text, FONT_PATH, bbox)
    assert direction == "vertical", f"窄长框应选竖排，实际选了{direction}"
    assert font_size >= 30, f"竖排字号应>=30，实际{font_size}（旧实现横排仅19px）"
    assert isinstance(lines, list) and len(lines) >= 1
    # 竖排多列：每列是子串，总字数等于原文
    assert sum(len(col) for col in lines) == len(text)


def test_wide_short_box_font_size_large():
    """宽扁框（宽380高222，8字）字号应>=35，方向任选（横竖排字号可能相等）。"""
    from amta.typeset.typeset_engine import fit_font_size
    bbox = [0, 0, 380, 222]
    text = "比起那个还是研究研究"
    font_size, direction, lines = fit_font_size(text, FONT_PATH, bbox)
    assert font_size >= 35, f"字号应>=35，实际{font_size}"
    assert direction in ("horizontal", "vertical")
    assert isinstance(lines, list) and len(lines) >= 1


def test_fit_font_size_returns_three_tuple():
    """fit_font_size 返回 (字号, 方向, 折行/分列) 三元组。"""
    from amta.typeset.typeset_engine import fit_font_size
    result = fit_font_size("测试", FONT_PATH, [0, 0, 100, 100])
    assert isinstance(result, tuple) and len(result) == 3
    assert isinstance(result[0], int)
    assert result[1] in ("horizontal", "vertical")
    assert isinstance(result[2], list)


def test_vertical_lines_are_columns():
    """竖排时 lines 是按列分割的列表，每列是子串，总字数等于原文。"""
    from amta.typeset.typeset_engine import fit_font_size
    bbox = [0, 0, 100, 300]
    text = "abcdefghij"
    font_size, direction, lines = fit_font_size(text, FONT_PATH, bbox)
    if direction == "vertical":
        assert all(isinstance(col, str) for col in lines)
        assert sum(len(col) for col in lines) == len(text)


def test_empty_text_returns_min_size():
    """空文本返回最小字号和空折行。"""
    from amta.typeset.typeset_engine import fit_font_size
    font_size, direction, lines = fit_font_size("", FONT_PATH, [0, 0, 100, 100])
    assert font_size >= 12
    assert lines == []


# === infer_direction_from_bbox 测试 ===

def test_infer_direction_tall_narrow_box_is_vertical():
    """高宽比 >= 1.5 的窄长框推断为竖排。"""
    from amta.typeset.typeset_engine import infer_direction_from_bbox
    bbox = [0, 0, 166, 691]  # 高宽比 4.16
    assert infer_direction_from_bbox(bbox) == "vertical"


def test_infer_direction_wide_short_box_is_horizontal():
    """宽高比 >= 1.5 的横长框推断为横排。"""
    from amta.typeset.typeset_engine import infer_direction_from_bbox
    bbox = [0, 0, 380, 222]  # 宽高比 1.71
    assert infer_direction_from_bbox(bbox) == "horizontal"


def test_infer_direction_square_box_returns_none():
    """接近方形的框返回 None（不强制方向，回退到字号选优）。"""
    from amta.typeset.typeset_engine import infer_direction_from_bbox
    bbox = [0, 0, 200, 200]  # 1:1
    assert infer_direction_from_bbox(bbox) is None


def test_infer_direction_boundary_ratio():
    """高宽比刚好 1.5 的框推断为竖排。"""
    from amta.typeset.typeset_engine import infer_direction_from_bbox
    bbox = [0, 0, 100, 150]  # 高宽比 1.5
    assert infer_direction_from_bbox(bbox) == "vertical"


def test_infer_direction_near_square_returns_none():
    """高宽比 1.3（<1.5）的框返回 None。"""
    from amta.typeset.typeset_engine import infer_direction_from_bbox
    bbox = [0, 0, 100, 130]  # 高宽比 1.3
    assert infer_direction_from_bbox(bbox) is None


# === fit_font_size preferred_direction 测试 ===

def test_preferred_direction_horizontal_for_wide_box():
    """横长框指定 preferred_direction='horizontal' 时，应选横排。"""
    from amta.typeset.typeset_engine import fit_font_size
    bbox = [0, 0, 380, 222]  # 横长框
    text = "比起那个还是研究研究"
    font_size, direction, lines = fit_font_size(
        text, FONT_PATH, bbox, preferred_direction="horizontal"
    )
    assert direction == "horizontal", f"横长框首选横排，实际选了{direction}"


def test_preferred_direction_vertical_for_tall_box():
    """窄长框指定 preferred_direction='vertical' 时，应选竖排。"""
    from amta.typeset.typeset_engine import fit_font_size
    bbox = [0, 0, 166, 691]  # 窄长框
    text = "冷、冷静点……并不是担心八意大人什么的"
    font_size, direction, lines = fit_font_size(
        text, FONT_PATH, bbox, preferred_direction="vertical"
    )
    assert direction == "vertical", f"窄长框首选竖排，实际选了{direction}"


def test_no_preferred_direction_matches_old_behavior():
    """不传 preferred_direction 时行为与旧版一致（纯字号选优）。"""
    from amta.typeset.typeset_engine import fit_font_size
    bbox = [0, 0, 200, 200]
    text = "测试文本"
    font_size, direction, lines = fit_font_size(text, FONT_PATH, bbox)
    assert direction in ("horizontal", "vertical")
    assert font_size >= 12


def test_preferred_direction_vertical_short_text():
    """短文本窄长框首选竖排，应选竖排且字号合理。"""
    from amta.typeset.typeset_engine import fit_font_size
    bbox = [0, 0, 100, 400]  # 窄长框
    text = "太好了！"
    font_size, direction, lines = fit_font_size(
        text, FONT_PATH, bbox, preferred_direction="vertical"
    )
    assert direction == "vertical", f"短文本窄长框首选竖排，实际选了{direction}"
    assert font_size >= 20



# === wrap_vertical 避头尾测试 ===

def test_wrap_vertical_avoid_punctuation_at_col_start():
    """竖排避头尾：标点不能出现在列首，应挤到上一列末尾。"""
    from amta.typeset.typeset_engine import wrap_vertical
    text = "一二三四五六七八九十，"
    chars_per_col = 10
    lines = wrap_vertical(text, chars_per_col)
    assert len(lines) == 1
    assert lines[0] == "一二三四五六七八九十，"


def test_wrap_vertical_avoid_multiple_punctuation():
    """多个连续标点都不落列首。"""
    from amta.typeset.typeset_engine import wrap_vertical
    text = "一二三四五六七八九十……"
    chars_per_col = 10
    lines = wrap_vertical(text, chars_per_col)
    assert len(lines) == 1
    assert lines[0] == "一二三四五六七八九十……"


def test_wrap_vertical_no_punctuation_normal_split():
    """没有标点时正常分割。"""
    from amta.typeset.typeset_engine import wrap_vertical
    text = "一二三四五六七八九十一二三四五六七八九十"
    chars_per_col = 10
    lines = wrap_vertical(text, chars_per_col)
    assert len(lines) == 2
    assert lines[0] == "一二三四五六七八九十"
    assert lines[1] == "一二三四五六七八九十"


def test_wrap_vertical_punctuation_in_middle_unchanged():
    """标点在列中间时，动态规划优先在标点后断列并避免单字尾列。"""
    from amta.typeset.typeset_engine import wrap_vertical
    text = "一二三四五，六七八九十一二三四五六七八九十"
    chars_per_col = 10
    lines = wrap_vertical(text, chars_per_col)
    assert len(lines) == 2, f"应避免单字尾列: {lines}"
    assert lines[0] == "一二三四五，六七八九"
    assert lines[1] == "十一二三四五六七八九十"
    assert sum(len(col) for col in lines) == len(text)
