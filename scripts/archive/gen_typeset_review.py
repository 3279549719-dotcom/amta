"""gen_typeset_review — typeset 成品图看图报告 CLI（amta.report.typeset_review 的薄壳）。

用法:
  uv run python scripts/gen_typeset_review.py --input-dir <dir> \
      --pattern "page_*_final.png" --out <output.html> --title "标题"

职责边界：本脚本只管"去哪找图 + 找不到怎么办"；HTML 生成在深接口
`src/amta/report/typeset_review.py`（CLAUDE.md HTML 报告铁律）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.report.typeset_review import render_typeset_review


def main() -> int:
    ap = argparse.ArgumentParser(description="typeset 成品图看图报告")
    ap.add_argument("--input-dir", required=True, type=Path, help="成品图目录")
    ap.add_argument("--pattern", default="page_*_final.png", help="文件名匹配模式")
    ap.add_argument("--out", required=True, type=Path, help="输出 HTML 路径")
    ap.add_argument("--title", default="Typeset 成品图审查", help="报告标题")
    a = ap.parse_args()

    images = sorted(a.input_dir.glob(a.pattern))
    if not images:
        print(f"[gen_typeset_review] 未找到匹配 {a.pattern} 的图片")
        return 1

    print(f"[gen_typeset_review] 找到 {len(images)} 张图片")
    for img_path in images:
        print(f"  - {img_path.name} ({img_path.stat().st_size // 1024} KB)")

    out = render_typeset_review(images, title=a.title, out_path=a.out, source=str(a.input_dir))
    print(f"[gen_typeset_review] 报告 -> {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
