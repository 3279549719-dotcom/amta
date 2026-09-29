"""Both render paths must supply the same metadata to PSD export."""
import re

from PIL import Image

from amta.typeset.psd_jsx_export import _generate_text_layer_jsx
from amta.typeset.typeset_render import render_item
from amta.typeset.vlm_render import render_text


def test_vlm_render_exports_its_position_font_color_and_alignment():
    block = {"bbox": [100, 100, 400, 300], "direction": "horizontal",
             "align": "left", "font": "serif", "font_size_ratio": 0.04,
             "color": "#FF0000", "stroke_color": None, "stroke_ratio": 0}
    meta = render_text(Image.new("RGB", (1000, 1000), "white"), "test", block)
    parts, _ = _generate_text_layer_jsx(0, meta)
    jsx = "".join(parts)
    position = re.search(r"position = \[([\d.-]+), ([\d.-]+)\]", jsx)
    assert position is not None
    assert float(position[1]) >= 100
    assert float(position[2]) >= 100
    assert "SimSun" in jsx
    assert "rgb.red = 255" in jsx
    assert "Justification.LEFT" in jsx


def test_both_renderers_emit_shared_export_fields():
    img = Image.new("RGB", (1000, 1000), "white")
    vlm = render_text(img, "测试", {
        "bbox": [100, 100, 400, 300], "direction": "horizontal", "align": "center",
        "font": "sans", "font_size_ratio": 0.04, "color": "#000000",
        "stroke_color": None, "stroke_ratio": 0,
    })
    normal = render_item(img, "测试", vlm["font_path"], [500, 100, 800, 300], stroke=0)
    required = {"anchor_pos", "font_family", "rendered_color", "rendered_stroke",
                "line_step", "align", "lines", "font_size", "layout_direction"}
    assert required <= normal.keys()
    assert required <= vlm.keys()
