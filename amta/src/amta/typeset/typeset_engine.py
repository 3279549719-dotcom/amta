"""排版引擎核心纯函数(Stage 5, Spec §3): 折行/避头尾/字号二分双方向选优。

ADR-031 决策C：删除 decide_direction，fit_font_size 同时计算横/竖排最大字号选最优。
第一性原理：在给定矩形内放给定文字，字号最大化且不溢出；横竖排只是两种排列方式。
竖排支持多列（与横排多行完全对称），窄长框长文本不再被压成极小字号。
"""
from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

NO_START_PUNCT = "，。！？、）》】……—"
MIN_SIZE = 12
MAX_SIZE = 52
SAFE_RATIO = 0.85
LINE_HEIGHT_RATIO = 1.2   # 行高 = 字号 * 1.2
CHAR_WIDTH_RATIO = 1.15   # 字宽 = 字号 * 1.15（中文等宽近似）

# 方向推断阈值：高宽比 >= 1.5 视为竖排框，宽高比 >= 1.5 视为横排框
DIRECTION_RATIO_THRESHOLD = 1.5


def infer_direction_from_bbox(bbox: list) -> str | None:
    """从文本框长宽比推断原文排版方向。

    日漫排版规律：窄长框（高>>宽）通常是竖排，横长框（宽>>高）通常是横排。
    接近方形的框返回 None，表示不强制方向，回退到字号选优。

    Args:
        bbox: [x1, y1, x2, y2]

    Returns:
        "vertical" | "horizontal" | None
    """
    x1, y1, x2, y2 = bbox
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    if h / w >= DIRECTION_RATIO_THRESHOLD:
        return "vertical"
    if w / h >= DIRECTION_RATIO_THRESHOLD:
        return "horizontal"
    return None


def wrap_text(text: str, font, max_width: float) -> list[str]:
    """贪心按字折行（横排）; 溢出字符为禁行首标点且当前行非空 → 并入当前行(避头尾)。"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        if font.getlength(cur + ch) <= max_width:
            cur += ch
        elif ch in NO_START_PUNCT and cur:
            cur += ch  # 禁则标点不落行首,容忍轻微溢出
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def wrap_vertical(text: str, chars_per_col: int) -> list[str]:
    """竖排按列分割，返回列列表（每列是一个字符串）。

    动态规划最优断点：在所有可能断点中找列数最少、列长最均衡、优先在标点后断的方案。
    替代纯机械按字符数切刀，避免单字占列和词语腰斩。

    成本优先级（从高到低）：
    1. 列数最少
    2. 最大列长最小（列长均衡）
    3. 最后一列长度最大（避免短尾）
    4. 强断点（标点后）断列有奖励

    避头尾：禁则标点（，。！？、）》】……—）不出现在列首。
    强断点容忍：在标点后断列时，当前列可超过 chars_per_col 最多 2 字（与 _fits 的 vertical_tolerance 对称）。
    """
    if chars_per_col <= 0:
        return [text] if text else []

    n = len(text)
    if n == 0:
        return []
    if n <= chars_per_col:
        return [text]

    no_start = set(NO_START_PUNCT)
    strong_break = set("，。！？、；：")
    overflow_tolerance = 2  # 强断点后可超过的字数

    # dp[i] = (成本, 列数, 最后一列长度, 最大列长, 前驱断点j)
    INF = float("inf")
    dp: list[tuple[float, int, int, int, int]] = [(INF, 0, 0, 0, -1)] * (n + 1)
    dp[0] = (0.0, 0, 0, 0, -1)

    for i in range(1, n + 1):
        # j 是当前列起始位置，遍历所有可能的断点
        j_min = max(0, i - chars_per_col - overflow_tolerance)
        for j in range(j_min, i):
            col_len = i - j
            # 避头尾：列首不能是禁则标点
            if j > 0 and text[j] in no_start:
                continue
            # 超过 chars_per_col 时，最后一列或强断点后才允许
            if col_len > chars_per_col:
                is_last_col = (i == n)
                is_after_strong = (j > 0 and text[j - 1] in strong_break)
                if not (is_last_col or is_after_strong):
                    continue

            prev_cost, prev_cols, _, prev_max, _ = dp[j]
            if prev_cost == INF:
                continue

            new_cols = prev_cols + 1
            new_max = max(prev_max, col_len)
            # 成本：列数优先(1000) → 最大列长(10) → 最后一列短尾惩罚
            tail_penalty = (chars_per_col - col_len) if i == n else 0
            cost = new_cols * 1000 + new_max * 10 + tail_penalty
            # 强断点奖励
            if j > 0 and text[j - 1] in strong_break:
                cost -= 5

            if cost < dp[i][0]:
                dp[i] = (cost, new_cols, col_len, new_max, j)

    # 回溯重建列
    cols: list[str] = []
    i = n
    while i > 0:
        _, _, _, _, j = dp[i]
        if j < 0:
            # 兜底：不应发生，但防止无限循环
            cols.append(text[:i])
            break
        cols.append(text[j:i])
        i = j
    cols.reverse()
    return cols


def _fits(lines: list[str], font: ImageFont.FreeTypeFont, bbox: list,
          direction: str) -> bool:
    """检查折行/分列结果是否放入框内。"""
    x1, y1, x2, y2 = bbox
    w, h = (x2 - x1) * SAFE_RATIO, (y2 - y1) * SAFE_RATIO
    if direction == "vertical":
        # 竖排：列数 * 字宽 <= 框宽；最长列字数 * 行高 <= 框高
        max_col_chars = max(len(col) for col in lines) if lines else 0
        total_w = len(lines) * font.size * CHAR_WIDTH_RATIO
        # 容忍避头尾导致的轻微溢出（最多2个字符高度），与横排 wrap_text 容忍溢出对称
        vertical_tolerance = 2 * font.size * LINE_HEIGHT_RATIO
        return total_w <= w and (max_col_chars * font.size * LINE_HEIGHT_RATIO) <= h + vertical_tolerance
    # 横排：最长行像素宽 <= 框宽；行数 * 行高 <= 框高
    max_line = max(font.getlength(ln) for ln in lines) if lines else 0
    return max_line <= w and len(lines) * font.size * LINE_HEIGHT_RATIO <= h


def _max_size_for_direction(text: str, font_path: Path, bbox: list,
                            direction: str, min_sz: int, max_sz: int
                            ) -> tuple[int, list[str]]:
    """对指定方向做字号二分，返回 (最大字号, 折行/分列结果)。"""
    if not text:
        return min_sz, []
    x1, y1, x2, y2 = bbox
    w, h = (x2 - x1) * SAFE_RATIO, (y2 - y1) * SAFE_RATIO
    lo, hi = min_sz, max_sz
    best, best_lines = min_sz, []
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(str(font_path), mid)
        if direction == "vertical":
            # 竖排：每列字数 = 框高 / 行高，按列分割
            chars_per_col = max(1, int(h / (mid * LINE_HEIGHT_RATIO)))
            lines = wrap_vertical(text, chars_per_col)
        else:
            lines = wrap_text(text, font, w)
        if lines and _fits(lines, font, bbox, direction):
            best, best_lines = mid, lines
            lo = mid + 1
        else:
            hi = mid - 1
    if not best_lines:  # min_sz 也放不下
        font = ImageFont.truetype(str(font_path), min_sz)
        if direction == "vertical":
            chars_per_col = max(1, int(h / (min_sz * LINE_HEIGHT_RATIO)))
            best_lines = wrap_vertical(text, chars_per_col)
        else:
            best_lines = wrap_text(text, font, w)
        return min_sz, best_lines
    return best, best_lines


def fit_font_size(text: str, font_path: Path, bbox: list,
                  min_sz: int = MIN_SIZE, max_sz: int = MAX_SIZE,
                  preferred_direction: str | None = None
                  ) -> tuple[int, str, list[str]]:
    """同时计算横排和竖排的最大可行字号，返回 (字号, 方向, 折行/分列)。

    第一性原理：在给定矩形内放给定文字，字号最大化且不溢出。
    两种方向约束方程一致（宽高互换），选字号更大者。

    preferred_direction: 首选方向（"horizontal"|"vertical"|None）。
        - 若指定，优先在该方向最大化字号；
        - 仅当首选方向字号 < 次选方向字号 * 0.70 时才切换到次选方向；
        - None 时纯字号选优（旧行为）。
    """
    h_size, h_lines = _max_size_for_direction(text, font_path, bbox, "horizontal", min_sz, max_sz)
    v_size, v_lines = _max_size_for_direction(text, font_path, bbox, "vertical", min_sz, max_sz)

    if preferred_direction == "horizontal":
        # 首选横排：横排字号不小于竖排70%就选横排
        if h_size >= v_size * 0.70:
            return h_size, "horizontal", h_lines
        return v_size, "vertical", v_lines
    if preferred_direction == "vertical":
        # 首选竖排：竖排字号不小于横排70%就选竖排
        if v_size >= h_size * 0.70:
            return v_size, "vertical", v_lines
        return h_size, "horizontal", h_lines

    # 无首选方向：纯字号选优，平局偏向竖排（旧行为）
    if v_size >= h_size:
        return v_size, "vertical", v_lines
    return h_size, "horizontal", h_lines
