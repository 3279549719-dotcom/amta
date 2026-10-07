"""metrics.norm() 归一化测试：片假名→平假名、小写→大写假名、标点剥离。

锁定 /simplify 合并后的 norm 在假名统一上的行为（book-level glossary Task 1）。
"""
from amta.common.metrics import norm


def test_norm_normalizes_katakana_to_hiragana():
    assert norm("スーさん") == norm("すーさん")


def test_norm_normalizes_small_kana():
    assert norm("スーサン") == norm("スーさん")  # ン vs ん after hiragana conv
    assert norm("ット") == norm("ツト")  # small tsu → big tsu


def test_norm_normalizes_hiragana_small_kana():
    # 平假名小写同样折叠：くぃ → くい（test_shared_lib 的旧翻转对因此改为普通假名串）
    assert norm("くぃ") == norm("くい")


def test_norm_still_strips_punctuation():
    assert norm("「スーさん」") == norm("スーさん")
