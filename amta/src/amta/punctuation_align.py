"""机械标点对齐（P2）：原文可删除标点数量是译文上限。

规则：
- 可删除标点：，。、；：（LLM"规范化"时额外添加的）
- 不可删除标点：！？……—（语气/情感表达，保留）
- 译文可删除标点总数 > 原文时，按优先级删除多余部分
- 删除优先级：句号 > 逗号 > 顿号 > 分号 > 冒号（从后往前删，避免索引偏移）

设计原理：日语漫画原文几乎零标点（靠换行断句），LLM 翻译时"规范化"加了
大量逗号句号，占用气泡空间影响观感。机械对齐比 prompt 硬约束更可靠。
"""
from __future__ import annotations

# 可删除标点，按删除优先级排序（索引越小越先删）
REMOVABLE_PUNCTUATION = ["。", "，", "、", "；", "："]

# 不可删除的语气标点（不计入上限）
EMOTIVE_PUNCTUATION = "！？…—"


def _count_removable(text: str) -> dict[str, int]:
    """统计文本中各类可删除标点的数量。"""
    return {p: text.count(p) for p in REMOVABLE_PUNCTUATION}


def align_punctuation(source: str, translation: str) -> str:
    """对齐译文标点到原文上限。

    Args:
        source: 原文（日语）
        translation: 译文（中文）

    Returns:
        标点对齐后的译文
    """
    if not translation:
        return translation

    src_counts = _count_removable(source)
    dst_counts = _count_removable(translation)

    src_total = sum(src_counts.values())
    dst_total = sum(dst_counts.values())

    # 译文标点不超过原文，无需处理
    if dst_total <= src_total:
        return translation

    # 需要删除的数量
    to_remove = dst_total - src_total

    # 按优先级从后往前删除标点
    result = list(translation)
    removed = 0

    for punct in REMOVABLE_PUNCTUATION:
        if removed >= to_remove:
            break
        # 从后往前遍历，删除该类型的标点
        for i in range(len(result) - 1, -1, -1):
            if removed >= to_remove:
                break
            if result[i] == punct:
                result.pop(i)
                removed += 1

    return "".join(result)
