"""规则过滤 — OCR 后假框过滤（纯标点/纯数字/极端宽高比/边缘框）。

在检测(conf=0.3) → OCR(baberu) 之后、翻译之前执行，过滤明显的假框。
VLM 三态裁决(stage3_minimal)在此基础上进一步 keep/fix/drop。
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


def is_edge_box(bbox: list, img_w: int, img_h: int, margin: int = 8) -> bool:
    """边缘框（距离图片边缘 <= margin 像素）。"""
    x1, y1, x2, y2 = bbox
    return (x1 <= margin) or (y1 <= margin) or (x2 >= img_w - margin) or (y2 >= img_h - margin)


def is_extreme_aspect(bbox: list, max_ratio: float = 8.0) -> bool:
    """极端宽高比（宽高比 > max_ratio 或高宽比 > max_ratio）。"""
    x1, y1, x2, y2 = bbox
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    return (w / h > max_ratio) or (h / w > max_ratio)


def rule_filter(blocks: list[dict], img_w: int, img_h: int) -> tuple[list[dict], list[dict]]:
    """规则过滤：返回 (kept, removed)，removed 的 block 带 filter_reason 字段。

    过滤规则（按优先级）：
    1. pure_punct: 纯标点/空白
    2. pure_number: 纯数字
    3. extreme_aspect: 宽高比 > 8（细长框，通常是背景线条/装饰）
    4. edge_box: 距离图片边缘 <= 8px（通常是页面编号/边缘装饰）
    """
    kept, removed = [], []
    for b in blocks:
        text = b.get("text", "") or b.get("baberu_text", "") or ""
        bbox = b.get("bbox", [0, 0, 0, 0])
        reason = None
        if is_pure_punct(text):
            reason = "pure_punct"
        elif is_pure_number(text):
            reason = "pure_number"
        elif is_extreme_aspect(bbox):
            reason = "extreme_aspect"
        elif is_edge_box(bbox, img_w, img_h):
            reason = "edge_box"
        if reason:
            b["filter_reason"] = reason
            removed.append(b)
        else:
            kept.append(b)
    return kept, removed
