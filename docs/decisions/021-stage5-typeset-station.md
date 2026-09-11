# 021 — Stage 5 排版工位:自研 Pillow 引擎 + node_id 关联契约

## Context

- Stage 4-6 蓝图（Gemini）Stage 5 Typesetting 要求自适应排版（椭圆内切折行/字号二分/避头尾/字体映射）。两路线：koharu 自带 renderer vs 自研 Pillow 纯算法引擎。
- 2026-08-27 架构讨论，Patrick 拍板 **Q1：自研 Pillow 引擎**（零依赖铁律 ADR-009/018，契约自控，可单测，不受 koharu 钉版约束）；**Q2：系统字体跑 MVP**（不下载不打包）。
- 契约前置：ADR-019（category/sub_tier/items/image_meta）。

## Decision

1. **引擎架构**：纯函数层（`typeset_engine.py`：方向决策/折行/避头尾/字号二分）+ 渲染层（`typeset_render.py`：横排居中/竖排单列/白描边）+ 字体注册表（`fonts.py`：4 级映射 + 降级链）+ 薄 CLI（`scripts/05_typeset.py`）。
2. **竖排漏洞修复落地**（spec §2）：`decide_direction` 对 `category == overlay_text` 强制竖排，无视 bbox 高宽比；其余按 H/W≥2.2 且字数≤6。
3. **bbox 关联零契约改动**：canon 无 bbox → 用 `canon.node_id → detection.blocks[].node_id` 关联（node_id 是检测器 UUID，空 OCR 跳过天然对齐）；缺失 → skip + 记 `skipped_no_bbox`。
4. **输出契约**：`*_typeset.json`（rendered_items: region_id/layout_direction/font_family/font_size/lines/stroke/anchor_pos + checks: rendered/translated/coverage_complete/overflow/skipped_no_bbox）+ `final/<page>_final.png`。断点续跑沿用"产物存在=跳过"。
5. **机械检查**：coverage（rendered == translated）+ overflow（字号触底 12px 且行内容 < 全文 → 记 region_id，交 Stage 6 反压）。
6. **编排接入**：00_run_all 新增 `--with-inpaint` / `--with-typeset`（顺带完成 Stage 4 计划 Task 5 的 04 接入；04/05 在语义评审+修复之后跑，保证译文修复后排版不陈旧）。
7. **字体映射**：dialogue→msyh.ttc（无描边）/ overlay·narration→simkai.ttf（2.5px 白描边）/ 呼喊（含！）→msyhbd.ttc / sfx→FZSTK.TTF；缺失降级 msyh.ttc→simhei.ttf，全缺抛 FontNotFoundError。

## Consequences

- fastcheck 181 全绿（新增 fonts 5 + engine 5 + render 3 + station 2 + runall 2 = 17 测试）。
- 05 工位输出为 Stage 6 QA 的直接输入（coverage/overflow 已内建）。
- 范围外：sfx side_annotation 旁注（等 sfx_triage）、多列竖排、任意多边形内切、字体打包分发。
- 与 Stage 4 关系：04 的 `*_clean.png` 是 05 输入；04 工位本体仍待 koharu 探针结论（rerun 后执行）。
