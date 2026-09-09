"""amta.backends — 引擎/传输后端（本地或远程确定性执行面）。

- chat_client    — OpenAI 兼容 chat/completions 深模块（翻译/OCR 共用接缝）
- koharu_client  — Koharu v0.59.1 REST 客户端
- koharu_blocks  — scene 节点 → blocks 纯整形
- ocr_engines    — OCR 引擎插拔（baberu ONNX / hayai PyTorch）
- runner         — 单页流水线执行器（跨引擎后台编排）
- vlm_verify     — VLM contact sheet 逐格转写校验后端

依赖: amta.common。
"""
