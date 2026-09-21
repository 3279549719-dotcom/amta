"""Experimental contracts; tiny synthetic fixtures, no manga scans."""
import pytest
from PIL import Image, ImageChops, ImageFont

from scripts.probes.paratext_layout import exclusive_crop, validate_regions
from scripts.probes.paratext_render import layout_text, render_text, wrap_text
from scripts.probes.probe_paratext_revise import parse_revisions


def test_rejects_stale_detection_outside_image():
    with pytest.raises(ValueError, match="outside"):
        validate_regions([{"region_id": "r0", "bbox": [1651, 445, 2910, 1633]}], (1540, 2268))


def test_explicit_horizontal_survives_tall_box():
    block = {"bbox": [10, 10, 190, 380], "direction": "horizontal", "align": "left",
             "source_lines": ["長い横書きの文章です"] * 12, "font": "sans"}
    meta = layout_text("这是一段横排文章。" * 50, block)
    assert meta["layout_direction"] == "horizontal"
    assert meta["ink_bbox"][2] <= 190
    assert meta["ink_bbox"][3] <= 380
    assert "".join(meta["lines"]) == "这是一段横排文章。" * 50


def test_wrap_preserves_email_and_explicit_line_breaks():
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
    lines = wrap_text("联系：syamisen.moonrabbit@gmail.com\n日期：2015.12.30", font, 360)
    assert any("syamisen.moonrabbit@gmail.com" in line for line in lines)
    assert any(line.startswith("日期") for line in lines)


def test_title_size_is_measured_from_source_not_global_cap():
    block = {"bbox": [20, 20, 620, 180], "direction": "horizontal", "align": "center",
             "source_lines": ["月天新地"], "font": "sans"}
    meta = layout_text("月天新地", block)
    assert meta["font_size"] > 52


def test_layout_uses_real_image_bounds():
    img = Image.new("RGB", (200, 400), "white")
    validate_regions([{"region_id": "r0", "bbox": [10, 10, 190, 380]}], img.size)


def test_closing_punctuation_does_not_force_whole_paragraph_to_shrink():
    font = ImageFont.truetype("C:/Windows/Fonts/simsun.ttc", 40)
    lines = wrap_text("甲乙丙丁。戊己庚辛。", font, 160)
    assert all(font.getlength(line) <= 160 for line in lines)
    assert not any(line.startswith("。") for line in lines)


def test_left_aligned_body_starts_at_region_top():
    block = {"bbox": [10, 10, 500, 900], "direction": "horizontal", "align": "left",
             "source_lines": ["文章"] * 20, "font": "serif"}
    meta = layout_text("短一点的译文", block)
    assert meta["ink_bbox"][1] == 10


def test_overlapping_crop_excludes_neighbours_partial_text():
    image = Image.new("RGB", (200, 100), "black")
    large = {"region_id": "r0", "bbox": [0, 0, 160, 100]}
    small = {"region_id": "r1", "bbox": [100, 0, 200, 30]}
    crop = exclusive_crop(image, large, [large, small])
    assert crop.getpixel((110, 10)) == (255, 255, 255)
    assert crop.getpixel((110, 50)) == (0, 0, 0)
    assert exclusive_crop(image, small, [large, small]).getpixel((10, 10)) == (0, 0, 0)


@pytest.mark.parametrize("text", ["fff", "jjj"])
def test_painted_glyph_bearings_stay_inside_region(text):
    image = Image.new("RGB", (150, 150), "white")
    before = image.copy()
    render_text(image, text, {"bbox": [20, 20, 40, 120], "direction": "horizontal",
                             "align": "right", "source_lines": [text], "font": "sans"})
    bounds = ImageChops.difference(image, before).getbbox()
    assert bounds is not None
    assert bounds[0] >= 20 and bounds[2] <= 40


def test_vertical_fields_keep_explicit_boundaries():
    block = {"bbox": [20, 20, 220, 420], "direction": "vertical", "align": "center",
             "source_lines": ["甲乙", "丙丁"], "font": "sans"}
    assert layout_text("甲乙\n丙丁", block)["lines"] == ["甲乙", "丙丁"]


def test_revision_contract_rejects_missing_or_extra_regions():
    raw = '{"revisions":{"r1":"修订一","r2":"修订二"}}'
    assert parse_revisions(raw, {"r1", "r2"}) == {"r1": "修订一", "r2": "修订二"}
    with pytest.raises(ValueError, match="coverage"):
        parse_revisions(raw, {"r1"})
