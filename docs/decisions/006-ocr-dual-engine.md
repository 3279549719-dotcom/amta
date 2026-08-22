# ADR-006：OCR 双引擎分流 = manga-ocr 认对白 + Baberu 认 SFX

**状态**：已采纳（数据背书，勿改）

## 决策

OCR 采用**双引擎分流**：`manga-ocr` 负责对白（框内 CER 0.16 / EM 0.795，验证优秀）；`Baberu OCR`（115M ONNX，CPU-only 可跑）负责 SFX 拟声词（CER 0.181 / EM 0.588，远超 manga-ocr 的 1.0/0）。

## 理由

- **manga-ocr 对 SFX 完全失明**（CER 1.0/EM 0）：它是"对白气泡专用"模型，训练分布不含 SFX（大号艺术字/倾斜/弯曲/描边）→ 分布外输入解码器吐空串。非 tuning 能救（详见 docs/04-SFX拟声词OCR调研-详报.md）。
- **Baberu 实测**：17 个 SFX 中 10 精确匹配、6 近匹配、1 漏；CER 0.181 vs manga-ocr 1.0。
- **不引入 SFX 专用检测器**：koharu 无此引擎，且 SFX 检测 recall 0.941（漏检低），加引擎收益不成比例。
- **不升级 Koharu 根治**：新版含 onomatopoeia 组件但已删 headless/HTTP/MCP，破坏自动化架构（见 ADR-001）。

## 后果 / 约束

- 双引擎分流需在流水线实现：manga-ocr 走对白路径，Baberu 走 SFX 区域路径。
- SFX 置信度低时走"保留原文 + 译注"兜底（Level C 策略）。
- 极端艺术字任何单模型都可能失败，需设 SFX 置信度阈值。
