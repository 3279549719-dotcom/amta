"""文本规范化测试（Stage 5 渲染前）：

两条与方向无关、一条与方向相关：
1. ASCII 连续点 `...` 归一化为全角横排省略号 `…`（断行前做，避免三点被拆开）。
2. 字体缺字形字符降级：♡(U+2661) 在微软雅黑里是 .notdef 方框，规范化为"心"。
3. 竖排渲染时 `…` 替换为竖排省略号 `︙`(U+FE19)（字体里唯一有真竖三点字形的）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from amta.typeset.typeset_render import (
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


def test_heart_glyph_falls_back():
    """♡ 在微软雅黑里画成方框，规范化为可渲染的"心"。"""
    assert _normalize_text_for_render("请让我留在您身边♡") == "请让我留在您身边心"


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
