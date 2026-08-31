# Stage 3 翻译层极简重构

- **日期**: 2026-08-31
- **状态**: 待启动
- **分支**: `feature/stage3-minimal-translation`
- **前置**: ADR-024（深接口改造）、ADR-025（agent-memory）已合并 main
- **相关**: 2026-08-30 commit 分类复盘、4 个开源项目对照调研

---

## 1. 背景与问题

### 1.1 当前状态

Stage 3 翻译层从 08-26 开始堆叠 function calling 工具，最终形成：

- **5 个工具**: `lookup_term` / `get_context` / `lookup_image` / `mark_invalid` / `mark_duplicate`
- **3 层循环**: 规划 ReAct 循环（最多4轮）→ 翻译 ReAct 循环（最多6轮）→ 重试+二分拆分（最多3次）
- **预算枷锁**: `TERM_BUDGET=10` / `GET_CONTEXT_BUDGET=3` / `VISION_BUDGET=2` / `MAX_TOOL_ROUNDS=6` / `MARK_INVALID_BUDGET_RATIO=0.5`
- **judge + repair**: `page_judge.py` 决策循环 + `repair_failed.py` 自动修复

### 1.2 实际运行结果（08-30 晚）

| 指标 | 数值 |
|---|---|
| page_11 单页工具循环轮次 | 70 轮 |
| lookup_image 单页调用 | 33 次 |
| 15 个 commit 中擦屁股 commit | ~10 个（70→4→13→10 一路收紧预算） |
| u01/u02 噪声框 | 被标 invalid 直接留空，译文出洞 |
| 最近一次 A/B 跑（p15-19） | DeepSeek 402 Payment Required，余额被循环烧穿 |

### 1.3 根因诊断

**不是"工具造多了"，是把"规划"外包给了模型。**

铁证：`translate.py:75-92` 的 `extract_relevant_terms()`（mit 式代码端术语 prefetch）完整存在，但在 `translate.py:119-132` 的 `_prompt_parts()` 中被故意禁用，注释写明"由模型通过 lookup_term / get_context 工具按需获取"。代码端 1 分钟能做完的事，交给模型花 10 轮往返做。

同样，`translate_tools.py:211-255` 的 `_build_semantic_context()`（代码端读 artifacts 构建前页上下文）完整存在，但只在 `get_context` 工具被模型调用时才执行。

**先造病（禁用代码端 prefetch），再治病（加工具循环 + 预算枷锁）。**

### 1.4 开源对照结论

4 个成熟项目（manga-image-translator 10.4k★、koharu 5.4k★、BallonsTranslator 5.1k★、comic-translate 2.9k★）一致：

- **翻译阶段零 function calling、零工具、零循环**
- **渐进式披露由代码做，不由模型做**：mit 的 `extract_relevant_terms()` 代码端过滤后拼进 system message，`set_prev_context()` 字符串注入
- **lookup_image 在所有成熟项目中不存在**：mit 2stage 中图只在 Stage1 OCR 精修出现一次（整页图+OCR文本，temp=0.0），Stage2 纯文本翻译不看图
- **预算由代码执行，不靠模型自觉**：token 双向上限 + 按 token 组批 + 递归拆批 + 有界重试 + fallback 模型链

---

## 2. 完成通过基准（DoD）

以下全部满足才算完成，逐条可测量：

| # | 维度 | 基准 | 测量方式 |
|---|---|---|---|
| D1 | 每页 LLM 调用次数 | ≤ 3 次（VLM 1 + 翻译 ≤2 含重试） | trace 统计 |
| D2 | 工具调用次数 | 0 次 | 代码审查 + trace |
| D3 | 单页耗时 | ≤ legacy 版的 30% | page_11 对比实测 |
| D4 | 单页 token | ≤ legacy 版的 20% | page_11 对比实测 |
| D5 | 译文出洞率（空译文） | = 0%（invalid 框除外） | page_11-19 全量检查 |
| D6 | 术语一致性 | glossary_violations 数 ≤ legacy 版 | check_glossary 自动校验 |
| D7 | 人工质量评分 | page_11-19 抽查 ≥ 4/5 | 人工评审（用户+龙虾各打5页取平均） |
| D8 | 402 抗性 | 连续跑 20 页不触发 402 | 实测 |
| D9 | legacy 回退可用 | `--mode legacy` 输出与重构前一致 | 回归测试 |
| D10 | 现有测试通过 | 所有现有单元测试不破坏（legacy 符号保留 re-export） | pytest |

---

## 3. 目标架构

### 3.1 每页 2 次 LLM 调用，0 工具，0 循环

```
┌─────────────────────────────────────────────────────────────┐
│ 输入：CanonArtifact（Stage2 输出，baberu_text 单引擎）       │
│       + 整页原图路径（从 detection artifact 的 source 字段读） │
│       + work_state（terms/characters/relationships）          │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 调用① VLM（temperature=0.0）                                  │
│ 模型：qwen3.5-omni-plus（A/B 测试对比 deepseek-v4-flash-vision-exp）│
│ 输入：整页原图(base64) + 全页OCR文本列表(region_id|text)     │
│ 输出：结构化JSON                                                │
│   {                                                             │
│     "ocr_refinements":  {rid: corrected_text},   // OCR精修   │
│     "bubble_types":     {rid: "dialogue"|"narration"|"sfx"},│
│     "scene":            "室内·夜晚·两人对峙",     // 画境      │
│     "invalid_regions":  [rid, ...],               // 无效框    │
│     "duplicate_regions": {rid: duplicate_of}      // 重复框    │
│   }                                                             │
│ 失败处理：VLM调用失败 → 用 baberu_text 原样继续，不重试        │
│         （VLM是增强不是依赖，失败不阻塞）                       │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 代码端 prefetch（零LLM，纯本地计算）                           │
│ ① extract_relevant_terms(当前页文本, work_state.terms)       │
│   → 拼 "term→translation" 进 system message                   │
│ ② build_semantic_context(前3页artifacts)                      │
│   → 拼前页译文（带category标注）进 user message                │
│ ③ 用 VLM 精修后的文本替换 baberu_text                          │
│ ④ 过滤 invalid_regions（不翻译，译文为空）                     │
│ ⑤ 标记 duplicate_regions（翻译后继承原框译文）                 │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 调用② LLM（temperature=0.3）                                  │
│ 模型：deepseek-v4-flash                                       │
│ System：翻译角色 + 相关术语表 + 画境描述 + 输出格式说明        │
│ User：前页上下文 + 当前页 region_id|精修后文本                │
│ 输出：{rid: 译文}                                              │
│ 后处理（确定性，零LLM）：                                       │
│   parse_translation_response() → JSON解析                     │
│   mechanical_guardrails() → 结构校验（无漏无重）              │
│   失败 → 重试1次 → 仍失败 → 二分拆分 → 单框失败保留原文       │
│   duplicate_regions → 继承原框译文                             │
│   invalid_regions → 译文为空                                   │
│   japanese_residue_check() → 残留检测（仅记录，不重试）       │
│   check_glossary() → 术语一致性（仅记录，不重试）             │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 输出：TranslationArtifact（schema_version="2.1"，契约不变）   │
│   {translations, residue, glossary_violations}               │
│   + 可选 vlm_refine 字段（记录VLM精修结果，供调试）           │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 调用预算对比

| 指标 | 当前（最坏） | 极简版 | 降幅 |
|---|---|---|---|
| 每页 LLM 调用 | 1(规划) + 3(重试)×6(轮) = 19次 | 2次 | 90% |
| 每页工具调用 | 3×6×(10+3+2) = 270次 | 0次 | 100% |
| 每页 VLM 调用 | lookup_image 最多 2×3×6 = 36次 | 1次（整页） | 97% |
| 循环/轮次 | 2层 ReAct（规划4轮 + 翻译6轮） | 0循环 | 100% |

---

## 4. 开源对照与抄取清单

**原则：能抄不写。每个组件必须有开源来源，amta 已有的资产直接恢复使用。**

### 4.1 抄取映射表

| amta 组件 | 抄取来源 | 来源实现方式 | amta 现状 | 动作 |
|---|---|---|---|---|
| 代码端术语 prefetch | **mit** `extract_relevant_terms()` | 代码端从原文提取相关术语→拼"term->translation"进 system message | `translate.py:75-92` 已完整实现，被 `_prompt_parts()` 禁用 | **恢复使用**，不重写 |
| 前页上下文注入 | **mit** `set_prev_context()` | 前后页已译文本字符串注入 system message | `translate_tools.py:211-255` `_build_semantic_context()` 已实现，仅工具内调用 | **提取为公开函数** `build_semantic_context()`，翻译前自动调用 |
| 整页一次翻译调用 | **koharu** `TranslationRequest::new(segments, target)` + `Translator.translate()` | 整页收集 SourceText → 一次 TranslationRequest → 写回；已译不覆盖，"…"直接透传 | `translate_with_retry()` 骨架在，但默认带 tools | **新增 `translate_plain()`**，骨架复用 `_one()` 去掉 `run_tool_loop`，直接 `llm(messages)` |
| 数量校验+二分拆分重试 | **mit** 数量校验+递归拆批（≤3层） | 格式校验（索引缺/重/错就重试）→ 不行就递归拆批 | `translate.py:264-269` 二分拆分已实现 | **复用**，max_retries 从 3 降到 1 |
| JSON 索引完整性校验 | **mit** 格式校验 | 索引缺/重/错检测 | `parse_translation_response()` + `mechanical_guardrails()` 已实现 | **复用** |
| 整页图 VLM OCR 精修 | **mit** 2stage Stage1 | 整页图+OCR文本，一次 VLM，temperature=0.0；图只出现一次 | `stage3_planner_vision.py` 有 VLM 调用基础设施（`load_page_image_base64`），但是规划循环不是精修 | **新增 `vlm_refine_page()`**，复用图加载，重写 prompt 和解析（精修+分类+画境+invalid/duplicate） |
| 翻译缓存 | **comic-translate** 块级源文匹配复用 | 源文 hash 作键，源文变才重翻 | `translate.py:95-116` `TranslationCache` 已实现 | **恢复使用**（如果之前被禁用的话） |
| 标点-only 译文跳过 | **comic-translate** 标点-only跳过不重绘 | 标点-only 译文直接跳过 | 未实现 | **可选**，非核心，后续优化再加 |
| fallback 模型链 | **mit** fallback 模型链 | 主模型失败→备用模型→原文透传 | 未实现 | **暂不实现**，留作后续优化 |
| token 上限+有界重试 | **mit** token 双向上限（入4096/出8192）+ 每类失败有界重试（2~3次） | 代码端强制执行 | 未实现 token 上限，重试上限有 | **暂不实现 token 上限**，重试上限用 max_retries=1；后续按页大小加 |

### 4.2 amta 已有的可复用资产（不重写）

| 资产 | 位置 | 用途 |
|---|---|---|
| `extract_relevant_terms()` | `translate.py:75-92` | 代码端术语过滤 |
| `TranslationCache` | `translate.py:95-116` | 翻译缓存 |
| `parse_translation_response()` | `translate.py:207-217` | JSON 解析 |
| `translate_with_retry()` 的 `_one()` 骨架 | `translate.py:250-270` | 重试+二分拆分骨架 |
| `_build_semantic_context()` | `translate_tools.py:211-255` | 代码端前页上下文构建 |
| `mechanical_guardrails()` | `guardrails.py:15-28` | 结构校验 |
| `japanese_residue_check()` | `guardrails.py:31-40` | 日文残留检测 |
| `check_glossary()` | `glossary.py:12-44` | 术语一致性校验 |
| `load_page_image_base64()` | `stage3_planner_vision.py:49-57` | 整页图加载 |
| `chat_client.chat_text()` | `chat_client.py` | 纯文本 LLM 调用 |
| `chat_client.chat()` | `chat_client.py` | 带 tools 的 LLM 调用（VLM 用） |

### 4.3 需要新写的最小集

| 组件 | 文件 | 行数估算 | 说明 |
|---|---|---|---|
| `vlm_refine_page()` | 新文件 `stage3_minimal.py` | ~80 行 | VLM 整页精修调用 + prompt 构建 + JSON 解析 |
| `build_prefetch_context()` | 新文件 `stage3_minimal.py` | ~50 行 | 组装术语+上下文+应用VLM精修结果（调用现有函数） |
| `translate_plain()` | `translate.py` 新增 | ~40 行 | 纯文本一次调用 + 重试1次 + 二分拆分（复用 `_one()` 骨架去掉 tools） |
| `translate_page_minimal()` | 新文件 `stage3_minimal.py` | ~60 行 | 极简翻译入口（VLM→prefetch→translate→护栏） |
| VLM A/B 测试脚本 | `scripts/spike_vlm_refine.py` | ~100 行 | spike 阶段对比 qwen vs deepseek vision |

**总计新写 ~330 行，复用现有 ~800 行。**

---

## 5. Spike 方案（先验证再全量）

### 5.1 Spike 目标

验证最大的未知项：**VLM 整页精修能不能稳定输出结构化 JSON，精修质量行不行，画境描述有没有用。**

### 5.2 Spike 范围

- 单页：page_11（之前跑出 70 轮循环的那个页，最有代表性）
- 两个 VLM 模型 A/B 对比：
  - A: `qwen3.5-omni-plus`（走 DashScope，`.env` 已配）
  - B: `deepseek-v4-flash-vision-exp`（走 DeepSeek，旧代码用过）
- 输入：page_11 整页原图 + page_11 canon 的 baberu_text 列表
- 输出：结构化 JSON（ocr_refinements / bubble_types / scene / invalid_regions / duplicate_regions）

### 5.3 Spike 通过标准

| # | 标准 | 测量 |
|---|---|---|
| S1 | JSON 可解析率 ≥ 90% | 每个模型跑 3 次，至少 2 次返回合法 JSON |
| S2 | OCR 精修有正面效果 | 精修后文本 vs baberu_text，人工抽查 5 个框，精修更准确的 ≥ 3 个 |
| S3 | invalid/duplicate 标记合理 | 人工检查标记的框，误标率 ≤ 20% |
| S4 | 画境描述非空且相关 | scene 字段非空，且与页面内容相关 |
| S5 | 单次调用耗时 ≤ 30 秒 | wall time |

### 5.4 Spike 产出

- `scripts/spike_vlm_refine.py`：可复现的 spike 脚本
- `output/reports/spike-vlm-refine-page11.md`：A/B 对比报告，包含两个模型的原始输出、解析结果、人工评分、推荐结论
- 决策：选定主 VLM 模型（或两个都保留为可配置）

### 5.5 Spike 不做的事

- 不实现 `translate_plain()`
- 不实现 `build_prefetch_context()`
- 不改 `translate_station.py` / CLI
- 不跑全量页

**Spike 通过后才进入全量实现。** 如果 Spike 失败（VLM 无法稳定输出结构化 JSON），回退方案：跳过 VLM 精修，直接用 baberu_text 做纯文本翻译（调用② alone），invalid/duplicate 标记暂时不做（用 Stage 1 的 category 推断）。

---

## 6. 实施切片

### Phase 0：Spike（预计 0.5 天）

1. 写 `scripts/spike_vlm_refine.py`
2. 跑 page_11，A/B 对比 qwen vs deepseek vision
3. 产出对比报告，选定主模型
4. **门控**：Spike 通过标准 S1-S5 全部满足才进入 Phase 1

### Phase 1：核心实现（预计 1-2 天）

1. **新增 `src/amta/stage3_minimal.py`**
   - `VlmRefineResult` dataclass
   - `vlm_refine_page(canon, raw_image_path, llm_vlm) -> VlmRefineResult | None`
   - `build_prefetch_context(canon, work_state, state_dir, vlm_refine) -> dict`
   - `translate_page_minimal(work_id, canon, ...) -> TranslationArtifact`

2. **修改 `src/amta/translate.py`**
   - 新增 `translate_plain(canon, llm, ...) -> dict[str, str]`（纯文本，无 tools，重试1次+二分拆分）
   - 修改 `_prompt_parts()`：恢复术语注入（调用 `extract_relevant_terms()`）和上下文注入
   - 保留 `translate_with_retry()` 作 legacy（加注释）

3. **修改 `src/amta/translate_tools.py`**
   - `_build_semantic_context()` 改名为 `build_semantic_context()`（去掉下划线，公开）
   - 保留其余作 legacy

4. **修改 `src/amta/translate_station.py`**
   - `translate_page()` 新增 `mode: str = "minimal"` 参数
   - `mode=="minimal"` → 调 `stage3_minimal.translate_page_minimal()`
   - `mode=="legacy"` → 走现有路径（with_plan / with_vision_plan / 默认工具循环）
   - 保留护栏/suggestions/failure_log 在 minimal 分支也执行

5. **修改 `scripts/03_translate.py`**
   - 新增 `--mode minimal|legacy`（默认 minimal）
   - 新增 `--raw-image`（可选，VLM 精修原图路径；不传时从 detection artifact 的 source 字段读）
   - `--with-plan` / `--with-vision-plan` 仅在 `--mode legacy` 时生效

### Phase 2：legacy 标记（预计 0.5 天）

1. 以下文件加文件头注释 `# legacy: 保留供 --mode legacy 回退，稳定后删除`：
   - `src/amta/translate_tools.py`（工具机）
   - `src/amta/stage3_planner.py`（文本规划循环）
   - `src/amta/stage3_planner_vision.py`（VLM 规划循环，`load_page_image_base64` 被 minimal 复用）
   - `src/amta/page_judge.py`（judge）
   - `scripts/repair_failed.py`（repair）
   - `scripts/06_page_judge.py`（judge CLI）

2. **不删除任何文件**。稳定运行 3 个 work 后，单独提 commit 删除。

3. 关闭 Stage 2 VLM 批量校验：`ocr_station.py` 默认 `vlm_enabled=False`（用户裁决："vlm单框和瞎子没区别"）。canon 变成单引擎（只有 baberu_text），翻译 prompt 去掉 `[VLM]` 分支。

### Phase 3：验证（预计 1 天）

1. 单页验证：page_11 跑 minimal vs legacy，记录耗时/token/调用次数/译文质量
2. 小批量验证：page_11-19 跑 minimal，统计出洞率/术语一致性/人工评分
3. 402 抗性：连续跑 20 页
4. legacy 回退验证：`--mode legacy` 跑 page_11，确认输出与重构前一致
5. 现有测试：`pytest` 全量通过
6. **门控**：DoD D1-D10 全部满足

### Phase 4：合并与清理（验证通过后）

1. 合并 `feature/stage3-minimal-translation` → `main`
2. 写 ADR-026：`docs/decisions/026-stage3-minimal-translation.md`
3. 稳定运行 3 个 work 后，单独提 commit 删除 legacy 文件

---

## 7. VLM A/B 测试方案

### 7.1 测试设计

| 维度 | A 模型 | B 模型 |
|---|---|---|
| 模型名 | `qwen3.5-omni-plus` | `deepseek-v4-flash-vision-exp` |
| base_url | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `https://api.deepseek.com` |
| api_key | `DASHSCOPE_API_KEY`（`.env` 已配） | `CHAT_API_KEY`（`.env` 已配） |
| 温度 | 0.0 | 0.0 |
| 输入 | 整页图 base64 + 全页 OCR 文本列表 | 同左 |
| 输出格式要求 | 严格 JSON，含 ocr_refinements/bubble_types/scene/invalid_regions/duplicate_regions | 同左 |
| 跑次 | 每模型 3 次（观察稳定性） | 同左 |

### 7.2 评判维度

| # | 维度 | 权重 | 测量方式 |
|---|---|---|---|
| A1 | JSON 可解析率 | 30% | 3 次中返回合法 JSON 的次数 |
| A2 | OCR 精修准确率 | 25% | 人工抽查 5 个框，精修更准确的比例 |
| A3 | invalid/duplicate 误标率 | 20% | 人工检查所有标记，误标比例（越低越好） |
| A4 | 画境描述质量 | 15% | 人工评分 1-5（是否非空、相关、有翻译参考价值） |
| A5 | 单次调用耗时 | 10% | wall time（越低越好） |

### 7.3 决策规则

- 综合得分 = A1×0.3 + A2×0.25 + (1-A3)×0.2 + A4×0.15 + (1/耗时归一化)×0.1
- 得分高者为主模型，另一个保留为可配置备选
- 如果两者 JSON 可解析率都 < 50%，Spike 失败，启用回退方案（跳过 VLM 精修）

---

## 8. 兼容与回滚

### 8.1 向后兼容

- **artifacts 契约不变**：`TranslationArtifact` schema_version 仍为 `"2.1"`，`translations`/`residue`/`glossary_violations` 字段不变。新增 `vlm_refine` 为可选字段
- **CLI 向后兼容**：`03_translate.py` 所有旧参数保留，新增 `--mode` 默认 `minimal`，旧脚本不传 `--mode` 自动走极简版
- **Python API 向后兼容**：`translate_page()` 新增 `mode` 关键字参数有默认值。`translate_with_retry()` / `run_tool_loop()` / `TOOLS_SCHEMA` 等符号保留 re-export
- **work_state 格式不变**：`terms`/`characters`/`relationships` 等 key 不变
- **state_dir 状态不变**：`failure_log.json` / `open_questions.json` / suggestions 格式不变，minimal 和 legacy 都读写相同文件

### 8.2 回滚方案

| 粒度 | 方式 | 操作 |
|---|---|---|
| 运行粒度 | `--mode legacy` | 任何一页/一个 work 出问题，CLI 加 `--mode legacy` 立即切回旧工具循环，无需改代码 |
| 代码粒度 | `git revert` | revert 本次重构 commit，`--mode` 参数移除，默认回到旧路径。旧代码未删除，revert 后直接可用 |
| 在途工作 | 状态不断裂 | state_dir 中的文件格式不变，切换 mode 不产生状态断裂；已生成的 translation artifact 不受影响 |
| artifacts 重跑 | 删除后重跑 | 如需用 legacy 重跑某页，删除该页的 `page_*_translation.json` 后用 `--mode legacy` 重跑 |

---

## 9. 验证方案

### 9.1 单元测试（新增）

| 测试 | 覆盖的错误机制 |
|---|---|
| `test_vlm_refine_page_parse_valid_response` | VLM 返回合法 JSON 时正确解析 5 个字段 |
| `test_vlm_refine_page_invalid_json_fallback` | VLM 返回非法 JSON/超时/402 时返回 None，调用方用 baberu_text 继续 |
| `test_build_prefetch_context_terms_injected` | `extract_relevant_terms()` 过滤后的术语正确拼进 system message |
| `test_build_prefetch_context_prev_pages` | 前3页 artifacts 存在时上下文正确注入，不存在时优雅降级 |
| `test_build_prefetch_context_vlm_refine_applied` | VLM 精修结果正确替换文本，invalid 被过滤，duplicate 被标记 |
| `test_translate_plain_no_tools` | `translate_plain()` 不传入 tools，直接调用 `llm(messages)`，不进入 `run_tool_loop` |
| `test_translate_plain_retry_once_on_guardrail_fail` | mechanical_guardrails 失败时重试1次，仍失败时二分拆分 |
| `test_translate_plain_duplicate_inherit` | duplicate_regions 译文正确继承原框 |
| `test_translate_page_minimal_artifact_contract` | 输出符合 TranslationArtifact schema |

### 9.2 集成验证（真实运行）

| 验证项 | 方法 | 通过标准 |
|---|---|---|
| 单页耗时对比 | page_11 minimal vs legacy | minimal ≤ legacy 的 30%（D3） |
| 单页 token 对比 | 同上 | minimal ≤ legacy 的 20%（D4） |
| 单页调用次数 | trace 统计 | ≤ 3 次（D1） |
| 译文出洞率 | page_11-19 全量检查 | = 0%（D5） |
| 术语一致性 | check_glossary | violations ≤ legacy（D6） |
| 人工质量评分 | page_11-19 抽查 | ≥ 4/5（D7） |
| 402 抗性 | 连续跑 20 页 | 不触发（D8） |
| legacy 回退 | `--mode legacy` 跑 page_11 | 输出与重构前一致（D9） |
| 现有测试 | pytest 全量 | 通过（D10） |

---

## 10. 开放问题

| # | 问题 | 状态 | 阻塞 |
|---|---|---|---|
| O1 | VLM 模型最终选 qwen 还是 deepseek vision | Spike 后定 | Phase 1 |
| O2 | Stage 2 VLM 关闭后，现有依赖 vlm_text 的测试/脚本是否需要调整 | Phase 2 验证 | Phase 2 |
| O3 | `TranslationCache` 是否之前被禁用、需要恢复接线 | 实施时确认 | Phase 1 |
| O4 | 整页图 base64 的 token 成本（取决于图片分辨率） | Spike 时测量 | 不阻塞，超预算则压缩图片 |
| O5 | 二分拆分后的子批是否仍注入完整上下文 | 实现时明确：子批共享同一份 system+prefix，仅当前页文本块变化 | 不阻塞 |
| O6 | legacy 文件稳定运行 3 个 work 后的删除时机 | 合并后跟踪 | 不阻塞 |

---

## 11. 不做的事（明确边界）

- **不实现** fallback 模型链（mit 有，但 amta 当前不需要，留后续）
- **不实现** token 双向上限（mit 有，当前用 max_retries=1 + 二分拆分足够，留后续按页大小加）
- **不实现** 标点-only 译文跳过（comic-translate 有，非核心，留后续）
- **不删除** legacy 文件（稳定后再删）
- **不改** Stage 1 检测（4-detector 并集，已验证）
- **不改** artifacts 契约层（schema_version="2.1" 不变）
- **不碰** Stage 4 inpaint / Stage 5 typeset
- **不碰** memory 系统（agent-memory 已合并，独立运行）
