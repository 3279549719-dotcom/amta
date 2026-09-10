# 重构：清晰目录结构 + 模块化 + 去重（refactor/clean-architecture）

> 目标：把 scripts/ 里重复的样板与逻辑收敛进 `src/amta/` 共享库，脚本只保留薄 CLI 编排。
> 验收：`npm run fastcheck` ALL PASS（compile + ruff + pyright + 全部单测）。

## 问题清单（重构前审计）

| # | 问题 | 位置 |
|---|------|------|
| 1 | `ROOT`/`OUTPUT`/`DATA` + `sys.path.insert` 样板重复 ~20 处 | 全部 scripts |
| 2 | 「建项目→传图→跑流水线→等待→回读→关项目」重复 4 份 | benchmark.run_detector / ocr_detect.run_ocr / recall_detect.run_one / smoke_test |
| 3 | OpenAI 兼容 OCR 请求（image_url data URI + "OCR" 提示）重复 2 份，dashscope/local 批量循环各写一遍 | ocr_run.send_one / dashscope_ocr_batch |
| 4 | CER/EM 按类型汇总（n/cer/em + ALL）重复 4 份 | ocr_eval / eval_86 / ocr_score / sfx_compare |
| 5 | 带 padding 裁剪重复 3 份 | benchmark.crop_page / recall_crop / ocr_run.crop_regions |
| 6 | UTF-8 stdout 样板重复 4 份 | ocr_run / ocr_eval_86 / eval_86 / gen_report_for_manga |
| 7 | `min(cer(g,p), cer(g,p))` 自比较表达式 | ocr_score.py |
| 8 | `_parse_pages` 的 png 分支是死代码（is_source 只收 page.jpg/.jpeg） | benchmark.py |
| 9 | recall_crop 手写并集去重（未复用 geometry.union_boxes） | recall_crop.py |
| 10 | `import statistics` 在函数体内 | sfx_compare.py |

## 目标结构

```
src/amta/
├── __init__.py       # 导出全部公共模块
├── paths.py          # 新增：ROOT/OUTPUT/DATA 常量 + ensure_output/ensure_utf8_stdio/read_json/write_json
├── koharu_client.py  # 保持：Koharu REST 封装
├── pipeline.py       # 保持：引擎 DAG 常量
├── metrics.py        # 保持：指标库
├── geometry.py       # 微调：bbox_from_block 支持已算好的 bbox 字段（recall_crop 复用 union_boxes）
├── runner.py         # 新增：run_pipeline_once / run_all_pages（合并 #2）
├── ocr_engines.py    # 新增：send_chat/send_one/local_ocr_batch/dashscope_ocr_batch/get_dashscope_key（合并 #3）
├── gt_alignment.py   # 新增：crop_regions（GT→detector 框对齐裁剪，ADR-011 逻辑）
├── images.py         # 新增：crop_with_pad（合并 #5）
└── evalkit.py        # 新增：TEXT_CLASSES / eval_rows / summarize_rows（合并 #4）

scripts/               # 全部收敛为薄 CLI（保留入口与参数，向后兼容旧 import 名）
```

## 兼容性约束

- `ocr_run` 继续导出 `crop_regions / send_one / local_ocr_batch / dashscope_ocr_batch / DASHSCOPE_URL`（tests/test_ocr_run.py 依赖）
- `ocr_eval` 继续导出 `eval_rows`（tests/test_ocr_eval.py 依赖）
- `amta.metrics / geometry / pipeline / koharu_client` 公共接口不变
- 输出 JSON 的落盘路径与字段名不变（eval_86 行内 crop 用 basename、补 page 字段）

## 顺手修复（行为微调，均不破坏消费方）

- ocr_score：删除自比较表达式
- benchmark._parse_pages：修复 png 死分支（按原始意图接受 page.png 原文页）
- recall_crop：复用 geometry.union_boxes + images.crop_with_pad，空框跳过（原实现会崩）
- ocr_detect / recall_detect：输出块保留 `bbox` 字段（消费方依赖），多余字段无害

## 验证证据

- [ ] `python scripts/fastcheck.py` → ALL PASS（compile + ruff + pyright + 单测）
- [ ] 新增 tests/test_refactor_shared.py（evalkit / images / runner / ocr_engines / geometry.bbox 优先级）
- [ ] `npm run test`（unittest discover）全绿
