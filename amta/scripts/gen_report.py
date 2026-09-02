"""gen_report — 专业 HTML 报告工具 CLI（深接口 amta.report 的薄壳）。

用法:
  python scripts/gen_report.py --work-id <id> --src-dir <原图目录> \
      --pages 1-5 --out output/report.html

阶段自动从 workspace/<work_id>/artifacts/ 读取，缺失的阶段自动跳过。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.report import load_from_workspace, render_report  # noqa: E402


def parse_pages(spec: str) -> list[int]:
    """解析 --pages 参数，支持 '1-5' 或 '1,3,5' 或混合。"""
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def main() -> int:
    ap = argparse.ArgumentParser(description="amta HTML 报告工具")
    ap.add_argument("--work-id", required=True, help="workspace 工作区 ID")
    ap.add_argument("--src-dir", required=True, type=Path, help="源图目录 (N.jpg)")
    ap.add_argument("--pages", required=True, help="页码范围，如 1-5 或 1,3,5")
    ap.add_argument("--out", required=True, type=Path, help="输出 HTML 路径")
    ap.add_argument("--workspace-root", default=None, type=Path,
                    help="workspace 根目录（默认用项目内 workspace/）")
    a = ap.parse_args()

    page_nums = parse_pages(a.pages)
    page_sections = []
    total_warnings = 0
    total_aligned = 0
    total_regions = 0

    for n in page_nums:
        page_idx = n - 1
        try:
            page = load_from_workspace(
                work_id=a.work_id,
                page_idx=page_idx,
                src_dir=a.src_dir,
                workspace_root=a.workspace_root,
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"[gen_report] page {n} 跳过: {e}")
            continue

        result = render_report(page)
        # 提取 page-section 内部内容（去掉 <!DOCTYPE> 外壳）
        inner = result.html.split('<div class="page-section">', 1)[-1]
        inner = inner.rsplit('</div>\n  <div class="footer">', 1)[0]
        page_sections.append(f'<div class="page-section">{inner}')

        total_warnings += len(result.warnings)
        total_aligned += result.regions_aligned
        total_regions += result.regions_total
        print(f"[gen_report] page_{page_idx} ({n}.jpg): "
              f"stages={result.stages_rendered} "
              f"regions={result.regions_total} aligned={result.regions_aligned} "
              f"warnings={len(result.warnings)} "
              f"({result.render_time_ms:.0f}ms)")

    if not page_sections:
        print("[gen_report] 没有成功渲染任何页面")
        return 1

    # 组装多页 HTML
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>amta 管线报告 — {a.work_id}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a2e; margin:0; padding:24px; line-height:1.6; }}
.container {{ max-width:1400px; margin:0 auto; }}
h1 {{ font-size:22px; margin-bottom:4px; }}
.subtitle {{ color:#666; font-size:13px; margin-bottom:20px; }}
.stats {{ display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }}
.stat {{ background:#fff; border-radius:10px; padding:12px 18px; box-shadow:0 1px 4px rgba(0,0,0,.06); min-width:100px; }}
.stat .num {{ font-size:24px; font-weight:700; color:#1e40af; }}
.stat .lbl {{ font-size:11px; color:#666; }}
.stat.ok .num {{ color:#16a34a; }}
.stat.warn .num {{ color:#dc2626; }}
.page-section {{ background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }}
.page-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }}
.page-title {{ font-size:16px; font-weight:700; color:#1e40af; }}
.page-warnings {{ font-size:11px; color:#d97706; }}
.layout {{ display:flex; gap:20px; align-items:flex-start; }}
.img-panel {{ flex:0 0 45%; }}
.img-panel img {{ width:100%; border-radius:8px; border:1px solid #e5e7eb; }}
.table-panel {{ flex:1; overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th {{ background:#f3f4f6; padding:6px 8px; text-align:left; border-bottom:2px solid #e5e7eb; position:sticky; top:0; }}
td {{ padding:6px 8px; border-bottom:1px solid #f3f4f6; vertical-align:top; }}
tr:hover {{ background:#f9fafb; }}
.rid {{ font-weight:600; color:#1e40af; white-space:nowrap; }}
.footer {{ text-align:center; color:#999; font-size:11px; margin-top:24px; padding:16px; }}
</style>
</head>
<body>
<div class="container">
  <h1>amta 管线报告 — {a.work_id}</h1>
  <div class="subtitle">页面: {a.pages} ｜ 总区域: {total_regions} ｜ 对齐: {total_aligned} ｜ 警告: {total_warnings}</div>
  {''.join(page_sections)}
  <div class="footer">amta report tool — 深接口渲染引擎 ｜ 阶段可插拔 ｜ 区域 bbox IoU 对齐</div>
</div>
</body>
</html>"""

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(html, encoding="utf-8")
    print(f"[gen_report] 报告 -> {a.out} ({a.out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
