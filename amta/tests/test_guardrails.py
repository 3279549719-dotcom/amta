"""guardrails 机械护栏测试 — 结构错 + 长度比异常检测。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_mechanical_guardrails_detects_missing_id():
    """缺失 region_id 应被检测。"""
    from amta.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "hello"}, {"region_id": "r01", "text": "world"}]
    translation = {"r00": "你好"}  # r01 缺失
    problems = mechanical_guardrails(canon, translation)
    assert any("r01" in p for p in problems), f"应检测到 r01 缺失，实际: {problems}"


def test_mechanical_guardrails_detects_empty_translation():
    """空译文应被检测。"""
    from amta.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "hello"}]
    translation = {"r00": "   "}
    problems = mechanical_guardrails(canon, translation)
    assert any("empty" in p for p in problems), f"应检测到空译文，实际: {problems}"


def test_length_ratio_detects_severe_truncation():
    """译文长度远小于原文（<30%）应被标记为可疑截断。"""
    from amta.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "ちょっと待て! 仮行さぼりたいだけでしょ"}]
    translation = {"r00": "等一下！"}  # 原文20字符，译文4字，比例20%
    problems = mechanical_guardrails(canon, translation)
    assert any("truncat" in p.lower() or "长度" in p or "ratio" in p.lower()
               for p in problems), f"应检测到严重截断，实际: {problems}"


def test_length_ratio_passes_normal_translation():
    """正常译文（长度比30%-200%）不应触发长度告警。"""
    from amta.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "こんにちは世界"}]
    translation = {"r00": "你好世界"}  # 比例合理
    problems = mechanical_guardrails(canon, translation)
    assert not any("truncat" in p.lower() or "长度" in p or "ratio" in p.lower()
                   for p in problems), f"正常翻译不应触发长度告警，实际: {problems}"


def test_length_ratio_very_short_text_exempt():
    """极短原文（<=4字符）不做长度比检测（避免误报）。"""
    from amta.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "はい"}]
    translation = {"r00": "嗯"}
    problems = mechanical_guardrails(canon, translation)
    assert not any("truncat" in p.lower() or "长度" in p or "ratio" in p.lower()
                   for p in problems), f"极短文本不应触发长度告警，实际: {problems}"


def test_length_ratio_detects_over_expansion():
    """译文长度远大于原文（>300%）应被标记为可疑过度展开。"""
    from amta.guardrails import mechanical_guardrails
    # <=4字符原文不检测（避免误报），所以用5字符以上的原文
    canon = [{"region_id": "r00", "text": "はい、そうです"}]
    translation = {"r00": "是的，我明白了，您说的非常有道理，我完全同意您的观点"}  # 过度展开
    problems = mechanical_guardrails(canon, translation)
    assert any("expansion" in p.lower() or "过度" in p
               for p in problems), f"应检测到过度展开，实际: {problems}"
