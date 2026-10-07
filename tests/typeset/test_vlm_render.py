"""tests/typeset/test_vlm_render.py"""
import json

from PIL import Image

from amta.typeset.vlm_render import layout_text, render_text


def test_layout_horizontal_fits():
    """横排文本应能在区域内找到合适字号。"""
    block = {
        "bbox": [10, 10, 200, 80],
        "direction": "horizontal",
        "align": "center",
        "font": "sans",
        "font_size_ratio": 0.04,
        "color": "#000000",
        "stroke_color": None,
        "stroke_ratio": 0.0,
    }
    meta = layout_text("测试文本测试文本", block, (400, 300))
    assert meta["layout_direction"] == "horizontal"
    assert meta["font_size"] > 0
    assert len(meta["lines"]) >= 1


def test_render_text_draws_on_image():
    """render_text 应在图片上画出文字并返回 meta。"""
    img = Image.new("RGB", (400, 300), "white")
    block = {
        "bbox": [10, 10, 200, 80],
        "direction": "horizontal",
        "align": "center",
        "font": "sans",
        "font_size_ratio": 0.04,
        "color": "#000000",
        "stroke_color": None,
        "stroke_ratio": 0.0,
    }
    meta = render_text(img, "测试", block)
    assert meta["font_size"] > 0
    # 在排版计算出的 ink_bbox 内扫描，确认确实画上了非白像素（文字）。
    # 不用固定像素点：单行短文本只占框上部，固定坐标可能落在文字之外。
    ix1, iy1, ix2, iy2 = (round(v) for v in meta["ink_bbox"])
    painted = [
        (x, y)
        for y in range(iy1, iy2 + 1)
        for x in range(ix1, ix2 + 1)
        if img.getpixel((x, y)) != (255, 255, 255)
    ]
    assert painted, "render_text 未在 ink_bbox 内绘制任何文字像素"


def test_station_vlm_branch_renders(tmp_path):
    """VLM canon（ocr_engine=vlm-paratext）应走 VLM 渲染分支并早期 return。"""
    from amta.typeset import typeset_station as station

    img = Image.new("RGB", (400, 300), "white")
    clean = tmp_path / "clean.png"
    img.save(clean)

    canon = {
        "work_id": "w", "page": "page_1", "schema_version": "2.1",
        "ocr_engine": "vlm-paratext",
        "items": [
            {"region_id": "page_1_u00", "bbox": [20, 20, 200, 90],
             "direction": "horizontal", "align": "center", "font": "sans",
             "font_size_ratio": 0.05, "color": "#000000",
             "stroke_color": None, "stroke_ratio": 0.0},
        ],
        "n_regions": 1,
    }
    trans = {"translations": {"page_1_u00": "你好世界"}}
    canon_path = tmp_path / "canon.json"
    trans_path = tmp_path / "translation.json"
    det_path = tmp_path / "det.json"
    canon_path.write_text(json.dumps(canon), encoding="utf-8")
    trans_path.write_text(json.dumps(trans), encoding="utf-8")
    det_path.write_text(json.dumps({"page": "page_1"}), encoding="utf-8")

    out = tmp_path / "typeset.json"
    final = tmp_path / "final" / "page_1_final.png"
    doc = station.run("w", canon_path, trans_path, det_path, clean, out, final)

    assert doc["renderer"] == "vlm-greedy-wrap"
    assert doc["checks"]["rendered"] == 1
    assert doc["checks"]["coverage_complete"] is True
    assert final.exists()
    rendered = Image.open(final)
    inked = any(rendered.getpixel((x, y)) != (255, 255, 255)
                for x in range(20, 200, 8) for y in range(20, 90, 8))
    assert inked


# === 竖排列末逗号消冗（VLM 贪心换行路径）===

def _vertical_cell(meta, col_idx: int, char_idx: int):
    """VLM 竖排的字格矩形，公式与 vlm_render.render_text 的 _render_vertical 调用一致。"""
    ix1, iy1, ix2, iy2 = meta["ink_bbox"]
    lines = meta["lines"]
    n = len(lines)
    lh = meta["line_step"]
    col_w = (ix2 - ix1) / max(1, n)
    cx, cy = (ix1 + ix2) / 2, (iy1 + iy2) / 2
    top = cy - max(len(c) for c in lines) * lh / 2
    left = cx + (n * col_w) / 2 - (col_idx + 1) * col_w
    return (left, top + char_idx * lh, left + col_w, top + (char_idx + 1) * lh)


def _ink_in(img, cell):
    x1, y1, x2, y2 = (int(v) for v in cell)
    return sum(1 for y in range(y1, y2) for x in range(x1, x2)
               if img.getpixel((x, y)) != (255, 255, 255))


def test_vlm_vertical_hides_column_end_comma():
    """VLM 竖排：列末逗号字形不画，但 meta['lines'] 契约原样保留。"""
    img = Image.new("RGB", (900, 1200), "white")
    block = {
        "bbox": [40, 40, 240, 440], "direction": "vertical", "align": "center",
        "font": "sans", "font_size_ratio": 0.05, "color": "#000000",
        "stroke_color": None, "stroke_ratio": 0.0,
    }
    meta = render_text(img, "你好，世界", block)
    assert meta["layout_direction"] == "vertical"
    assert meta["lines"] == ["你好，", "世界"], meta["lines"]
    # 第 0 列（最右列）列末字格 = 被掩码的逗号格 → 无墨迹
    comma_cell = _vertical_cell(meta, 0, len(meta["lines"][0]) - 1)
    assert _ink_in(img, comma_cell) == 0, "VLM 竖排列末逗号仍被绘制"
    # 同列其他字格照画（不是整列被清空）
    assert _ink_in(img, _vertical_cell(meta, 0, 0)) > 0


def test_vlm_vertical_keeps_sentence_final_mark():
    """VLM 竖排：句末 ！ 落在列末时保留。"""
    img = Image.new("RGB", (900, 1200), "white")
    block = {
        "bbox": [40, 40, 240, 340], "direction": "vertical", "align": "center",
        "font": "sans", "font_size_ratio": 0.05, "color": "#000000",
        "stroke_color": None, "stroke_ratio": 0.0,
    }
    meta = render_text(img, "请收下，这是一点薄礼！", block)
    assert meta["layout_direction"] == "vertical"
    assert meta["lines"][-1].endswith("！"), meta["lines"]
    last = meta["lines"][-1]
    final_cell = _vertical_cell(meta, len(meta["lines"]) - 1, len(last) - 1)
    assert _ink_in(img, final_cell) > 0, "句末 ！ 被误隐藏"


# === Task 2：VLM 路径的时机 / 元数据 / 颜色不受掩码影响 ===

def _vertical_block(height: int, fsr: float = 0.05) -> dict:
    return {
        "bbox": [40, 40, 240, 40 + height], "direction": "vertical",
        "align": "center", "font": "sans", "font_size_ratio": fsr,
        "color": "#000000", "stroke_color": None, "stroke_ratio": 0.0,
    }


def test_vlm_mask_is_computed_on_post_split_columns(monkeypatch):
    """掩码必须在**断列之后**、按最终列序列计算（VLM 的 _vertical_columns 先跑）。

    用 spy 抓住掩码实参：它必须等于 `layout_text` 落盘的 `meta["lines"]`
    —— 说明掩码时机在断列之后，而不是断列之前（断列前算就不知道谁在列末）。
    """
    import amta.typeset.vlm_render as vr

    seen: list[list[str]] = []
    real = vr.column_end_pause_mask

    def spy(columns):
        seen.append(list(columns))
        return real(columns)

    monkeypatch.setattr(vr, "column_end_pause_mask", spy)
    img = Image.new("RGB", (900, 1200), "white")
    meta = render_text(img, "你好，世界", _vertical_block(400))

    assert len(seen) == 1, f"掩码应恰好调用一次，实际 {len(seen)}"
    assert seen[0] == meta["lines"] == ["你好，", "世界"], (seen, meta["lines"])


def test_vlm_mid_column_comma_is_still_drawn():
    """列中逗号不是边界冗余：VLM 路径也必须照画。"""
    img = Image.new("RGB", (900, 1200), "white")
    meta = render_text(img, "仙人，风范端庄贤淑哦", _vertical_block(700))
    # 2026-10-07 度量口径改造后（切列单位=渲染行）断列结果：
    assert meta["lines"] == ["仙人，风", "范端庄贤淑哦"], meta["lines"]
    comma_cell = _vertical_cell(meta, 0, meta["lines"][0].index("，"))
    assert _ink_in(img, comma_cell) > 0, "VLM 列中逗号被误隐藏"


def test_vlm_mask_indices_survive_verticalize(monkeypatch):
    """掩码按横排原文算、作用在 verticalize 之后的列上：下标必须仍然对齐。

    样例列 '（你' 竖排后是 '︵你'（`（` → `︵`）。若下标错位，
    要么别的字被误隐藏、要么 `︵` 被误隐藏。

    2026-10-07 度量口径改造后（切列单位=渲染行）断列结果是
    ['（你', '好），世界']——逗号落在第 1 列列中（不是列末），
    因此这里断言的是「列中逗号照画」+「列首 `︵` 照画」+ 同列其它字照画，
    下标若错位就会命中错误的字格。
    """
    img = Image.new("RGB", (900, 1200), "white")
    meta = render_text(img, "（你好），世界", _vertical_block(320, fsr=0.03))
    assert meta["lines"] == ["（你", "好），世界"], meta["lines"]
    # 第 1 列列中逗号（下标 2）照画
    idx_comma = meta["lines"][1].index("，")
    assert _ink_in(img, _vertical_cell(meta, 1, idx_comma)) > 0, "列中逗号被误隐藏"
    # 第 0 列的 `（`（竖排形式 `︵`，下标 0）照画 → 下标没错位
    assert _ink_in(img, _vertical_cell(meta, 0, 0)) > 0, "列首括号被误隐藏（下标错位）"
    # 同列其它字也照画
    assert _ink_in(img, _vertical_cell(meta, 0, 1)) > 0


def _render_meta_and_pixels(text: str, block: dict, hide: bool):
    """渲染一次；hide=False 时把 VLM 模块里的掩码换成"什么都不隐藏"。"""
    import amta.typeset.vlm_render as vr

    saved = vr.column_end_pause_mask
    if not hide:
        vr.column_end_pause_mask = lambda cols: [[False] * len(c) for c in cols]
    try:
        img = Image.new("RGB", (900, 1200), "white")
        meta = render_text(img, text, block)
    finally:
        vr.column_end_pause_mask = saved
    return meta, img


def test_vlm_mask_does_not_touch_typography_metadata():
    """掩码只改"画不画"：字体/字号/颜色/描边/lines/位置/ink_bbox 全部不变。"""
    block = _vertical_block(400)
    meta_off, _ = _render_meta_and_pixels("你好，世界", block, hide=False)
    meta_on, _ = _render_meta_and_pixels("你好，世界", block, hide=True)
    assert meta_off == meta_on, "掩码改变了 VLM 落盘元数据"
    for key in ("font_size", "font_path", "color", "stroke_width", "stroke_color",
                "lines", "line_step", "ink_bbox", "align", "layout_direction"):
        assert meta_off[key] == meta_on[key], f"{key} 发生变化"


def test_vlm_changed_pixels_confined_to_masked_cell():
    """零位移：VLM 路径 before/after 的全部差异只在被掩码的那一个字格里。"""
    block = _vertical_block(400)
    meta_on, img_on = _render_meta_and_pixels("你好，世界", block, hide=True)
    _, img_off = _render_meta_and_pixels("你好，世界", block, hide=False)

    cell = _vertical_cell(meta_on, 0, len(meta_on["lines"][0]) - 1)
    assert _ink_in(img_on, cell) == 0, "被掩码字格仍有墨"
    assert _ink_in(img_off, cell) > 0, "修复前该字格本应有墨"

    x1, y1, x2, y2 = (int(v) for v in cell)
    changed = [(x, y) for y in range(img_on.height) for x in range(img_on.width)
               if img_on.getpixel((x, y)) != img_off.getpixel((x, y))]
    assert changed, "掩码应至少改变被隐藏逗号格的像素"
    outside = [p for p in changed
               if not (x1 <= p[0] < x2 and y1 <= p[1] < y2)]
    assert not outside, f"VLM 路径发生位移，改动溢出字格: {outside[:5]}"


def test_vlm_horizontal_path_never_calls_mask(monkeypatch):
    """VLM 横排不经过掩码：spy 断言零调用，且输出与修复前逐字节一致。"""
    import amta.typeset.vlm_render as vr

    calls: list[list[str]] = []
    real = vr.column_end_pause_mask

    def spy(columns):
        calls.append(list(columns))
        return real(columns)

    monkeypatch.setattr(vr, "column_end_pause_mask", spy)
    block = {
        "bbox": [10, 10, 400, 200], "direction": "horizontal", "align": "center",
        "font": "sans", "font_size_ratio": 0.05, "color": "#000000",
        "stroke_color": None, "stroke_ratio": 0.0,
    }
    meta_spy, img_spy = _render_meta_and_pixels("你好，世界，再见", block, hide=True)
    assert calls == [], f"VLM 横排不应调用列末掩码，实际 {calls}"
    meta_off, img_off = _render_meta_and_pixels("你好，世界，再见", block, hide=False)
    assert meta_spy == meta_off
    assert img_spy.tobytes() == img_off.tobytes(), "VLM 横排输出被掩码影响"
    assert "，" in "".join(meta_spy["lines"]), "横排逗号不应被删"
