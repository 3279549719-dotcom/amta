# 016 — Translate Harness 对齐 GPT 设计：Guardrails 补全 / Eval 四维 / Tools / State 四层 / 验收阈值

## Context

- ADR-014 落地了翻译工位的"最小子集"：机械护栏 ①② + 语义护栏 ③（粗筛）+ 分层 Loop + suggestions。
- 实现后与 `reference/html by GPT/translation_harness_recommended_design.html`（Translation Harness 设计）逐条对照审计，发现现状是"已落地的子集"，而非设计全貌。
- **方法论修正**：以 GPT 设计为基准评估差距，**不以现有实现放行**——已有代码只算"已做到 X"，不构成"该有 Y 但可以不做"的理由。
- grill-me 定案：四维评分全量合并进同一次 ③ 调用（不当闸门）、恢复三工具 + Tool Contract、work_state 加 observed 层、判例库替代参考译文 Golden Set、验收阈值 ≥90% + 导演清 FAILED。

## Decision

### 1. Guardrails 6 类 × Soft/Hard/Lifecycle 全量清单

| 约束 | GPT 要求 | 现状（ADR-014 后） | 本 ADR 落地 |
|---|---|---|---|
| **Input**（硬） | pre-translate：page_id/text_id/坐标/原文候选存在 | 03 直接读文件，零校验 | 新增 `validate_canon()`（canon_schema.py），03 前置 gate |
| **Output**（硬） | 每 text_id 必有译文；不得凭空产生 | `mechanical_guardrails` ① region_id 一一对应 | 保留（唯一完整条目） |
| **Knowledge**（硬） | 已确认 canon 译名不得静默改写 | 仅 system prompt 软约束 | 新增 `check_glossary()`（glossary.py） |
| **Tool**（硬） | Tool Contract：按需查、限制调用 | 无工具、无契约（"脚本直读文件=无约束读"） | 恢复三工具 + Contract（见 §4） |
| **State Mutation**（硬） | 只能先 candidate/inferred，不能直接 canonical | status 分层有、无 commit gate | merge_suggestions 跨页一致才 confirmed |
| **Quality**（硬） | Consistency 违规/语义分低于阈值不得通过 | ③ 只粗筛 Accuracy | Glossary Validator + 四维评分（监控） |

Lifecycle hook：pre-translate（T2/T3）、post-translate（既有 ①②）、on-failure（新增 record_failure）。

### 2. Eval 四维

- **Accuracy**：③ 粗筛升级为四维评分（accuracy/fluency/consistency/readability 1~5），**合并进同一次 VLM 调用**，成本几乎不增。
- **Consistency**：Glossary Validator（机械，最强）。Readability：归 05_typeset 工位边界（本 ADR 声明边界外）。
- **四维分数不当验收闸门**：③ 实测会漏检（语境润色）/误报（加"但"），是"粗筛+随机"性质；分数只作导演复核排序 + 趋势监控。验收闸门 = 机械全过 + ③ 通过率 + 导演终审。

### 3. Golden Set 形态

无参考 GT（同人无标准译文）→ 不建参考译文对照集；建**判例库 case-law**（`output/data/case_law.json`）：4 条实测样本 + 案例，标 verdict + 四维分 + reason + lesson，校准 ③ 与验收口径。

### 4. Tools 恢复 + Tool Contract

"脚本直读文件"本质是无约束读文件。恢复：
- **lookup_term**（本地 glossary 查当前页相关术语）、**get_context**（前 3 页译文）→ **预取式**（脚本先行注入 prompt，模型不主动调，成本≈0）。
- **vision**（OCR 冲突复查）→ 走 ③ 的 VLM 通道，**多轮按需**。
- **Contract**：`TERM_BUDGET=10`/页（预取术语上限）、`VISION_BUDGET=2`/页（token 控制，vision 调用最贵）。

### 5. State 四层

work_state 状态由三层（confirmed/inferred/candidate）**加 observed 层变四层**（observed/confirmed/inferred/candidate）：
- **observed**=直接从页面证据观察到（OCR/视觉，可信但可能看错）；**confirmed**=跨页一致/多方印证；**inferred**=推断；**candidate**=待定。
- 晋升：同一事实跨页再次 observed 且一致 → 自动升 confirmed；**导演可降级**（新证据可修正旧状态）。

### 6. Loop 分层

- 脚本机械层：retry+split（既有）+ on-failure 结构化落盘（`record_failure`，供 00_run_all 断点重跑）。
- 导演语义层：③ 拦出 FAILED → `apply_revisions` 应用导演修订 → `--only` 补跑重评审（Re-verify）→ **budget=1 轮** → 仍 FAILED 则 `needs_review` 终态（不无限循环）。

### 7. 验收阈值

**③ 通过率 ≥90% + 导演清 FAILED 队列**（判例库 acceptance 记录）。③ 的 FAILED=导演过目队列，非判决书。

## Consequences

- ✅ Guardrails 从"仅 Output 完整"补到 6 类全覆盖（Input/Knowledge/Tool/State Mutation 新增或补全）。
- ✅ Eval 四维有消费方：Consistency 机械、Accuracy ③、Fluency/Readability 靠判例 + 导演；分数监控不当闸门。
- ✅ Tools 有契约（TERM_BUDGET/VISION_BUDGET），vision token 受控。
- ✅ State 四层语义完整，observed→confirmed 自动晋升 + 导演降级。
- ⚠️ **修订 ADR-014 的"③ 是粗筛+随机"表述**：保留"粗筛+随机"性质判定，补充"四维评分=导演排序/监控、不当闸门"。
- ✅ 参考：实现见 `docs/superpowers/plans/2026-08-26-translate-harness-alignment.md`；判例库 `output/data/case_law.json`。
