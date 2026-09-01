# 调研：VLM 筛选 + LM 翻译 两层架构在漫画翻译中的应用

> 日期：2026-09-01
> 分支：feature/detect-ab-rtdetr
> 背景：RT-DETR-v2 检测器全量 42 页测试后，存在 8.4% 纯标点误报 + 17.8% 短框（≤3字），需验证"VLM 筛选 + LM 翻译"两层架构的可行性。

---

## 一、全量检测基线数据（RT-DETR-v2 + Baberu OCR，42页）

| 指标 | 数值 |
|---|---|
| 检测页数 | 42/42 |
| 总检测框 | 415（平均 9.9 框/页） |
| 总字符数 | 6003（平均 142.9 字/页） |
| 非空率 | 100% |
| **纯标点框** | **35（8.4%）** — `．．．`/`～` 等，可规则过滤 |
| **短框 ≤3字** | **74（17.8%）** — 部分合法 SFX，部分误报 |
| 检测耗时 | 56.1s（1.3s/页） |
| OCR 耗时 | 319.7s（7.6s/页） |

数据文件：`output/data/detect_full/results.json`
报告：`output/data/detect_full/report.html`

---

## 二、高星项目架构对比（4个，已 clone 到 reference/repos/）

### 2.1 comic-translate（ogkalu2，2.9k stars）⭐ 最相关

- **检测**：RT-DETR-v2（ogkalu/comic-text-and-bubble-detector）— **跟本项目同一个模型**
- **OCR**：manga-ocr（默认日语）/ PPOCRv5 / **VLM OCR**（Gemini-2.5-Flash-Lite / GPT-4.1-mini / Microsoft Azure Vision，逐框裁剪识别）
- **翻译**：GPT-4.1 / Claude-4.6 / Gemini-2.5 / Deepseek，**可选 `img_as_llm_input` 把整页图 base64 作为上下文传给多模态模型**
- **架构本质**：多模态模型**一次调用**完成"看图理解 + 翻译"，图片是翻译的上下文辅助，**没有单独的 VLM 筛选层**

#### 可直接复用的组件

1. **`has_translatable_content(text)`**（`modules/utils/translator_utils.py`）：
   ```python
   def has_translatable_content(text):
       if not text:
           return False
       return any(ch.isalnum() for ch in text)
   ```
   纯标点文本不送翻译、不渲染。**一行代码砍掉 8.4% 纯标点误报。**

2. **VLM OCR 的 prompt 模式**（`modules/ocr/gemini_ocr.py`）：
   - 逐框裁剪 → base64 → prompt "Extract the text exactly as it appears. Only output raw text."
   - 可改造为 VLM 筛选 prompt："看全页图，判断以下每个 OCR 文本是否真实存在于对应位置"

3. **JSON 翻译协议**（`modules/translation/llm/base.py`）：
   - 输入：`{"block_0": "text", "block_1": "text", ...}`
   - 输出：同结构翻译 JSON
   - 正则提取 JSON + 解析写回每个 block

4. **`is_renderable_translation()`**：纯标点翻译不渲染（避免 inpaint 后空白）

### 2.2 koharu（koharu-rs，5.4k stars）

- **检测**：Koharu Layout RF-DETR Seg 2XL（自研）
- **OCR**：PaddleOCR-VL 1.6 / MangaOCR / **Baberu OCR**（本项目在用的）/ Hayai OCR
- **翻译**：**纯文本 LLM**（OpenAI/Claude/Gemini/Deepseek/DeepL/Google/Caiyun 等），本地 GGUF 也支持
- **架构**：detection → ocr → inpainting → translation 四个独立 stage，**没有 VLM 筛选层**
- **可复用**：翻译 provider 抽象（`crates/koharu-translator/src/`）、pipeline stage 设计

### 2.3 BallonsTranslator（dmMaze，5.1k stars）

- **检测**：CTBD（comic-text-bubble-detector，RT-DETR 架构）— **本项目 detect_rtdetr.py 的移植来源**
- **OCR**：manga-ocr / PaddleOCR / surya / Magi
- **翻译**：纯文本 LLM
- **可复用**：CTBD 检测器的后处理逻辑（重复框合并、包含框移除、切片检测），本项目已移植

### 2.4 manga-image-translator（zyddnys，10.4k stars）

- **检测**：CTD（comic-text-detector）— 本项目 4 引擎并集之一，通过 Koharu API 调用
- **OCR**：manga-ocr / PaddleOCR
- **翻译**：纯文本 LLM
- **可复用**：CTD 模型 + Koharu API 集成方式

---

## 三、低星但架构匹配的项目（未 clone，需进一步验证）

### 3.1 ocrTranslate（PureChocolate）

- **明确的两层分离架构**：
  - Vision Model (Qwen3-VL 8B)：扫描原图，提取气泡文本
  - Language Model (TranslateGemma 12B)：翻译提取的文本
- 本地 Ollama 运行，零外部 API
- 支持竖排日语、SFX、NSFW 内容
- **架构完全匹配"VLM 提取/筛选 + LM 翻译"**，但 stars 低，需验证代码质量

### 3.2 kotoba-manga-translator（andrey231）

- **检测**：RT-DETRv2（跟本项目同一个！）
- **OCR**：GLM-OCR（via transformers）
- **VLM 层**：页面分析（角色+场景）、说话人归因
- **翻译**：文本 LLM 批量翻译
- **角色记忆**：跨页追踪人物身份，翻译一致性更好
- VLM 做的是角色分析不是误报筛选，但 VLM+LM 分离的架构可参考

---

## 四、关键结论

1. **四个高星项目里，没有一个是"VLM 专门做筛选过滤 + LM 专门做翻译"的两层架构。** comic-translate 最接近，但它是多模态模型一次调用完成看图+翻译，没有单独筛选步骤。

2. **comic-translate 是最适合复用组件的项目**，因为：
   - 用同一个 RT-DETR-v2 模型，检测输出格式一致
   - `has_translatable_content()` 可直接抄
   - VLM OCR 的 prompt 模式可改造为 VLM 筛选
   - JSON 翻译协议可复用

3. **本项目的"VLM 筛选 + LM 翻译"两层架构是创新组合**，没有现成项目完全一样，需要自己实现 VLM 筛选层。

4. **纯标点误报（8.4%）不需要 VLM**，规则过滤即可。VLM 应该聚焦在"短框是否为合法 SFX"和"OCR 文本是否准确"这两个规则解决不了的问题上。

---

## 五、待验证的对比实验设计（下一步）

在相同的 10-15 页代表性样本上，对比以下方案：

| 方案 | 检测 | OCR | 筛选 | 翻译 | 预期成本 |
|---|---|---|---|---|---|
| baseline | RT-DETR-v2 | Baberu | 无（直接送翻译） | LM | 最低 |
| A：VLM 全量筛选 | RT-DETR-v2 | Baberu | VLM 对所有框 keep/drop/fix | LM | 高（1次VLM/页） |
| B：VLM 替代 OCR | RT-DETR-v2 | 无（VLM 直接识别） | 天然过滤（空框输出空） | LM | 中高 |
| C：规则+VLM 可疑框 | RT-DETR-v2 | Baberu | 规则过滤纯标点 + VLM 只验可疑框 | LM | 中 |

评估指标：翻译质量（人工评分）、误报率、漏检率、VLM/LM 调用成本、速度。

---

## 六、参考文件路径

- clone 的项目：`reference/repos/{comic-translate, koharu, BallonsTranslator, manga-image-translator}`
- 全量检测数据：`output/data/detect_full/results.json`
- 全量检测报告：`output/data/detect_full/report.html`
- 检测器源码：`scripts/detect_rtdetr.py`
- 全量检测脚本：`scripts/run_detect_full.py`
