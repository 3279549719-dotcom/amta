"""竖排列末逗号消冗 —— 渲染层集成（Task 3）。

验证"只隐藏字形、不动布局"这一核心不变量：
- lines 元数据（落盘契约）逐字不变；
- 字格推进 / 列高 / 整组列垂直居中不变 → 无位移；
- 变化像素只出现在被掩码的那个字格里；
- 横排路径完全不经过掩码（列末/行尾逗号照画）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from amta.typeset.typeset_render import _render_vertical, render_item  # noqa: E402

FONT = "C:/Windows/Fonts/msyh.ttc"

pytestmark = pytest.mark.skipif(
    not Path(FONT).exists(), reason=f"需要中文字体 {FONT}"
)

WHITE = (255, 255, 255)


def ink_stats(img: Image.Image, bbox) -> tuple[int, tuple | None]:
    """bbox 内非白像素数与墨迹 bbox。"""
    x1, y1, x2, y2 = (int(v) for v in bbox)
    xs, ys, n = [], [], 0
    px = img.load()
    for y in range(y1, y2):
        for x in range(x1, x2):
            if px[x, y] != WHITE:
                xs.append(x)
                ys.append(y)
                n += 1
    if not n:
        return 0, None
    return n, (min(xs), min(ys), max(xs), max(ys))


def _vertical_result(text, bbox, img=None):
    img = img or Image.new("RGB", (400, 900), "white")
    return img, render_item(img, text, FONT, bbox, stroke=0,
                            preferred_direction="vertical")


def _horizontal_result(text, bbox, img=None):
    img = img or Image.new("RGB", (800, 400), "white")
    return img, render_item(img, text, FONT, bbox, stroke=0,
                            preferred_direction="horizontal")


def _no_hide(columns):
    """旧行为：不隐藏任何字形。"""
    return [[False] * len(c) for c in columns]


def _cell_of(result, col_idx_from_right: int, char_idx: int, bbox):
    """列/字格在页面坐标系里的矩形（与 _render_vertical 的排布一致）。"""
    lines = result["lines"]
    lh = result["line_step"]
    col_w = result["col_step"]
    cx, cy = result["anchor_pos"]
    max_col_h = max(len(c) for c in lines) * lh
    top = cy - max_col_h // 2
    # 第 0 列是最右列
    col_left = cx + (len(lines) * col_w) / 2 - (col_idx_from_right + 1) * col_w
    return (int(col_left), int(top + char_idx * lh),
            int(col_left + col_w), int(top + (char_idx + 1) * lh))


# === 布局不变量 ===

def test_render_item_preserves_lines_metadata():
    """关键回归：译文与 lines 元数据不得被改写（只隐藏渲染）。"""
    text = "仙人风范，端庄贤淑"
    _, result = _vertical_result(text, [100, 100, 240, 700])
    assert result["layout_direction"] == "vertical"
    assert [c for c in result["lines"]] == ["仙人风范，", "端庄贤淑"], result["lines"]
    assert sum(len(col) for col in result["lines"]) == len(text)


def test_render_item_keeps_cell_advance_and_column_height():
    """只隐藏字形：列高与组位置不变（不会因删字而重新居中/位移）。"""
    text = "仙人风范，端庄贤淑"
    bbox = [100, 100, 240, 700]
    img, result = _vertical_result(text, bbox)
    lines = result["lines"]
    lh = result["line_step"]
    _, cy = result["anchor_pos"]
    top = cy - max(len(c) for c in lines) * lh // 2

    left_ink_top = None
    px = img.load()
    for y in range(bbox[1], bbox[3]):
        if any(px[x, y] != WHITE for x in range(bbox[0], bbox[2])):
            left_ink_top = y
            break
    assert left_ink_top is not None
    assert abs(left_ink_top - top) < lh, f"列顶 {left_ink_top} 偏离预期 {top}"
    assert result["anchor_pos"] == [(bbox[0] + bbox[2]) // 2,
                                    (bbox[1] + bbox[3]) // 2]


def test_changed_pixels_confined_to_masked_cell(monkeypatch):
    """像素级最强断言：改动只发生在被掩码的字格，其余字格逐像素一致。

    这直接证明"列高 / 字格推进 / 居中不变"——没有任何位移。
    """
    import amta.typeset.typeset_render as tr

    text = "仙人风范，端庄贤淑"
    bbox = [100, 100, 240, 700]

    img_after, result_after = _vertical_result(text, bbox)
    monkeypatch.setattr(tr, "column_end_pause_mask", _no_hide)
    img_before, result_before = _vertical_result(text, bbox)

    for key in ("lines", "line_step", "col_step", "anchor_pos", "font_size"):
        assert result_before[key] == result_after[key], f"{key} 发生变化"

    masked_cell = _cell_of(result_after, 0, len(result_after["lines"][0]) - 1, bbox)
    assert ink_stats(img_after, masked_cell)[0] == 0, "被掩码字格应无墨迹"

    pa, pb = img_after.load(), img_before.load()
    changed = [(x, y)
               for y in range(bbox[1], bbox[3])
               for x in range(bbox[0], bbox[2])
               if pa[x, y] != pb[x, y]]
    assert changed, "掩码应至少改变被隐藏逗号格的像素"
    x1, y1, x2, y2 = masked_cell
    outside = [p for p in changed
               if not (x1 <= p[0] < x2 and y1 <= p[1] < y2)]
    assert not outside, f"改动溢出被掩码字格外: {outside[:5]}"


# === 掩码确实生效 ===

def test_render_item_hides_column_end_comma_glyph():
    """渲染层：列末逗号的字形不再出现在列末字格里。"""
    text = "仙人风范，端庄贤淑"
    bbox = [100, 100, 240, 700]
    img, result = _vertical_result(text, bbox)
    assert result["lines"] == ["仙人风范，", "端庄贤淑"]
    cell = _cell_of(result, 0, len(result["lines"][0]) - 1, bbox)
    n_cell, _ = ink_stats(img, cell)
    assert n_cell == 0, f"列末逗号字格仍被绘制: {n_cell}px @ {cell}"


def test_render_item_keeps_sentence_final_mark():
    """渲染层：句末 ！ 落在列末时保留。"""
    text = "太好了！我们走吧走吧走吧走吧走吧走吧走吧走吧走吧走吧"
    _, result = _vertical_result(text, [100, 100, 240, 800])
    assert result["layout_direction"] == "vertical"
    assert "！" in "".join(result["lines"]), f"句末标点被误删: {result['lines']}"


def test_render_item_keeps_mid_column_comma_glyph():
    """列中逗号不是边界冗余，字形必须照画。

    bbox 高度决定列宽：这个高度下断列结果是 ['仙人，风', '范端庄贤淑哦']，
    逗号位于第 0 列**内部**（不是列末），因此必须保留。
    """
    text = "仙人，风范端庄贤淑哦"
    bbox = [100, 100, 240, 900]
    img, result = _vertical_result(text, bbox)
    lines = result["lines"]
    assert lines[0] == "仙人，风", lines
    idx = lines[0].index("，")
    assert idx < len(lines[0]) - 1, "本用例要求逗号在列内部"
    cell = _cell_of(result, 0, idx, bbox)
    n_cell, _ = ink_stats(img, cell)
    assert n_cell > 0, f"列中逗号被误隐藏 @ {cell}"


# === 横排不受影响（Task 3 边界要求）===

def test_horizontal_path_never_calls_column_mask(monkeypatch):
    """掩码只挂在竖排分支：横排渲染一次都不该调用它。"""
    import amta.typeset.typeset_render as tr

    calls: list[list[str]] = []
    real = tr.column_end_pause_mask

    def spy(columns):
        calls.append(list(columns))
        return real(columns)

    monkeypatch.setattr(tr, "column_end_pause_mask", spy)
    _, result = _horizontal_result("仙人风范，端庄贤淑，", [50, 50, 750, 350])
    assert result["layout_direction"] == "horizontal"
    assert calls == [], f"横排不应调用列末掩码，实际调用 {calls}"


def test_horizontal_trailing_comma_is_still_drawn():
    """横排的行尾逗号照画：列末冗余只属于竖排分列语境。"""
    bbox = [50, 50, 750, 350]
    img_with, _ = _horizontal_result("仙人风范，端庄贤淑，", bbox)
    img_without, _ = _horizontal_result("仙人风范，端庄贤淑", bbox)
    n_with, _ = ink_stats(img_with, bbox)
    n_without, _ = ink_stats(img_without, bbox)
    assert n_with > n_without, (
        f"横排行尾逗号未被绘制: 含逗号 {n_with}px 应 > 不含 {n_without}px")


# === 空译文（lines == []）不得让竖排渲染炸掉 ===============================

def test_render_vertical_with_no_columns_is_a_noop():
    """`lines == []` 时 `_render_vertical` 必须是空操作，而不是 ValueError。

    真实触发点：`artifacts/translation/page_5.json` 的 r13 是空串 `""`，
    `fit_font_size("")` 返回 `lines == []`。旧实现把 `max(_count_vertical_lines(c)
    for c in lines)` 写在列循环**内部**，空列表时循环体不执行所以侥幸不炸；
    main 的重构把它提到循环外，`max()` 对空序列直接 `ValueError`。
    这条测试把"空译文路径不许炸"钉死。
    """
    img = Image.new("RGB", (200, 200), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 24)
    _render_vertical(img, draw, font, [], 100, 100, 24, 30,
                     col_width=24.0, stroke=0, color=(0, 0, 0))
    assert ink_stats(img, [0, 0, 200, 200])[0] == 0, "空列不应画出任何东西"


def test_render_item_with_empty_text_returns_empty_lines():
    """端到端：空译文渲染不抛异常，落盘 lines 仍是空列表（契约不变）。"""
    img = Image.new("RGB", (400, 900), "white")
    result = render_item(img, "", FONT, [100, 100, 240, 700], stroke=0,
                         preferred_direction="vertical")
    assert result["layout_direction"] == "vertical"
    assert result["lines"] == []
    assert ink_stats(img, [0, 0, 400, 900])[0] == 0
