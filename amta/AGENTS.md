# AGENTS.md

> 规范本体是 `CLAUDE.md`（自动全文加载，含核心事实 + 坑 + 渐进式加载表）。本文件仅作入口，避免双份漂移。

AMTA：会话驱动漫画翻译自动化——DSH 会话=导演，amta Python=执行器，koharu v0.59.1 headless（:4000）=引擎。翻译走 03_translate 脚本直调 DeepSeek API（ADR-014，弃 koharu 内 llm 引擎）；VQA 走 vqa() 抽象（describe_image）。

**最致命坑**：钉 0.59.1；`comic-text-detector-seg` 只细化已有文字框，前置 detector 漏检则 OCR/mask/inpaint 全漏（`pp-doclayout-v3` 是文档模型，框外字漏检嫌疑元凶）。

细节（接口/流程/坑全表）→ 读 `CLAUDE.md`（Python 一律 `uv run python`，见其末段）；Ralph Loop 规章 → `docs/ralph-loop.md`；按需技能见 `.dsh/skills/`（DSH 原生技能根）。

一次性实验脚本只进 scripts/probes/ 或 scripts/archive/,根目录与 docs/ 不出现 _ 前缀文件，每次项目收尾后要记住这点
