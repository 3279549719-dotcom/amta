"""amta.backends — 引擎/传输后端（本地或远程确定性执行面）。

- chat_client    — OpenAI 兼容 chat/completions 深模块（翻译/OCR 共用接缝）
- koharu_client  — Koharu REST 客户端（headless :4000）
- koharu_blocks  — scene 节点 → blocks 纯整形
- ocr_engines    — OCR 引擎插拔（baberu ONNX 默认 / hayai PyTorch，token 级 confidence）
- runner         — 单页流水线执行器（跨引擎后台编排）
- vlm_verify     — VLM contact sheet 逐格转写校验后端

本地漫画 OCR 部署：独立 llama-server（models/llama-cpp，端口 8118，--mmproj，OpenAI 兼容）
跑 PaddleOCR-VL-For-Manga GGUF，启动脚本 scripts/start_llama_ocr.ps1；baberu-ONNX 作
fast path（约 1s/张，对白 CER 相当）。koharu 内置 llama.cpp 过旧，其 paddle/mit48px OCR
不可用（只 manga-ocr 可用），版本/踩坑见 docs/lessons.md。
依赖: amta.common。
"""
