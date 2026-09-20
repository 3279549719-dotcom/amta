"""文本规范化 + 字符级字体 fallback 测试（Stage 5 渲染前/渲染时）。

方向无关：
1. ASCII 连续点 `...` → 全角横排省略号 `…`（断行前做，避免被拆开）。
方向相关：
2. 竖排渲染时 `…` → 竖排省略号 `︙`(U+FE19)。
字体 fallback：
3. ♡ 在微软雅黑里是 .notdef 空框，但**字符本身不替换**（仍是 ♡），
   而是渲染时借一个有真字形的字体单独画这一个字。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from amta.typeset.typeset_render import (
    _font_for_char,
    _normalize_text_for_render,
    render_item,
)

FONT = "C:/Windows/Fonts/msyh.ttc"


def test_ascii_dots_normalized_to_horizontal_ellipsis():
    """连续 ASCII 点 → 全角横排省略号，且不被拆散。"""
    assert _normalize_text_for_render("...以前...") == "…以前…"
    assert _normalize_text_for_render("谢、谢谢您...！") == "谢、谢谢您…！"


def test_single_ascii_dot_untouched():
    """单个 ASCII 点（如日期 2017.3.26）不是省略号，保持原样。"""
    assert _normalize_text_for_render("2017.3.26 东方祭") == "2017.3.26 东方祭"


def test_heart_not_replaced_by_hanzi():
    """♡ 不被替换成汉字"心"：字符原样保留，靠字体 fallback 渲染。"""
    out = _normalize_text_for_render("请让我留在您身边♡")
    assert "♡" in out
    assert "心" not in out


def test_heart_uses_fallback_font():
    """♡ 在主字体里是 .notdef，_font_for_char 应返回思源黑体。"""
    fb = _font_for_char(FONT, 40, "♡")
    assert "NotoSansSC" in getattr(fb, "path", "") or "NotoSans" in str(fb), \
        f"♡ 应走 fallback 字体：{getattr(fb,'path','?')}"
    # 普通汉字仍用主字体
    main = _font_for_char(FONT, 40, "字")
    assert "NotoSans" not in str(getattr(main, "path", ""))


def test_vertical_ellipsis_uses_vertical_glyph():
    """竖排渲染：省略号必须用竖排形 ︙，不得残留横躺的 . 或 …。"""
    img = Image.new("RGB", (300, 500), "white")
    result = render_item(img, "八意大人...", FONT, [60, 40, 240, 460],
                         stroke=0, preferred_direction="vertical")
    joined = "".join(result["lines"])
    assert "︙" in joined, f"竖排应使用竖排省略号 ︙：{result['lines']}"
    assert "." not in joined, f"不得残留横躺 ASCII 点：{result['lines']}"
    assert "…" not in joined, f"竖排不应残留横排省略号：{result['lines']}"


def test_horizontal_ellipsis_stays_horizontal():
    """横排渲染：省略号保留横排形，不被竖排化。"""
    img = Image.new("RGB", (700, 200), "white")
    result = render_item(img, "总觉得...", FONT, [40, 40, 660, 160],
                         stroke=0, preferred_direction="horizontal")
    joined = "".join(result["lines"])
    assert "…" in joined, f"横排应保留横排省略号 …：{result['lines']}"
    assert "︙" not in joined, f"横排不应出现竖排省略号：{result['lines']}"


def test_vertical_brackets_use_vertical_glyph():
    """竖排：全角括号（）换成竖排括号 ︵︶。"""
    img = Image.new("RGB", (300, 500), "white")
    result = render_item(img, "别为这种事（无聊）吵架", FONT, [60, 40, 240, 460],
                         stroke=0, preferred_direction="vertical")
    joined = "".join(result["lines"])
    assert "︵" in joined and "︶" in joined, f"竖排应使用竖排括号：{result['lines']}"
    assert "（" not in joined and "）" not in joined, f"不应残留横排括号：{result['lines']}"


def test_wave_dash_rotates():
    """竖排：日文波浪号 〜(U+301C) 必须被旋转，不能横躺。"""
    from amta.typeset.vertical_punct import should_rotate
    assert should_rotate("〜"), "〜(U+301C) 应被判定为需旋转"
    img = Image.new("RGB", (300, 500), "white")
    result = render_item(img, "成了宠物啊〜", FONT, [60, 40, 240, 460],
                         stroke=0, preferred_direction="vertical")
    joined = "".join(result["lines"])
    assert "〜" in joined, f"波浪号应保留：{result['lines']}"
