# 11-20 页跑批问题日志（/loop 迭代记录）

> 跑批过程中发现的每个问题在此记录，含现象/根因/修复状态。每轮 /loop 回填。

## 未解决

（无）

## 未解决

- **00_run_all 不维护合并文件（已修）**：00_run_all 只写 per-page，不并入 `artifacts/translation.json`。**已修**：加 `_refresh_merged_translation`，每完成一页刷新合并文件；get_context 前页回溯始终可用。

## 已解决

- **修复后 semantic.json 残留旧快照误报（/loop 发现，已修）**：page_13_u08 / page_14_u00 被 auto_repair 修好（revisions source=auto-repair，译文正确），但 `semantic.json` failed 数组未随 repair 更新 → 误报仍显示 FAILED。根因：`repair_failed.run()` 只写 translation + needs_review，不回写 semantic。**修复**：run() 末尾把 repaired 区域从 semantic failed 移除并回写（更新 passed/pass_rate）。已跑产物 page_13/14 semantic 手动同步（导演终审确认译文正确）。测试 +1（semantic writeback 断言）。

- **get_context 合并文件缺口（已修）**：get_context 只读 `artifacts/translation.json`，1-10 页无此产物。**修复**：`backfill_1_10.py` 转正 1-10 页 + 生成合并文件；00_run_all 新增 `_refresh_merged_translation` 持续维护。合并文件现含 20 页 148 条。

## 观察记录（非问题，evidence）

- **baberu 提速实证**：run c8e151a5af9c page_10 02_ocr = **17.78s**（baberu auto），对比 1 页冒烟 run e359b7035932 02_ocr = 156.6s（For-Manga 全量）。~9× 提速，auto fast path 生效。
- **跨页 state + 前页回溯验证通过**：11-20 页每页 trace 均有真实 `get_context`（前页回溯，args `{"pages":3}`）+ `lookup_term`（术语/角色）工具调用（page_11: 9 次、page_15/18: 各 2 次）。合并 translation.json 含 20 页 148 条 → get_context 必然读到前页。方案 B 跨页 state 累积链路通。
- **11-20 跑批结果**：10 页全完整（detection/canon/translation/semantic 齐备）；语义评审 65/67 首轮 pass（page_13/14 各 1 FAILED 经 auto_repair 修复 + 导演终审确认正确）。

- **baberu 提速实证**：run c8e151a5af9c page_10 02_ocr = **17.78s**（baberu auto），对比 1 页冒烟 run e359b7035932 02_ocr = 156.6s（For-Manga 全量）。~9× 提速，auto fast path 生效。

## 已解决

