# ADR-023 — 前三阶段（Detect/OCR/Translate）整体重构决策（2026-08-28）

> 背景：从 2026-08-27 起，围绕"漫画文字漏检"问题进行了多轮诊断和架构讨论。
> 根因链：4-detector 并集后处理（absorb_contained 丢弃嵌套框 + build_regions 分大小字 + flatten_regions 展平灭口大字）→ OCR 只读到碎片文本 → 翻译跟着错。
> 中间方案（02.5 pre-OCR VLM 校正）经 probe 验证不可行（VLM 会改错拟声词/短文本）。
> 本 ADR 记录最终重构方案：砍掉硬编码微观规则，守住边界不变量，把语义判断交给 LLM。

## 问题诊断

### 1. Detector 后处理误杀（上游根因）

当前 Stage 1 后处理链：
```
4-detector 并集 → union_blocks(IoU 0.5) → absorb_contained(IoA 0.75 直接丢弃)
  → build_regions(嵌套挂载 child_lines) → flatten_regions(展平子行送 OCR)
```

三层误杀：
- **absorb_contained**：IoA ≥ 0.75 的嵌套小框被直接丢弃。detector 检到了，但后处理扔了。
- **build_regions**：把子行框挂载到容器框下，输出 `{bbox, child_lines: [...]}` 结构。这是"分大小字"的源头。
- **flatten_regions**：展平时只输出 child_lines，容器框本身被丢弃。当子行覆盖率不足（如大字气泡只扫到 52px 小条），大字被灭口。

实测案例：
- 14.jpg「では豊ちゃん、輝夜様にこの羽根を見せに行ってきます」：容器 241px 宽，子行仅 46px，flatten 只输出 46px 子行，大字漏检。
- 15.jpg「弟子だからね」：容器 134px 宽，子行仅 52px，同上。

### 2. 02.5 pre-OCR VLM 校正不可行（中间方案失败）

ADR-022 的 probe 验证了 VLM 审计能力（80% 命中率），但后续 probe（probe_vision_batch）发现：
- VLM 在汉字长句上比 baberu 强（能修正「ハ意様→八意様」）
- **VLM 在拟声词/短文本上会改错**：「くだらない→ぐだらない」「すっ→か」「ビフン→ビクッ」「キョコ→ギロッ」「1→だ、だ、だ」
- 如果 pre-OCR 层自动用 VLM 结果覆盖 baberu，会引入新错误

结论：VLM 不能做"自动校正器"，只能做"第二意见提供者"。

### 3. 逐片段 Evaluator 不可行（旧翻译架构问题）

旧架构：每页 N 个框 → N 次 Evaluator 调用（逐片段 OCR + 原文 + 译文）。
问题：调用次数多、看不到全局上下文（对话顺序、角色关系、气泡归属）、成本高。

## 理论基础

重构遵循三个原则：

1. **The Bitter Lesson（Rich Sutton）**：硬编码微观规则（IoA 0.75 丢弃、1.4 倍行宽比、sub_tier 分级）最终会被通用大模型和粗粒度计算碾压。
2. **Anthropic Harness Design**：持续删除随模型能力增强而变得多余的中间态。不要逼迫无语义的 CV 检测器分辨主台词和碎碎念，那是 LLM 的本职。
3. **OpenAI Invariant Engineering**：守住边界不变量（Stage 1 不漏字、Stage 2 不过噪、Stage 3 语义完整），不微观管理中间步骤。

## 决策：前三阶段重构方案

### Stage 1：粗粒度高召回采集

**不变量：召回率优先，宁滥无缺，绝不微观切碎。**

改动：
1. **4-detector 并集保留**，不加 confidence 过滤（当前已无 conf 过滤，所有框全进）。
2. **union_blocks IoU 0.5 去重保留**——防止完全重复框，合理去重。
3. **absorb_contained 改成标记不丢弃**：嵌套小框加 `contained_in: <parent_id>` 标记，不丢弃。信息留给下游。
4. **砍掉 build_regions**：不再做 child_lines 嵌套挂载，所有框平级。
5. **砍掉 flatten_regions**：不再展平，所有框独立送 OCR。flatten 的残差保底逻辑使命完成（因为不再有子行灭口问题）。
6. **每个框记录 `source_engines`**：哪些 detector 检到了这个框，供诊断用。

输出格式（detection.json）：
```json
{
  "page": "14",
  "blocks": [
    {
      "region_id": "u00",
      "bbox": [1600, 2630, 1870, 3150],
      "category": "dialogue_bubble",
      "bubble_type": "...",
      "source_engines": ["pp-doclayout-v3", "comic-text-detector"],
      "contained_in": null
    }
  ]
}
```

### Stage 2：双引擎会诊

**不变量：两个引擎结果并列，不自动除噪，假框由下游 LLM 判断。**

组件：
1. **Baberu-OCR**：对每个框独立 OCR，快速出文本。（当前已实现）
2. **VLM 整页 contact sheet 批量校验**：
   - 把所有 crop 图拼成 contact sheet（网格拼图），送 VLM
   - 配置：thinking=disabled, detail=low（probe B 组验证最优，2-3s/页）
   - VLM 输出完整转写文本列表，按输入顺序对应
   - 不输出 is_suspect/reason 等人为结构，VLM 只做它擅长的事（看图转写）
3. **不自动除噪**：所有区域保留，包括假框。Baberu 和 VLM 都输出乱码的区域，由 Stage 3 LLM 判断是否跳过。
4. **VLM 失败容错**：重试 2 次，仍失败则降级到只用 Baberu（标记 vlm_status=failed）。

输出格式（canon.json）：
```json
[
  {
    "region_id": "u00",
    "bbox": [1600, 2630, 1870, 3150],
    "baberu_text": "では豊ちゃん…",
    "vlm_text": "では豊ちゃん、輝夜様にこの羽根を見せに行ってきます",
    "contained_in": null,
    "source_engines": ["pp-doclayout-v3", "comic-text-detector"],
    "vlm_status": "ok"
  }
]
```

### Stage 3：纯文本语义翻译

**不变量：语义完整，专有名词锁定，自然保留语调层级。**

- **DeepSeek 纯文本翻译**（不用 VLM 翻译）：纯文本 LLM 翻译能力比 VLM 强，成本更低。
- 输入：每个区域的 baberu_text + vlm_text + bbox + contained_in 标记。
- LLM 自己判断：用哪个文本、嵌套框怎么合并、怎么翻译、对话顺序。
- 保留 function calling（lookup_term / get_context）。

### Tracing：每阶段独立 trace 文件

主工件保持干净，trace 纯诊断用：
- `{page}_01_detect_trace.json`：4-detector 原始框数、union 后框数、contained_in 标记列表、每框来源引擎、耗时。
- `{page}_02_ocr_trace.json`：Baberu OCR 耗时/引擎、VLM 调用参数/耗时/输出对齐率、Baberu vs VLM 差异列表。
- `{page}_03_translate_trace.json`：LLM 模型/参数、每个区域选择 Baberu 还是 VLM、选择理由、重试次数、耗时。

### 验证策略

- **分步实施，每步验证**：Stage 1 → 验证 → Stage 2 → 验证 → Stage 3 → 验证。
- **验证范围**：11-20 页全本（10 页）。
- **数据维度**：框数/每引擎贡献/已知漏检覆盖率/假框率（双引擎都空的比例）/双引擎一致率/VLM 输出对齐率/Stage 3 选择率/端到端召回率/每页处理时间。
- **报告形式**：数据指标 + HTML 对比报告 + 人工抽检核心 case（14/15 页）。

## 与之前 ADR 的关系

- **ADR-022（audit probe 结论）**：VLM 审计能力 80% 命中，但幻觉检测有假阳性。本 ADR 整合了其结论——VLM 不做自动删除/校正，只做第二意见。
- **ADR-007（分层验证循环）**：旧的逐片段 Evaluator 架构被本 ADR 的 Stage 3 纯文本翻译取代。
- **ADR-014（翻译工位架构）**：function calling 机制保留，输入格式更新为双引擎文本。
- **ADR-006（OCR 双引擎）**：Baberu + local 回退保留，新增 VLM 作为第三引擎（第二意见）。

## 实施顺序

1. **Stage 1 重构**：改 01_detect.py，砍 build_regions/flatten，absorb_contained 改标记，加 tracing。跑 11-20 页验证。
2. **Stage 2 新增**：新增 VLM contact sheet 校验模块，改 02_ocr.py 输出双引擎文本，加 tracing。跑验证。
3. **Stage 3 改造**：改 03_translate.py 输入为双引擎文本，加 tracing。跑端到端验证。

## 风险与回退

- **风险 1**：砍 flatten 后，嵌套小框独立 OCR 可能读出碎片文本。→ 缓解：Stage 3 LLM 根据 contained_in 标记自行合并。
- **风险 2**：VLM contact sheet 丢失空间位置信息。→ 缓解：bbox 坐标随文本传给 Stage 3，VLM 只做转写不做位置判断。
- **风险 3**：不自动除噪导致假框进入翻译，增加成本。→ 缓解：假框通常很短（1-3 字符），翻译成本低；Stage 3 LLM 能判断无效文本并跳过。
- **回退**：每步独立验证，如 Stage 1 重构后效果差，可回退到旧 build_regions/flatten（代码保留不删）。
