"""翻译机械护栏 — 从 translate.py 拆出的深模块。

唯一归属：
- mechanical_guardrails   护栏① 结构错（region_id 一一对应/无漏无重/长度比异常）
- japanese_residue_check  护栏② 日文残留/空译文
- _run_guardrails_for_test 测试桥（机械护栏 + Glossary Validator 合并，ADR-016）

纯校验，无 I/O 无状态；日文判据复用 metrics.contains_japanese（文本事实归 metrics）。
"""
from __future__ import annotations

from amta.metrics import contains_japanese

# 长度比异常阈值：译文/原文字符数比低于此值视为可疑截断，高于此值视为可疑过度展开
TRUNCATION_RATIO = 0.30
OVER_EXPANSION_RATIO = 3.0
MIN_SRC_LENGTH_FOR_RATIO_CHECK = 5  # 极短原文不做长度比检测（避免误报）


def mechanical_guardrails(canon: list[dict], translation: dict[str, str]) -> list[str]:
    """护栏①结构错：region_id 与输入一一对应（无漏无重）、字段齐全、长度比异常。"""
    problems = []
    ids = {r["region_id"] for r in canon}
    for r in canon:
        rid = r["region_id"]
        if rid not in translation:
            problems.append(f"missing region_id {rid}")
        elif not translation[rid].strip():
            problems.append(f"empty translation for {rid}")
        else:
            # 长度比异常检测：译文字符数 / 原文字符数
            src = (r.get("text") or r.get("baberu_text") or "").strip()
            tgt = translation[rid].strip()
            if len(src) >= MIN_SRC_LENGTH_FOR_RATIO_CHECK:
                ratio = len(tgt) / len(src) if len(src) > 0 else 1.0
                if ratio < TRUNCATION_RATIO:
                    problems.append(
                        f"suspected truncation {rid}: "
                        f"src={len(src)}chars tgt={len(tgt)}chars ratio={ratio:.2f}"
                    )
                elif ratio > OVER_EXPANSION_RATIO:
                    problems.append(
                        f"suspected over-expansion {rid}: "
                        f"src={len(src)}chars tgt={len(tgt)}chars ratio={ratio:.2f}"
                    )
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
