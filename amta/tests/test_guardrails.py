"""guardrails 机械护栏测试 — 仅结构错（region_id 一一对应）。

长度比护栏与 empty translation 检查已于 8a576d2（2026-09-08）移除：
- 日译中天然压缩，0.30/3.0 阈值误报正常压缩
- 乱码框/无意义框输出空串是合法结果（"乱码→空"条款）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_mechanical_guardrails_detects_missing_id():
    """缺失 region_id 应被检测。"""
    from amta.guards.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "hello"}, {"region_id": "r01", "text": "world"}]
    translation = {"r00": "你好"}  # r01 缺失
    problems = mechanical_guardrails(canon, translation)
    assert any("r01" in p for p in problems), f"应检测到 r01 缺失，实际: {problems}"


def test_mechanical_guardrails_detects_extra_id():
    """多出的 region_id 应被检测。"""
    from amta.guards.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "hello"}]
    translation = {"r00": "你好", "r99": "幻觉"}
    problems = mechanical_guardrails(canon, translation)
    assert any("extra" in p for p in problems), f"应检测到多余 id，实际: {problems}"


def test_mechanical_guardrails_allows_empty_translation():
    """空译文合法：乱码框/无意义框应输出为空（8a576d2 移除 empty 检查）。"""
    from amta.guards.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "hello"}]
    translation = {"r00": "   "}
    problems = mechanical_guardrails(canon, translation)
    assert not problems, f"空译文不应报错，实际: {problems}"


def test_normal_compressed_translation_not_flagged():
    """日译中天然压缩（短译文）不触发任何护栏（长度比已移除）。"""
    from amta.guards.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "ちょっと待て! 仮行さぼりたいだけでしょ"}]
    translation = {"r00": "等一下！"}  # 原文20字符，译文4字 —— 正常压缩
    problems = mechanical_guardrails(canon, translation)
    assert not problems, f"正常压缩不应报错，实际: {problems}"
