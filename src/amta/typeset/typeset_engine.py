"""排版引擎核心纯函数(Stage 5, Spec §3): 折行/避头尾/字号搜索双方向选优。

ADR-033 决策C：删除 decide_direction，fit_font_size 同时计算横/竖排最大字号选最优。
第一性原理：在给定矩形内放给定文字，字号最大化且不溢出；横竖排只是两种排列方式。
竖排支持多列（与横排多行完全对称），窄长框长文本不再被压成极小字号。

2026-09-11 基准字号改造（ADR-033 补充）：
- 专业排版原则：所有文字字号应基本一致，不为撑满框而放大字号。
- fit_font_size 新增 base_size 参数：从基准字号往下找（而非从 MAX_SIZE 往下找），
  大框不撑满、小框才缩小到相对下限。
- 不传 base_size 时保持旧行为（向后兼容）。

2026-10-07 度量口径改造（docs/lessons.md L54 的完整版）：
- 渲染层的切分单位是「渲染行」（typeset_render.iter_vertical_rows 的 VerticalRow）：
  连续标点 !!/!?/！！ 并排占一行，连续拉丁串按縦中横占一行。
- 度量层（本模块）过去用「字符数」近似渲染行数，导致两处系统性错判：
  ① _fits 的列高 = max(len(col)) 把「!!」当两行 → 明明一列放得下被判放不下；
  ② 断列 DP 以字符下标切分 → 把 6 个字符切成两列、每列都不超 cpc，却不等于
     渲染出来的一列。
  修复方式不是加阈值，而是让度量层用和渲染层**同一套切分单位**：以渲染行为
  单位量列高、断列、算列宽。同时把竖排搜索从「二分 + 线性补扫」（依赖
  「字号越大越放不下」的单调性，而竖排列数跳变会让它不成立）改为在
  (字号 × 列数) 可行域上有界枚举。
- 横排断行同步改为按真实字形像素宽度累加，不再拿「字宽的整数倍」当等宽假设。

2026-10-07 竖排选优顺序改造：
- 原顺序「字号最大优先，同字号才比列数」把**列数变成了几何副产品**：气泡卡在
  零余量边界时，+1px 字号就足以让列数从 1 翻到 2 —— 一句短促喊话被腰斩。
  实测全库 1816 个竖排片区：一列几何不可能的占 70%，列数优先只在约 2% 的
  紧框上以平均约 10% 字号为代价。
- 新顺序：**列数最少优先（主目标），列数内再最大化字号（次目标）**。字号候选
  仍以 base_size 为上限、min_sz 为下限，只在可行域内比较。原文一列的气泡因此
  保持一列，不再被 +1px 拆开；原文多列的气泡由几何自然决定，不受影响。
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

from PIL import ImageFont

# 行頭禁則：这些标点不能出现在新行/新列的开头（闭标点 + 句读符号）
# 依据中日文排版惯例：，。！？、：；）》】…— 及半角对应
NO_START_PUNCT = "，。！？、：；）》】……—"
# 行末禁則：这些标点不能留在行/列的末尾（开括号）
NO_END_PUNCT = "「（【《〈"
MIN_SIZE = 12
MAX_SIZE = 52
SAFE_RATIO = 0.85

# 基准字号参数（2026-09-11）：
# 基准字号 = 图片长边 / BASE_SIZE_DIVISOR（如 3258px 图 → 36px）
# 相对下限 = 基准字号 * MIN_SIZE_RATIO（如 36px → 18px）
BASE_SIZE_DIVISOR = 90
MIN_SIZE_RATIO = 0.7  # 相对下限 = 基准字号 * 0.7（如 38px → 27px），低于此值宁可溢出也不缩小

# 方向推断阈值：高宽比 >= 1.5 视为竖排框，宽高比 >= 1.5 视为横排框
DIRECTION_RATIO_THRESHOLD = 1.5


def _is_latin_token_char(ch: str) -> bool:
    """判断字符是否属于不可分割的横向 token（拉丁字母、数字、常见连接符）。

    断行时拉丁 token 内部不允许断开，避免 cosplay 被拆成 c-osplay。
    用 Unicode 类别 + 常见符号判断，不硬编码单词表。
    """
    cat = unicodedata.category(ch)
    if cat in ("Ll", "Lu", "Lt", "Lm", "Nd"):
        return True
    return ch in " _@./=+%-"


def _inside_latin_token(text: str, pos: int) -> bool:
    """判断断行点 pos 是否落在拉丁 token 内部（前后都是 token 字符 → 不允许断）。"""
    if pos <= 0 or pos >= len(text):
        return False
    return _is_latin_token_char(text[pos - 1]) and _is_latin_token_char(text[pos])


def compute_base_font_size(img_long_side: int) -> int:
    """基于图片长边计算基准字号。

    专业排版原则：所有文字字号应基本一致，基准字号由图片分辨率决定。
    公式：base_size = max(MIN_SIZE, img_long_side // BASE_SIZE_DIVISOR)

    Args:
        img_long_side: 图片长边像素值

    Returns:
        基准字号（整数 px）
    """
    return max(MIN_SIZE, img_long_side // BASE_SIZE_DIVISOR)


def infer_direction_from_bbox(bbox: list) -> str | None:
    """从文本框长宽比推断原文排版方向。

    日漫排版规律：窄长框（高>>宽）通常是竖排，横长框（宽>>高）通常是横排。
    接近方形的框返回 None，表示不强制方向，回退到字号选优。

    Args:
        bbox: [x1, y1, x2, y2]

    Returns:
        "vertical" | "horizontal" | None
    """
    x1, y1, x2, y2 = bbox
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    if h / w >= DIRECTION_RATIO_THRESHOLD:
        return "vertical"
    if w / h >= DIRECTION_RATIO_THRESHOLD:
        return "horizontal"
    return None


# --- 渲染单位（「行」）序列：度量层与渲染层共用的唯一口径 --------------------
# 渲染层 typeset_render.iter_vertical_rows 是唯一切分真源（PNG 与 PSD 都消费它，
# 见 psd_jsx.py）。这里延迟导入以免 typeset_engine ←→ typeset_render 循环依赖。


def _cell_rows(text: str) -> list[tuple[str, str]]:
    """把文本拆成渲染行序列 [(kind, text)]，kind ∈ {"char","latin","punct"}。"""
    from amta.typeset.typeset_render import iter_vertical_rows
    return [(r.kind, r.text) for r in iter_vertical_rows(text)]


def _cell_count(text: str) -> int:
    """竖排一列的实际渲染行数 = 与渲染层同源的切分单位数量。

    不能按 len(text) 算——「!!」是两字符一行、縦中横把 n 个字母并成一行。
    """
    return len(_cell_rows(text))


def _cell_width(kind: str, txt: str, char_w: float, font) -> float:
    """一个渲染单位占的横向宽度，与 _render_vertical 的实际画法一致。

    - punct：整组并排在同一字格内，逐字符均分（_render_vertical 的 punct_w）。
    - latin：整组横排渲染后顺时针旋转90°贴入，旋转后的横向宽度 = 原横排字高
      ≈ line_h ≈ char_w（不再是横排宽度）。
    - char ：一个字格宽。
    """
    if kind == "punct":
        return char_w / max(1, len(txt))
    if kind == "latin":
        return char_w
    return char_w


def _vertical_rows_weighted(col_text: str, font, line_h: float) -> int:
    """竖排一列的渲染行数（span 加权）：拉丁组旋转90°后占 ceil(横宽/行高) 行。

    汉字/标点组各占 1 行；拉丁组（数字/英文）旋转后高度 = 横排宽度，
    因此占 ceil(font.getlength(text) / line_h) 行。纯中文列结果与
    len(iter_vertical_rows(col_text)) 完全一致，不影响纯中文气泡布局。
    """
    from amta.typeset.typeset_render import iter_vertical_rows
    total = 0
    for row in iter_vertical_rows(col_text):
        if row.kind == "latin":
            import math
            w = font.getlength(row.text)
            total += max(1, int(math.ceil(w / line_h)))
        else:
            total += 1
    return total


def _column_width(col_text: str, char_w: float, font) -> float:
    """竖排一列的实际占宽 = 该列最宽的渲染单位。"""
    width = char_w
    for kind, txt in _cell_rows(col_text):
        width = max(width, _cell_width(kind, txt, char_w, font))
    return width


def _break_units(units: list, max_units: int, cost) -> list[list]:
    """统一断行 DP：把 units 切成每段不超过 max_units 段，返回段列表。

    units 可以是字符（list[str]，横排默认口径）或渲染行（list[tuple]）。
    cost(seg, is_last) 由调用方给出，负责「列数最少 → 段长均衡 → 避免短尾」。
    """
    if not units:
        return []
    if max_units <= 0:
        return [units]
    n = len(units)
    if n <= max_units:
        return [units]

    no_start = set(NO_START_PUNCT)
    no_end = set(NO_END_PUNCT)
    punct_only = no_start | set("!?")

    def head(seg) -> str:
        u = seg[0]
        return u[1] if isinstance(u, tuple) else u

    def tail(seg) -> str:
        u = seg[-1]
        return u[1] if isinstance(u, tuple) else u

    def is_punct_only(seg) -> bool:
        for u in seg:
            text = u[1] if isinstance(u, tuple) else u
            if text[0] not in punct_only:
                return False
        return True

    INF = float("inf")
    # dp[i] = (cost, prev_break)
    dp: list[tuple[float, int]] = [(INF, -1)] * (n + 1)
    dp[0] = (0.0, -1)

    for i in range(1, n + 1):
        for j in range(max(0, i - max_units), i):
            seg = units[j:i]
            # 超长容忍：只有最后一列允许略超（overflow_tolerance=0 的兜底，
            # 行为与改造前逐项一致——见 break_lines 的原有说明）。
            if len(seg) > max_units and i != n:
                continue
            # 行首禁则：标点不出现在行首/列首
            if j > 0 and head(seg)[0] in no_start:
                continue
            # 行末禁则：行尾不能是开括号
            if j > 0 and tail(seg)[0] in no_end:
                continue
            # 整行纯标点（标点独占一行/一列）：禁止
            if is_punct_only(seg):
                continue
            prev_cost, _ = dp[j]
            if prev_cost == INF:
                continue
            total = prev_cost + cost(seg, i == n)
            if total < dp[i][0]:
                dp[i] = (total, j)

    # 回溯；无可行断点时原样返回（整段一列/一行）
    out: list[list] = []
    i = n
    while i > 0:
        _, j = dp[i]
        if j < 0:
            return [units]
        out.append(units[j:i])
        i = j
    out.reverse()
    return out


def _wrap_cost(max_units: int):
    """统一代价函数：段数最少（主目标）→ 段长均衡 → 避免短尾。

    与改造前逐项等价（含「严格不超 max_units」与短尾重罚），只是单位从字符
    换成调用方给定的单位。
    """
    def cost(seg, is_last: bool) -> float:
        seg_len = len(seg)
        c = 10000.0  # 每多一段 +10000（主目标）
        c += abs(seg_len - max_units) * 10  # 段长均衡
        if seg_len < max_units // 2:
            c += 500 if is_last else 200  # 短尾惩罚
        return c
    return cost


def break_lines(text: str, max_chars: int) -> list[str]:
    """统一断行：给定每行/列最大**字符数**，DP 找最优断点，遵守硬禁则。

    ⚠️ 这是**字符**口径的公开接口，供 wrap_vertical / 外部调用保持向后兼容。
    竖排生产路径必须走 break_cells（渲染行口径），否则会重现
    「一列能放下却分成两列」（见模块 docstring 与 lessons L54）。

    硬禁则：
    - 标点不出现在行首（行頭禁則）
    - 开括号不出现在行尾（行末禁則）
    - 短文本不断行

    成本函数：行数最少 → 行长均衡 → 避免短尾。
    """
    if max_chars <= 0:
        return [text] if text else []
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces = _break_units(list(text), max_chars, _wrap_cost(max_chars))
    # 保留既有行为：行首（多为被拉下来的空格）去掉前导空白
    return ["".join(p).lstrip() for p in pieces]


def break_cells(text: str, max_cells: int) -> list[str]:
    """竖排断列：单位是**渲染行**（连续标点/縦中横各算一行），不是字符。

    度量层与渲染层共用 typeset_render.iter_vertical_rows 这一切分真源，
    所以「一列放得下」的判断与「渲染出来到底几行」永远一致。
    """
    if max_cells <= 0:
        return [text] if text else []
    if not text:
        return []
    cells = _cell_rows(text)
    if len(cells) <= max_cells:
        return [text]

    groups = _break_units(cells, max_cells, _wrap_cost(max_cells))
    return ["".join(t for _k, t in g).lstrip() for g in groups]


def wrap_cells_to_columns(cells: list[tuple[str, str]], n_cols: int) -> list[str]:
    """把渲染行序列均分成 n_cols 列（列长均衡，前列可多 1 行）。

    竖排搜索用：对每个候选列数构造「正好 n_cols 列」的版式，再交给 _fits 判定。
    """
    if n_cols <= 0 or not cells:
        return []
    base, extra = divmod(len(cells), n_cols)
    cols: list[str] = []
    i = 0
    for k in range(n_cols):
        size = base + (1 if k < extra else 0)
        if size <= 0:
            continue
        cols.append("".join(t for _kind, t in cells[i:i + size]))
        i += size
    return cols


def wrap_text(text: str, font, max_width: float) -> list[str]:
    """横排折行：按**真实字形像素宽度**断行，遵守避头尾与拉丁 token 保护。

    不按 `max_width / font.getlength("字")` 折算字符数——比例字体（拉丁、半角
    标点、混合串）下那个等宽假设不成立，会把行断在错误的位置。
    """
    if not text:
        return []
    if max_width <= 0:
        return [text]
    if font.getlength(text) <= max_width:
        return [text]

    n = len(text)
    # 前缀像素宽：prefix[i] = text[:i] 的宽度
    prefix = [0.0] * (n + 1)
    for i, ch in enumerate(text):
        prefix[i + 1] = prefix[i] + font.getlength(ch)

    def cost(seg, is_last: bool) -> float:
        seg_len = len(seg)
        c = 10000.0
        c += abs(seg_len - _avg_chars_per_line) * 10
        if seg_len < _avg_chars_per_line // 2:
            c += 500 if is_last else 200
        return c

    _avg_chars_per_line = max(1, int(max_width / max(1.0, font.getlength("字"))))
    units = list(text)
    no_start = set(NO_START_PUNCT) | set("!?")
    no_end = set(NO_END_PUNCT)

    INF = float("inf")
    dp: list[tuple[float, int]] = [(INF, -1)] * (n + 1)
    dp[0] = (0.0, -1)
    for i in range(1, n + 1):
        j = i - 1
        while j >= 0:
            if prefix[i] - prefix[j] > max_width:
                break
            seg = units[j:i]
            ok = True
            if j > 0 and seg[0] in no_start:
                ok = False
            if j > 0 and seg[-1] in no_end:
                ok = False
            if _inside_latin_token(text, j):
                ok = False
            if ok:
                prev_cost, _ = dp[j]
                if prev_cost != INF:
                    c = prev_cost + cost(seg, i == n)
                    if c < dp[i][0]:
                        dp[i] = (c, j)
            j -= 1

    out: list[str] = []
    i = n
    while i > 0:
        _, j = dp[i]
        if j < 0:
            return [text]
        out.append(text[j:i])
        i = j
    out.reverse()
    return [ln.lstrip() for ln in out]


def wrap_vertical(text: str, chars_per_col: int) -> list[str]:
    """竖排按列分割（**字符**口径，公开兼容接口）：复用统一 break_lines。"""
    return break_lines(text, chars_per_col)


def wrap_vertical_cells(text: str, cells_per_col: int) -> list[str]:
    """竖排断列（**渲染行**口径，生产路径）：见 break_cells。"""
    return break_cells(text, cells_per_col)


def _font_metrics(font: ImageFont.FreeTypeFont) -> tuple[float, float]:
    """精确测量单个中文字符的宽和行高（利用字体本身的度量，不用硬编码比例）。"""
    char_w = font.getlength("字")
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    return char_w, line_h


def _vertical_col_width(col_text: str, font, char_w: float) -> float:
    """竖排一列的实际宽度（保留旧接口名，内部走渲染行口径）。

    普通字符占 char_w；连续拉丁字母/数字按縦中横的实际像素宽度算；
    连续标点按字格内均分算（与渲染一致）。不再假设每个字符各占一个字宽。
    """
    return _column_width(col_text, char_w, font)


def _fits(lines: list[str], font: ImageFont.FreeTypeFont, bbox: list,
          direction: str) -> bool:
    """检查折行/分列结果是否放入框内（精确测量，无溢出容忍）。

    竖排的列高/列宽一律按**渲染行**口径（与渲染层同源），不再用 len(col)。
    """
    x1, y1, x2, y2 = bbox
    w, h = (x2 - x1) * SAFE_RATIO, (y2 - y1) * SAFE_RATIO
    char_w, line_h = _font_metrics(font)
    if direction == "vertical":
        # 竖排：各列实际宽度之和 <= 框宽；最长列渲染行数（span 加权）* 行高 <= 框高
        max_col_rows = max((_vertical_rows_weighted(col, font, line_h) for col in lines), default=0)
        total_w = sum(_column_width(col, char_w, font) for col in lines)
        return total_w <= w and (max_col_rows * line_h) <= h
    # 横排：最长行像素宽 <= 框宽；行数 * 行高 <= 框高
    max_line = max(font.getlength(ln) for ln in lines) if lines else 0
    return max_line <= w and len(lines) * line_h <= h


def _split_cells_into_columns(cells: list, n_cols: int) -> list[str] | None:
    """把渲染行序列切成正好 n_cols 列，遵守行頭/行末禁则。

    朴素等分（wrap_cells_to_columns）不看首字符，会把 `？`/`，`/`—` 切到列首。
    这里用 DP 在 kinsoku 约束下找最均衡的 n_cols 个断点：
    - 首列豁免（句首可以是任意字符）
    - 后续列首不得是 no_start 标点
    - 列尾不得是 no_end 开括号
    - 纯标点段禁止
    找不到合法 n_cols 分时返回 None（调用方应试 n_cols+1）。
    """
    if n_cols <= 1:
        return ["".join(t for _k, t in cells)] if cells else []
    n = len(cells)
    if n < n_cols:
        return None

    no_start = set(NO_START_PUNCT) | set("!?")
    no_end = set(NO_END_PUNCT)
    punct_only = no_start

    def head_txt(seg):
        u = seg[0]
        return u[1] if isinstance(u, tuple) else u

    def tail_txt(seg):
        u = seg[-1]
        return u[1] if isinstance(u, tuple) else u

    avg = n / n_cols
    INF = float("inf")
    # dp[k][i] = (cost, prev_j)：前 i 个 cells 切成 k 列的最优代价
    dp: list[list[tuple[float, int]]] = [
        [(INF, -1)] * (n + 1) for _ in range(n_cols + 1)
    ]
    dp[0][0] = (0.0, -1)

    for k in range(1, n_cols + 1):
        for i in range(k, n + 1):
            for j in range(k - 1, i):
                prev_cost = dp[k - 1][j][0]
                if prev_cost == INF:
                    continue
                seg = cells[j:i]
                # 非首列：行頭禁则
                if j > 0:
                    h = head_txt(seg)
                    if h and h[0] in no_start:
                        continue
                # 行末禁则：开括号不落在列尾
                t = tail_txt(seg)
                if t and t[0] in no_end:
                    continue
                # 纯标点段禁止
                all_punct = True
                for u in seg:
                    txt = u[1] if isinstance(u, tuple) else u
                    if txt[0] not in punct_only:
                        all_punct = False
                        break
                if all_punct:
                    continue
                # 均衡代价：段长贴近 avg
                cost = prev_cost + abs(len(seg) - avg)
                if cost < dp[k][i][0]:
                    dp[k][i] = (cost, j)

    if dp[n_cols][n][0] == INF:
        return None

    # 回溯
    cols: list[str] = []
    i = n
    for k in range(n_cols, 0, -1):
        j = dp[k][i][1]
        cols.append("".join(t for _kind, t in cells[j:i]).lstrip())
        i = j
    cols.reverse()
    return cols


def _fill_columns(text: str, cells, n_cols: int) -> list[str] | None:
    """把文本渲染行切成 n_cols 列（kinsoku-aware）；不可行返回 None。"""
    if n_cols <= 1:
        return [text]
    return _split_cells_into_columns(cells, n_cols)


def _enum_vertical_feasible(text: str, font_path: Path, bbox: list,
                            min_sz: int, max_sz: int
                            ) -> dict[int, tuple[int, list[str]]]:
    """有界枚举竖排 (字号 × 列数) 可行域，返回 {字号: (最少列数, 该列数的分列结果)}。

    每个可行字号只保留**最少列数**的版式（同字号列越少越贴近原文版式）；
    字号键的最大值即「放开列数限制后的最大字号」。空 dict 表示连 min_sz 都放不下。
    """
    best_by_size: dict[int, tuple[int, list[str]]] = {}
    for size in range(min_sz, max_sz + 1):
        got = _vertical_layout_at(text, font_path, bbox, size)
        if got is not None:
            best_by_size[size] = got
    return best_by_size


def _vertical_layout_at(text: str, font_path: Path, bbox: list, size: int
                        ) -> tuple[int, list[str]] | None:
    """给定字号的竖排最少列数版式；放不下返回 None。"""
    x1, y1, x2, y2 = bbox
    w = (x2 - x1) * SAFE_RATIO
    cells = _cell_rows(text)
    font = ImageFont.truetype(str(font_path), size)
    char_w, _line_h = _font_metrics(font)
    for n_cols in range(1, len(cells) + 1):
        cols = _fill_columns(text, cells, n_cols)
        if cols is None:
            # kinsoku 不允许这么多列（标点会落到列首）——试更多列
            continue
        # 列距不可能放下就直接剪枝（列更宽只会更放不下）
        if sum(_column_width(c, char_w, font) for c in cols) > w:
            break
        if _fits(cols, font, bbox, "vertical"):
            return len(cols), cols
    return None


def _vertical_pick(text: str, font_path: Path, bbox: list,
                   min_sz: int, max_sz: int,
                   diag: dict | None = None) -> tuple[int, list[str], int, bool]:
    """竖排选优：**列数少优先，但只在字号代价可接受时**。

    返回 (字号, 分列结果, 参考字号, 是否单列版式)。
    diag: 传入时填充决策记录（candidate_count, single_col_size, rejection_reason 等）。

    选优规则（无新旋钮，全部复用既有尺度）：
    - 参考字号 ref = **放开 base_size 上限**、放开列数限制后能取到的最大字号，
      即「字号最大优先」会拿到的那个字号。base_size 只是「大框不撑满」的封顶，
      分母若也被它封顶，紧框的参考字号会被一起压低，「单列代价」看着就很小 —
      曾把原图两列的气泡（单列 19px / 参考 36px）误判成一列。
    - base_size 上限内若存在**可行的一列版式**，且其字号 >= ref * MIN_SIZE_RATIO
      （项目既有的「可接受字号比例」），则取一列 —— 这才是「一句短促喊话不该被
      腰斩」的场景，代价落在相对下限以内。
    - 否则走旧行为：能取到的最大字号，同字号取最少列。此时「能一列」的代价已
      超过相对下限，说明分列是版式需求而非 +1px 的偶然。
    """
    x1, y1, x2, y2 = bbox
    h = (y2 - y1) * SAFE_RATIO
    # 单列版式可能只出现在更小字号上：只枚举 base_size 上限内（决定真正返回的版式）
    capped = _enum_vertical_feasible(text, font_path, bbox, min_sz, max_sz)
    # 参考字号 = **放开 base_size 上限**能取到的最大字号（即旧「字号最大优先」的
    # 结果），从 MAX_SIZE 往下找，命中即可停。分母必须放开上限：base_size 只是
    # 「大框不撑满」的封顶，拿它当分母会把紧框的参考字号一起压低，让「单列代价」
    # 看着很小（曾把原图两列的气泡误判成一列）。
    ref = 0
    ref_cols: list[str] | None = None
    for size in range(MAX_SIZE, max_sz, -1):
        got = _vertical_layout_at(text, font_path, bbox, size)
        if got is not None:
            ref, ref_cols = size, got[1]
            break
    if ref == 0:
        # 上限内已有可行版式：最大字号即参考
        if capped:
            ref = max(capped)
            ref_cols = capped[ref][1]
        else:
            font = ImageFont.truetype(str(font_path), min_sz)
            _char_w, line_h = _font_metrics(font)
            cells_per_col = max(1, int(h / line_h))
            return min_sz, break_cells(text, cells_per_col), min_sz, False

    one = next(((s, v) for s, v in sorted(capped.items(), reverse=True)
                if v[0] == 1), None)
    # 只在「单列代价落在相对下限以内」时才让列数赢：否则分列是版式需求，
    # 不是 +1px 的偶然（原文多列气泡的代价会远超此线，仍走旧行为）
    if diag is not None:
        diag["candidate_count"] = len(capped)
        diag["searched_range"] = [min_sz, max_sz]
        diag["ref_size"] = ref
        diag["single_col_size"] = one[0] if one else None
    if one is not None and one[0] >= ref * MIN_SIZE_RATIO:
        size, (_n_cols, cols) = one
        if diag is not None:
            diag["chosen"] = "single_column"
            diag["chosen_size"] = size
            diag["rejection_reason"] = None
        return size, cols, ref, True
    if diag is not None and one is not None:
        diag["rejection_reason"] = (
            f"single_col {one[0]}px < ref*{MIN_SIZE_RATIO}={ref*MIN_SIZE_RATIO:.1f}px"
        )
    # 否则走旧行为：能取到的最大字号，同字号取最少列
    if capped:
        best_size = max(capped)
        n_cols, cols = capped[best_size]
    else:
        best_size, n_cols = ref, len(ref_cols or [])
        cols = ref_cols or []
    if diag is not None:
        diag["chosen"] = "max_size_multi_col"
        diag["chosen_size"] = best_size
        diag["chosen_cols"] = n_cols
    return best_size, cols, ref, n_cols == 1


def _max_size_for_direction(text: str, font_path: Path, bbox: list,
                            direction: str, min_sz: int, max_sz: int
                            ) -> tuple[int, list[str]]:
    """对指定方向做字号搜索，返回 (字号, 折行/分列结果)。

    竖排：在 (字号 × 列数) 可行域上**有界枚举**，然后按
    **列数最少优先 → 同列数内字号最大**选优（见 _vertical_pick）。
    旧的「二分 + 线性补扫」依赖「字号越大越放不下」的单调性，但竖排列数跳变
    会让它不成立（3 列能放 → 2 列卡住 → 更大字号又能放），于是一旦二分的 mid
    失败就会跳过更大的可行字号。
    """
    if not text:
        return min_sz, []
    x1, y1, x2, y2 = bbox
    w = (x2 - x1) * SAFE_RATIO

    if direction == "vertical":
        size, cols, _ref, _is_one = _vertical_pick(text, font_path, bbox, min_sz, max_sz)
        return size, cols

    # 横排：行宽随字号单调，二分 + 线性补扫即可
    lo, hi = min_sz, max_sz
    best, best_lines = min_sz, []
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(str(font_path), mid)
        lines = wrap_text(text, font, w)
        if lines and _fits(lines, font, bbox, "horizontal"):
            best, best_lines = mid, lines
            lo = mid + 1
        else:
            hi = mid - 1
    if not best_lines:  # min_sz 也放不下
        font = ImageFont.truetype(str(font_path), min_sz)
        return min_sz, wrap_text(text, font, w)
    for sz in range(best + 1, max_sz + 1):
        font = ImageFont.truetype(str(font_path), sz)
        lines = wrap_text(text, font, w)
        if lines and _fits(lines, font, bbox, "horizontal"):
            best, best_lines = sz, lines
    return best, best_lines


def fit_font_size(text: str, font_path: Path, bbox: list,
                  min_sz: int = MIN_SIZE, max_sz: int = MAX_SIZE,
                  preferred_direction: str | None = None,
                  base_size: int | None = None,
                  diag: dict | None = None
                  ) -> tuple[int, str, list[str]]:
    """同时计算横排和竖排的最大可行字号，返回 (字号, 方向, 折行/分列)。

    第一性原理：在给定矩形内放给定文字，不溢出且版式正确。
    横排按行折、竖排按列分；方向由几何契约或首选方向决定（见下）。

    base_size（2026-09-11 新增）：基准字号模式。
    - 传入时：max_sz = base_size（大框不撑满）
    - 搜索范围从 MIN_SIZE（绝对下限）到 max_sz；MIN_SIZE_RATIO 是选择偏好
      （在 _vertical_pick 内部作为"单列代价可接受线"），不是搜索截断。
      这样几何可行但小于相对下限的布局也能进入候选集，由选择层决定是否采用。
    - 不传时：用旧的 max_sz/min_sz（向后兼容，框内最大化字号）

    preferred_direction: 首选方向（"horizontal"|"vertical"|None）。
        - 若指定：在该方向排版，仅当该方向的**参考字号** < 次选方向 * 0.70
          时才切换（参考字号 = 放开列数限制的最大字号，见 _vertical_pick）；
        - None 时：同样按参考字号选优，平局偏向竖排（宽扁框的竖排参考字号本来
          就远小于横排，不会被列数优先后的版式误判）。

    选优顺序（2026-10-07）：**列数少优先，但只在字号代价不超过相对下限
    （MIN_SIZE_RATIO）时才让列数赢**——见 _vertical_pick。
    """
    # 基准字号模式：搜索从绝对下限 MIN_SIZE 开始，MIN_SIZE_RATIO 是选择偏好而非搜索截断
    if base_size is not None:
        max_sz = int(base_size)
        min_sz = MIN_SIZE

    h_size, h_lines = _max_size_for_direction(text, font_path, bbox, "horizontal", min_sz, max_sz)
    # 竖排：列数少优先（受相对下限约束），参考字号只用于方向判定
    v_size, v_lines, v_ref, _is_one = _vertical_pick(text, font_path, bbox, min_sz, max_sz, diag=diag)
    if diag is not None:
        diag["h_size"] = h_size
        diag["v_ref"] = v_ref

    if preferred_direction == "vertical":
        # 首选竖排：竖排参考字号不小于横排70%就选竖排
        if v_ref >= h_size * 0.70:
            return v_size, "vertical", v_lines
        return h_size, "horizontal", h_lines
    if preferred_direction == "horizontal":
        # 首选横排：横排参考字号不小于竖排70%就选横排
        if h_size >= v_ref * 0.70:
            return h_size, "horizontal", h_lines
        return v_size, "vertical", v_lines

    # 无首选方向：按参考字号选优，平局偏向竖排（旧行为）
    if v_ref >= h_size:
        return v_size, "vertical", v_lines
    return h_size, "horizontal", h_lines
