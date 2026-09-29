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

    def _jsx(self, index: int, item: dict) -> str:
        parts, _ = _generate_text_layer_jsx(index, item)
        return "".join(parts)

    def test_horizontal_layer_generates_code(self):
        jsx = self._jsx(0, self._make_item())
        assert "Direction.HORIZONTAL" in jsx
        assert "Justification.CENTER" in jsx
        assert "测试文字" in jsx
        assert "Microsoft YaHei" in jsx
        assert "tl0" in jsx

    def test_vertical_layer_generates_code(self):
        jsx = self._jsx(1, self._make_item(layout_direction="vertical"))
        assert "Direction.VERTICAL" in jsx
        assert "Justification.LEFT" in jsx
        assert "tl1" in jsx

    def test_multiline_text_uses_cr(self):
        jsx = self._jsx(0, self._make_item(lines=["第一行", "第二行"]))
        assert "第一行\\r第二行" in jsx

    def test_empty_lines_returns_empty(self):
        assert _generate_text_layer_jsx(0, self._make_item(lines=[])) == ([], 0)

    def test_horizontal_position_x_equals_anchor(self):
        """横排居中：x = anchor_x"""
        jsx = self._jsx(0, self._make_item(anchor_pos=[1000, 500]))
        # position = [1000.0, y]
        assert "[1000.0," in jsx

    def test_horizontal_single_line_y_has_baseline_offset(self):
        """横排单行：y = anchor_y + baseline_offset (0.35 * font_size)"""
        jsx = self._jsx(0, self._make_item(anchor_pos=[1000, 500], font_size=52))
        # y = 500 + 52*0.35 = 518.2
        assert "518.2" in jsx

    def test_horizontal_multiline_y_offset(self):
        """横排多行：y = anchor_y - (n-1)*leading/2 + baseline"""
        jsx = self._jsx(
            0, self._make_item(lines=["a", "b"], anchor_pos=[1000, 500], font_size=52)
        )
        # leading = 52 * 1.15 = 59.8
        # y = 500 - 1*59.8/2 + 52*0.35 = 500 - 29.9 + 18.2 = 488.3
        assert "488.3" in jsx

    def test_vertical_multiline_x_offset(self):
        """竖排多列：x = anchor_x + (n-1)*leading/2"""
        jsx = self._jsx(
            0,
            self._make_item(
                layout_direction="vertical",
                lines=["第一列", "第二列"],
                anchor_pos=[1000, 500],
                font_size=40,
            ),
        )
        # leading = 40 * 1.2 = 48
        # x = 1000 + 1*48/2 = 1024
        assert "1024" in jsx

    def test_vertical_y_centers_column(self):
        """竖排：y = anchor_y - 实际行数*leading/2（CJK 逐字占一行）"""
        jsx = self._jsx(
            0,
            self._make_item(
                layout_direction="vertical",
                lines=["一二三"],
                anchor_pos=[1000, 500],
                font_size=40,
            ),
        )
        # leading = 40*1.2 = 48；3 个 CJK 字 = 3 行
        # col_height = 3 * 48 = 144；y = 500 - 144/2 = 428
        assert "428" in jsx

    def test_layer_name_contains_region_id(self):
        jsx = self._jsx(0, self._make_item(region_id="r42"))
        assert "r42:" in jsx

    def test_font_size_in_code(self):
        jsx = self._jsx(0, self._make_item(font_size=73))
        assert "73" in jsx

    def test_color_rgb_in_code(self):
        jsx = self._jsx(0, self._make_item(rendered_color="#FF8000"))
        assert "255" in jsx  # red
        assert "128" in jsx  # green
        assert "0" in jsx  # blue

    def test_leading_set(self):
        jsx = self._jsx(0, self._make_item(font_size=52))
        # leading = 52 * 1.15 = 59.8
        assert "59.8" in jsx
        assert "useAutoLeading = false" in jsx

    def test_conjoined_punct_uses_tcy_not_ligature(self):
        """竖排 ！？ 保留真字符，由 Photoshop 縦中横整段横排并排（不换缺字连字）。"""
        parts, consumed = _generate_text_layer_jsx(
            0,
            self._make_item(
                layout_direction="vertical",
                lines=["按钮是什么！？"],
                anchor_pos=[923, 1356],
                font_size=35,
            ),
        )
        joined = "".join(parts)
        assert consumed == 1  # 单个文字层，縦中横不另开层
        # 真字符保留在 contents 里（雅黑有字形，不会变缺字框）
        assert "ti0.contents = '按钮是什么！？'" in joined
        # 生成縦中横代码，让 PS 把这段标点在格子里横排居中
        assert "applyTateChuYoko" in joined
        assert "Direction.VERTICAL" in joined

    def test_lone_punct_stays_in_main_layer(self):
        """单个 ！（后面没跟？）不触发縦中横，留在主竖排文字里。"""
        parts, consumed = _generate_text_layer_jsx(
            0,
            self._make_item(
                layout_direction="vertical",
                lines=["别死啊！"],
                anchor_pos=[1000, 500],
                font_size=29,
            ),
        )
        assert consumed == 1
        assert "applyTateChuYoko" not in "".join(parts)

    def test_vertical_row_pitch_uses_line_step_not_col_step(self):
        """回归：竖排行高必须用 line_step(ascent+descent)，不能把 col_step(字宽)当行高。

        旧 bug：col_step=30 被同时当行高，每行少走 20px，越往下标点越偏。
        """
        parts, _ = _generate_text_layer_jsx(
            0,
            self._make_item(
                layout_direction="vertical",
                lines=["按钮！？"],
                anchor_pos=[923, 1356],
                font_size=35,
                col_step=30,   # 字宽（x 方向列距）
                line_step=50,  # 行高（y 方向行距）
            ),
        )
        joined = "".join(parts)
        # 主竖排行距 = line_step=50，绝不是 col_step=30
        assert "leadingVal0 = 50.0" in joined
        assert "leadingVal0 = 30" not in joined
        # 叠层 y 也按 50 行距推进：3 行*50 = 150，列顶 y = 1356-75 = 1281
        assert "1281" in joined
