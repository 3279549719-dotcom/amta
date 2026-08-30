"""字体注册表(Stage 5): 4 级字体映射 + 探测 + 降级。

蓝图 4 类字体映射: 对白→黑体/准圆(无描边); 独白/压脸→楷体(强制白描边 2.5px);
呼喊→粗体; SFX→手写体。字体只读系统目录,不下载不打包(Spec §2/Q2)。
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_FONT_DIR = Path("C:/Windows/Fonts")

FONT_LEVELS = {
    "dialogue": "msyh.ttc",            # 微软雅黑(对白)
    "overlay_narration": "simkai.ttf",  # 楷体(独白/压脸字)
    "shout": "msyhbd.ttc",             # 微软雅黑粗(呼喊/感叹)
    "sfx": "FZSTK.TTF",                # 方正舒体(拟声,手写风格)
}

STROKE = {"dialogue": 0, "overlay_narration": 2.5, "shout": 0, "sfx": 2.5}
FALLBACK_CHAIN = ["msyh.ttc", "simhei.ttf"]


class FontNotFoundError(RuntimeError):
    pass


def _level_for(category: str, text: str) -> str:
    if "！" in text or "!" in text:
        return "shout"
    if category == "overlay_text":
        return "overlay_narration"
    if category == "sfx":
        return "sfx"
    return "dialogue"


def resolve_font(category: str, text: str,
                 font_dir: Path | None = None) -> tuple[Path, int]:
    """返回 (字体路径, 描边宽度)。目标字体缺失按 FALLBACK_CHAIN 降级。"""
    d = Path(font_dir) if font_dir else DEFAULT_FONT_DIR
    level = _level_for(category, text)
    candidates = [FONT_LEVELS[level], *FALLBACK_CHAIN]
    for name in candidates:
        p = d / name
        if p.exists():
            return p, STROKE[level]
    raise FontNotFoundError(f"no CJK font found in {d} (tried {candidates})")
