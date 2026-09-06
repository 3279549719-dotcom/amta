# 2026-09-06 orchestrator code-simplify 方案

## 目标

对管线编排器 `src/amta/orchestrator/` 做 code-simplify：**去重复、减少嵌套、接口清晰、复用公共函数**。
只做质量与结构改进，不 hunt bug、不扩功能、不改行为（纯重构）。由 `/simplify` 语义驱动，但按本仓 verify-first 文化先落方案再执行。

## 基底与范围

- **基底**：main @ 5a93768（artifact_cache 已集成进 pipeline），执行于 worktree `amta-wt-orchestrator-simplify`，分支 `feat/orchestrator-simplify`。
- **范围**：`src/amta/orchestrator/` 全包：
  - `pipeline.py`(290)、`registry.py`(187)、`context.py`(97)、`__init__.py`(44)
  - `adapters/`：detect(49) / ocr(59) / translate(96) / inpaint(66) / typeset(88)
- **不改**：工位 station 本体（`*_station.py`）、产物契约、registry 的语义（阶段名/依赖/默认值只可清死键）。
- **不进 main**：只推 branch；合 main 留给用户。

## 现状判断（一句话）

模块整体不烂、seam 清楚、接口小而统一（`run_pipeline(PipelineConfig) -> PipelineResult`，station = `fn(StationContext) -> StationResult`）。
真正的病点三处：主循环失败分支重复 + 嵌套深、fingerprint 每 stage 重复算、registry/adapters 默认值双份。其余为次要。

---

## P1 — 必做

### ① `pipeline.py`：失败处理写两遍 + 6 段 if/break 主循环
- 重复：`_resolve` 后的主循环里，**上游缺失**(4b) 与 **station failed**(4f) 两段 record+print+`page_failed`+`first_failure`+`break` 几乎同构。
- 嵌套：page-loop → stage-loop → 4a~4f，关键路径深 6~7。
- 改法：
  - 抽 `_run_stage(config, page_*, ctx_inputs, log, run_id, stage, out_path, force_rerun) -> StationResult`：内部完成 依赖检查 / cache 判断 / 调 station / 存指纹 / 记日志，**失败统一返回 failed 的 StationResult**（错误已含 "上游缺失" 或 station error）。
  - 主循环收敛：建 ctx → `_run_stage` → 收结果：`skipped` 继续、`failed` 记 page 失败并 break、`ok` 继续。
  - 抽 `_record_failure(page_key, stage, error, log, run_id, page_results)` 处理 first_failure/page_failed，删两处同构块。
  - 顺带：消除每 stage 重复 `get_stage()`（现 4 处：主循环 / `_build_context` / `_stage_code_paths` / cache 助手）——stage 对象主循环已取，传引用即可。

### ② fingerprint 每 stage 重复组装输入清单
- `_is_cache_fresh` 与 `_save_stage_fingerprint` 各自重算 `_stage_input_files` + `_stage_code_paths`；ok 路径下连续跑两个 = 同一 stage 组装两次。
- 改法：调用方算一次 `(input_files, code_files)`，两函数改收参数（或合成 `_refresh_stage_cache(stage, ctx, out_path)`）。纯局部，零行为。

### ③ 消灭「双份默认值」（默认在 registry 与 adapter 字面量各一份）
- registry `default_config` ↔ adapter `ctx.config.get(k, 字面量)` 成对重复，且 `_build_context` 已把默认合并进 `ctx.config` → adapter 回退是纯冗余 + 改一处漏一处=漂移：
  - detect `conf_threshold`：registry ↔ `adapters/detect.py`
  - ocr `engine`：registry ↔ `adapters/ocr.py`
  - inpaint `refine_mask`/`inpaint_engine`：registry ↔ `adapters/inpaint.py`
  - translate `vlm_enabled`：registry ↔ `adapters/translate.py`
- 改法：adapter 直读 `ctx.config["engine"]` 等（合并后必有），删字面回退。契约 docstring 注明「ctx.config = 已合并默认+覆盖」。

---

## P2 — 建议做

### ④ 上游依赖双重检查
- 编排器 4b 已用 `stage.consumes` 在进 station 前拦截缺失；adapter 内再各自 `ctx.inputs.get`→`if None: raise`（translate/typeset/inpaint/ocr 共 ~6 处）。
- 决策二选一：**(a)** 明确依赖保证唯一归属编排器 4b，删 adapter 层检查（typeset 4 连 raise 最啰嗦）；**(b)** 若担心直连 adapter 则保留但只在编排器层维护。默认倾向 (a)，删除时保留一条注释。

### ⑤ `out_path` 的 `None` 连带
- `artifact_paths(...).get(stage.produces)` 造出 `Path|None` → 连带 2 处 `out_path is not None` 卫语句。所有 stage 都设了 `produces`。
- 改法：改下标取 `[...]`（`artifacts.artifact_paths` 契约确认必有该键），删卫语句、收紧类型。

---

## P3 — 可选，克制（别为省 10 行牺牲可读）

### ⑥ adapters 样板
- 5 个 adapter try/perf_counter/StationResult 骨架同构但 body 各异。**只做最薄助手**：`_ok(...)`/`_failed(ctx, stage, t0, e)` 收 `perf_counter`+`type(e).__name__: ...[:200]` 那段；不做 `@run_station` 全装饰器（多一层间接、藏控制流，本仓工位逻辑值得显式）。

---

## 接口清晰附加观察（可顺手清，不改行为）
- ocr `default_config` 里的 `vlm_enabled`/`rule_filter`：adapter 实际只消费 `engine`——死配置键。确认后删或用起来（`vlm_enabled` 若确无消费者则删）。

## 回归网
- `tests/test_orchestrator_smoke.py`（7 测：basic / skip_existing / force_rerun / stage_failure_stops / missing_upstream / artifact_cache_fingerprint / artifact_cache_rerun_on_input_change）
- `tests/fakes.py`、`tests/test_refactor_shared.py`、`tests/test_koharu_inpaint.py`
- 消费方：`scripts/run_pipeline.py` / `scripts/smoke_test.py` / `runner.py`（只读接口，别破坏 `run_pipeline`/`get_stage`/`available_stages` 签名）
- 质量门：`py -3.13 scripts/fastcheck.py`（compile+ruff+pyright+pytest+depguard+memory）；pre-commit hook 会在 commit 时拦红。

## 落地顺序（每步独立 commit + fastcheck 绿）
1. ③ + ⑤（纯局部、零行为）+ 死配置键清理 → commit
2. ② fingerprint 一次组装 → commit
3. ① 抽 `_run_stage`/失败助手（主重构）→ commit，重点跑 test_orchestrator_smoke
4. ④ 依赖检查二选一 → commit
5. P3 ⑥ 视情况 → commit（可选）
6. 复核：`/simplify` 或 review 产出 diff

## 验收
- fastcheck ALL PASS 全程绿
- `test_orchestrator_smoke.py` 7/7 过
- orchestrator 包净减行数可度量；`pipeline.py` 主循环嵌套显著下降；无行为变更（run_pipeline 外部契约不变）
- 不夹带无关改动（不碰 station 本体 / 产物契约 / 其他包）
