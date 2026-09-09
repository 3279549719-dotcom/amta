"""共享指标库：OCR/recall 评分用的归一化、编辑距离、CER/EM 与匹配函数。

唯一归属（/simplify 合并产物）：
- norm/levenshtein/cer/best_match   ← 合并自 ocr_score.py / sfx_compare.py
- match_score                       ← 合并自 recall_score.py
⚠️ 统一后的 norm 保留字母数字（recall_score 旧版丢 0-9，已修正）。
"""
from __future__ import annotations

import re

# 保留：日文假名 / 汉字 / 拉丁字母 / 数字（去掉标点、空白、特殊符号）
_NORM_RE = re.compile(r"[^\u3040-\u30ff\u4e00-\u9fffA-Za-z0-9]")

# 日文残留判别特征：仅假名区（汉字与中文共用 U+4E00-U+9FFF，不可作残留依据）
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff]")


def contains_japanese(s: str) -> bool:
    """字符串是否含日文假名（日文残留判据；汉字不判，因与中文共用字面）。"""
    return bool(_JAPANESE_RE.search(s or ""))


def norm(s: str) -> str:
    """归一化：去掉空白/标点/特殊符号，保留假名、汉字、字母、数字。"""
    return _NORM_RE.sub("", s or "")


def levenshtein(a: str, b: str) -> int:
    """编辑距离（已内部归一化）。"""
    a, b = norm(a), norm(b)
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(gt: str, pred: str) -> float:
    """字符错误率：编辑距离 / GT 长度。两者皆空 = 0；GT 空预测非空 = 1。"""
    a, b = norm(gt), norm(pred)
    if not a and not b:
        return 0.0
    if not a:
        return 1.0
    return levenshtein(a, b) / max(len(a), 1)


def best_match(gt_text: str, pred_list: list[str]) -> tuple[float, str]:
    """从候选预测里挑 CER 最低的。返回 (min_cer, best_pred)。"""
    best, best_p = 1.0, ""
    for p in pred_list:
        sc = cer(gt_text, p)
        if sc < best:
            best, best_p = sc, p
    return best, best_p


def match_score(gt: str, det: str) -> float:
    """内容级匹配分：子串包含 = 1.0，否则按字符集合重合度。"""
    g, d = norm(gt), norm(det)
    if not g or not d:
        return 0.0
    if g in d or d in g:
        return 1.0
    inter = len(set(g) & set(d))
    return inter / max(len(set(g)), 1)
