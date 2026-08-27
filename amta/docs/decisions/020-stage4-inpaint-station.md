# 020 — Stage 4 inpaint 工位:koharu lama-manga 链路 + 探针定案

## Context

- Stage 4（Mask/Inpainting）工位需要基于 ADR-019 的 category 三级分类做擦除（dialogue_bubble 白底直填 bypass / overlay_text+sfx mask+inpaint）。
- 引擎选型：koharu v0.59.1 内置 lama-manga（CPU-only 唯一现实选择，CLAUDE.md 定案）；koharu 文档未明示 mask 上传/结果取回契约 → **2026-08-27 探针实测定案**（`docs/superpowers/plans/2026-08-27-stage4-probe-findings.md`）。

## Decision

1. **koharu inpaint 链路（探针定案）**：
   - mask role：`segment` + `bubble` **双 mask 都要**（lama-manga ENGINE_NEEDS = SegmentMask + BubbleMask，缺一 completed_with_errors）
   - mask payload：**PNG 编码字节**（`Image.save(BytesIO, "PNG")`；裸像素 400）
   - 步骤：`run_pipeline([page_id], ["lama-manga"])` 即够（无需先跑 bubble 分割），~20s（400×600 CPU）
   - 结果取回：**弃 export**（400/422，需 renderer 节点）→ `get_page_nodes` 找 `kind.image.role == "inpainted"` 节点 → `get_blob` → **WEBP 字节**，PIL 转换
2. **客户端封装**：`KoharuClient.run_inpaint(page_id, masks: dict[role, png], engine="lama-manga", steps=None, timeout=1800)`（上传全部 masks → run_pipeline → wait_operation）+ `fetch_inpainted(page_id) -> bytes | None`。
3. **04_inpaint 工位**（scripts/04_inpaint.py）：`plan_inpaint`（纯函数，ADR-019 消费）→ fill_white 涂白 + 双 mask 聚合 → run_inpaint → fetch_inpainted 整页替换 → **重放 fill_white**（保险）→ `clean/<page>_clean.png` + `*_inpaint.json`（actions + checks: filled/inpainted/skipped/size_ok/**pixel_diff_ratio**）。
4. **机械检查口径**：pixel_diff_ratio = clean vs raw 像素差异比例（ImageChops.difference + histogram，>0 证明有擦除）。
5. **编排**：00_run_all `--with-inpaint`（ADR-021 一并落地）；断点 `*_inpaint.json` 存在即跳过。
6. **范围外**：sfx_triage（side_annotation/skip）仍延后；overlay_text 检测盲区补强仍为已知风险。

## Consequences

- 04 工位全链路可跑（单测 2 + 封装 4 + 策略 5 = 11 测试，fastcheck 192 全绿）。
- 05_typeset 消费 `clean/<page>_clean.png`（ADR-021），Stage 4→5 链路闭环。
- lama-manga 整页（2243×3465）耗时按面积外推 1-3 分钟/页，全 41 页约 1-2 小时（后续可考虑只 inpaint 局部 patch 加速——蓝图 Anime-LaMa 局部裁剪思路，本期不做）。
- 探针脚本 `scripts/probe_inpaint.py` 为一次性工具，用完删除（不入库）。
