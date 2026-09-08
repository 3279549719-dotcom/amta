"""翻译机械护栏 — 从 translate.py 拆出的深模块。

唯一归属：
- mechanical_guardrails   护栏① 结构错（region_id 一一对应/无漏无重）
- japanese_residue_check  护栏② 日文残留/空译文
- _run_guardrails_for_test 测试桥（机械护栏 + Glossary Validator 合并，ADR-016）

纯校验，无 I/O 无状态；日文判据复用 metrics.contains_japanese（文本事实归 metrics）。

长度比护栏（TRUNCATION_RATIO/OVER_EXPANSION_RATIO）已移除（2026-09-08）：
日译中天然压缩，0.30/3.0 阈值误报正常压缩；"防截断"反而"制造截断"。
"""
from __future__ import annotations

from amta.metrics import contains_japanese


def mechanical_guardrails(canon: list[dict], translation: dict[str, str]) -> list[str]:
    """护栏①结构错：region_id 与输入一一对应（无漏无重）、字段齐全。

    长度比检测已移除：日译中天然压缩，阈值误报正常压缩。
    """
    problems = []
    ids = {r["region_id"] for r in canon}
    for r in canon:
        rid = r["region_id"]
        if rid not in translation:
            problems.append(f"missing region_id {rid}")
        # 注：empty translation 不视为错误——乱码框/无意义框应输出为空（"乱码→空"条款）
    extra = set(translation) - ids
    if extra:
        problems.append(f"extra region_ids: {sorted(extra)}")
    return problems


def japanese_residue_check(texts: list[str]) -> list[str]:
    """护栏②残留错：日文残留/空译文检测。返回有问题文本列表。"""
    bad = []
    for t in texts:
        t = t or ""
        if not t.strip():
            bad.append("")
        elif contains_japanese(t):
            bad.append(t)
    return bad


def _run_guardrails_for_test(canon: list[dict], translation: dict[str, str],
                             work_state: dict) -> list[str]:
    """测试桥：机械护栏 + Glossary Validator 合并（ADR-016 双层机械硬约束）。"""
    from amta.glossary import check_glossary
    return mechanical_guardrails(canon, translation) + check_glossary(canon, translation, work_state)
