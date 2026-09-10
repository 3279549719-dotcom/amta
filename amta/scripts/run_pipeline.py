"""管线编排器 CLI — 替代 00_run_all.py 的统一入口。

用法：
  python scripts/run_pipeline.py --work-id touhou-single-wing \
      --src-dir "D:\\我的汉化\\汉化作品\\东方\\单翼停留之地" \
      --start-page 11 --end-page 20 \
      --stages detect,ocr,translate \
      [--force-rerun] [--continue-on-error]

阶段配置通过 --config 参数传入 JSON，例如：
  --config '{"ocr": {"engine": "hayai", "rule_filter": true}}'

后续加 inpaint/typeset：只需在 --stages 里加名字，不需要改这个脚本。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common.environment import run_environment_check
from amta.orchestrator import PipelineConfig, available_stages, run_pipeline


def main() -> int:
    ap = argparse.ArgumentParser(description="amta 管线编排器（统一入口）")
    ap.add_argument("--work-id", required=True, help="工作区 ID，如 touhou-single-wing")
    ap.add_argument("--src-dir", required=True, type=Path, help="原始图片目录（N.jpg）")
    ap.add_argument("--start-page", type=int, required=True, help="起始页（1 基，对应文件名）")
    ap.add_argument("--end-page", type=int, required=True, help="结束页（1 基，包含）")
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

    config = PipelineConfig(
        work_id=a.work_id,
        src_dir=a.src_dir,
        start_page=a.start_page,
        end_page=a.end_page,
        stages=stages,
        stage_configs=stage_configs,
        force_rerun=a.force_rerun,
        continue_on_error=a.continue_on_error,
    )

    # 环境自检门卫（Embedded，自动执行，不需要 AI 记得调用）
    if not run_environment_check(stages):
        print("[pipeline] 环境自检未通过，终止运行")
        return 1

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
    print("=" * 60)

    return 1 if result.failed_pages else 0


if __name__ == "__main__":
    raise SystemExit(main())
