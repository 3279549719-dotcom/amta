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
    from amta.typeset_engine import fit_font_size
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
    from amta.typeset_engine import fit_font_size
    bbox = [0, 0, 380, 222]
    text = "比起那个还是研究研究"
    font_size, direction, lines = fit_font_size(text, FONT_PATH, bbox)
    assert font_size >= 35, f"字号应>=35，实际{font_size}"
    assert direction in ("horizontal", "vertical")
    assert isinstance(lines, list) and len(lines) >= 1


def test_fit_font_size_returns_three_tuple():
    """fit_font_size 返回 (字号, 方向, 折行/分列) 三元组。"""
    from amta.typeset_engine import fit_font_size
    result = fit_font_size("测试", FONT_PATH, [0, 0, 100, 100])
    assert isinstance(result, tuple) and len(result) == 3
    assert isinstance(result[0], int)
    assert result[1] in ("horizontal", "vertical")
    assert isinstance(result[2], list)


def test_vertical_lines_are_columns():
    """竖排时 lines 是按列分割的列表，每列是子串，总字数等于原文。"""
    from amta.typeset_engine import fit_font_size
    bbox = [0, 0, 100, 300]
    text = "abcdefghij"
    font_size, direction, lines = fit_font_size(text, FONT_PATH, bbox)
    if direction == "vertical":
        assert all(isinstance(col, str) for col in lines)
        assert sum(len(col) for col in lines) == len(text)


def test_empty_text_returns_min_size():
    """空文本返回最小字号和空折行。"""
    from amta.typeset_engine import fit_font_size
    font_size, direction, lines = fit_font_size("", FONT_PATH, [0, 0, 100, 100])
    assert font_size >= 12
    assert lines == []
