# 018 — 流水线编排器:00_run_all + step tracing + LLM 观测(零依赖自造,借鉴开源思想)

## Context

- ADR-013/014 定了 per-work 产物契约与翻译工位,但 01_detect/02_ocr 只有评测脚本,无工位;00_run_all 编排器缺失——"脚本串成可断点续跑的流水线"未落地。
- Patrick 指示:调研 GitHub 高星开源项目(Prefect/Metaflow/Dagster/LangSmith/LiteLLM/OpenTelemetry/Pydantic/Great Expectations,3 个 subagent 并行调研,存档 reference/pipeline-orchestration-research-report.html),结论:**全部不引依赖**(个人 DIY + 最小依赖铁律),借鉴思想自造薄层。
- 借思想:Metaflow resume(断点续跑)、OpenTelemetry span(step tracing)、LiteLLM 调用日志(LLM 观测)、Pydantic 契约(Pydantic 本身观望)。

## Decision

1. **编排器** `scripts/00_run_all.py`(~150 行):01_detect → 02_ocr → 03_translate → [③ 评审 → 自动修复](--with-review);**文件存在=跳过**(断点,借 Metaflow resume 思想);失败中止写 failed_step 锚点;页面映射 src-dir/N.jpg → page_idx=N-1。
2. **工位契约** `scripts/01_detect.py`(koharu comic-text-detector → detection.json)、`scripts/02_ocr.py`(local_ocr_batch For-Manga → canon_text.json,crop 按 region_id.png 命名供评审③)。
3. **step tracing** `src/amta/pipeline_log.py`(借 OTel span 思想):run_id + git_head + 每步 span(step/page/status/input/output/duration),append 不覆盖,落 state/pipeline_log.json。
4. **LLM 观测** 03 --trace(借 LiteLLM 日志思想):每轮 messages roles + tool_calls 摘要 + content 前 200 字,落 trace_<page>.json。
5. **get_context 升级**:读 state_dir/../artifacts/translation.json(前页产物),回退旧路径。

## Consequences

- ✅ 1 页冒烟通过(单翼 1.jpg):01 8 boxes(与评测一致)→ 02 8 regions(156s)→ 03 8/8 译文零残留(40s)→ 评审 8/8 pass(58s);trace 记录 2 轮 lookup_term 调用;断点续跑验证(01 重跑 skipped)。
- ✅ 零新增依赖(requests/pillow 不变);fastcheck 144 全绿。
- ⚠️ 02 OCR 单页 156s(CPU),41 页整本约 2h+;检测框偶发合并(如 u01 含两段文字)。
- ⚠️ 下一步(handoff 2026-08-26):1-10 页评测产物转正为流水线布局、11 页起续翻验证 state 跨页累积、get_context 前页回溯、工单通知;LiteLLM 3+ 供应商时再考虑;Pydantic schema 膨胀时再考虑。
