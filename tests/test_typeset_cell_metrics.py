"""竖排/横排断行的度量口径回归测试。

核心契约（docs/lessons.md L54 的完整版）：
度量层（_fits / 断行 DP）和渲染层（typeset_render._render_vertical）必须共享
同一套「一个渲染单位占多宽、占几行」的认知。渲染层把一个渲染单位叫「行」
（iter_vertical_rows 的 VerticalRow），所以度量层也必须以「行」为切分单位，
不能按字符数近似。

本文件锁定三件事：
1. 成对标点（!!/!?/！！/？！）与连续 ASCII 点归一化后的省略号，在竖排里
   各占**一个**渲染行，即使它们是多个字符。
2. 一列能容纳的字符数可以**多于**「可用高度 / 行高」（因为标点组把多个字符
   压成一行），这种一列版式必须被接受，而不是被判为放不下。
3. 横排断行按真实字形像素宽度算，比例字体/拉丁串不能靠「等宽假设」蒙。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from amta.typeset.typeset_engine import (
    _cell_count,
    _fits,
    _font_metrics,
    break_lines,
    fit_font_size,
    infer_direction_from_bbox,
    wrap_text,
)
from amta.typeset.typeset_render import (
    _normalize_text_for_render as norm,
    iter_vertical_rows,
)

FONT = Path("C:/Windows/Fonts/msyh.ttc")
FONT_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")

# 真实事故区域（tagatame 系列，见 plan 与本文件底部探测注释）
P17_R08_BBOX = [698.0, 680.0, 731.0, 783.0]      # 0030 r08 「こいつ...!!」→「这家伙…!!」
P33_R04_BBOX = [450.0, 749.0, 484.0, 842.0]      # 0033 r04 「霊夢...!?」→「灵梦…!?」


def _pytest_guard() -> None:
    """字体缺失时跳过整个模块（非 Windows 环境无微软雅黑）。"""
    if not FONT.exists():
        pytest.skip(f"字体不存在: {FONT}", allow_module_level=True)


_pytest_guard()


# === 1. 渲染行数才是行数 =====================================================

class TestPunctGroupIsOneCell:
    def test_double_exclamation_is_one_cell(self):
        """「!!」两个字符在竖排里并排占一行。"""
        assert _cell_count("!!") == 1

    def test_question_exclamation_is_one_cell(self):
        """「!?」同理。"""
        assert _cell_count("!?") == 1

    def test_double_punct_at_end_of_text(self):
        """「这家伙…!!」= 这/家/伙/…/!! 共 5 行，不是 6 个字符。"""
        assert _cell_count("这家伙…!!") == 5

    def test_lone_punct_is_still_one_cell(self):
        """单个「!」也只是 1 行。"""
        assert _cell_count("!") == 1
        assert _cell_count("啊…!!") == 3

    def test_cell_count_matches_renderer_rows(self):
        """度量层的行数必须等于渲染层拆出来的行数（同源契约）。"""
        for text in ["这家伙…!!", "灵梦…!?", "呼…", "咳哈…", "!!", "好难喝…!"]:
            assert _cell_count(text) == len(iter_vertical_rows(text)), text


# === 2. 一列放得下就必须判为放得下 =========================================

class TestSingleColumnFitsByRows:
    def test_one_column_accepted_when_rows_fit(self):
        """0030 r08 在 12px：一列 5 行 = 85px <= 87.55px，必须判为放得下。

        修复前 _fits 用 max(len(col)) = 6 字符算高度 → 102px > 87.55px →
        误判放不下 → 断行 DP 把文本切成两列。这就是「一列变两列」的根因。
        """
        from PIL import ImageFont
        text = norm("这家伙...!!")
        font = ImageFont.truetype(str(FONT_BOLD), 12)
        _cw, lh = _font_metrics(font)
        x1, y1, x2, y2 = P17_R08_BBOX
        assert _cell_count(text) * lh <= (y2 - y1) * 0.85, "前提：行数口径下 1 列放得下"
        assert _fits([text], font, P17_R08_BBOX, "vertical") is True

    def test_char_count_would_have_rejected_it(self):
        """把上面的前提钉死：按字符数算确实放不下（旧的错误路径）。"""
        from PIL import ImageFont
        text = norm("这家伙...!!")
        font = ImageFont.truetype(str(FONT_BOLD), 12)
        _cw, lh = _font_metrics(font)
        x1, y1, x2, y2 = P17_R08_BBOX
        assert len(text) * lh > (y2 - y1) * 0.85, "旧口径必须判为放不下"
        assert len(text) > _cell_count(text)


class TestReportedRegionsCollapseToOneColumn:
    """两个真实事故区域：同译文重排后必须是 1 列。

    注意：生产路径由 render_item 先做 _normalize_text_for_render（ASCII 点 →
    全角省略号）再调 fit_font_size，见 typeset_render.render_item。这里镜像
    真实调用顺序，所以用 norm() 后的译文。
    """

    def test_0030_r08_is_one_column(self):
        """0030 r08：单列 12px 成立，多列参考 14px，代价 12/14 > 0.7 → 取一列。

        base_size=14 是该区真实的 target（原文「こいつ...!!」的基准字号）。
        """
        size, direction, lines = fit_font_size(
            norm("这家伙...!!"), FONT_BOLD, P17_R08_BBOX,
            preferred_direction="vertical", base_size=14,
        )
        assert direction == "vertical"
        assert len(lines) == 1, f"应为一列，实际 {lines}"
        assert size == 12, f"单列可行上限应为 12px，实际 {size}"

    def test_0033_r04_is_one_column(self):
        size, direction, lines = fit_font_size(
            norm("灵梦...!?"), FONT, P33_R04_BBOX,
            preferred_direction="vertical", base_size=14,
        )
        assert direction == "vertical"
        assert len(lines) == 1, f"应为一列，实际 {lines}"
        assert size == 14, f"单列可行上限应为 14px，实际 {size}"

    def test_original_two_column_bubble_stays_two_columns(self):
        """对照：原图本来就是两列的气泡，列数不许被压成一列。

        「好啦我知道啦」在 87x186 的窄框里：单列可行字号 19px，多列参考字号
        36px，19/36 < MIN_SIZE_RATIO(0.7) —— 单列代价超过相对下限，仍按旧行为
        分列（这里 base_size 取该区的 target，同样是紧框场景）。
        """
        _size, _direction, lines = fit_font_size(
            "好啦我知道啦", FONT, [163.0, 1169.0, 250.0, 1355.0],
            preferred_direction="vertical", base_size=24,
        )
        assert len(lines) >= 2, f"原图两列的气泡不应被压成一列: {lines}"

    def test_single_column_wins_only_within_relative_floor(self):
        """选优规则的边界：单列代价 < 相对下限 → 一列；>= 相对下限 → 分列。

        同一句话、同一个框，只改 base_size 不会改变单列可行性，所以用两个不同
        几何的框对照：
        - 0030 r08（33x103）：单列 12 / 参考 14 = 0.86 → 一列
        - 0033 r01（87x186）：单列 19 / 参考 36 = 0.53 → 分列
        """
        _s1, _d1, one = fit_font_size(
            norm("这家伙...!!"), FONT_BOLD, P17_R08_BBOX,
            preferred_direction="vertical", base_size=14,
        )
        _s2, _d2, multi = fit_font_size(
            "好啦我知道啦", FONT, [163.0, 1169.0, 250.0, 1355.0],
            preferred_direction="vertical", base_size=24,
        )
        assert len(one) == 1 and len(multi) >= 2, (one, multi)

    def test_base_size_cap_does_not_distort_the_comparison(self):
        """参考字号必须不受 base_size 上限约束，否则紧框的「单列代价」会被算小。

        0033 r01 的 base_size=24 会封顶可行字号，若拿封顶后的 24 当分母，
        单列 19/24 = 0.79 > 0.7 就会误判成一列。真实参考是放开后的 36px。
        """
        _size, _direction, lines = fit_font_size(
            "好啦我知道啦", FONT, [163.0, 1169.0, 250.0, 1355.0],
            preferred_direction="vertical", base_size=24,
        )
        assert len(lines) >= 2, f"base_size 封顶不得把多列气泡误判成一列: {lines}"


# === 3. 横排按真实字形宽度断行 ==============================================

class TestHorizontalUsesGlyphWidths:
    def test_wrapped_lines_never_exceed_pixel_width(self):
        from PIL import ImageFont
        font = ImageFont.truetype(str(FONT), 20)
        text = "灵梦和魔理沙在这条路上走了很久很久"
        lines = wrap_text(text, font, 120)
        assert len(lines) >= 2
        for line in lines:
            assert font.getlength(line) <= 120, f"横排溢出: {line!r}"

    def test_latin_token_not_split_from_width_break(self):
        """拉丁 token（Suu）不能被腰斩成 S / uu。"""
        from PIL import ImageFont
        font = ImageFont.truetype(str(FONT), 24)
        lines = wrap_text("别这么随便地叫Suu小姐啊 人类", font, 200)
        assert any("Suu" in ln for ln in lines), f"Suu 被腰斩: {lines}"

    def test_short_text_single_line(self):
        from PIL import ImageFont
        font = ImageFont.truetype(str(FONT), 24)
        assert wrap_text("你好", font, 500) == ["你好"]

    def test_break_lines_keeps_char_semantics(self):
        """break_lines 的公开语义仍是「每行最大字符数」，不被本改动改写。"""
        lines = break_lines("一二三四五六七八九十", 5)
        assert lines == ["一二三四五", "六七八九十"]


# === 4. 边界与退化情形 ======================================================

class TestDegenerateCases:
    def test_empty_text(self):
        assert _cell_count("") == 0

    def test_punct_only_text_does_not_crash_fit(self):
        size, direction, lines = fit_font_size(
            "!!", FONT_BOLD, [1115.0, 888.0, 1159.0, 1007.0],
            preferred_direction="vertical", base_size=52,
        )
        assert direction == "vertical"
        assert size > 0 and len(lines) >= 1

    def test_empty_fit_returns_empty_lines(self):
        _size, _direction, lines = fit_font_size("", FONT, [0, 0, 100, 100])
        assert lines == []

    def test_direction_inference_unchanged(self):
        assert infer_direction_from_bbox(P17_R08_BBOX) == "vertical"
        assert infer_direction_from_bbox([0, 0, 380, 222]) == "horizontal"
        assert infer_direction_from_bbox([0, 0, 200, 200]) is None


# === 5. 竖排列首禁则（kinsoku）==============================================
# 2026-10-18：_vertical_layout_at 原来用 wrap_cells_to_columns 朴素等分，
# 会把 ？/，/— 切到列首。改用 _split_cells_into_columns（DP + kinsoku）。

NO_START_PUNCT = set("，。！？、）》】……—!?！？")


def _assert_no_punct_at_col_start(cols: list[str]) -> None:
    for i, c in enumerate(cols):
        c = c.strip()
        if i == 0 or not c:
            continue  # 首列豁免
        assert c[0] not in NO_START_PUNCT, f"col{i+1} starts with punct {c[0]!r}: {cols}"


class TestVerticalKinsokuColumns:
    def test_question_mark_not_at_col_start(self):
        """page_12 r02: '真的吗？好开心！' 分 3 列，？不得开列。"""
        from amta.typeset.typeset_engine import _split_cells_into_columns, _cell_rows
        cells = _cell_rows("真的吗？好开心！")
        result = _split_cells_into_columns(cells, 3)
        assert result is not None
        _assert_no_punct_at_col_start(result)

    def test_comma_not_at_col_start(self):
        """page_11 r01: 末列不得以 ， 开头。"""
        from amta.typeset.typeset_engine import _split_cells_into_columns, _cell_rows
        cells = _cell_rows("……不用我说你也明白吧，笨蛋")
        result = _split_cells_into_columns(cells, 4)
        assert result is not None
        _assert_no_punct_at_col_start(result)

    def test_em_dash_not_at_col_start(self):
        """page_11 r02: 次列不得以 — 开头。"""
        from amta.typeset.typeset_engine import _split_cells_into_columns, _cell_rows
        cells = _cell_rows("不适合你——啦")
        result = _split_cells_into_columns(cells, 2)
        assert result is not None
        _assert_no_punct_at_col_start(result)

    def test_first_column_exempt(self):
        """句首可以以 —— 开头（首列豁免）。"""
        from amta.typeset.typeset_engine import _split_cells_into_columns, _cell_rows
        cells = _cell_rows("——真是的")
        result = _split_cells_into_columns(cells, 2)
        assert result is not None
        assert result[0].startswith("——")

    def test_too_many_columns_returns_none(self):
        """短文本切超多数列数应返回 None，不强行分列。"""
        from amta.typeset.typeset_engine import _split_cells_into_columns, _cell_rows
        cells = _cell_rows("你好")
        result = _split_cells_into_columns(cells, 5)
        assert result is None

    def test_leading_space_stripped(self):
        """列首空格应被 lstrip（page_17 r03 ' 婚礼'）。"""
        from amta.typeset.typeset_engine import _split_cells_into_columns, _cell_rows
        cells = _cell_rows("我啊 一直很憧憬 婚礼")
        result = _split_cells_into_columns(cells, 3)
        assert result is not None
        for c in result:
            assert not c.startswith(" "), f"col starts with space: {c!r}"

    def test_colon_semicolon_not_at_col_start(self):
        """：； 也不得开列（统一 kinsoku，vlm_render 与 engine 共用）。"""
        from amta.typeset.typeset_engine import _split_cells_into_columns, _cell_rows
        cells = _cell_rows("我说：真的吗；骗人")
        result = _split_cells_into_columns(cells, 3)
        assert result is not None
        _assert_no_punct_at_col_start(result)

    def test_char_conservation(self):
        """kinsoku 重排不能漏字或删标点。"""
        from amta.typeset.typeset_engine import _split_cells_into_columns, _cell_rows
        text = "……不用我说你也明白吧，笨蛋！"
        cells = _cell_rows(text)
        result = _split_cells_into_columns(cells, 3)
        assert result is not None
        joined = "".join(result)
        # 去掉空格后字符数应守恒
        assert joined.replace(" ", "") == text.replace(" ", ""), \
            f"chars lost: {text!r} -> {joined!r}"


class TestBookBec83KinsokuRegression:
    """book-bec83a161b2f5f80 实页回归：这些列首标点事故不能再犯。

    几何参数从实页 bbox 提取，译文用当时的真实翻译。
    这些是 Task 1 的基线证据——改算法后这些断言必须仍通过。
    """

    def test_page11_r01_no_comma_at_col_start(self):
        """page_11 r01: 末列不得以逗号开头（2026-10-18 事故）。"""
        from amta.typeset.typeset_engine import _split_cells_into_columns, _cell_rows
        cells = _cell_rows("……不用我说你也明白吧，笨蛋")
        result = _split_cells_into_columns(cells, 4)
        assert result is not None
        _assert_no_punct_at_col_start(result)

    def test_page12_r02_no_question_at_col_start(self):
        """page_12 r02: 次列不得以问号开头。"""
        from amta.typeset.typeset_engine import _split_cells_into_columns, _cell_rows
        cells = _cell_rows("真的吗？好开心！")
        result = _split_cells_into_columns(cells, 3)
        assert result is not None
        _assert_no_punct_at_col_start(result)

    def test_direction_preserved_under_font_shrink(self):
        """方向判定与最终字号分开：竖排框缩小后不应翻转成横排。

        一个窄高 bbox，preferred_direction=vertical。即使字号因紧框变小，
        方向仍必须是 vertical，不能因为字号变小就改成横排。
        """
        _size, direction, _lines = fit_font_size(
            "短台词", FONT, [50, 100, 100, 400],
            preferred_direction="vertical", base_size=20,
        )
        assert direction == "vertical", \
            f"竖排窄框不应翻转成横排: dir={direction}"

