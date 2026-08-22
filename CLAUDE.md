# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AMTA — Automation Manga Translate Agent：会话驱动的自动化漫画翻译流水线。DSH 会话（单 LLM Agent）当导演（决策/翻译判断/修复决策/验收），amta Python 执行器当确定性工具层，本地 koharu v0.59.1 headless（REST :4000）当引擎。第一里程碑：Benchmark A/B/C。

## 核心架构（决策 §9.1 定案）

```
DSH 会话（单 LLM Agent = 导演）
  ├── 决策：规划 / 翻译判断 / 修复决策 / 验收
  ├── 眼睛：describe_image（Vision QA，经 vqa() 抽象）
  └── 手：amta Python 执行器（本仓库 src/）
        └── koharu v0.59.1 headless（D:\我的汉化\workflow\bin\koharu.exe）
              REST /api/v1 + MCP /mcp，端口 4000
              引擎 DAG：detectors → OCR → llm(翻译) → inpaint → renderer
```

翻译走 koharu 内 `llm` 引擎（Story Memory 经 `systemPrompt` 注入）；Vision QA 走 `vqa()` 抽象（会话内用 describe_image 实现，预留守护进程化接口）。确定性执行，会话结束后不依赖任何后台进程。

## 关键非显然点

- **版本分水岭（钉 0.59.1）**：本地是 server 世代 v0.59.1（REST /api/v1 + MCP /mcp + mask 机制）；当前上游 0.77.5（0.63.0 起）已删除 headless/HTTP/MCP，升级即失去全部自动化面。
- **引擎 DAG 实证**：`comic-text-detector-seg` 只把「已有文字框」细化为像素 SegmentMask（needs TextBoxes）——前置 detector 漏检则 OCR/mask/inpaint 全漏；`pp-doclayout-v3` 是文档版面模型（非漫画专用），是框外字漏检嫌疑元凶 —— Benchmark A 必须四 detector 同页对比。
- **像素 mask 可经 REST 读写**：GET /scene.json + /blobs/{hash} 读、PUT /pages/{id}/masks/{role}（segment|brushInpaint）写 —— 修复循环（Repair Loop）的技术前提，segment mask 可读已冒烟验证。
- **算力约束**：CPU-only（i5-1135G7 4C8T / Iris Xe / 16GB RAM）→ 并发 workers 必须 =1（>1 会 Vulkan 断连）；inpainter 现实选择只有 lama-manga；本地 VLM 不可行（VQA 走 API/describe_image）。
- **网络与编码**：Clash 代理破坏 localhost，必须 `NO_PROXY=127.0.0.1,localhost`（koharu_client 已自动处理，start_koharu.ps1 也会设）；start_koharu.ps1 含中文路径，必须 UTF-8 **带 BOM** 保存，否则 PS5.1 按 GBK 解析报错。
- **翻译通道**：koharu 内 `llm` 引擎（做法 1），systemPrompt 注入 Story Memory；当前 llm 引擎状态 **not-ready**（需在 koharu Settings 配 DashScope/DeepSeek provider，`llm_status()`/`ensure_llm_ready()` 校验）；Benchmark A/B/C 不需要翻译。
- **重渲染教训**（本地轮子）：patch 译文后必须重跑 koharu-renderer，否则导出缓存旧图。

## 工具接口（src/koharu_client.py —— 被反复利用的稳定面）

- 生命周期：`wait_server` / `llm_status`（+`ensure_llm_ready`）/ `create_project` / `close_current_project`
- 页面：`import_page`（multipart 传图）/ `get_scene` / `get_page_nodes`
- 流水线：`run_pipeline`（steps+pages+targetLanguage+systemPrompt → operationId）/ `wait_operation`（轮询，超时 1200s）
- mask：`get_mask_blob_hash` / `get_blob` / `save_mask`（存 PNG）/ `put_mask`（回写，可选带 engine）
- 导出：`export_page`（zip 自动解包）
- 回读：`collect_blocks`（含 bubble_type 推断）/ `sort_by_reading_order`（y 升、同行 x 降，日漫阅读序）
- **规划中**：`vqa()`、`prompt.py`、`story_memory.py`（Phase 2）、`benchmark.py`；`pipeline.py` 常量已实现（FULL_STEPS / DETECTOR_STEPS / OCR_ENGINES / INPAINT_STEPS / ENGINE_NEEDS）

## 工具与回归门槛

- `python scripts/smoke_test.py` — 冒烟测试（当前回归门槛）：连引擎 → 建项目 → 传图 → 跑检测 → 读场景 → 读 mask blob → 关项目，PASS 即通路 OK；需先启动 koharu
- `scripts/start_koharu.ps1` — 启动引擎（`--port 4000 --headless --cpu`，自带 NO_PROXY 与就绪轮询）
- package.json planned scripts（check/bench）— 由配套产出，概念：check = 语法/冒烟回归，bench = Benchmark A/B/C 跑分（此处只写概念，见 package.json）

## 按需加载

- 决策记录（架构/翻译通道/Benchmark 方法论）→ `docs/01-调研报告与集成编排方案.md`（§9 已确认决策、§2.2 koharu 细节）
- 可复用资产（本地轮子 API 通路/工具）→ `docs/02-本地轮子详报.md`
- 上游能力（0.77.5 迁移权衡/自动化矩阵）→ `docs/03-koharu上游详报.md`
- 引擎 DAG / 目录结构 → `README.md`
