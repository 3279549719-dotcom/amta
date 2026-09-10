# Stage 1-3 深接口改造设计（feat/stage123-deep-interfaces）

> 2026-08-30 · brainstorming 定案（Patrick 批准 B 案）· 词汇表遵循 codebase-design skill（module/interface/seam/adapter/depth）

## 背景与问题

Stage 1-3（01_detect → 02_ocr → 03_translate）的库层已有多个深模块（chat_client / geometry / koharu_blocks / runner / ocr_engines.ocr_batch），但**工位之间的接口是隐式的**：产物契约 = 散落在脚本里的 JSON 字段约定，没有单一事实源。审计（2026-08-30，全文见 AutoClaw workspace deliver/2026-08-30-amta-stage123-interface-audit.html）确认 8 项发现：

| ID | 级别 | 摘要 |
|----|------|------|
| F1 | P0 | 04_inpaint 读 `det["regions"]`，01 只写 `blocks`——测试 fixture 同错，真实链路 inpaint 恒空 |
| F2 | P0 | 02_ocr 双契约：落盘裸 list，函数返回带 `items` 的 doc；CLAUDE.md 宣称的 items 契约不在磁盘上 |
| F3 | P1 | region_id 双空间：01 分配 `u05`，02 重编 `page_5_u05`，`contained_in` 透传旧空间值 |
| F4 | P1 | env/.env 解析三处独立实现（translate / 02_ocr / ocr_engines） |
| F5 | P1 | 工位内联副作用：trace/raw_dump 落盘、suggestions 读写合并（曾出 4fc5037 崩溃）、failure log |
| F6 | P1 | 00_run_all 内联全部工位契约知识（文件名、断点判据、judge 决策语义） |
| F7 | P2 | trace/旁路产物命名不一致，无 owner |
| F8 | P1 | 03_translate.run() 10+ 参数，接口≈实现 |

## 目标

1. 产物契约单一事实源：`src/amta/artifacts.py`（schema + validate + load/save + 命名 + region_id 规则）。
2. 三个深工位模块：`detect_station` / `ocr_station` / `translate_station`，脚本退化为薄 CLI（CLI 参数名不变）。
3. 配置收敛：`src/amta/config.py` 唯一 env/.env 解析（修 F4）。
4. suggestions 逻辑唯一归属：`src/amta/suggestions.py`（提取 + 追加 + 合并，修 F5 一半）。
5. 00_run_all 减负：产物路径走 artifacts 契约；judge 决策语义移入 `page_judge.apply_decisions()`（修 F6）。
6. 契约回归护栏测试：01→02→03 假适配器全链，id/键一致性断言——契约再漂移时 fastcheck 直接红。

## 非目标（Patrick 裁决 2026-08-30）

- **Stage 4-6 消费方同步剔除**：04/05「text segmentation 等都没实质开发」，本次不管。04 读 `regions`（F1）、05 读 canon 裸 list 记为**已知陈旧消费方**，未来 Stage 4-6 实质开发时再修。
- 不改 subprocess 编排与「文件存在=跳过」断点语义（ADR-018 保留）。
- 不引外部依赖（TypedDict/dataclass，depguard 纪律）。
- benchmark / eval_stage1_robust 自有 emit 路径（1 基页码命名）不动。
- 不做旧磁盘产物回填（load_* 兼容读即可；断点续跑只看文件存在性）。

## 契约层设计（artifacts.py）

**统一信封**：`{work_id, page, schema_version, generated_at, ...payload}`；`schema_version` 起步 `"2.1"`（front3 2.0 → canon doc 化 + region_id 单空间）。

**页键与 ID 规则（唯一归属）**：
- `page_key(idx) = "page_{idx}"`（0 基，与 00_run_all / region_id / eval_stage2/3 对齐）
- `page_idx_from_raw(raw) = int(raw.stem) - 1`（`11.jpg` → 10）
- `region_id(idx, order) = "page_{idx}_u{order:02d}"`——全链单空间（修 F3）；`mark_contained` 的 `u` 编号由 `normalize_region_ids` 整体重命名（含 `contained_in` 值）。

**三种产物**：
- `DetectionArtifact`: `blocks[]`（region_id/bbox/category/sub_tier/bubble_type/node_id/text/source_engines/contained_in）+ `image_meta` + `n_boxes` + `per_engine_boxes` + `detect_steps`；doc["page"] 语义从「1 基 stem」改为页键 `"page_10"`。
- `CanonArtifact`: **doc 化定案**——`items[]`（region_id/bbox/baberu_text/vlm_text/vlm_status/contained_in/source_engines/page/category/sub_tier）+ `n_regions` + `vlm_status`（修 F2：磁盘与返回同形）。
- `TranslationArtifact`: 现形状 `{work_id, translations, residue, glossary_violations}` 保持，信封补 `page/schema_version`（加法变更）。

**load_\* = normalize + validate**：`load_canon` 兼容旧裸 list（`{"items": doc}`）；校验失败 raise ValueError（region_id 唯一非空 / 双引擎文本至少一个非空 / page int / category∈3 值 / sub_tier∈2 值——语义收编自 canon_schema.validate_canon，后者保留别名）。`load_detection` 校验 blocks 有 bbox。`load_translation` 校验 translations 为 dict。

**命名唯一归属（修 F6 文件名知识 / F7）**：`artifact_paths(artifacts_dir, page)` 给出 detection/canon/translation/semantic/judge/inpaint/typeset/needs_review/crops 全部路径；`trace_path(artifacts_dir, page, station)` 统一 `{page}_{station}_trace.json`；`write_trace(artifacts_dir, page, station, payload)` 盖章落盘。

## 三个深工位（接口与藏匿物）

```
detect_station.detect_page(work_id, raw_page, artifacts_dir, *, page_idx=None,
                           client=None, host, port) -> DetectionArtifact
  藏: KoharuClient 生命周期、4-detector 并集→compact→union→assign_category→
      mark_contained→normalize_region_ids、raw_dump 落盘、trace、image_meta
  接缝: client 注入（协议=现有 KoharuClient 方法面），测试用 FakeKoharu

ocr_station.ocr_page(work_id, det, raw_page, artifacts_dir, *, page_idx,
                     engine="auto", vlm_enabled=True,
                     ocr_fn=None, vlm_fn=None) -> CanonArtifact
  藏: 裁框（region_id 直接取 det blocks，缺省兜底重推）、ocr_batch 分发、
      VLM contact sheet、VLM key 解析（config）、双引擎合并、trace、save_canon
  接缝: ocr_fn/vlm_fn 函数注入（内部接缝，测试用 fake）

translate_station.translate_page(work_id, canon, *, state_dir=None,
                                 artifacts_dir=None, page=None,
                                 with_plan=False, with_vision_plan=False,
                                 trace_enabled=False, crop_dir=None,
                                 llm=None) -> TranslationArtifact
  藏: config、llm 闭包+观测、plan 双模式（text/vision）、translate_with_retry/
      translate_with_plan、residue/glossary 护栏、failure log、suggestions 提取+追加
  接缝: llm 函数注入（现有测试同款 fake 模式）
```

## 配套模块

- `config.py`: `get_chat_config()` / `get_vlm_api_key()`（VLM_API_KEY→CHAT_API_KEY→None）/ `get_dashscope_key()`；模块级 `_ENV_PATH = ROOT.parent / ".env"` 供测试 monkeypatch；translate/ocr_engines 保留 re-export 别名。
- `suggestions.py`: `SuggestionsExtractor`（片假名提取，translate 保留 re-export）+ `append_suggestions(state_dir, work_id, items)`（03 内联段收编）+ `merge_into_state(state, items)`（merge_suggestions.py 的 merge 收编，脚本留别名）。
- `page_judge.apply_decisions(judge_doc, sem_doc) -> {"repair": [rid], "tickets": [{region_id, reason, kind}]}`：纯函数，judge→repair/ticket 语义唯一归属；00_run_all 只执行。

## 消费方同步（仓内小改）

| 消费方 | 改动 |
|--------|------|
| 03_translate.py | 薄 CLI → translate_page |
| 01/02 脚本 | 薄 CLI → 各自 station |
| translate_semantic_check / repair_failed / apply_revisions | canon/translation 读取走 load_canon / load_translation |
| eval_stage2 | 载入走 load_canon，删除 isinstance 双形状防御 |
| eval_stage3 | 载入走 load_canon（原假定裸 list） |
| 00_run_all | 路径全走 artifact_paths；judge 段调 apply_decisions；_refresh_merged_translation 保留（有测试） |
| merge_suggestions.py | merge → suggestions.merge_into_state 别名 |
| 04_inpaint / 05_typeset | **不动**（已知陈旧，见非目标） |

## 测试策略（replace, don't layer）

- 新增 `test_artifacts` / `test_config` / `test_detect_station`（FakeKoharu）/ `test_ocr_station`（fake ocr/vlm）/ `test_translate_station`（fake llm）/ `test_suggestions` / `apply_decisions` 单测 / `test_contract_compatibility`（假适配器 01→02→03 全链：canon region_ids == detection blocks region_ids、contained_in ⊆ region_ids、translations keys ⊇ canon region_ids）。
- 迁移：test_pipeline_flow 的 02 用例断言从「盘上 list」改为「盘上 doc.items」；test_translate 的 `_ENV_PATH` monkeypatch 目标改 `amta.config`；test_front3_stage1/2/3 纯函数测试原样保留（geometry/vlm_verify/_current_block 未动）。
- 旧 disk 上裸 list canon 由 load_canon 兼容读；不做迁移脚本。

## 基线（worktree 实测 2026-08-30）

`py -3.13 -m pytest tests -q --basetemp output/logs/.pytest-basetemp` → **296 passed, 2 failed**：`test_audit_hygiene::test_duplicate_files_detected`、`test_get_context_ab::test_ab_comparison_real_data`——均依赖主仓 gitignored 真实数据，worktree 环境性失败，非本次回归，不修。前置目录 `output/logs/` 需手动建（basetemp 父目录，gitignored）。

## 风险与教训映射

- L19（pytest Windows 尾部噪音）：一律 `py -3.13` + `--basetemp output/logs/.pytest-basetemp`，看 N passed 不信 exit code。
- L26：PATH `python` 是 AutoClaw 解释器（无 pytest/ruff），必须 `py -3.13`。
- L27：OpenClaw 显示会脱敏 `api_key=`，改 config/translate 后须校验真实文件内容。
- L20：`_NN_*.py` 桥脚本保留（test_pipeline_flow 依赖其加载机制）。
- canon doc 化是唯一 breaking 点：消费方全在仓内且被护栏罩住；04/05 已按裁决豁免。
