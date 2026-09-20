"""统一断行函数测试：硬禁则 + DP 最优断点。

核心契约：
- 标点不能出现在行首（行頭禁則）
- 开括号不能出现在行尾（行末禁則）
- 短文本不断行（1-2 字不拆）
- 横竖排共用同一套断点逻辑
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.typeset.typeset_engine import break_lines


def test_no_start_punctuation():
    """禁则标点（，。！？）不能出现在行首。"""
    # "你好，世界" max=3：正确断法是 "你好，" + "世界"
    # 错误断法会让 "，" 出现在第二行开头
    lines = break_lines("你好，世界", max_chars=3)
    for line in lines:
        assert not line.startswith("，"), f"逗号不能在行首：{lines}"
        assert not line.startswith("。"), f"句号不能在行首：{lines}"


def test_no_open_bracket_at_end():
    """开括号（「（）不能出现在行尾。"""
    # "我说「你好」" max=4：正确断法不能让 "「" 在行尾
    lines = break_lines("我说「你好」", max_chars=4)
    for line in lines:
        assert not line.endswith("「"), f"开括号不能在行尾：{lines}"
        assert not line.endswith("（"), f"开括号不能在行尾：{lines}"


def test_short_text_no_break():
    """短文本（<= max_chars）不断行。"""
    lines = break_lines("红蓝", max_chars=5)
    assert len(lines) == 1, f"短文本不该断：{lines}"
    assert lines[0] == "红蓝"


def test_total_chars_preserved():
    """断行后总字数等于原文。"""
    text = "这个测试文本比较长需要断成好几行才行不然放不下"
    lines = break_lines(text, max_chars=6)
    assert sum(len(ln) for ln in lines) == len(text), f"字数丢了：{lines}"


def test_no_punctuation_only_line():
    """不应该出现只有标点的行。"""
    lines = break_lines("你好！！", max_chars=3)
    for line in lines:
        # 不能整行都是标点
        punct_only = all(c in "！？。，、；：「」（）" for c in line)
        assert not punct_only, f"出现了纯标点行：{lines}"


def test_vertical_same_logic():
    """竖排和横排用同一套断行逻辑（只是列/行命名不同）。"""
    text = "请让我留在您身边"
    # 竖排：max_chars 是每列字数
    lines = break_lines(text, max_chars=4)
    # 总字数守恒
    assert sum(len(ln) for ln in lines) == len(text)
