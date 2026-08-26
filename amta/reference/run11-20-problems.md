# 11-20 页跑批问题日志（/loop 迭代记录）

> 跑批过程中发现的每个问题在此记录，含现象/根因/修复状态。每轮 /loop 回填。

## 未解决

（无）

## 未解决

- **跨页回溯缺口（get_context）**：`get_context`（translate.py L278）只读**合并单文件** `artifacts/translation.json`，但 00_run_all 写的是 per-page `page_N_translation.json` → 跨页前页回溯当前**不工作**（无合并文件）。**方案 B 转正已补**（backfill_1_10.py 生成合并文件，含 1-10 页 86 条）。
- **00_run_all 不维护合并文件**：00_run_all 只写 per-page `page_N_translation.json`，不会把新完成的页并入 `artifacts/translation.json`。若 get_context 依赖合并文件，跑批新增页不会自动反映到前页回溯 → 需 00_run_all 每完成一页更新合并文件，或 get_context 改为读 per-page。**待跑批完成后处理。**

## 观察记录（非问题，evidence）

- **baberu 提速实证**：run c8e151a5af9c page_10 02_ocr = **17.78s**（baberu auto），对比 1 页冒烟 run e359b7035932 02_ocr = 156.6s（For-Manga 全量）。~9× 提速，auto fast path 生效。

## 已解决

