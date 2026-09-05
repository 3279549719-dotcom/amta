"""punctuation_align 机械标点对齐测试。

规则：原文可删除标点（，。、；：）数量是译文上限，超出部分按优先级删除。
语气标点（！？……—）不删，保留情感表达。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_no_punct_source_removes_all_removable_punct():
    """原文0可删除标点，译文的逗号句号全部删除，语气标点保留。"""
    from amta.punctuation_align import align_punctuation
    src = "これはテストです"  # 0标点
    dst = "这是，一个测试。句子。"
    result = align_punctuation(src, dst)
    assert "，" not in result
    assert "。" not in result
    assert result == "这是一个测试句子"


def test_source_has_comma_keeps_one_comma():
    """原文1逗号，译文2逗号1句号 → 删1逗号1句号，保留1逗号。"""
    from amta.punctuation_align import align_punctuation
    src = "これは、テストです"  # 1逗号
    dst = "这是，一个，测试。"
    result = align_punctuation(src, dst)
    assert result.count("，") == 1
    assert result.count("。") == 0


def test_exclamation_and_question_preserved():
    """语气标点！？不删除，即使原文没有。"""
    from amta.punctuation_align import align_punctuation
    src = "これはテスト"  # 0标点
    dst = "这是测试！真的吗？"
    result = align_punctuation(src, dst)
    assert "！" in result
    assert "？" in result
    assert "，" not in result
    assert "。" not in result


def test_ellipsis_preserved():
    """省略号……不删除。"""
    from amta.punctuation_align import align_punctuation
    src = "これはテスト"
    dst = "这是测试……也许吧……"
    result = align_punctuation(src, dst)
    assert result.count("…") == 4  # 两个省略号=4个…


def test_dash_preserved():
    """破折号—不删除。"""
    from amta.punctuation_align import align_punctuation
    src = "これはテスト"
    dst = "这是——测试"
    result = align_punctuation(src, dst)
    assert "—" in result


def test_dst_punct_less_than_src_unchanged():
    """译文标点少于原文时不修改。"""
    from amta.punctuation_align import align_punctuation
    src = "これは、テスト、です、よ"  # 3逗号
    dst = "这是测试"
    result = align_punctuation(src, dst)
    assert result == dst


def test_mixed_punct_removal_priority():
    """混合标点时按优先级删除：句号>逗号>顿号。"""
    from amta.punctuation_align import align_punctuation
    src = "これはテスト"  # 0可删除标点
    dst = "这是、一个，测试。"
    result = align_punctuation(src, dst)
    assert "、" not in result
    assert "，" not in result
    assert "。" not in result
    assert result == "这是一个测试"


def test_empty_text():
    """空文本返回空。"""
    from amta.punctuation_align import align_punctuation
    assert align_punctuation("", "") == ""
    assert align_punctuation("", "测试") == "测试"


def test_only_removable_punct_counted():
    """只有可删除标点计入上限，语气标点不计入。"""
    from amta.punctuation_align import align_punctuation
    src = "これはテスト"  # 0可删除标点
    dst = "这是！测试？真的……"
    result = align_punctuation(src, dst)
    # 语气标点全部保留
    assert "！" in result
    assert "？" in result
    assert "…" in result
