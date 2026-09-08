"""规则过滤 — OCR 后假框过滤（纯标点/纯数字）。

在检测 → OCR 之后、翻译之前执行，过滤明显的假框。
仅保留基于 OCR 文本内容的规则（pure_punct / pure_number）。

几何规则（extreme_aspect / edge_box）已移除：
- 日漫竖排对话天然高宽比，extreme_aspect>8 会误杀竖排喊叫/长对话/横排标题
- 日漫气泡天然贴边绘制，edge_box≤8px 会误杀贴边对话/旁白
- 全40页审计：edge_box 100%误伤（3/3），extreme_aspect 60%误伤（3/5）
"""
from __future__ import annotations

PUNCT_CHARS = set("．。・〜~…—-「」『』、！？!?　 \t\n.,;:!?\"'()[]{}<>/\\|@#$%^&*_+=`~")


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (0x3040 <= cp <= 0x30FF) or (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF)


def is_pure_punct(text: str) -> bool:
    """纯标点（含日文/英文标点、空白、非字母数字非CJK字符）。"""
    if not text:
        return True
    return all(ch in PUNCT_CHARS or (not ch.isalnum() and not _is_cjk(ch)) for ch in text)


def is_pure_number(text: str) -> bool:
    """纯数字（有数字但没有 CJK 或字母）。"""
    if not text:
        return False
    has_digit = any(ch.isdigit() for ch in text)
    has_cjk_or_alpha = any(_is_cjk(ch) or ch.isalpha() for ch in text)
    return has_digit and not has_cjk_or_alpha


def rule_filter(blocks: list[dict], img_w: int, img_h: int) -> tuple[list[dict], list[dict]]:
    """规则过滤：返回 (kept, removed)，removed 的 block 带 filter_reason 字段。

    过滤规则（按优先级）：
    1. pure_punct: 纯标点/空白
    2. pure_number: 纯数字

    注：img_w / img_h 参数保留为接口兼容（几何规则已移除，不再使用）。
    """
    kept, removed = [], []
    for b in blocks:
        text = b.get("text", "") or b.get("baberu_text", "") or ""
        reason = None
        if is_pure_punct(text):
            reason = "pure_punct"
        elif is_pure_number(text):
            reason = "pure_number"
        if reason:
            b["filter_reason"] = reason
            removed.append(b)
        else:
            kept.append(b)
    return kept, removed
