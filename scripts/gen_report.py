"""gen_report — amta HTML 报告统一入口（深接口模式）。

统一接口，不再枚举报告类型。通过 --granularity 和 --stages 自由组合。

用法:
  # 框级详细报告（默认）：左图右表，所有阶段
  python scripts/gen_report.py --work-id <id> --src-dir <dir> --pages 1-5

  # 页级快速对比：只看原图和干净图
  python scripts/gen_report.py --work-id <id> --src-dir <dir> --pages 11-15 \
      --granularity page --stages raw,inpaint

  # 页级三阶段对比
  python scripts/gen_report.py --work-id <id> --src-dir <dir> --pages 11-15 \
      --granularity page --stages raw,inpaint,typeset

  # 框级但只看 detect 和 ocr
  python scripts/gen_report.py --work-id <id> --src-dir <dir> --pages 1-5 \
      --granularity region --stages detect,ocr
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.common.paths import ROOT as _PATHS_ROOT
from amta.report import load_from_workspace
from amta.report.engine import (
    _composite_overlays,
    _load_image,
    render_compare_section,
    render_page_section,
    render_report_shell,
)

ROOT = _PATHS_ROOT


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


def _extract_stage_image(page_report, stage_key: str, raw_img):
    """从 PageReport 提取某个阶段的代表图（页级对比用）。

    - raw: 原图
    - inpaint: page_artifact 里的 clean_image
    - typeset: page_artifact 里的 final_image
    - 其他阶段(detect/ocr/translate/filter): 原图叠加该阶段 overlay
    """
    if stage_key == "raw":
        return raw_img

    stage = next((s for s in page_report.stages if s.key == stage_key), None)
    if stage is None:
        return None

    # inpaint / typeset 有整页产出图
    if stage_key == "inpaint" and stage.page_artifact:
        img = stage.page_artifact.get("clean_image")
        if img is not None:
            return img
    if stage_key == "typeset" and stage.page_artifact:
        img = stage.page_artifact.get("final_image")
        if img is not None:
            return img

    # 其他阶段：原图叠加 overlay
    return _composite_overlays(raw_img, [stage])


_STAGE_LABELS = {
    "raw": "原图",
    "detect": "检测框",
    "ocr": "OCR",
    "filter": "筛选",
    "translate": "翻译",
    "inpaint": "干净图",
    "typeset": "最终成图",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="amta HTML 报告统一入口（深接口模式）")
    ap.add_argument("--work-id", required=True, help="workspace 工作区 ID")
    ap.add_argument("--src-dir", required=True, type=Path, help="源图目录 (N.jpg)")
    ap.add_argument("--pages", required=True, help="页码范围，如 1-5 或 1,3,5")
    ap.add_argument("--granularity", choices=["page", "region"], default="region",
                    help="展示粒度：page=全图快速对比，region=全图+区域表格（默认）")
    ap.add_argument("--stages", default=None,
                    help="展示阶段，逗号分隔，如 raw,detect,inpaint。默认全部存在的阶段")
    ap.add_argument("--out", type=Path, default=None, help="输出 HTML 路径")
    ap.add_argument("--workspace-root", type=Path, default=None, help="workspace 根目录")
    a = ap.parse_args()

    page_nums = parse_pages(a.pages)
    stages_filter = None
    if a.stages:
        stages_filter = [s.strip() for s in a.stages.split(",") if s.strip()]

    # assembler 的 stages_filter 不认识 "raw"，过滤掉
    artifact_stages = [s for s in stages_filter if s != "raw"] if stages_filter else None

    out = a.out or ROOT / "output" / f"{a.work_id}-report.html"
    out.parent.mkdir(parents=True, exist_ok=True)

    sections = []
    total_regions = 0
    total_warnings = 0

    for n in page_nums:
        try:
            page = load_from_workspace(
                work_id=a.work_id,
                page_idx=n,
                src_dir=a.src_dir,
                workspace_root=a.workspace_root,
                stages_filter=artifact_stages,
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"[gen_report] page {n} 跳过: {e}")
            continue

        if a.granularity == "page":
            # 页级：多图左右对比
            raw_img = _load_image(page.raw_image)
            # 确定要展示的阶段列表
            if stages_filter:
                show_stages = [s for s in stages_filter if s == "raw" or
                               any(st.key == s for st in page.stages)]
            else:
                show_stages = ["raw"] + [s.key for s in page.stages]

            images = []
            for sk in show_stages:
                img = _extract_stage_image(page, sk, raw_img)
                if img is not None:
                    label = _STAGE_LABELS.get(sk, sk)
                    images.append((img, label))

            if not images:
                print(f"[gen_report] page {n} 没有可展示的图片，跳过")
                continue

            section = render_compare_section(images, n)
            sections.append(section)
            print(f"[gen_report] page_{n}: page级对比 ({len(images)} 张图)")

        else:
            # region 级：全图 + 区域表格
            section, stats_info = render_page_section(page, granularity="region")
            sections.append(section)
            total_regions += stats_info.get("regions_total", 0)
            total_warnings += len(stats_info.get("warnings", []))
            print(f"[gen_report] page_{n}: region级 "
                  f"stages={stats_info['stages_rendered']} "
                  f"regions={stats_info.get('regions_total', 0)} "
                  f"warnings={len(stats_info.get('warnings', []))}")

    if not sections:
        print("[gen_report] 没有成功渲染任何页面")
        return 1

    title = f"amta 报告 — {a.work_id}"
    subtitle = f"第 {a.pages} 页 ｜ 粒度: {a.granularity}"
    if stages_filter:
        subtitle += f" ｜ 阶段: {', '.join(stages_filter)}"
    if total_regions:
        subtitle += f" ｜ 区域: {total_regions}"
    if total_warnings:
        subtitle += f" ｜ 警告: {total_warnings}"

    html = render_report_shell(sections, title=title, subtitle=subtitle)
    out.write_text(html, encoding="utf-8")
    print(f"[gen_report] 报告 -> {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
