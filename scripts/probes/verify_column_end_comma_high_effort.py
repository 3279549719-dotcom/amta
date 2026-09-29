"""竖排列尾逗号消冗 —— High effort 边缘案例验证（Task 1/2/3）。

对**整部作品**（默认 65 页）走生产入口 `typeset_station.run()` 渲染两次：

- before：把两个渲染模块的 `column_end_pause_mask` 临时换成"什么都不隐藏"
  → 等价于修复前行为；
- after：正常走修复后的代码。

两次输入（clean/canon/translation/detection）逐字节相同，唯一变量是本次修复，
所以 diff 归因是干净的。绝不手改译文或成品图；上游产物**只读**。

## 判据：字形回放（glyph replay），而不是"字格内无墨"

真实漫画页的字格里**本来就可能有不属于该字的墨**：上一行的字溢出、原作框线、
网点等。所以"字格内墨迹数 == 0"是错的判据（实测 page_60 r02 列 3 的列末字格里
有一条原作横线，before/after 都在，会被误报成"残留逗号墨迹"）。

正确判据：把被掩码的字形**按渲染器原语重放**到 after 图上，结果必须与 before
**逐像素完全相等**：

    after + replay(被掩码字形) == before      （全图，0 像素差异）

这条等式同时证明两件事：
1. **无残留逗号墨迹**：after 里没有该字形的任何像素（否则重放会叠加出多余墨迹）；
2. **零位移**：除该字形外，全图逐像素不变（任何位移都会让等式不成立）。

## 产出的四类证据

1. **白字深底**（Task 1）：文字接近白色 + 背景深色的竖排区域的列末逗号，
   逐像素等式成立 + ASCII 位图留证。
2. **VLM 路径**（Task 2）：canon `ocr_engine == "vlm-paratext"` 的页走
   `vlm_render`，断言其字体/字号/颜色/lines 元数据 before/after 完全一致。
3. **横排零影响**（Task 3）：所有横排区域的**墨迹矩形**内 before/after 逐像素一致；
   并且横排文本里的逗号（句中/句末）字格内有墨（按渲染器几何复算字格）。
4. **零位移**（通用）：全图改动像素全部落在被掩码字格内。

用法：
  uv run python scripts/probes/verify_column_end_comma_high_effort.py --pages all
  uv run python scripts/probes/verify_column_end_comma_high_effort.py --pages 4 8 60 --bitmaps
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "src"))

from PIL import Image, ImageChops, ImageDraw, ImageFont  # noqa: E402

from render_page_before_after import (  # noqa: E402
    DEFAULT_SRC_ROOT,
    _ink,
    _render_page,
)
from amta.typeset.typeset_render import (  # noqa: E402
    VERTICAL_COMBINE,
    _font_for_char,
    _paste_glyph_centered,
)
from amta.typeset.vertical_punct import should_rotate  # noqa: E402

DEFAULT_OUT_ROOT = Path("workspace/column-end-comma-high-effort-verify")
COMMA_FAMILY = set("，、,")
_SRC_ROOT = DEFAULT_SRC_ROOT


# --- 行拆分（与 typeset_render 的行序列规则一致） ---------------------------

def _is_horizontal_char(ch: str) -> bool:
    """复制 typeset_render._is_horizontal_char 的判定，避免依赖私有符号。"""
    cat = unicodedata.category(ch)
    if cat in ("Ll", "Lu", "Lt", "Lm", "Nd"):
        return True
    if cat == "Lo":
        cp = ord(ch)
        return not (
            0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
            or 0x3040 <= cp <= 0x30FF or 0xAC00 <= cp <= 0xD7AF
        )
    return False


def _row_spans(col_text: str) -> list[tuple[int, int, str]]:
    """把一列拆成 (起始字符下标, 长度, 类型)。类型同 iter_vertical_rows。"""
    spans: list[tuple[int, int, str]] = []
    i, n = 0, len(col_text)
    while i < n:
        ch = col_text[i]
        if ch in VERTICAL_COMBINE:
            j = i
            while j < n and col_text[j] in VERTICAL_COMBINE:
                j += 1
            kind = "punct"
        elif _is_horizontal_char(ch):
            j = i
            while j < n and (_is_horizontal_char(col_text[j]) or col_text[j] == " "):
                j += 1
            kind = "latin"
        else:
            j = i + 1
            kind = "char"
        spans.append((i, j - i, kind))
        i = j
    return spans


def _vertical_layout(item: dict) -> tuple[float, float, float, float, list[str]]:
    """(cx, cy, lh, col_width, lines) —— 区分 MITS 路径与 VLM 路径的几何。"""
    lines = list(item["lines"])
    lh = float(item["line_step"])
    if "ink_bbox" in item:  # vlm_render：列宽由 ink_bbox 反推
        ix1, iy1, ix2, iy2 = (float(v) for v in item["ink_bbox"])
        stroke = float(item.get("stroke_width") or 0)
        n = max(1, len(lines))
        return ((ix1 + ix2) / 2, (iy1 + iy2) / 2, lh,
                (ix2 - ix1 - 2 * stroke) / n, lines)
    cx, cy = (float(v) for v in item["anchor_pos"])
    return cx, cy, lh, float(item["col_step"]), lines


def _vertical_rect(item: dict, col_idx: int, char_idx: int,
                   cx: float, cy: float, lh: float, col_width: float,
                   lines: list[str]) -> tuple[float, float, float, float]:
    """竖排某列某字符的字格矩形（复算渲染器几何）。

    第 0 列是最右列；列高用**行数**（縦中横/标点组合各占一行）。
    char_idx 先映射到行下标，再算 y —— 这正是 main 重构后容易踩错的地方。
    """
    n = len(lines)
    spans = _row_spans(lines[col_idx])
    row_idx = inner = None
    row_kind = "char"
    for r, (start, length, kind) in enumerate(spans):
        if start <= char_idx < start + length:
            row_idx, inner, row_kind = r, char_idx - start, kind
            break
    if row_idx is None:
        raise SystemExit(f"char_idx {char_idx} 越界: {lines[col_idx]!r}")

    max_rows = max((len(_row_spans(c)) for c in lines), default=0)
    top = cy - (max_rows * lh) // 2
    left = cx + (n * col_width) / 2 - (col_idx + 1) * col_width
    y = top + row_idx * lh
    start, length, _ = spans[row_idx]
    if row_kind == "punct":
        group = lines[col_idx][start:start + length]
        w = col_width / len(group)
        x = left + (col_width - len(group) * w) / 2 + inner * w
        return (x, y, x + w, y + lh)
    if row_kind == "latin":
        group = lines[col_idx][start:start + length]
        widths = [_font_for_char(item["font_path"], int(item["font_size"]), c).getlength(c)
                  for c in group]
        x = left + (col_width - sum(widths)) / 2 + sum(widths[:inner])
        return (x, y, x + widths[inner], y + lh)
    return (left, y, left + col_width, y + lh)


def _vertical_ink_rect(item: dict) -> tuple[float, float, float, float]:
    """整个竖排区域的墨迹矩形（复算渲染器几何，不依赖 detection bbox）。"""
    cx, cy, lh, col_width, lines = _vertical_layout(item)
    n = len(lines)
    max_rows = max((len(_row_spans(c)) for c in lines), default=0)
    top = cy - (max_rows * lh) // 2
    right = cx + (n * col_width) / 2
    left = right - n * col_width
    return (left, top, right, top + max_rows * lh)


def _horizontal_char_rect(item: dict, line_idx: int, char_idx: int):
    """横排某字符的字格矩形（复算渲染器几何）。

    MITS 与 VLM 两条横排路径的推进方式不同：
    - MITS(`typeset_render.render_item`)：逐字符用 fallback 字体画，整行水平居中；
    - VLM(`vlm_render.render_text`)：整行一次 `draw.text`，按 align 对齐到 block bbox。
    """
    lines = list(item["lines"])
    lh = float(item["line_step"])
    size = int(item["font_size"])
    path = str(item["font_path"])
    line = lines[line_idx]

    if "ink_bbox" in item:
        stroke = float(item.get("stroke_width") or 0)
        pad = stroke + 3
        font = ImageFont.truetype(path, size)
        bounds = font.getbbox(line or "字")
        length = (bounds[2] - bounds[0]) + 2 * stroke
        bx1, _by1, bx2, _by2 = (float(v) for v in item["bbox"])
        align = item.get("align", "center")
        if align == "left":
            x = bx1
        elif align == "right":
            x = bx2 - length
        else:
            x = (bx1 + bx2 - length) / 2
        x += stroke
        pen = x - bounds[0]
        widths = [font.getlength(ch) for ch in line]
        left = pen + sum(widths[:char_idx])
        right = left + widths[char_idx]
        iy1 = float(item["ink_bbox"][1])
        y = iy1 + stroke + line_idx * lh
        return (left - pad, y - pad, right + pad, y + lh + pad)

    cx, cy = (float(v) for v in item["anchor_pos"])
    y0 = cy - (len(lines) * lh) // 2
    widths = [_font_for_char(path, size, ch).getlength(ch) for ch in line]
    x = cx - sum(widths) / 2 + sum(widths[:char_idx])
    y = y0 + line_idx * lh
    return (x, y, x + widths[char_idx], y + lh)


def _horizontal_ink_rect(item: dict) -> tuple[float, float, float, float]:
    """整个横排区域的墨迹矩形。"""
    if "ink_bbox" in item:  # VLM：ink_bbox 就是画出来的范围（含描边）
        ix1, iy1, ix2, iy2 = (float(v) for v in item["ink_bbox"])
        pad = float(item.get("stroke_width") or 0) + 3
        return (ix1 - pad, iy1 - pad, ix2 + pad, iy2 + pad)

    lines = list(item["lines"])
    lh = float(item["line_step"])
    cx, cy = (float(v) for v in item["anchor_pos"])
    size = int(item["font_size"])
    path = str(item["font_path"])
    y0 = cy - (len(lines) * lh) // 2
    lefts, rights = [], []
    for line in lines:
        widths = [_font_for_char(path, size, ch).getlength(ch) for ch in line]
        lefts.append(cx - sum(widths) / 2)
        rights.append(cx - sum(widths) / 2 + sum(widths))
    return (min(lefts), y0, max(rights), y0 + len(lines) * lh)


def _dominant_color(img: Image.Image, rect) -> tuple[int, int, int]:
    """矩形内出现次数最多的颜色（= 背景色）。

    用 `Image.getcolors`（C 实现）而不是 Python 逐像素——整部作品 65 页
    逐像素扫会慢到不可用。
    """
    x1, y1, x2, y2 = (int(round(v)) for v in rect)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img.width, x2), min(img.height, y2)
    if x2 <= x1 or y2 <= y1:
        return (255, 255, 255)
    colors = img.crop((x1, y1, x2, y2)).getcolors(maxcolors=1 << 24)
    if not colors:
        return (255, 255, 255)
    return max(colors, key=lambda t: t[0])[1]


def _changed_mask(a: Image.Image, b: Image.Image) -> Image.Image:
    """逐像素"是否不同"的二值掩码（全 C 实现）。"""
    r, g, bl = ImageChops.difference(a, b).split()
    m = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    return m.point(lambda v: 255 if v else 0)


def _mask_count(mask: Image.Image) -> int:
    return mask.histogram()[255]


def _rects_mask(size, rects, pad: int = 0) -> Image.Image:
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for (x1, y1, x2, y2) in rects:
        d.rectangle([int(x1) - pad, int(y1) - pad, int(x2) + pad, int(y2) + pad], fill=255)
    return m


def _mask_sample(mask: Image.Image, limit: int = 5) -> list[list[int]]:
    """二值掩码里前若干个置位像素的坐标（只在有异常时调用）。"""
    out: list[list[int]] = []
    px = mask.load()
    for y in range(mask.height):
        for x in range(mask.width):
            if px[x, y]:
                out.append([x, y])
                if len(out) >= limit:
                    return out
    return out


def _luma(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _hex_rgb(value: str) -> tuple[int, int, int]:
    value = (value or "#000000").lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


# --- 字形回放（核心判据） ---------------------------------------------------

def _replay_glyph(img: Image.Image, item: dict, ch: str,
                  cell: tuple[float, float, float, float],
                  lh: float) -> None:
    """把被掩码的字形按 `_render_vertical` 的同一原语重放回图上。

    与渲染器唯一可能的差别是字体/颜色/描边的来源 —— 这里全部取自落盘元数据
    （`font_path` / `rendered_color` / `rendered_stroke` / `stroke_width`），
    所以重放就是"如果没被掩码会画成什么样"。
    """
    size = int(item["font_size"])
    font = _font_for_char(str(item["font_path"]), size, ch)
    if "ink_bbox" in item:  # vlm_render：颜色/描边来自 VLM 观察值
        color = _hex_rgb(item.get("color") or item.get("rendered_color") or "#000000")
        stroke = float(item.get("stroke_width") or 0)
    else:  # MITS：颜色/描边来自背景自适应
        color = _hex_rgb(item.get("rendered_color") or "#000000")
        stroke = float(item.get("rendered_stroke") or 0)
    cell_w = cell[2] - cell[0]
    _paste_glyph_centered(img, font, ch, cell[0], cell[1], cell_w, lh,
                          stroke, color, rotate=should_rotate(ch))


def _count_glyph_pixels(item: dict, ch: str,
                        cell: tuple[float, float, float, float],
                        lh: float) -> int:
    """该字形单独的墨迹像素数（用来验证"改动像素数 == 字形像素数"）。

    在小画布上重放，四周留 8px 余量，避免整页画布的开销。
    """
    margin = 8
    cw = max(1, int(round(cell[2] - cell[0])))
    canvas = Image.new("RGB", (cw + 2 * margin, int(lh) + 2 * margin + 1), (0, 0, 0))
    _replay_glyph(canvas, item, ch, (float(margin), float(margin), float(margin + cw), margin + lh), lh)
    px = canvas.load()
    return sum(1 for y in range(canvas.height) for x in range(canvas.width)
               if px[x, y] != (0, 0, 0))


# --- 逐页分析 ---------------------------------------------------------------

def analyse(page: str, out_root: Path, want_bitmaps: bool = False) -> dict:
    doc_before, png_before = _render_page(page, _SRC_ROOT, out_root, hide=False)
    doc_after, png_after = _render_page(page, _SRC_ROOT, out_root, hide=True)
    img_before = Image.open(png_before).convert("RGB")
    img_after = Image.open(png_after).convert("RGB")
    if img_before.size != img_after.size:
        raise SystemExit(f"page_{page}: before/after 尺寸不一致")

    items_after = {it["region_id"]: it for it in doc_after["rendered_items"]}
    items_before = {it["region_id"]: it for it in doc_before["rendered_items"]}
    meta_identical = all(items_before[rid] == items_after[rid] for rid in items_after)

    # --- 1/2：竖排列末逗号 ---
    cells: list[dict] = []
    for rid, item in items_after.items():
        if item.get("layout_direction") != "vertical":
            continue
        cx, cy, lh, col_width, lines = _vertical_layout(item)
        if not any(lines):
            # 空译文（translation 里是 ""）会得到 lines == []；没有列就没有列末逗号。
            continue
        ink_rect = _vertical_ink_rect(item)
        bg = _dominant_color(img_after, ink_rect)
        text_rgb = _hex_rgb(item.get("rendered_color", "#000000"))
        white_on_dark = _luma(text_rgb) > 200 and _luma(bg) < 110
        for ci, col in enumerate(lines):
            if not col or col[-1] not in COMMA_FAMILY:
                continue
            cell = _vertical_rect(item, ci, len(col) - 1, cx, cy, lh, col_width, lines)
            cells.append({
                "region_id": rid, "line_idx": ci, "char_idx": len(col) - 1,
                "char": col[-1], "column_text": col,
                "cell": [round(v, 1) for v in cell],
                "_cell": cell, "_item": item, "_lh": lh,
                "ink_before": _ink(img_before, cell),
                "ink_after": _ink(img_after, cell),
                "rendered_color": item.get("rendered_color"),
                "bg_color": list(bg),
                "white_on_dark": white_on_dark,
                "font_size": item.get("font_size"),
                "font_family": item.get("font_family")
                or Path(str(item.get("font_path"))).name,
            })

    # 全图改动 + 归因（全 C 实现：PIL 掩码运算，不逐像素 Python 循环）
    changed_mask = _changed_mask(img_before, img_after)
    changed_count = _mask_count(changed_mask)
    cells_mask = _rects_mask(img_before.size,
                             [(c["_cell"][0], c["_cell"][1], c["_cell"][2], c["_cell"][3])
                              for c in cells])
    orphan_mask = ImageChops.subtract(changed_mask, cells_mask)
    orphan_count = _mask_count(orphan_mask)

    # 核心：after + replay(被掩码字形) == before
    scratch = img_after.copy()
    for c in cells:
        _replay_glyph(scratch, c["_item"], c["char"], c["_cell"], c["_lh"])
        c["glyph_pixels"] = _count_glyph_pixels(
            c["_item"], c["char"], c["_cell"], c["_lh"])
        x1, y1, x2, y2 = (int(round(v)) for v in c["_cell"])
        c["removed_pixels_in_cell"] = _mask_count(
            changed_mask.crop((max(0, x1 - 4), max(0, y1 - 4),
                               min(img_before.width, x2 + 5),
                               min(img_before.height, y2 + 5))))

    replay_mask = _changed_mask(scratch, img_before)
    replay_mismatch = _mask_count(replay_mask)

    # --- 3：横排零影响 ---
    horizontal_items = []
    for rid, item in items_after.items():
        if item.get("layout_direction") != "horizontal":
            continue
        x1, y1, x2, y2 = (int(round(v)) for v in _horizontal_ink_rect(item))
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img_before.width, x2), min(img_before.height, y2)
        diff = _mask_count(changed_mask.crop((x1, y1, x2, y2))) if x2 > x1 and y2 > y1 else 0
        comma_cells, glyph_cells, glyph_inked = [], 0, 0
        for li, line in enumerate(item.get("lines", [])):
            for ki, ch in enumerate(line):
                if ch in (" ", "\u3000"):
                    continue
                cell = _horizontal_char_rect(item, li, ki)
                ink = _ink(img_before, cell)
                glyph_cells += 1
                glyph_inked += 1 if ink > 0 else 0
                if ch in COMMA_FAMILY:
                    comma_cells.append({"line_idx": li, "char_idx": ki,
                                        "char": ch, "ink": ink})
        horizontal_items.append({
            "region_id": rid,
            "ink_rect": [x1, y1, x2, y2],
            "rect_changed_pixels": diff,
            "glyph_cells": glyph_cells,
            "glyph_cells_inked": glyph_inked,
            "comma_cells": comma_cells,
        })

    # 位图留证（白字深底 + VLM）
    bitmaps = {}
    if want_bitmaps:
        interesting = [c for c in cells if c["white_on_dark"]] or cells
        for c in interesting:
            x1, y1, x2, y2 = (int(round(v)) for v in c["_cell"])
            bitmaps[f"{page}:{c['region_id']}:col{c['line_idx']}"] = {
                "before": _ascii_bitmap(img_before, x1, y1, x2, y2),
                "after": _ascii_bitmap(img_after, x1, y1, x2, y2),
            }

    for c in cells:
        c.pop("_item", None)
        c.pop("_cell", None)
        c.pop("_lh", None)

    wd = [c for c in cells if c["white_on_dark"]]
    return {
        "page": page,
        "renderer": doc_after.get("renderer", "mits"),
        "is_vlm": doc_after.get("renderer") == "vlm-greedy-wrap",
        "lines_metadata_identical": meta_identical,
        "n_column_end_commas": len(cells),
        "vertical_cells": cells,
        "white_on_dark_cells": wd,
        "horizontal_items": horizontal_items,
        "n_horizontal_items": len(horizontal_items),
        "total_changed_pixels": changed_count,
        "orphan_changed_pixels": orphan_count,
        "orphan_sample": _mask_sample(orphan_mask) if orphan_count else [],
        "replay_mismatch_pixels": replay_mismatch,
        "replay_mismatch_sample": _mask_sample(replay_mask) if replay_mismatch else [],
        "bitmaps": bitmaps,
        "before_png": str(png_before),
        "after_png": str(png_after),
    }


def _ascii_bitmap(img: Image.Image, x1: int, y1: int, x2: int, y2: int,
                  step: int = 2) -> list[str]:
    """字格的 ASCII 位图：`#` = 与格内主色差异 > 60 的像素。"""
    bg = _dominant_color(img, (x1, y1, x2, y2))
    rows = []
    for y in range(max(0, y1), min(img.height, y2), step):
        rows.append("".join(
            "#" if max(abs(img.getpixel((x, y))[i] - bg[i]) for i in range(3)) > 60 else "."
            for x in range(max(0, x1), min(img.width, x2))))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", required=True,
                    help="页码列表，或 'all'（1..65）")
    ap.add_argument("--src-root", type=Path, default=DEFAULT_SRC_ROOT)
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    ap.add_argument("--report-name", default="verify_report.json")
    ap.add_argument("--bitmaps", action="store_true",
                    help="额外输出被掩码字格的 ASCII 位图（留证）")
    args = ap.parse_args()

    global _SRC_ROOT
    _SRC_ROOT = args.src_root
    if not _SRC_ROOT.exists():
        raise SystemExit(f"上游产物根目录不存在: {_SRC_ROOT}")

    pages = ([str(n) for n in range(1, 66)]
             if len(args.pages) == 1 and args.pages[0] == "all" else args.pages)
    args.out_root.mkdir(parents=True, exist_ok=True)

    results = []
    for page in pages:
        r = analyse(page, args.out_root, want_bitmaps=args.bitmaps)
        results.append(r)
        print(f"page_{page:<3} renderer={r['renderer']:<16} "
              f"列末逗号 {r['n_column_end_commas']:>2} 白字深底 "
              f"{len(r['white_on_dark_cells']):>2} 横排 {r['n_horizontal_items']:>2} "
              f"改动 {r['total_changed_pixels']:>5}px 位移 {r['orphan_changed_pixels']:>3} "
              f"回放差 {r['replay_mismatch_pixels']}"
              f"{'  !!' if (r['orphan_changed_pixels'] or r['replay_mismatch_pixels']) else ''}",
              flush=True)

    out = args.out_root / args.report_name
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 汇总 ---
    cells = [c for r in results for c in r["vertical_cells"]]
    wd_cells = [c for r in results for c in r["white_on_dark_cells"]]
    print("\n" + "=" * 72)
    print(f"页数 {len(results)}")
    print(f"竖排列末逗号合计   : {len(cells)}")
    print(f"  白字深底         : {len(wd_cells)}")
    print(f"  非白字深底       : {len(cells) - len(wd_cells)}")
    print(f"  标点分布         : "
          f"{ {m: sum(1 for c in cells if c['char'] == m) for m in sorted({c['char'] for c in cells})} }")
    silent = [c for c in cells if c["removed_pixels_in_cell"] <= 0]
    print(f"  掩码确实生效(格内有像素被移除): {len(cells) - len(silent)}/{len(cells)}"
          + (f"  !! {[c['region_id'] for c in silent][:5]}" if silent else "  OK"))
    mismatch = sum(r["replay_mismatch_pixels"] for r in results)
    orphans = sum(r["orphan_changed_pixels"] for r in results)
    print(f"字形回放等式 after+glyph==before: "
          f"{'OK（0 像素差异）' if not mismatch else f'!! {mismatch} 像素差异'}")
    print(f"  白字深底子集回放差异: "
          f"{sum(1 for c in wd_cells if c['removed_pixels_in_cell'] <= 0)} 处异常")
    print(f"全图改动像素合计   : {sum(r['total_changed_pixels'] for r in results)}")
    print(f"改动溢出掩码字格(位移): {orphans}" + ("  OK" if not orphans else "  !!"))
    hn = [h for r in results for h in r["horizontal_items"]]
    hbad = [h for h in hn if h["rect_changed_pixels"]]
    print(f"横排区域           : {len(hn)}（墨迹矩形内 before/after 逐像素一致: "
          f"{len(hn) - len(hbad)}/{len(hn)}" + (f"  !! {hbad[:3]}" if hbad else "  OK)"))
    hc = [c for h in hn for c in h["comma_cells"]]
    hc_bad = [c for c in hc if c["ink"] <= 0]
    print(f"横排逗号字格       : {len(hc)}（有墨 {len(hc) - len(hc_bad)}"
          + (f"  !! 无墨 {hc_bad[:3]}" if hc_bad else "  OK)"))
    gc = sum(h["glyph_cells"] for h in hn)
    gci = sum(h["glyph_cells_inked"] for h in hn)
    print(f"  （几何自校验：横排非空字符格 {gci}/{gc} 有墨，用于证明字格几何复算无误）")
    vlm_pages = [r["page"] for r in results if r["is_vlm"]]
    vlm_cells = [c for r in results if r["is_vlm"] for c in r["vertical_cells"]]
    print(f"VLM 页             : {vlm_pages}")
    print(f"  VLM 列末逗号     : {len(vlm_cells)} 处")
    print(f"  VLM 元数据(before/after 完全一致): "
          f"{all(r['lines_metadata_identical'] for r in results if r['is_vlm'])}")
    print(f"\n报告已写入 {out}")
    return 1 if (silent or mismatch or orphans or hbad or hc_bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
