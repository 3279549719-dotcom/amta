"""vertical_punct 接口测试：竖排形式换算 + 旋转判断（按 Unicode 自动推导）。"""
from amta.typeset.vertical_punct import VERTICAL_COMBINE, should_rotate, verticalize_text


class TestVerticalize:
    def test_brackets_to_vertical_forms(self):
        assert verticalize_text("（无聊）") == "︵无聊︶"

    def test_quotes_to_vertical_forms(self):
        assert verticalize_text("「」") == "︷︸"

    def test_ellipsis_to_vertical(self):
        assert verticalize_text("…") == "︙"

    def test_ordinary_text_untouched(self):
        # 汉字、逗号、句号不在竖排形式表里，原样保留。
        assert verticalize_text("你好，世界。") == "你好，世界。"

    def test_mixed_line(self):
        assert verticalize_text("别为这种事（无聊）吵架…") == "别为这种事︵无聊︶吵架︙"


class TestShouldRotate:
    def test_dashes_rotate(self):
        for ch in ["–", "—", "―", "‒"]:
            assert should_rotate(ch), f"{ch!r} 应旋转"

    def test_wave_dashes_rotate(self):
        for ch in ["〜", "～", "~", "゠", "－"]:
            assert should_rotate(ch), f"{ch!r} 应旋转"

    def test_hanzi_does_not_rotate(self):
        for ch in ["你", "好", "月", "天"]:
            assert not should_rotate(ch), f"{ch!r} 不应旋转"

    def test_fullwidth_punctuation_does_not_rotate(self):
        # 句读点和成对方块是直立小字形，不旋转。
        for ch in ["。", "、", "，", "！", "？", "「", "」"]:
            assert not should_rotate(ch), f"{ch!r} 不应旋转"

    def test_ellipsis_does_not_rotate(self):
        # … 已在 verticalize 换成 ︙，到不了旋转这步。
        assert not should_rotate("…")

    def test_combine_set_has_exclamation_and_question(self):
        assert "！" in VERTICAL_COMBINE and "？" in VERTICAL_COMBINE
