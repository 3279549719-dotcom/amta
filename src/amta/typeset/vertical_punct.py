"""竖排标点处理（接口层）：按 Unicode 标准自动推导，不针对具体字符硬编码。

设计原则（与 typeset_render 的旧实现对比）：
- 旧做法：维护"哪些具体字符要旋转"的名单（VERTICAL_ROTATE = set("～~—…〜")），
  冒一个新符号加一行——打地鼠。
- 新做法：按 Unicode 区块/属性判断。新冒出来的符号只要属于同类，自动归位。

对外接口（唯一入口，typeset_render 只依赖这三个函数）：
- verticalize_text(line): 竖排时把横排标点换成字体自带的竖排 Unicode 形式。
- should_rotate(ch): 该字符在竖排时是否需要旋转 90°（横向延展的连线/波浪）。
- column_end_pause_mask(columns): 标出"列末逗号，渲染时不显示"的位置（列边界即停顿）。

横排↔竖排标点的配对，来自 Unicode 标准"竖排形式区块"(U+FE30–U+FE4F)，
是标准给定的固定对照，不是为本项目试出来的特例。
"""
from __future__ import annotations

# 横排标点 -> 竖排形式（Unicode 标准竖排形式区块 U+FE30–U+FE4F 的固定配对）。
# 这些字符字体里有现成竖排字形，直接换字符即可，无需旋转。
_HORIZ_TO_VERTICAL: dict[str, str] = {
    "\uFF08": "\uFE35",  # （ -> ︵
    "\uFF09": "\uFE36",  # ） -> ︶
    "\u300C": "\uFE37",  # 「 -> ︷
    "\u300D": "\uFE38",  # 」 -> ︸
    "\u300E": "\uFE39",  # 『 -> ︹
    "\u300F": "\uFE3A",  # 』 -> ︺
    "\u2026": "\uFE19",  # … -> ︙（竖排三点省略号）
}

# 竖排里连续出现时应左右并排、而不是一个叠一个的成对标点（！？）。
# 这是独立于"方向旋转"的排版规则：感叹/问号成对时横排并排。
VERTICAL_COMBINE: set[str] = set("\uFF01\uFF1F!?")


def verticalize_text(line: str) -> str:
    """竖排一行：把有竖排 Unicode 形式的横排标点换成竖排形式。

    没有竖排形式的字符（汉字、以及横向延展符号）原样保留——后者由
    should_rotate 在渲染时决定是否旋转。
    """
    out = []
    for ch in line:
        mapped = _HORIZ_TO_VERTICAL.get(ch)
        out.append(mapped if mapped is not None else ch)
    return "".join(out)


# 竖排"列末逗号消冗"：只针对逗号家族（句读中的"顿"），不碰句末标点。
# 逗号的作用是标记句中停顿；当它正好落在列末时，换列本身已经把停顿视觉化了，
# 再画一个逗号就是同一停顿的重复表达 → 冗余。
# 。！？… 是句末/语气标点，承载"句子结束"的语义，列末也必须保留。
# 、（顿号）与逗号同族，同为"列内并列停顿"；同一条"列末停顿不显示"策略
# 对它同样成立，因此在同一名单里，不做单独特例。
_COLUMN_END_REDUNDANT: frozenset[str] = frozenset("，、,")


def column_end_pause_mask(columns: list[str]) -> list[list[bool]]:
    """标出竖排列末"应停止显示"的停顿符位置（纯函数，唯一入口）。

    返回与 columns 同形状的 bool 掩码：True = 该字符位于某一列的**末位**
    且属于逗号家族（，、,），渲染时跳过其字形；False = 正常显示。

    设计约束（与"删除标点"方案的关键区别）：
    - 只关掉**渲染**。译文文本、lines 元数据、字格推进、列高、整组列的
      垂直居中全部不变——因此列不会缩短、不会重新居中、不会发生位移。
    - 覆盖**所有**视觉列，包括最后一列：一条对白气泡的末列，其列末逗号
      同样是与气泡边界重复的停顿，适用同一条列末显示策略。
    - 列中逗号、句末标点（。！？…；：）一律不掩码，绝不做全局去标点。
    - 单列只有一个字符的退化情形不掩码，避免整列变空白。
    """
    mask = [[False] * len(col) for col in columns]
    for i, col in enumerate(columns):
        if col and col[-1] in _COLUMN_END_REDUNDANT and len(col) > 1:
            mask[i][-1] = True
    return mask


def should_rotate(ch: str) -> bool:
    """竖排时该字符是否需要旋转 90°（"横着躺"的横向延展符号）。

    按 Unicode 码位区块自动判断，不枚举字符：
    - 连接号 U+2010–U+2015（– —）：横向拉长线，竖排要立起来。
    - 波浪/连音符 U+301C 〜、U+30A0 ゠、U+FF5E ～、U+FF0D －、U+007E ~。
    - 句读点（、。！？）和成对方块括号是"直立小字形"，不在这里，返回 False。
    - 省略号 … 已经在 verticalize_text 里换成竖排 ︙，不会走到这步。
    """
    o = ord(ch)
    if 0x2010 <= o <= 0x2015:
        return True
    return o in (0x301C, 0x30A0, 0xFF5E, 0xFF0D, 0x007E)
