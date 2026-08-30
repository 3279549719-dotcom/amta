# 024 — Stage 1-3 深接口改造：产物契约单一事实源 + 三深工位

> 2026-08-30 · Patrick 批准 B 案 · 前置 brainstorming 审计（AutoClaw workspace deliver/2026-08-30-amta-stage123-interface-audit.html）

## 背景（为什么）

Stage 1-3（01_detect → 02_ocr → 03_translate）库层已有深模块（chat_client / geometry / runner / ocr_engines），但**工位间接口是隐式的**：产物契约 = 散落在脚本里的 JSON 字段约定，无单一事实源。审计确认 8 项发现：

| ID | 级别 | 摘要 |
|----|------|------|
| F1 | P0 | 04_inpaint 读 `det["regions"]`，01 只写 `blocks`——inpaint 恒空 |
| F2 | P0 | 02_ocr 双契约：落盘裸 list，返回带 items 的 doc |
| F3 | P1 | region_id 双空间：01 分配 u05，02 重编 page_5_u05，contained_in 透传旧空间 |
| F4 | P1 | env/.env 解析三处独立实现（translate / 02_ocr / ocr_engines） |
| F5 | P1 | 工位内联副作用：trace/raw_dump、suggestions 读写合并、failure log |
| F6 | P1 | 00_run_all 内联全部工位契约知识（文件名、断点判据、judge 语义） |
| F7 | P2 | trace/旁路产物命名不一致，无 owner |
| F8 | P1 | 03_translate.run() 10+ 参数，接口≈实现 |

## 决策（怎么选，B 案）

1. **契约层单一事实源**：新增 `src/amta/artifacts.py`（TypedDict 信封 + 纯函数校验 + load_*/save_* + 文件命名 + 页键/region_id 规则）。`canon_schema.validate_canon` 改为 re-export 别名，语义不变。
2. **三个深工位模块**：`detect_station.detect_page` / `ocr_station.ocr_page` / `translate_station.translate_page`，把编排副作用（trace/raw_dump/suggestions/failure log/配置解析）藏进实现，`01/02/03_translate.py` 退化为薄 CLI（CLI 参数名不变）。
3. **配置收敛**：`src/amta/config.py` 唯一 env → .env 回退解析（env 优先、双位置、引号剥离、不打印密钥）；translate / ocr_engines 保留 re-export 薄壳。
4. **suggestions 唯一归属**：`src/amta/suggestions.py`（SuggestionsExtractor + append_suggestions + merge_into_state）；merge_suggestions.py 委托。
5. **00_run_all 减负**：产物路径全走 `artifacts.artifact_paths`；judge 决策语义移入 `page_judge.apply_decisions` 纯函数。
6. **subprocess 编排与「文件存在=跳过」断点语义保留**（ADR-018 不动）。
7. **零外部依赖**：TypedDict/dataclass，depguard 纪律。

## 后果（影响）

**Breaking**：canon 落盘从裸 list 改为 doc 信封（schema_version "2.1"，含 items/n_regions/vlm_status）。仓内消费方全被护栏罩住；`load_canon` 兼容旧裸 list 读取，不做磁盘回填（断点续跑只看文件存在性）。

**豁免（Patrick 裁决）**：Stage 4-6 消费方（04_inpaint 读 regions、05 读 canon 裸 list）记为**已知陈旧消费方**，未实质开发，本次不动；未来 Stage 4-6 实质开发时再修。

**护栏位置**：契约再漂移即 fastcheck 红——
- `tests/test_contract_compatibility.py`：01→02→03 假适配器全链，canon region_ids == detection blocks region_ids、contained_in ⊆ region_ids、translations keys ⊇ canon region_ids、盘上 doc 信封。
- 各工位单测（test_detect_station / test_ocr_station / test_translate_station）用 fake adapter / fake llm，无真实 koharu server。
