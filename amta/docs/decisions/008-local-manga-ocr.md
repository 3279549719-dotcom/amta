# ADR-008：框外对白 OCR = 本地 PaddleOCR-VL-For-Manga（独立 llama-server），弃 koharu paddle 引擎

**状态**：已采纳（实测背书，勿改）

## 决策

框外对白 OCR 替换 manga-ocr：**本地跑 `PaddleOCR-VL-For-Manga`（GGUF + 独立 llama-server b10582，端口 8118，OpenAI 兼容接口，prompt `OCR:`）**；koharu 内置 paddle-ocr-vl-1.5 / mit48px-ocr 引擎**判定不可用，不再尝试**；GLM-OCR-Manga-LoRA **出局**（无 API、需 GPU≥4GB）。

## 理由

- **koharu 的 paddle/mit48px 引擎全坏**：实弹复现 `completed_with_errors`（detector 有 confidence、ocr 全空），日志 `unable to initialize multimodal projector: MTMD context initialization returned null`。根因 = koharu 内置 llama.cpp b8935 太旧（2026-05-18）；同 GGUF 用现代 b10582（2026-08-22）秒加载、OCR 正常（实测 `月の都` ✅ 12s/图）。
- **通用 VLM 竖排日语系统性差**（arXiv 2511.15059；qwen-vl-ocr 实测词序错乱；PaddleOCR-VL 基座 EM 9%/CER 55.41%）→ 远程 API 基座模型（SiliconFlow PaddleOCR-VL / DashScope qwen-vl-ocr / DeepSeek-OCR）都不可靠，放弃远程 API 路线（无需注入 SiliconFlow key）。
- **漫画微调版有效**：jzhang533/PaddleOCR-VL-For-Manga（Manga109-s 整句 70% vs 基座 27%；openvino-book 复现 CER 10.88% vs 55.41%）。实测竖排词序完美（qwen 错乱的 case 逐字正确）。
- **零成本本地**：GGUF 892MB + mmproj 841MB，CPU 10-19s/图可跑；绕开 koharu 坏引擎，符合 ADR-003 执行器直调模式。

## 后果 / 约束

- 漫画 OCR 走独立 llama-server:8118（`models/llama-cpp/llama-server.exe` ≥b10582 + `models/paddle-manga/`），不入 koharu 引擎 DAG。
- llama.cpp 版本硬约束：≥b10582（旧版 MTMD 投影初始化失败）。
- GLM-OCR-Manga-LoRA 如需启用，须 GPU≥4GB 本地推理（无托管 API），本机不可行，记出局。
- 测评产物：`output/data/benchmark_b_paddle_manga.json`（全量 CER/EM）；报表 `output/reports/benchmark_b_paddle_manga_report.html`。
