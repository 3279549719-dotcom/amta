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
