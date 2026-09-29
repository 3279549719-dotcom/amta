"""竖排列末逗号消冗 —— 真实页面 before/after 重渲染（Task 4/5）。

走**生产入口** `typeset_station.run()`（与 orchestrator/adapters/typeset.py 相同的
调用方式与产物命名），把同一份上游产物渲染两次：

- before：把 `typeset_render.column_end_pause_mask` 临时替换为"不隐藏任何字形"
  → 等价于修复前的行为；
- after：正常走修复后的代码。

两次渲染的输入（clean 图 / canon / translation / detection）完全相同，唯一变量
就是本次修复，因此 diff 归因是干净的。绝不手改译文或成品图。

上游产物是**只读**读取的（默认来自主项目 workspace），所有输出都写在本项目
工作区内。

用法：
  uv run python scripts/probes/render_page_before_after.py --pages 4 12 13 16
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image  # noqa: E402

from amta.common.paths import read_json  # noqa: E402
from amta.typeset import typeset_render  # noqa: E402
from amta.typeset.typeset_render import _count_vertical_lines  # noqa: E402
from amta.typeset.typeset_station import run as typeset_run  # noqa: E402

DEFAULT_SRC_ROOT = Path(r"E:\manga translator agent\workspace\touhou-getten-shinchi")
DEFAULT_OUT_ROOT = Path("workspace/column-end-comma-fix")
COMMA_FAMILY = set("，、,")
WHITE = (255, 255, 255)
# 真实页面背景是近白（如 254,254,254），不能按"等于纯白"判背景。
INK_LUMA_MAX = 128


def _no_hide(columns):
    """修复前行为：不隐藏任何字形。"""
    return [[False] * len(c) for c in columns]


def _render_page(page: str, src_root: Path, out_root: Path, hide: bool):
    """用生产入口渲染一页，返回 (typeset doc, final 图路径)。"""
    tag = "after" if hide else "before"
    a = src_root / "artifacts"
    out_dir = out_root / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    inpaint_doc = read_json(a / "inpaint" / f"page_{page}.json")
    clean_name = inpaint_doc.get("clean_image", "")
    if not clean_name:
        raise SystemExit(f"page_{page}: inpaint.json 缺少 clean_image")
    clean_path = a / clean_name
    if not clean_path.exists():
        raise SystemExit(f"page_{page}: clean 图不存在 {clean_path}")

    saved = typeset_render.column_end_pause_mask
    if not hide:
        typeset_render.column_end_pause_mask = _no_hide
    try:
        doc = typeset_run(
            work_id=f"column-end-comma-fix-{tag}",
            canon_path=a / "canon" / f"page_{page}.json",
            trans_path=a / "translation" / f"page_{page}.json",
            det_path=a / "detection" / f"page_{page}.json",
            clean_path=clean_path,
            out_path=out_dir / f"page_{page}_typeset.json",
            final_path=out_dir / f"page_{page}_final.png",
        )
    finally:
        typeset_render.column_end_pause_mask = saved
    return doc, out_dir / f"page_{page}_final.png"


def _cell_of(item: dict, col_idx: int, char_idx: int) -> tuple[float, float, float, float]:
    """竖排某列某字格在页面坐标系里的矩形（与 _render_vertical 排布一致）。

    第 0 列是最右列。max_col_h 用 `_count_vertical_lines`（縦中横/标点组合各占
    一行），不是字符数 —— 与渲染器的列高计算保持一致。
    """
    lines = item["lines"]
    n = len(lines)
    lh = item["line_step"]
    cw = item["col_step"]
    cx, cy = item["anchor_pos"]
    max_col_h = max(_count_vertical_lines(c) for c in lines) * lh
    top = cy - max_col_h / 2
    left = cx + (n * cw) / 2 - (col_idx + 1) * cw
    return (left, top + char_idx * lh, left + cw, top + (char_idx + 1) * lh)


def _ink(img: Image.Image, cell) -> int:
    """字格内的"墨迹"像素数。

    真实漫画页的背景不是纯白（inpaint 后常见 254,254,254），所以不能用
    `!= (255,255,255)` 判墨——那会把整格都算成墨。改用亮度阈值：
    明显暗于背景的像素才算字形墨迹。
    """
    x1, y1, x2, y2 = (int(round(v)) for v in cell)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img.width, x2), min(img.height, y2)
    px = img.load()
    return sum(1 for y in range(y1, y2) for x in range(x1, x2)
               if sum(px[x, y]) / 3 < INK_LUMA_MAX)


def _column_end_commas(doc: dict) -> list[tuple[str, int, int, str]]:
    """(region_id, 列号, 末字格下标, 列文本) —— 列末是逗号族的竖排列。"""
    hits = []
    for item in doc.get("rendered_items", []):
        if item.get("layout_direction") != "vertical":
            continue
        for ci, col in enumerate(item.get("lines", [])):
            if col and col[-1] in COMMA_FAMILY:
                hits.append((item.get("region_id", "?"), ci, len(col) - 1, col))
    return hits


def process_page(page: str, src_root: Path, out_root: Path) -> dict:
    doc_before, png_before = _render_page(page, src_root, out_root, hide=False)
    doc_after, png_after = _render_page(page, src_root, out_root, hide=True)

    img_before = Image.open(png_before).convert("RGB")
    img_after = Image.open(png_after).convert("RGB")
    if img_before.size != img_after.size:
        raise SystemExit(f"page_{page}: before/after 尺寸不一致")

    items_after = {it["region_id"]: it for it in doc_after["rendered_items"]}
    items_before = {it["region_id"]: it for it in doc_before["rendered_items"]}

    meta_identical = ([it.get("lines") for it in doc_before["rendered_items"]]
                      == [it.get("lines") for it in doc_after["rendered_items"]])

    checks = []
    for rid, ci, ki, col in _column_end_commas(doc_after):
        cell = _cell_of(items_after[rid], ci, ki)
        checks.append({
            "region_id": rid,
            "line_idx": ci,
            "char_idx": ki,
            "column_text": col,
            "cell": [round(v, 1) for v in cell],
            "ink_before": _ink(img_before, cell),
            "ink_after": _ink(img_after, cell),
        })

    # 全图差异总量（归因：只应来自被隐藏的逗号字形）
    pb, pa = img_before.load(), img_after.load()
    total_changed = sum(1 for y in range(img_before.height)
                        for x in range(img_before.width) if pb[x, y] != pa[x, y])

    return {
        "page": page,
        "lines_metadata_identical": meta_identical,
        "n_column_end_commas": len(checks),
        "regions": sorted({c["region_id"] for c in checks}),
        "checks": checks,
        "total_changed_pixels": total_changed,
        "before_png": str(png_before),
        "after_png": str(png_after),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", required=True)
    ap.add_argument("--src-root", type=Path, default=DEFAULT_SRC_ROOT)
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = ap.parse_args()

    if not args.src_root.exists():
        raise SystemExit(f"上游产物根目录不存在: {args.src_root}")
    args.out_root.mkdir(parents=True, exist_ok=True)

    results = []
    for page in args.pages:
        r = process_page(page, args.src_root, args.out_root)
        results.append(r)
        print("=" * 72)
        print(f"page_{page}: 列末逗号 {r['n_column_end_commas']} 处，"
              f"区域 {r['regions']}，全图改动 {r['total_changed_pixels']}px")
        print(f"  lines 元数据 before/after 一致: {r['lines_metadata_identical']}")
        for c in r["checks"]:
            ok = "OK" if (c["ink_before"] > 0 and c["ink_after"] == 0) else "!! 异常"
            print(f"    [{ok}] {c['region_id']} 列{c['line_idx']} "
                  f"{c['column_text']!r} 字格墨迹 before={c['ink_before']} "
                  f"after={c['ink_after']}")

    (args.out_root / "render_report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入 {args.out_root / 'render_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
