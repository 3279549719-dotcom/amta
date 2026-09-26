"""psd_jsx_export 单元测试 — JSX 脚本生成逻辑。"""
from __future__ import annotations

from amta.typeset.psd_jsx_export import (
    _escape_jsx_path,
    _escape_jsx_string,
    _generate_text_layer_jsx,
    _hex_to_rgb,
    _resolve_font_family,
)


class TestEscapeFunctions:
    def test_escape_jsx_string_basic(self):
        assert _escape_jsx_string("hello") == "hello"

    def test_escape_jsx_string_single_quote(self):
        assert _escape_jsx_string("it's") == "it\\'s"

    def test_escape_jsx_string_newline(self):
        assert _escape_jsx_string("line1\nline2") == "line1\\rline2"

    def test_escape_jsx_string_backslash(self):
        assert _escape_jsx_string("a\\b") == "a\\\\b"

    def test_escape_jsx_string_empty(self):
        assert _escape_jsx_string("") == ""

    def test_escape_jsx_path_windows(self):
        assert _escape_jsx_path(r"C:\test\file.png") == "C:/test/file.png"

    def test_escape_jsx_path_with_quote(self):
        assert _escape_jsx_path("C:/it's/file.png") == "C:/it\\'s/file.png"


class TestFontResolution:
    def test_known_font_msyh(self):
        assert _resolve_font_family("msyh.ttc") == "Microsoft YaHei"

    def test_known_font_msyhbd(self):
        assert _resolve_font_family("msyhbd.ttc") == "Microsoft YaHei"

    def test_known_font_simhei(self):
        assert _resolve_font_family("simhei.ttf") == "SimHei"

    def test_unknown_font_returns_stem(self):
        assert _resolve_font_family("mycustomfont.ttf") == "mycustomfont"


class TestColorConversion:
    def test_black(self):
        assert _hex_to_rgb("#000000") == (0, 0, 0)

    def test_white(self):
        assert _hex_to_rgb("#FFFFFF") == (255, 255, 255)

    def test_red(self):
        assert _hex_to_rgb("#FF0000") == (255, 0, 0)

    def test_without_hash(self):
        assert _hex_to_rgb("00FF00") == (0, 255, 0)


class TestTextLayerJsx:
    def _make_item(self, **kwargs):
        item = {
            "region_id": "r00",
            "lines": ["测试文字"],
            "font_size": 52,
            "anchor_pos": [1000, 500],
            "layout_direction": "horizontal",
            "font_family": "msyh.ttc",
            "rendered_color": "#000000",
        }
        item.update(kwargs)
        return item

    def test_horizontal_layer_generates_code(self):
        jsx = _generate_text_layer_jsx(0, self._make_item())
        assert "Direction.HORIZONTAL" in jsx
        assert "Justification.CENTER" in jsx
        assert "测试文字" in jsx
        assert "Microsoft YaHei" in jsx
        assert "tl0" in jsx

    def test_vertical_layer_generates_code(self):
        jsx = _generate_text_layer_jsx(1, self._make_item(layout_direction="vertical"))
        assert "Direction.VERTICAL" in jsx
        assert "Justification.LEFT" in jsx
        assert "tl1" in jsx

    def test_multiline_text_uses_cr(self):
        jsx = _generate_text_layer_jsx(0, self._make_item(lines=["第一行", "第二行"]))
        assert "第一行\\r第二行" in jsx

    def test_empty_lines_returns_empty(self):
        assert _generate_text_layer_jsx(0, self._make_item(lines=[])) == ""

    def test_horizontal_position_x_equals_anchor(self):
        """横排居中：x = anchor_x"""
        jsx = _generate_text_layer_jsx(0, self._make_item(anchor_pos=[1000, 500]))
        # position = [1000.0, y]
        assert "[1000.0," in jsx

    def test_horizontal_single_line_y_has_baseline_offset(self):
        """横排单行：y = anchor_y + baseline_offset (0.35 * font_size)"""
        jsx = _generate_text_layer_jsx(0, self._make_item(anchor_pos=[1000, 500], font_size=52))
        # y = 500 + 52*0.35 = 518.2
        assert "518.2" in jsx

    def test_horizontal_multiline_y_offset(self):
        """横排多行：y = anchor_y - (n-1)*leading/2 + baseline"""
        jsx = _generate_text_layer_jsx(
            0, self._make_item(lines=["a", "b"], anchor_pos=[1000, 500], font_size=52)
        )
        # leading = 52 * 1.15 = 59.8
        # y = 500 - 1*59.8/2 + 52*0.35 = 500 - 29.9 + 18.2 = 488.3
        assert "488.3" in jsx

    def test_vertical_multiline_x_offset(self):
        """竖排多列：x = anchor_x + (n-1)*leading/2"""
        jsx = _generate_text_layer_jsx(
            0,
            self._make_item(
                layout_direction="vertical",
                lines=["abc", "def"],
                anchor_pos=[1000, 500],
                font_size=40,
            ),
        )
        # leading = 40 * 1.2 = 48
        # x = 1000 + 1*48/2 = 1024
        assert "1024" in jsx

    def test_vertical_y_centers_column(self):
        """竖排：y = anchor_y - col_height/2"""
        jsx = _generate_text_layer_jsx(
            0,
            self._make_item(
                layout_direction="vertical",
                lines=["abc"],
                anchor_pos=[1000, 500],
                font_size=40,
            ),
        )
        # col_height = 3 * 40 = 120
        # y = 500 - 120/2 = 440
        assert "440" in jsx

    def test_layer_name_contains_region_id(self):
        jsx = _generate_text_layer_jsx(0, self._make_item(region_id="r42"))
        assert "r42:" in jsx

    def test_font_size_in_code(self):
        jsx = _generate_text_layer_jsx(0, self._make_item(font_size=73))
        assert "73" in jsx

    def test_color_rgb_in_code(self):
        jsx = _generate_text_layer_jsx(0, self._make_item(rendered_color="#FF8000"))
        assert "255" in jsx  # red
        assert "128" in jsx  # green
        assert "0" in jsx  # blue

    def test_leading_set(self):
        jsx = _generate_text_layer_jsx(0, self._make_item(font_size=52))
        # leading = 52 * 1.15 = 59.8
        assert "59.8" in jsx
        assert "useAutoLeading = false" in jsx
