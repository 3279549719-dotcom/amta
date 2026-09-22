"""Experimental contracts; tiny synthetic fixtures, no manga scans."""
import pytest
from PIL import Image, ImageChops, ImageFont

from scripts.probes.paratext_layout import exclusive_crop, validate_regions
from scripts.probes.paratext_render import layout_text, render_text, wrap_horizontal


def _block(bbox, direction="horizontal", align="left", font="sans",
           font_size_ratio=0.04, color="#000000", stroke_color=None, stroke_ratio=0.0):
    return {"bbox": bbox, "direction": direction, "align": align, "font": font,
            "font_size_ratio": font_size_ratio, "color": color,
            "stroke_color": stroke_color, "stroke_ratio": stroke_ratio}


# --- validate_regions ---

def test_rejects_stale_detection_outside_image():
    with pytest.raises(ValueError, match="outside"):
        validate_regions([{"region_id": "r0", "bbox": [1651, 445, 2910, 1633]}], (1540, 2268))


# --- exclusive_crop ---

def test_overlapping_crop_excludes_neighbours():
    img = Image.new("RGB", (200, 200), "white")
    region = {"region_id": "r0", "bbox": [0, 0, 200, 100]}
    smaller = {"region_id": "r1", "bbox": [50, 20, 150, 80]}
    crop = exclusive_crop(img, region, [region, smaller])
    assert crop.getpixel((100, 50)) == (255, 255, 255)


# --- wrap_horizontal ---

def test_wrap_preserves_email_and_explicit_line_breaks():
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
    lines = wrap_horizontal("联系：syamisen.moonrabbit@gmail.com\n日期：2015.12.30", font, 360)
    assert any("syamisen.moonrabbit@gmail.com" in line for line in lines)
    assert any(line.startswith("日期") for line in lines)


def test_closing_punctuation_does_not_start_line():
    font = ImageFont.truetype("C:/Windows/Fonts/simsun.ttc", 40)
    lines = wrap_horizontal("甲乙丙丁。戊己庚辛。", font, 160)
    assert all(font.getlength(line) <= 160 for line in lines)
    assert not any(line.startswith("。") for line in lines)


def test_wrap_empty_string_returns_empty():
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
    assert wrap_horizontal("", font, 100) == [""]


# --- layout_text ---

def test_horizontal_survives_tall_box():
    block = _block([10, 10, 190, 380], direction="horizontal", align="left", font_size_ratio=0.05)
    meta = layout_text("这是一段横排文章。" * 10, block, (200, 400))
    assert meta["layout_direction"] == "horizontal"
    assert meta["ink_bbox"][2] <= 190
    assert meta["ink_bbox"][3] <= 380
    assert "".join(meta["lines"]) == "这是一段横排文章。" * 10


def test_font_size_ratio_controls_visual_hierarchy():
    block = _block([20, 20, 620, 180], direction="horizontal", align="center", font_size_ratio=0.08)
    meta = layout_text("月天新地", block, (640, 1000))
    assert meta["font_size"] > 52


def test_smaller_ratio_produces_smaller_font():
    big = _block([20, 20, 620, 180], font_size_ratio=0.08)
    small = _block([20, 20, 620, 180], font_size_ratio=0.02)
    assert layout_text("月天新地", big, (640, 1000))["font_size"] > \
           layout_text("月天新地", small, (640, 1000))["font_size"]


def test_layout_uses_real_image_bounds():
    img = Image.new("RGB", (1540, 2268), "white")
    validate_regions([{"region_id": "r0", "bbox": [10, 10, 190, 380]}], img.size)


def test_left_aligned_body_starts_at_region_top():
    block = _block([10, 10, 500, 900], direction="horizontal", align="left", font="serif", font_size_ratio=0.04)
    meta = layout_text("短一点的译文", block, (500, 900))
    assert meta["ink_bbox"][1] == 10


def test_center_aligned_centers_horizontally():
    block = _block([10, 10, 500, 100], direction="horizontal", align="center", font_size_ratio=0.04)
    meta = layout_text("居中", block, (500, 900))
    used_w = meta["ink_bbox"][2] - meta["ink_bbox"][0]
    assert abs(meta["ink_bbox"][0] - (10 + (490 - used_w) / 2)) < 1


def test_vertical_fields_keep_explicit_boundaries():
    block = _block([20, 20, 220, 420], direction="vertical", align="center", font_size_ratio=0.08)
    meta = layout_text("甲乙\n丙丁", block, (220, 420))
    assert meta["layout_direction"] == "vertical"
    assert meta["ink_bbox"][0] >= 20 and meta["ink_bbox"][2] <= 220
    assert meta["ink_bbox"][1] >= 20 and meta["ink_bbox"][3] <= 420


def test_custom_color_is_used():
    image = Image.new("RGB", (100, 100), "white")
    before = image.copy()
    block = _block([10, 10, 90, 90], color="#FF0000", font_size_ratio=0.1)
    render_text(image, "红", block)
    diff = ImageChops.difference(image, before)
    assert diff.getbbox() is not None


@pytest.mark.parametrize("text", ["あ", "ア", "亜", "A", "。"])
def test_painted_glyph_bearings_stay_inside_region(text):
    image = Image.new("RGB", (150, 150), "white")
    before = image.copy()
    block = _block([20, 20, 40, 120], direction="horizontal", align="right", font_size_ratio=0.1)
    render_text(image, text, block)
    bounds = ImageChops.difference(image, before).getbbox()
    assert bounds is not None
    assert bounds[0] >= 20 and bounds[2] <= 40


def test_stroked_glyphs_stay_inside_region():
    image = Image.new("RGB", (200, 200), "white")
    before = image.copy()
    block = _block([20, 20, 100, 100], direction="horizontal", align="left",
                    font_size_ratio=0.1, stroke_color="#FF0000", stroke_ratio=0.2)
    render_text(image, "ABC", block)
    bounds = ImageChops.difference(image, before).getbbox()
    assert bounds is not None
    assert bounds[0] >= 20 and bounds[1] >= 20
    assert bounds[2] <= 100 and bounds[3] <= 100
