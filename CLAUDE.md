# CLAUDE.md

AMTA — Automation Manga Translate Agent：会话驱动的漫画翻译自动化。DSH 会话（单 LLM Agent）= 导演（决策/翻译判断/修复决策/验收），amta Python 执行器 = 确定性工具层，koharu v0.59.1 headless（REST :4000）= 引擎。第一里程碑：Benchmark A/B/C。

## 核心事实

- **钉 koharu v0.59.1**（server 世代，REST /api/v1 + MCP /mcp + 像素 mask 机制）；上游 0.77.5 起已删 headless/HTTP/MCP，升级即失去全部自动化面。
- **翻译通道**：koharu 内 `llm` 引擎，Story Memory 经 `systemPrompt` 注入（做法 1）；当前 llm 引擎 not-ready（需 Settings 配 provider，`llm_status()` 校验）；Benchmark A/B/C 不需要翻译。
- **Vision QA**：`vqa()` 抽象，会话内 describe_image 实现。
- **算力**：CPU-only（i5-1135G7 4C8T / 16GB），并发 workers 必须 =1；inpainter 现实选择只有 lama-manga；本地 VLM 不可行。
- **工具面**：`src/koharu_client.py`（16 方法，清单见 koharu-drive skill）+ `src/pipeline.py`（引擎 DAG 常量）。

## 坑（不踩会死）

- **NO_PROXY**：Clash 破坏 localhost，必须 `NO_PROXY=127.0.0.1,localhost`（koharu_client 自动处理，start_koharu.ps1 已设）。
- **ps1 编码**：含中文路径的 .ps1 必须 UTF-8 **带 BOM**，否则 PS5.1 按 GBK 解析报错。
- **DAG 依赖**：`comic-text-detector-seg` 只细化「已有文字框」——前置 detector 漏检则 OCR/mask/inpaint 全漏；`pp-doclayout-v3` 是文档模型，框外字漏检嫌疑元凶（Benchmark A 四 detector 同页对比）。
- **重渲染**：patch 译文后必须重跑 koharu-renderer，否则导出缓存旧图。
- **workers>1 崩**：CPU/集显下并发流水线 Vulkan 断连。

## 渐进式加载

| 触发 | 读 |
|---|---|
| 跑 Benchmark A/B/C | `.claude/skills/benchmark/SKILL.md` |
| 驱动 koharu（接口/mask/修复循环） | `.claude/skills/koharu-drive/SKILL.md` |
| 回归/发布流程 | `.claude/skills/verify/SKILL.md` |
| 架构决策背景 | `docs/01-调研报告与集成编排方案.md` |
| 可复用轮子资产 | `docs/02-本地轮子详报.md` |
| 上游能力/迁移权衡 | `docs/03-koharu上游详报.md` |
| 引擎 DAG / 目录结构 | `README.md` |

Skills 与 docs 均按需加载：先看名字/一句话，任务触发时才读全文。
