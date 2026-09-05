# Stage 4 探针总结与决策记录

> **日期**：2026-09-03
> **分支**：`feat/stage4-ctd-mask-probe`
> **状态**：框内字涂白已验证，框外字 inpaint 待修复 bug 后验证

---

## 一、探针背景

前三个 stage（detect → OCR → translate）已稳住，进入 Stage 4（擦除/inpaint）。
目标：验证 text segmentation + inpainting 的最佳方案。

---

## 二、实验与发现

### 2.1 CTD DBNet 像素级 Mask 探针（已否决）

**假设**：CTD 模型的 DBNet 热图可以生成像素级文字 mask，精确擦除文字不碰背景。

**实验**：用 CTD 模型跑 21.jpg、22.jpg，取 DBNet shrink_map，阈值化+膨胀生成 mask。

**发现**：
- CTD 的 DBNet 对**气泡内文字**响应强，对**框外字零响应**（max=0.0005~0.0014）
- CTD 检测框粒度太细（每列竖排文字一个细竖条框），不适合做文本块检测
- CTD 对框外字检测召回率 0/8
- 原因：CTD 主要训练气泡内黑字白底，对网点背景、黑底白字、衣服上的字无泛化能力

**结论**：CTD 不适合 Stage 4，否决。

**产物**：
- `scripts/probe_ctd_mask.py`
- `scripts/gen_ctd_mask_report.py`
- `docs/stage4-ctd-mask-probe-report-2026-09-03.md`
- `output/tmp/ctd_mask_probe/`

### 2.2 框外字检测对比（RT-DETR-v2 vs CTD）

**发现**：
- RT-DETR-v2 对框外字召回率高，且有 bubble_type 分类
- CTD 对框外字几乎检测不到
- 确认检测器保持 RT-DETR-v2 不变

**产物**：
- `scripts/probe_overlay_text.py`
- `scripts/gen_overlay_report.py`
- `output/tmp/overlay_probe/`

### 2.3 端到端 Inpaint 探针（发现两个 Bug）

**假设**：矩形 mask + koharu lama-manga inpaint 可以处理框外字。

**发现两个 Bug**：

#### Bug 1: mask 黑白约定搞反了

- `04_inpaint.py` 的 `_build_mask()`：要修复区域=黑色(0)，其余=白色(255)
- koharu 实际约定：**要修复区域=白色(255)，其余=黑色(0)**
- 导致 mask 全白（没有要修复的区域），inpaint 什么都不做
- 验证：反色 mask 后 changed pixels 从 0 → 186,204，inpaint 正常工作

#### Bug 2: 分类映射断了

- `inpaint_strategy.py` 读 `category` 字段（dialogue_bubble/overlay_text/sfx）
- 但 `01_detect.py` 输出的 detection.json 只有 `bubble_type`（text_bubble/text_free）
- 导致所有框默认 `dialogue_bubble` → 全部涂白，框外字没走 inpaint

**修复后效果**：
- 矩形 mask + lama-manga inpaint 效果很好
- 文字完全擦除，网点背景/衣服纹理自然修复
- 不需要像素级 mask，矩形 mask 已够用

**产物**：
- `scripts/probe_e2e_inpaint.py`
- `scripts/gen_e2e_report.py`
- `output/tmp/e2e_inpaint/`

### 2.4 框内字涂白验证（已通过）

**实验**：5 页（page_10-14，对应 11-15.jpg），21 个 text_bubble 框涂白，15 个 text_free 框红框标注。

**结果**：
- 残字率 0.00%（所有涂白区域无非纯白像素）
- 无涂到框外的情况
- 框内字涂白完全可行

**产物**：
- `scripts/probes/probe_fill_white.py`
- `scripts/probes/gen_fill_white_report.py`
- `output/tmp/fill_white_probe/`

---

## 三、关键决策

| 决策 | 结论 | 理由 |
|------|------|------|
| 检测器 | 保持 RT-DETR-v2 | 框外字召回率高，有 bubble_type 分类 |
| 框内字处理 | 直接涂白 | 气泡本来就是白的，零副作用 |
| 框外字处理 | 矩形 mask + koharu inpaint | 效果已验证，不需要像素级 mask |
| CTD 像素 mask | 否决 | 对框外字零响应，过度设计 |
| inpaint 引擎 | 先用 lama-manga | 已验证有效，aot 待对比 |
| 分类体系 | text_bubble / text_free 两类 | 用户确认，简化设计 |

---

## 四、Stage 4 最终架构

```
Stage 4 输入: detection.json (bbox + bubble_type)
     ↓
按 bubble_type 分流:
  ├─ text_bubble → 矩形涂白 (气泡本来就是白的)
  └─ text_free → 矩形mask(要修复区域=白色) + koharu lama-manga inpaint
     ↓
输出: 干净页面 (原文擦除, 背景修复)
```

---

## 五、待修复的 Bug

1. **`04_inpaint.py` `_build_mask()`**：黑白约定反了，要修复区域应=白色
2. **`inpaint_strategy.py`**：分类映射应读 `bubble_type` 而非 `category`
   - text_bubble → fill_white
   - text_free → inpaint
3. **`04_inpaint.py` 调用 inpaint_strategy 时**：需要传入正确的字段映射

---

## 六、下一步计划

1. 修复上述两个 Bug
2. 跑 5 页（page_10-14）端到端验证：框内字涂白 + 框外字 inpaint
3. 对比 inpaint 引擎（lama-manga vs aot-inpainting），选最优
4. 写 ADR-021 记录 Stage 4 决策
5. 合并到 main

---

## 七、已知风险

1. 复杂背景（渐变、特效）上的框外字，inpaint 修复质量可能下降
2. 超大框外字区域（整页 SFX）可能需要分段处理
3. koharu inpaint 单并发，多页时是瓶颈
4. mask 膨胀量（pad）需要根据实际效果微调
