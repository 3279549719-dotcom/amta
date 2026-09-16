"""amta.backends — 引擎/传输后端（本地或远程确定性执行面）。

- chat_client    — OpenAI 兼容 chat/completions 深模块（翻译/OCR 共用接缝）
- ocr_engines    — OCR 引擎插拔（baberu ONNX 默认 / hayai PyTorch，token 级 confidence）
- vlm_verify     — VLM contact sheet 逐格转写校验后端

本地漫画 OCR 部署：独立 llama-server（models/llama-cpp，端口 8118，--mmproj，OpenAI 兼容）
跑 PaddleOCR-VL-For-Manga GGUF，启动脚本 scripts/start_llama_ocr.ps1；baberu-ONNX 作
fast path（约 1s/张，对白 CER 相当）。
依赖: amta.common。
"""
