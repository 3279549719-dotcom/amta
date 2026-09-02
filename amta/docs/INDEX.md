# INDEX — 项目记忆索引（一跳定位，正文按需读）

> **这是什么**：项目级记忆层的入口（Stage 2-d，Lesson 03 加餐 III）。
> **读协议**：动手改翻译策略 / 工位架构 / 引擎选型前，先 `python scripts/memory.py search <关键词>`；命中后 `read <ID>` 深读原文。
> **写协议**：会话 / 迭代收尾产生新经验时，`python scripts/memory.py add --id ... --trigger ... --path ... --value ...` 追加索引行，并把正文写进对应文档。
> **格式**：`| ID | 触发条件 | 路径 | 一句话价值 |`。触发条件 = "什么情况下必须来读"，是索引的灵魂，写不准不如不写。
> **状态**：v0。D 行一句话价值由文件名推导（待 Patrick 校准）；L 行来自 lessons.md 实际标题。

## 决策（D = docs/decisions/）

| ID | 触发条件 | 路径 | 一句话价值 |
|---|---|---|---|
| D-001 | 升级/更换 koharu 版本前 | docs/decisions/001-koharu-v0.59.1-pin.md | 锁定 koharu v0.59.1：升级会破坏渲染链 |
| D-002 | 定翻译粒度 / MVP 范围时 | docs/decisions/002-scene-translation-not-mvp.md | 场景级翻译不是 MVP，先按框走 |
| D-003 | 想拆多 agent 时 | docs/decisions/003-single-agent-not-multiagent.md | 单 agent 路线，不拆多 agent |
| D-004 | 想引入重框架时 | docs/decisions/004-harness-lightweight.md | 轻量自造薄层，拒绝重型框架 |
| D-005 | 设计评测 / 验收口径时 | docs/decisions/005-benchmark-vlm-oracle.md | benchmark 以 VLM oracle 为参照 |
| D-006 | 改 OCR 引擎选型时 | docs/decisions/006-ocr-dual-engine.md | OCR 双引擎策略 |
| D-007 | 设计质检 / 重试层级时 | docs/decisions/007-verification-loop-layered.md | 验证循环分层（机械→语义→人） |
| D-008 | 本地 OCR 模型选型时 | docs/decisions/008-local-manga-ocr.md | 本地 manga-ocr 方案 |
| D-009 | 调整 DSH / 外部驱动方式时 | docs/decisions/009-harness-dsh-native.md | DSH 原生驱动约定 |
| D-010 | 定义 / 对比指标时 | docs/decisions/010-metric-caliber.md | 指标口径统一 |
| D-011 | 做 OCR 评测时 | docs/decisions/011-ocr-eval-caliber.md | OCR 评测口径 |
| D-012 | 动 src/ 分层结构时 | docs/decisions/012-clean-architecture-refactor.md | 清洁架构重构约定 |
| D-013 | 调 workspace 结构 / 产物路径时 | docs/decisions/013-per-work-workspace-rebaseline.md | per-work workspace 基线 |
| D-014 | 改翻译工位（工具/护栏/prompt 分层）前 | docs/decisions/014-translate-station-architecture.md | 翻译工位三段式架构 + 语义护栏定位 |
| D-015 | 新增依赖前 | docs/decisions/015-dependency-bloat-governance.md | 依赖膨胀治理 |
| D-016 | 改翻译链路 / harness 对齐时 | docs/decisions/016-translate-harness-alignment.md | 翻译 harness 对齐 |
| D-017 | 设计工单 / 人工审查流时 | docs/decisions/017-needs-review-ticket-store.md | needs_review 工单存储 |
| D-018 | 改 00_run_all / 编排时 | docs/decisions/018-pipeline-orchestrator.md | 流水线编排器约定 |
| D-019 | 处理检测契约 / 分流时 | docs/decisions/019-contract-triage.md | 契约分流 |
| D-020 | 改 inpaint 工位时 | docs/decisions/020-stage4-inpaint-station.md | Stage4 inpaint 工位 |
| D-021 | 改 typeset 工位时 | docs/decisions/021-stage5-typeset-station.md | Stage5 typeset 工位 |
| D-022 | 引用审计 / 探针结论时 | docs/decisions/022-audit-probe-conclusion.md | 审计探针结论 |
| D-023 | 做 front3 重构相关工作时 | docs/decisions/023-front3-reconstruction.md | front3 重构决策 |
| D-024 | 改 Stage 1-3 产物契约 / 深工位时 | docs/decisions/024-deep-interface-refactor.md | 产物契约单一事实源 + 三深工位 |
| D-025 | 设计记忆机制时 | docs/decisions/025-agent-memory-mechanism.md | 记忆四层闭环（基线/推送/拉取/护栏） |
| D-026 | 记忆选型时 | docs/decisions/026-memory-system-build-vs-buy.md | 选型定案：暂缓开源（agentmemory Windows 弱），自建字典 |
| D-027 | 改注入 / 检索 / 接续时 | docs/decisions/027-memory-dictionary-mcp.md | 注入瘦身 + MCP 字典 + loop_state 接续 |

## 经验（L = docs/lessons.md 分节）

| ID | 触发条件 | 路径 | 一句话价值 |
|---|---|---|---|
| L-001 | 让模型输出坐标 / 整页标注时 | docs/lessons.md#L1 | describe_image 整页坐标不可靠 |
| L-002 | 构造测试数据 / 落盘校验时 | docs/lessons.md#L2 | 假数据落盘是最致命的坑 |
| L-003 | 写轮询 / 等待逻辑时 | docs/lessons.md#L3 | wait_operation 需处理 completed_with_errors |
| L-004 | 配置并行 worker 时 | docs/lessons.md#L4 | CPU/集显下 workers>1 崩溃 |
| L-005 | 写 PowerShell 脚本时 | docs/lessons.md#L5 | .ps1 含中文路径必须 UTF-8 带 BOM |
| L-006 | 本地服务连不上时 | docs/lessons.md#L6 | Clash 破坏 localhost，需 NO_PROXY |
| L-007 | 检测框后处理时 | docs/lessons.md#L7 | ctd_seg 只细化已有文字框（DAG 依赖） |
| L-008 | 手改译文 / 重渲染时 | docs/lessons.md#L8 | patch 译文后必须重跑 koharu-renderer |
| L-009 | OCR 引擎报错 / 选型时 | docs/lessons.md#L9 | koharu 内置 llama.cpp 太旧，paddle/mit48px 全不可用 |
| L-010 | 选 OCR / VLM 模型时 | docs/lessons.md#L10 | 通用 VLM 竖排日语系统性差，必须漫画微调模型 |
| L-011 | 配置 DSH / skills 时 | docs/lessons.md#L11 | DSH 技能根 ≠ CC 约定，.claude/skills 是死配置 |
| L-012 | 检测合并 / 去重时 | docs/lessons.md#L12 | IoU>0.5 去重漏合并竖排碎片框 |
| L-013 | 构造 GT 标注时 | docs/lessons.md#L13 | VLM per-crop GT 不可靠，正式 GT 用整页枚举 |
| L-014 | 怀疑指标算错时 | docs/lessons.md#L14 | 缓存派生指标不重算 → 假 bug（GT=OCR 却 EM=0） |
| L34 | 预算 工具循环 轮次 API | docs/lessons.md | L34|工具循环预算分批内+整页两层，缺整页硬顶会API失控 |
