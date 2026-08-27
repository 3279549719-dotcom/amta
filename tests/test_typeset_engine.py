import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import ImageFont

from amta.typeset_engine import decide_direction, fit_font_size, wrap_text


def test_overlay_always_vertical():
    assert decide_direction("overlay_text", [0, 0, 300, 40], 5) == "vertical"  # 扁框也竖排


def test_bubble_uses_bbox_ratio():
    assert decide_direction("dialogue_bubble", [0, 0, 100, 300], 4) == "vertical"   # h/w=3
    assert decide_direction("dialogue_bubble", [0, 0, 300, 100], 4) == "horizontal"
    assert decide_direction("dialogue_bubble", [0, 0, 100, 300], 10) == "horizontal"  # 字多
    assert decide_direction(None, [0, 0, 100, 100], 4) == "horizontal"  # 无 category 默认


def test_wrap_text_basic_and_no_start_punct():
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
    lines = wrap_text("一二三四五六七八九十", font, 100.0)
    assert all(len(ln) <= 5 for ln in lines)          # ~20px/字, max 100 → 每行≤5字
    assert "".join(lines) == "一二三四五六七八九十"
    # 避头尾: 标点不落行首
    lines2 = wrap_text("今天天气真好，我们去散步吧。", font, 80.0)
    assert all(not ln.startswith(("，", "。", "！", "、")) for ln in lines2)
    assert "".join(lines2) == "今天天气真好，我们去散步吧。"


def test_fit_font_size_binary_search(tmp_path):
    f = tmp_path / "f.ttf"
    shutil.copy("C:/Windows/Fonts/msyh.ttc", f)
    size, lines = fit_font_size("今天天气真好", f, [0, 0, 200, 100], "horizontal")
    assert 12 <= size <= 52
    assert lines and all(ln for ln in lines)
    # 超大文本触底 → 12 且仍有行
    size2, _ = fit_font_size("啊" * 200, f, [0, 0, 30, 30], "horizontal")
    assert size2 == 12


def test_fit_vertical_single_column(tmp_path):
    f = tmp_path / "f.ttf"
    shutil.copy("C:/Windows/Fonts/msyh.ttc", f)
    size, lines = fit_font_size("月都", f, [0, 0, 40, 300], "vertical")
    assert size >= 12
    assert "".join(lines) == "月都"
