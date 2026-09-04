"""amta.report — 深接口 HTML 报告工具（ADR-024）。

## 报告类型一览

| 类型 | 入口 | 用途 | CLI |
|------|------|------|-----|
| 通用管线报告 | `render_report()` + `load_from_workspace()` | 多页管线报告（detect/ocr/translate/inpaint/typeset），阶段可插拔 | `scripts/gen_report.py` |
| 三阶段最终报告 | `final_report.render_final_report()` | 简洁三阶段视图 + base64 内嵌原图 | `scripts/gen_final_report.py` |
| Stage4 验证报告 | (gen_stage4_report 内联深接口) | Stage4 11-20页验证 | `scripts/gen_stage4_report.py` |
| Inpaint A/B 对比 | (gen_inpaint_ab_report 内联深接口) | Inpainting 引擎速度对比 | `scripts/gen_inpaint_ab_report.py` |

## 新增报告的规范

1. **优先用通用引擎**：`load_from_workspace()` + `render_report()` 已支持阶段可插拔，
   新阶段只需在 `assembler.py` 加 StageOutput 组装逻辑。
2. **特殊模板上移到 src/**：如果通用引擎的 HTML 模板不满足需求，把渲染逻辑写成
   `amta.report.<type>_report.render_*()` 模块，scripts/ 下只留薄 CLI。
3. **一次性实验脚本放 scripts/probes/**：A/B 实验、探针验证等非生产报告归档到
   `scripts/probes/`，不占用 scripts/ 根目录。

唯一公共入口: render_report(page: PageReport) -> ReportResult
数据模型: PageReport, StageOutput, ReportResult
数据组装: load_page_report, load_from_workspace
"""
from .model import PageReport, ReportResult, StageOutput
from .engine import render_report
from .assembler import load_page_report, load_from_workspace

__all__ = [
    "render_report",
    "PageReport",
    "StageOutput",
    "ReportResult",
    "load_page_report",
    "load_from_workspace",
]
