"""规则过滤 — OCR 后假框过滤（已废弃，保留接口兼容）。

Q3 (2026-09-09): pure_punct / pure_number 规则已被 OCR confidence 过滤替代。
hayai 引擎通过自定义 greedy decoding 提取首 token confidence，first_token_conf < 0.4
的框被判定为假框。57 框样本验证：3 个已知杂质框全部 < 0.3，所有真实文字 > 0.43，
阈值 0.4 时 0 误伤。OCR confidence 是模型原生能力，比人为硬编码规则更通用（The Bitter Lesson）。

历史规则（已移除）：
- pure_punct: 纯标点/空白 → 被 OCR confidence 覆盖（p2 t04 "..." first_conf=0.27）
- pure_number: 纯数字 → 被 OCR confidence 覆盖
- extreme_aspect: 宽高比 > 8 → ADR-024 移除（日漫竖排对话天然高宽比，60% 误伤）
- edge_box: 贴边 ≤ 8px → ADR-024 移除（日漫气泡天然贴边，100% 误伤）
"""
from __future__ import annotations


def rule_filter(blocks: list[dict], img_w: int, img_h: int) -> tuple[list[dict], list[dict]]:
    """规则过滤（已废弃）。直接返回所有框，removed 为空。

    保留此函数仅为接口兼容（ocr_station.py 仍在调用）。
    假框过滤已由 OCR confidence 过滤替代，见 ocr_station.py 的 OCR_CONF_THRESHOLD。

    Args:
        blocks: OCR 后的框列表
        img_w: 原图宽度（保留参数兼容，不再使用）
        img_h: 原图高度（保留参数兼容，不再使用）

    Returns:
        (kept, removed): kept = 全部输入框，removed = 空列表
    """
    return blocks, []
