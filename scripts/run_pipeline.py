"""管线编排器 CLI — 替代 00_run_all.py 的统一入口。

用法：
  python scripts/run_pipeline.py --work-id touhou-single-wing \
      --src-dir "D:\\我的汉化\\汉化作品\\东方\\单翼停留之地" \
      --start-page 11 --end-page 20 \
      --stages detect,ocr,translate \
      [--force-rerun] [--continue-on-error]

阶段配置通过 --config 参数传入 JSON，例如：
  --config '{"ocr": {"engine": "hayai"}}'

后续加 inpaint/typeset：只需在 --stages 里加名字，不需要改这个脚本。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common.environment import run_environment_check
from amta.common.workstate import ensure_workspace
from amta.orchestrator import PipelineConfig, available_stages, run_pipeline
from amta.orchestrator.quality_audit import audit_run, format_redlist


def main() -> int:
    ap = argparse.ArgumentParser(description="amta 管线编排器（统一入口）")
    ap.add_argument("--work-id", required=True, help="工作区 ID，如 touhou-single-wing")
    ap.add_argument("--src-dir", required=True, type=Path, help="原始图片目录（N.jpg）")
    ap.add_argument("--start-page", type=int, default=1, help="起始页（1 基，对应文件名）")
    ap.add_argument("--end-page", type=int, default=9999, help="结束页（1 基，包含）")
    ap.add_argument("--pages", default=None,
                    help="离散页选择，逗号分隔（如 5,40,60）。指定后覆盖 --start-page/--end-page")
    ap.add_argument("--vlm-pages", default="",
                    help="走 VLM 模式的页面，逗号分隔（如 60,63,67）。不在此列表的页走普通模式")
    ap.add_argument("--stages", default="detect,ocr,translate",
                    help=f"要执行的阶段，逗号分隔。可用阶段: {','.join(available_stages())}")
    ap.add_argument("--config", default="{}", help="阶段配置覆盖（JSON 字符串）")
    ap.add_argument("--force-rerun", action="store_true", help="忽略断点，所有阶段强制重跑")
    ap.add_argument("--continue-on-error", action="store_true", help="单页失败后继续下一页")
    a = ap.parse_args()

    stages = [s.strip() for s in a.stages.split(",") if s.strip()]
    try:
        stage_configs = json.loads(a.config) if isinstance(a.config, str) else {}
    except json.JSONDecodeError as e:
        print(f"[ERROR] --config 不是合法 JSON: {e}")
        return 1

    pages = None
    if a.pages:
        pages = [int(p.strip()) for p in a.pages.split(",") if p.strip()]
    vlm_pages = []
    if a.vlm_pages:
        vlm_pages = [int(p.strip()) for p in a.vlm_pages.split(",") if p.strip()]

    config = PipelineConfig(
        work_id=a.work_id,
        src_dir=a.src_dir,
        start_page=a.start_page,
        end_page=a.end_page,
        pages=pages,
        vlm_pages=vlm_pages,
        stages=stages,
        stage_configs=stage_configs,
        force_rerun=a.force_rerun,
        continue_on_error=a.continue_on_error,
    )

    # 环境自检门卫（Embedded，自动执行，不需要 AI 记得调用）
    if not run_environment_check(stages):
        print("[pipeline] 环境自检未通过，终止运行")
        return 1

    # 状态摘要（Embedded，自动打印当前 git 状态，不需要 AI 记得跑 state bootstrap）
    from amta.common.state_manager import StateManager
    sm = StateManager()
    snap = sm.bootstrap(env_check=False)  # 环境已自检过，不重复
    print(f"[pipeline] branch={snap.branch}, dirty={snap.dirty}")
    if snap.dirty:
        print("[pipeline] 未提交改动:")
        for line in snap.git_status.strip().splitlines()[:5]:
            print(f"  {line}")
    print("[pipeline] 最近 3 commits:")
    for line in snap.git_log.strip().splitlines()[:3]:
        print(f"  {line}")
    print()

    # 书级 glossary：从 src_dir 推导 book_id、落 meta、检测是否已有确认词典（book-level glossary Task 5）
    from amta.common.book_store import book_id_from_src_dir, has_glossary, save_meta
    from amta.common import workstate

    book_id = book_id_from_src_dir(a.src_dir)
    save_meta(book_id, a.src_dir)
    print(f"[book] book_id={book_id} (src_dir={a.src_dir})")
    if has_glossary(book_id):
        print("[book] existing glossary found, skipping pre-scan")
    else:
        print("[book] no glossary yet — first run: will trigger name pre-scan")

    # 把 book_id 写进 work_state，供 stage3_minimal 读取书级词典
    ws = workstate.load_state(a.work_id)
    ws["book_id"] = book_id
    workstate.save_state(a.work_id, ws)

    result = run_pipeline(config)

    # 摘要输出
    print("\n" + "=" * 60)
    print(f"run_id: {result.run_id}")
    print(f"pages: {len(result.pages)}, failed: {len(result.failed_pages)}")
    print(f"stages: {', '.join(result.stages)}")
    print(f"total duration: {result.total_duration_s}s")
    if result.failed_step:
        print(f"first failure: page={result.failed_step['page']} "
              f"stage={result.failed_step['stage']} reason={result.failed_step['reason']}")

    if not result.pages:
        print("[pipeline] ERROR: 未处理任何页面；请检查 --src-dir、页码范围和输入文件名")
        print("=" * 60)
        return 1

    # 质量体检红榜（friction 2026-09-16：质量信号不再静默埋在 JSON 里）
    artifacts_dir = ensure_workspace(a.work_id) / "artifacts"
    redlist = audit_run(artifacts_dir, result.pages)
    if redlist:
        print("quality flags (内容异常非执行失败,下钻: gen_report --granularity region):")
        print(format_redlist(redlist))
    else:
        print("quality audit: all clean")
    print("=" * 60)

    return 1 if result.failed_pages else 0


if __name__ == "__main__":
    raise SystemExit(main())
