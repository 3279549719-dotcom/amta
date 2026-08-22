# AGENTS.md

> 完整规范见同目录 `CLAUDE.md`（本文件为 DSH/其他 agent 的自动注入精简版；规范本体在 CLAUDE.md，避免双份漂移）。

## 定位

会话驱动的自动化漫画翻译：DSH 会话（单 LLM Agent）= 导演（决策/翻译判断/修复决策/验收），amta Python 执行器 = 确定性工具层，koharu v0.59.1 headless（REST :4000）= 引擎。翻译走 koharu 内 `llm` 引擎（Story Memory 经 `systemPrompt` 注入）；Vision QA 走 `vqa()` 抽象（会话内 describe_image）。

## 最易踩的非显然点

- **钉 0.59.1**：上游 0.77.5 已删 headless/HTTP/MCP，升级即失去全部自动化面。
- **DAG 依赖**：`comic-text-detector-seg` 只细化「已有文字框」→ 前置 detector 漏则 OCR/mask/inpaint 全漏；`pp-doclayout-v3` 是文档模型，框外字漏检嫌疑元凶（Benchmark A 四 detector 同页对比）。
- **算力**：CPU-only（i5-1135G7 4C8T），并发 workers 必须 =1（>1 会 Vulkan 断连）；inpainter 现实只有 lama-manga；本地 VLM 不可行。
- **网络/编码**：Clash 破坏 localhost → `NO_PROXY=127.0.0.1,localhost`（koharu_client 自动处理）；start_koharu.ps1 含中文路径，必须 UTF-8 **带 BOM** 保存（否则 PS5.1 按 GBK 解析报错）。
- **翻译/渲染**：llm 引擎当前 not-ready（需 Settings 配 DashScope/DeepSeek provider，`llm_status()` 校验）；Benchmark A/B/C 不需翻译；patch 译文后必须重跑 koharu-renderer，否则导出缓存旧图。

## 工具接口（src/koharu_client.py）

`wait_server` / `llm_status` / `create_project` / `close_current_project` / `import_page` / `get_scene` / `get_page_nodes` / `run_pipeline` / `wait_operation` / `get_mask_blob_hash` / `get_blob` / `save_mask` / `put_mask` / `export_page` / `collect_blocks` / `sort_by_reading_order`。规划中：`vqa()`、`prompt.py`、`story_memory.py`、`benchmark.py`（`pipeline.py` 常量已实现）。

## 回归命令

- `python scripts/smoke_test.py` — 冒烟测试（当前回归门槛），需先启动 koharu
- `scripts/start_koharu.ps1` — 启动引擎（`--port 4000 --headless --cpu`）
