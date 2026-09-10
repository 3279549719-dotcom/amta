# AGENTS.md

> 规范本体是 `CLAUDE.md`（自动全文加载，含核心事实 + 坑 + 渐进式加载表）。本文件仅作入口，避免双份漂移。

AMTA：会话驱动漫画翻译自动化——DSH 会话=导演，amta Python=执行器。**全管线纯本地**（ADR-029）：detect=RT-DETR-v2，OCR=baberu/hayai，inpaint=本地 lama-manga，typeset 本地；只有 translate 阶段需要 LLM API（DeepSeek，ADR-014）。koharu v0.59.1 已**退出主链路**，仅存 legacy 客户端（`backends/koharu_client.py`、`start_koharu.ps1`），不要在主线路上依赖它；旧的 `03_translate.py` 等编号脚本已删除，翻译入口是 `run_pipeline.py --stages translate`。VQA 走 vqa() 抽象（describe_image）。

**最致命坑（通用形态）**：前置 detector 漏检 = OCR/mask/inpaint 全漏——下游再精细也救不回没框到的字。koharu 时代的 `comic-text-detector-seg` 只细化已有文字框、`pp-doclayout-v3` 是文档模型（框外字漏检嫌疑元凶），两者已随 koharu 退出主链路；但这条**链路依赖关系在当前 RT-DETR-v2 主链上同样成立**。

细节（接口/流程/坑全表）→ 读 `CLAUDE.md`（Python 一律 `uv run python`，见其末段）；Ralph Loop 规章 → `docs/ralph-loop.md`；按需技能见 `.dsh/skills/`（DSH 原生技能根）。

一次性实验脚本只进 scripts/probes/ 或 scripts/archive/,根目录与 docs/ 不出现 _ 前缀文件，每次项目收尾后要记住这点
