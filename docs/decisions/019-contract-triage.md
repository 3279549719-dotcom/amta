# 019 — Stage 4-6 契约裁剪:category/sub_tier 契约 + 字段卫生

## Context

- Stage 4-6（Mask/Inpainting → Typesetting → QA）开工前，对 Gemini 蓝图（`reference/suggestion from other model/stage4-6 blue master.html`）的 12 个 artifact 契约点逐项甄别（Backward Reasoning：从下游硬依赖倒推上游必须持久化什么）。
- 关键事实：业界标杆 manga-image-translator / BallonsTranslator **无磁盘 artifact 契约**（内存对象传递，仅最终图落盘）。磁盘契约是我们为断点续跑/step tracing/人工审查自创，应保持**最小充分**：只存「下游硬依赖 + 续跑必需」，其余用时派生。
- 决策过程：2026-08-27 架构讨论（Patrick 定调"能现算的不存、能派生的不存、已有等价机制的不重复造"）。

## Decision

1. **category 三级分类（必须）**：01_detect 的 `bubble_type`（dialogue/narration/sfx/unknown）映射到 `category ∈ {dialogue_bubble, overlay_text, sfx}`。映射：dialogue/narration/unknown → dialogue_bubble（保守，避免误判 overlay 被错误 inpaint）；sfx → sfx；overlay_text 透传。保留原 `bubble_type` 字段（兼容）。category 只给 Stage 4 提供**初始擦除策略**，最终裁决留给 04 工位 VLM 仲裁。
2. **sub_tier 贯穿（必须）**：02_ocr 展平时把 `sub_tier`（primary/aside）透传到 canon 条目，供 05 typeset 主次排版分化。可选字段，无则不硬造。
3. **region_id 编号统一 u00 起（必须）**：流水线 02_ocr 已从 u00 起；评测历史数据 `translation_ocr_paddle_fc.json`（u01 起）为历史基准产物，不重命名（重命名会破坏已发布的 1-10 转正对比），只在本 ADR 固化约定。
4. **02_ocr 返回 doc 字段 `regions` → `items`（必须）**：消除与 01_detect 层级 `regions` 的撞名歧义（02 的 regions 实为扁平 canon 列表）。落盘文件本就是扁平 list，不受影响。
5. **image_meta（建议，已做）**：01_detect 输出 `{width, height, channels}`，一行成本，typeset 全局坐标映射用。
6. **砍掉不跟（5 项）**：reading_direction（typeset 用 bbox 高宽比现算）、candidates 多引擎（OCR 成本翻倍，语义评审已承担仲裁）、speaker（work_state 术语表已覆盖）、char_count（len() 现算）、state_updates（suggestions + merge_suggestions 已有等价）。
7. **延后（2 项）**：sfx_triage（schema 留枚举 `{inpaint_and_render, side_annotation, skip}`，判定逻辑 04 工位 VLM 实现）、polygon（bbox 内切椭圆 + U-Net mask 够用，按需触发）。
8. **新发现漏洞（Stage 5 实现时修复）**：overlay_text 排版方向必须**无视 bbox 高宽比强制竖排**（原蓝图 H/W≥2.2 逻辑对压脸字失效）；reading_direction 砍掉后由 `category + bbox` 现算——缺的是业务分支不是 schema 字段。

## Consequences

- canon 仍是扁平 `[{region_id, text, page, node_id?, category?, sub_tier?}]`，translation 仍是扁平 dict，无层级结构变化。
- fastcheck 164 全绿（新增 category 映射 4 测 + canon_schema 可选字段 3 测 + 02 透传/改名 1 测）。
- 未来 04/05 消费：DetectionArtifact.regions[].category + child_lines[].sub_tier + image_meta；CanonicalTextArtifact.items[].category/sub_tier。
- 落盘两级化（default 只落工作集 / debug 全量）未在本 ADR 范围，待 Stage 4-6 稳定后评估。
