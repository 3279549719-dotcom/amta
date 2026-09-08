"""实验：移除几何规则（edge_box/extreme_aspect），只保留pure_punct/pure_number。

跑全40页 detect + OCR + translate，验证：
1. 救回的6个真实对话的翻译质量
2. p6黑竖条流下来后LLM怎么处理
3. 全40页框数变化
"""
import os
# 代理没开时直连 deepseek（交接文档说明：pop 环境变量可直连）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from amta.orchestrator.pipeline import run_pipeline, PipelineConfig

result = run_pipeline(PipelineConfig(
    work_id="touhou-remove-geo-rules",
    src_dir=Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地"),
    start_page=0,
    end_page=41,
    stages=["detect", "ocr", "translate"],
    stage_configs={
        "detect": {
            "conf_threshold": 0.7,
            "tiling_enabled": True,
            "tiling_cols": 3,
            "tiling_rows": 4,
        },
        "ocr": {
            "engine": "hayai",
            "vlm_enabled": False,
            "rule_filter_enabled": True,  # 只剩 pure_punct/pure_number
        },
        "translate": {
            "vlm_enabled": False,  # 关闭VLM全页refine，纯prompt-slim翻译
        },
    },
    continue_on_error=True,
))

print(f"\n=== 跑完 ===")
print(f"work_id: {result.work_id}")
print(f"页数: {len(result.pages)}")
print(f"失败页: {result.failed_pages}")
print(f"总耗时: {result.total_duration_s:.1f}s")
