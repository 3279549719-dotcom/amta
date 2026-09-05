# SFX 拟声词 OCR 调研详报（researcher-ocr · t1）

> 背景复核：manga-ocr 对框内对白 CER 0.16、对 SFX 输出为空（CER 1.0）。SFX 通常竖排/倾斜/艺术字/大号特效字。
> 结论先行：**问题不在「读得差」，而在「训练分布里根本没有 SFX 这类输入」。manga-ocr 是"漫画对白气泡"专用识别器，不是通用漫画文字识别器；SFX 是独立且更难的任务。**

---

## 1. manga-ocr 为什么对 SFX「失明」

### 1.1 架构与训练数据（来源：[manga-ocr GitHub](https://github.com/kha-white/manga-ocr)、[HF 卡](https://huggingface.co/kha-white/manga-ocr-base)）

- **架构**：Vision Encoder–Decoder（ViT 视觉编码器 + Transformer 解码器），端到端、单次前向读多行文本，**字符级输出**。本身不是检测模型——只负责「对给定的裁剪图识别出文本序列」。
- **训练数据仅两类**：
  1. **Manga109-s**（真实漫画裁剪，但标注对象是**对白气泡/说明文字**）；
  2. **合成数据**：用 CC-100 日语语料 + html2image 渲染——见[合成数据生成器](https://github.com/kha-white/manga-ocr/tree/master/manga_ocr_dev/synthetic_data_generator)，特征是：**规整横排/竖排文字、标准字体、在气泡内或背景上**。
- 作者在 README 明确自我限定：主要目标是漫画对白；**「probably won't be able to handle handwritten text」**；且模型**永远尝试输出文本、即使图上没有**（会「dream up」看似合理的句子）。

### 1.2 对 SFX 失明的根因（结论）

| 因素 | 说明 |
| --- | --- |
| **训练分布不覆盖** | 合成数据只有规整字型排版；真实数据只标对白。SFX 的「大号特效字 / 倾斜 / 弯曲 / 描边 / 渐变 / 融入背景速度线」在训练集中**占比极低甚至为零**，模型没见过这类视觉形态。 |
| **文本长度假设** | 合成/对白数据多为完整句子，解码器学到的是「句子级」语言先验；SFX 是短促音节（ドン/バキ/ゴゴゴ），长度分布和字符组合都不同。 |
| **不是检测失败而是识别失败** | 即便把 SFX 区域裁好喂进去，编码器特征与训练分布差异大，解码器要么输出乱码要么直接吐空串 → CER 1.0。 |
| **会静默失败** | 因为模型「永远尝试输出」，空白结果其实是「分布外输入 → 解码器找不到合理路径」。不会报错，表现为空。 |

> 一句话：**manga-ocr = 漫画对白专用模型；SFX 需要专用模型或专门增强，不是 tuning 能救。**

---

## 2. 开源 SFX 拟声词识别方案

### 2.1 社区现状：SFX 是「检测 + 识别」两步，识别是最难一环
漫画文字工作流普遍是 `检测(定位) → 识别(OCR) → 翻译`。检测已有成熟模型（见 §3），**卡点集中在识别**。

### 2.2 候选模型/方法（按实用性排序）

**① Baberu OCR —— 首选，明确为 SFX/气泡设计的 115M 轻量模型**
- [HF: genshiai-daichi/baberu-ocr](https://huggingface.co/genshiai-daichi/baberu-ocr)
- 特色：**字符级 14630 词表**，专门说明「sound effects、竖排、混排全/半角」都是单个 token，无子词碎片化 → **天然适合 SFX**。
- 三语（ja/zh/en）；115M 参数；**ONNX 141KB~242MB，仅需 onnxruntime+numpy+pillow → CPU-only 完全可行**。
- 日本基准（Manga109-v2026, n=2000）：lCER **0.0345**，**胜过其教师 manga-ocr（0.0422）和 PaddleOCR-VL 0.9B（0.0368）**。
- 局限：输入是**单气泡/单区域裁剪**（需上游检测器）；会混淆濁点（ポ/ボ）；非常见汉字可能漏。
- **结论：同参数量级里最适合 SFX 的现成 CPU 模型。但注意——它仍是"气泡阅读器"，艺术字极端形态仍可能失败，需实测。**

**② PaddleOCR-VL（及 Manga SFT 版）—— 0.9B 视觉语言模型**
- 官方 [PaddleOCR-VL](https://huggingface.co/PaddlePaddle/PaddleOCR-VL)，支持 109 语言，通用视觉语言 OCR。
- **漫画专用微调版** [PaddleOCR-VL-For-Manga](https://github.com/jzhang533/PaddleOCR-VL-For-Manga)（Manga109-s + 150 万合成数据 SFT）：Manga109-s 测试集全句准确率 **70% vs 原版 27%**，README 明确提到「stylized fonts」（艺术字）。
- **但**：0.9B VLM 推理开销大，CPU-only 很慢（这正是 t2 要调研的远程调用场景）。
- 注意：其 Manga109 基准得分存在「数据泄漏」（训练数据含测试集），别被数字迷惑。

**③ MangaLMM / MangaVQA —— 专用 VLM，但太重**
- [MangaLMM](https://github.com/manga109/MangaLMM)：Manga109 官方实验室出的漫画理解 VLM，MangaOCR 基准 Hmean **71.5**（GPT-4o/Qwen2.5-VL 全为 ~0）。但需 **4×A100 训练、10 小时/图推理**，CPU-only 无望，仅作参照。

**④ 传统通用 OCR（Tesseract/PP-OCRv5 等）—— 不推荐**
- PP-OCRv5 在 Baberu 同基准 ja lCER 0.63（远差）；通用 OCR 无漫画/SFX 先验，艺术字同样不行。

**⑤ 拟声词词典 / 语言模型约束（可作后处理）**
- 结合 jp-onomatopoeia 词典（[nanoskript/jp-onomatopoeia](https://github.com/nanoskript/jp-onomatopoeia)、[yuiseki/onomatopoeia-ja](https://huggingface.co/datasets/yuiseki/onomatopoeia-ja)）对识别结果做候选纠偏，可小幅提升，但不解决核心识别问题。

---

## 3. Koharu v0.59.1 内部能否解决？

### 3.1 本机 v0.59.1 实际状态（源码核查）
- 本地源码 tag 0.59.1，`koharu-ml/src/` 下 OCR 相关模块只有：**`manga_ocr`、`mit48px_ocr`、`paddleocr_vl`**。
- **v0.59.1 没有 `comic_onomatopoeia`（拟声词）专用组件**——该组件（detector+recognizer）只存在于**当前 main/较新版本**（koharu-tree 显示 `comic_onomatopoeia/{detector,recognizer}`，含 `character_set.txt`）。这是较新版本的能力，**0.59.1 无**。
- 当前 config 的 OCR = `manga-ocr`（正是失明那个）。

### 3.2 v0.59.1 内部可用的「组合拳」（不升级版本）
1. **换 OCR 引擎到 mit48px-ocr**（本机已下载 `mayocream/mit48px-ocr`）：这是为**大号/高分辨率文字**设计的识别器（text_height=48px，见源码 config），比 manga-ocr 更接近 SFX 的大号特性。**值得实测**。
2. **检测换成能框出 SFX 的模型**：v0.59.1 有 `comic-text-detector` / `speech-bubble-segmentation`。但 SFX 的**专用检测类**（如新版 KoharuLayout 的 `onomatopoeia` 类）v0.59.1 未必有——SFX 框不好，识别无从谈起。
3. **接入 Baberu OCR（外部）**：v0.59.1 没有原生 Baberu 支持（那是新版本 OCR 选项），需外部集成。

### 3.3 关键判断
- **仅靠 v0.59.1 现有 manga-ocr，改不出 SFX 能力。**
- **v0.59.1 内最务实路径**：`comic-text-detector(检测) → mit48px_ocr(识别 SFX 区域)`，对 SFX 单独跑一遍，而非走 manga-ocr。
- **要真正解决，方向是「升级获取新组件 或 外部接入 Baberu OCR」。**

---

## 4. 最务实、CPU-only 可落地的方案建议

### 方案分层

**A.（推荐，改动最小）双 OCR 分流 + mit48px/Baberu 认 SFX**
- 保持 manga-ocr 认对白（效果已验证 CER 0.16）。
- **SFX 区域单独走专用识别**：检测阶段用漫画文本/气泡检测把「非气泡大号文字」识别为 SFX 候选区 → 交给 **Baberu OCR（ONNX，CPU 可跑）** 或 **mit48px-ocr** 识别。
- 优点：只加一路，不动对白质量；Baberu 是 115M 现成权重，CPU 几秒/区。
- 行动项：先用测试集实测 Baberu vs mit48px vs manga-ocr 在 SFX 裁剪上的 CER/EM，用数据定哪个。

**B.（升级路径，最完整）迁移到含 `comic_onomatopoeia` 的新版 Koharu**
- 新版自带拟声词检测+识别专用组件，是最「省事」的根治方案。
- 代价：v0.59.1 是 headless REST/MCP（可脚本化），新版桌面 Agent 自动化面大幅收窄（见 03 详报）。**与团队既定「钉 v0.59.1 headless」决策冲突，需上层决策**。

**C.（兜底）SFX 保留原文 + 译注，不强行识别/翻译**
- 项目已有此策略（01 详报 Level C）：复杂 SFX 让 LLM 判断保留原文+注释，视觉自然 > 100% 删日文。
- 适用于极端艺术字确实认不出的场景。

### 落地优先级（CPU-only）
1. **实测**：收集本批 SFX 裁剪 → Baberu(ONNX) vs mit48px vs manga-ocr 三路对比 CER/EM（工作量最小、决策最硬）。
2. 若 Baberu 达标 → **外部接入 Baberu 认 SFX + manga-ocr 认对白** 的双引擎方案。
3. 若 Baberu 也差 → 升级到含 onomatopoeia 组件的新版（与决策层沟通自动化面损失），或走方案 C。

### 风险与注意
- SFX 艺术字极端形态（严重弯曲、透视、嵌入背景）**任何单模型都可能失败**，需设 SFX 置信度阈值 → 低于阈值走保留原文策略。
- 检测是前置硬依赖：SFX 框不准，识别必失败；建议先核验检测 Recall（项目已有四类 Recall 指标）。
- Baberu 为 Apache-2.0，CPU ONNX 无 GPU 依赖，license 友好。

---

## 5. 参考来源
- manga-ocr：[GitHub](https://github.com/kha-white/manga-ocr) · [HF kha-white/manga-ocr-base](https://huggingface.co/kha-white/manga-ocr-base) · [合成数据生成器](https://github.com/kha-white/manga-ocr/tree/master/manga_ocr_dev/synthetic_data_generator)
- Baberu OCR：[HF genshiai-daichi/baberu-ocr](https://huggingface.co/genshiai-daichi/baberu-ocr)
- PaddleOCR-VL-For-Manga：[GitHub jzhang533](https://github.com/jzhang533/PaddleOCR-VL-For-Manga) · [HF](https://huggingface.co/jzhang533/PaddleOCR-VL-For-Manga)
- MangaLMM：[GitHub manga109/MangaLMM](https://github.com/manga109/MangaLMM)
- Koharu：[README](https://github.com/mayocream/koharu) · [KoharuLayout 检测模型卡](https://huggingface.co/mayocream/koharu-layout-rfdetr-seg-2xl-1152)（含 onomatopoeia 类说明）
- 拟声词词典：[jp-onomatopoeia](https://github.com/nanoskript/jp-onomatopoeia) · [onomatopoeia-ja 数据集](https://huggingface.co/datasets/yuiseki/onomatopoeia-ja)
- SFX 翻译难度背景：[Why Manga Sound Effects Are Hard to Translate](https://ai-manga-translator.com/zh/blog/why-manga-sound-effects-are-hard-to-translate)
