# AGENTS.md

> 规范本体是 `CLAUDE.md`（本文件仅作入口，避免双份漂移）。CLAUDE.md 全文自动加载，含核心事实 + 坑 + 渐进式加载表。

AMTA：会话驱动漫画翻译自动化——DSH 会话=导演，amta Python=执行器，koharu v0.59.1 headless（:4000）=引擎。翻译走 03_translate 脚本直调 DeepSeek API（ADR-014，弃 koharu 内 llm 引擎）；VQA 走 vqa() 抽象（describe_image）。

**最致命坑**：钉 0.59.1；`comic-text-detector-seg` 只细化已有文字框，前置 detector 漏检则 OCR/mask/inpaint 全漏（`pp-doclayout-v3` 是文档模型，框外字漏检嫌疑元凶）。

细节（接口/流程/坑全表）→ 读 `CLAUDE.md`；按需技能见 `.dsh/skills/`（DSH 原生技能根，进 skill catalog 按需加载）。
