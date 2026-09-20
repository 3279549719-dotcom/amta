"""竖排标点处理（接口层）：按 Unicode 标准自动推导，不针对具体字符硬编码。

设计原则（与 typeset_render 的旧实现对比）：
- 旧做法：维护"哪些具体字符要旋转"的名单（VERTICAL_ROTATE = set("～~—…〜")），
  冒一个新符号加一行——打地鼠。
- 新做法：按 Unicode 区块/属性判断。新冒出来的符号只要属于同类，自动归位。

对外接口（唯一入口，typeset_render 只依赖这两个函数）：
- verticalize_text(line): 竖排时把横排标点换成字体自带的竖排 Unicode 形式。
- should_rotate(ch): 该字符在竖排时是否需要旋转 90°（横向延展的连线/波浪）。

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
