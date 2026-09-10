# AMTA · Stage 4-6 契约甄别执行指南（Spec，Patrick + 外部顾问最终决策 2026-08-27）

> **文档性质**：面向本地 AI 的 guidance 文档，指导 Stage 4-6（Mask/Inpainting → Typesetting → QA）的 Artifact 契约裁剪与实现。
> **依据**：stage4-6 blue master.html（Gemini 蓝图）+ 现状代码核查 + manga-image-translator 调研 + 架构讨论。
> **方法论**：Backward Reasoning（从下游硬依赖倒推上游必须持久化什么）

## 0. 核心原则

1. **磁盘契约是我们自己发明的超额配置**：业界标杆 manga-image-translator / BallonsTranslator 无磁盘 artifact 契约（内存对象传递，仅最终图落盘）。我们为断点续跑/step tracing/人工审查自创，已比业界多一个数量级可观测性。
2. **契约保持最小充分**：磁盘只放「下游硬依赖 + 断点续跑必需」字段，其余用时派生。蓝图是理想设计不是必须全跟。
3. **数据契约 ≠ 磁盘文件**：Artifact 本质是数据结构契约（schema），落盘是运行时可开关行为。运行时优先内存对象流转；需要缓存/调试/断点续跑时序列化写盘。

## 1. 12 个契约点甄别（已由 ADR-019 固化）

| # | 契约点 | 判定 | 状态 |
|---|--------|------|------|
| 1 | category 三级分类（dialogue_bubble/overlay_text/sfx） | **必须** | ✅ ADR-019 已落地 |
| 2 | sub_tier 贯穿传递 | **必须** | ✅ ADR-019 已落地 |
| 3 | region_id 编号统一（u00 起） | **必须** | ✅ ADR-019 固化约定 |
| 4 | 02_ocr 输出字段 regions→items | **必须** | ✅ ADR-019 已落地 |
| 5 | image_meta 宽高通道 | 建议 | ✅ ADR-019 已落地 |
| 6 | sfx_triage 枚举预留 | 延后 | schema 留枚举 {inpaint_and_render, side_annotation, skip}，判定逻辑 Stage 4 工位内 VLM 实现 |
| 7 | polygon 多边形 | 延后 | bbox 内切椭圆 + U-Net mask 够用，按需触发 |
| 8 | reading_direction | **砍掉** | typeset 用 bbox 高宽比现算 |
| 9 | candidates 多引擎 | **砍掉** | 语义评审已承担仲裁 |
| 10 | speaker | **砍掉** | work_state 术语表已覆盖 |
| 11 | char_count | **砍掉** | len() 现算 |
| 12 | state_updates | **砍掉** | suggestions + merge_suggestions 已有等价 |

## 2. 新发现漏洞（Stage 5 实现时修复）

**overlay_text 排版方向缺失**：原蓝图 H/W≥2.2 才竖排的逻辑对 overlay_text（压脸/框外字）失效——原图竖排日文会被输出成横排中文，无法覆盖狭长文字区域。修复：`category == overlay_text → 强制竖排`，其余沿用 bbox 逻辑。anchor_pos 以原文字区域中心为锚点。schema 零改动（category 已有）。
**次要**：sfx side_annotation 旁注坐标布局逻辑（Stage 5 配套实现）。

## 3. 执行阶段（Phase 2/3/4）

- **Phase 2（Stage 4 Mask/Inpainting）**：基于 category 擦除策略分支（气泡白底直填 / overlay+sfx mask+inpaint）；sfx_triage VLM 仲裁工位内做；overlay 检测盲区补强或确认兜底。
- **Phase 3（Stage 5 Typesetting）**：category==overlay_text 强制竖排分支；anchor_pos 锚点微调；sfx side_annotation 布局；sub_tier 主次风格分化；椭圆内切折行 + 字号二分 + 避头尾 + 4 级字体映射。
- **Phase 4（Stage 6 QA）**：机械检查（漏字/边界/格式）；VLM 语义评审复用；反压修复闭环（≤3 轮）。

## 4. 验证检查清单

- [ ] 01_detect 每个 region 有 category ∈ {dialogue_bubble, overlay_text, sfx}
- [ ] 02_ocr 输出字段 items（非 regions），每个 item 带 sub_tier
- [ ] canon_schema 校验通过（可选字段向后兼容）
- [ ] 同页 region_id 检测/OCR/翻译/排版各阶段一致（u00 起）
- [ ] overlay_text 排版强制竖排；dialogue_bubble 沿用 H/W 逻辑
- [ ] 断点续跑：删 translation 后可从未完成步骤继续
- [ ] 无 reading_direction/candidates/speaker/char_count/state_updates 字段

## 5. 一句话原则

> **磁盘契约只放「下游硬依赖 + 断点续跑必需」，其余用时派生；业界标杆连磁盘契约都没有，我们的已经比它多一个数量级的可观测性，够了。**
