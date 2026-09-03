## [2026-09-04 01:16] 迭代完成
- 做了什么：删除 3 个编码损坏/已死的一次性 stage4 探针脚本，修复 fastcheck compile 阶段
- 改了哪些文件：scripts/probe_inpaint_mask_compare.py（删）、scripts/probe_refine_mask.py（删）、scripts/probe_refined_aot_compare.py（删，依赖被删模块连带清理）、ralph.ps1（带上上次未提交的 BOM 修复一起提交）、loop_state.json
- fastcheck 结果：没过（但 compile 阶段已绿）。剩余红全为 pre-existing：ruff lint 54 errors、pytest 18 failed（task #6）、depguard（其余 probe_*.py + hayai_ocr 归一化 bug + text_mask_refiner cv2）
- 经验/教训：一次性探针实验完该删就删；删除被 import 的模块前先查依赖方（probe_refined_aot_compare import probe_refine_mask）；uv venv 无 ruff，fastcheck 须用 py -3.13 全局解释器跑
- 下一步：修 depguard.py 下划线/连字符归一化（hayai_ocr vs hayai-ocr）；剩余探针命运待人类裁决
---
