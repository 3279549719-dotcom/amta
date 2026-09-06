"""竖排分列均衡测试 — 动态规划最优断点，替代纯机械切刀。

Seam: wrap_vertical(text, chars_per_col) -> list[str]
只验证输入输出行为，不碰内部实现。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.typeset_engine import wrap_vertical


class TestAvoidSingleCharLastColumn:
    """最后一列不应只剩1个字（单字占列观感最差）。"""

    def test_should_not_leave_single_char_tail(self):
        """「应该先道谢吧」6字，每列限5字 → 不应出现 5+1，可单列溢出或均衡分列。"""
        cols = wrap_vertical("应该先道谢吧", 5)
        # 核心诉求：无单字列
        for col in cols:
            assert len(col) > 1, f"不应出现单字列: {cols}"
        # 总字数不变
        assert sum(len(c) for c in cols) == 6

    def test_name_two_char_tail_balanced(self):
        """「请告诉我你的名字」8字，每列限6字 → 不应有过短尾列。"""
        cols = wrap_vertical("请告诉我你的名字", 6)
        for col in cols:
            assert len(col) > 1, f"不应出现单字列: {cols}"
        assert sum(len(c) for c in cols) == 8

    def test_long_text_balanced_split(self):
        """长文本必须分列时，列长应均衡，不出现单字尾。"""
        # 15字，N=5，必须分3列
        cols = wrap_vertical("在那之后我的研究可能是因为八意大人", 5)
        assert len(cols) >= 2, f"长文本应分列: {cols}"
        for col in cols:
            assert len(col) > 1, f"不应出现单字列: {cols}"
        # 列长差不超过2
        lengths = [len(c) for c in cols]
        assert max(lengths) - min(lengths) <= 2, f"列长不均衡: {cols}"


class TestPreferBreakAfterPunct:
    """优先在标点后断列，避免腰斩词语。"""

    def test_thanks_not_split(self):
        """「探女姐姐谢谢！」6字，每列限5字 → "谢谢"不应被腰斩。"""
        cols = wrap_vertical("探女姐姐谢谢！", 5)
        # "谢谢"应该在同一列
        joined_check = any("谢谢" in col for col in cols)
        assert joined_check, f"'谢谢'被腰斩了: {cols}"

    def test_comma_is_strong_break_point(self):
        """有逗号时优先在逗号后断。"""
        cols = wrap_vertical("那么，丰酱，去把羽毛给辉夜大人看看", 7)
        # 第一列应该在第一个逗号后结束
        assert cols[0].endswith("，"), f"第一列应在逗号后断: {cols}"


class TestKeepExistingBehavior:
    """已有功能不回归。"""

    def test_no_punct_normal_split(self):
        """无标点长文本正常分割，列数正确。"""
        cols = wrap_vertical("一二三四五六七八九十一二三四五六七八九十", 10)
        assert len(cols) == 2
        assert cols[0] == "一二三四五六七八九十"
        assert cols[1] == "一二三四五六七八九十"

    def test_punct_not_at_col_start(self):
        """避头尾：标点不出现在列首。"""
        cols = wrap_vertical("一二三四五六七八九十，", 10)
        # 标点应挤到第一列，不单独成列
        assert len(cols) == 1, f"标点不应单独成列: {cols}"
        assert cols[0] == "一二三四五六七八九十，"

    def test_short_text_single_column(self):
        """短文本不拆列。"""
        cols = wrap_vertical("你好", 5)
        assert cols == ["你好"]

    def test_empty_text(self):
        """空文本返回空列表。"""
        assert wrap_vertical("", 5) == []

    def test_chars_per_col_zero(self):
        """chars_per_col<=0 回退为单列。"""
        cols = wrap_vertical("你好世界", 0)
        assert cols == ["你好世界"]
