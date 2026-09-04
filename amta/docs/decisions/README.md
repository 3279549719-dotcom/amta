# Architecture Decision Records

回答："为什么这样选？" — 保存有意义的架构决策与理由（不是失败日志）。

约定：
- 每条一个文件，`NNN-标题.md`，短小。
- 只有**改动架构/方向**的决策才写；日常实现细节不写。
- 与 `docs/progress.md` 的「已锁定决策」互补：这里存**理由**，progress.md 只存当前状态指针。

## 索引

- [001 — 钉 koharu v0.59.1 headless（REST+MCP+像素 mask）](./001-koharu-v0.59.1-pin.md)
- [002 — 场景级翻译不在 MVP（先 Story Memory + 前页上下文）](./002-scene-translation-not-mvp.md)
- [003 — 单 Agent + 确定性工具层，而非 Multi-Agent](./003-single-agent-not-multiagent.md)
- [004 — Harness = 脚本/hooks/tests/docs，而非外部基础设施](./004-harness-lightweight.md)
- [005 — Benchmark 方法论 = VLM-as-oracle + 零人工全量标注 + 内容级匹配](./005-benchmark-vlm-oracle.md)
- [006 — OCR 双引擎分流 = manga-ocr 认对白 + Baberu 认 SFX](./006-ocr-dual-engine.md)
- [007 — 验证循环分层 + 中止才落盘](./007-verification-loop-layered.md)
- [008 — 框外对白 OCR = 本地 PaddleOCR-VL-For-Manga（独立 llama-server），弃 koharu paddle 引擎](./008-local-manga-ocr.md)
- [009 — Harness 机制 DSH 原生化（.dsh/skills 唯一技能根 + 判断链五路分流 + hook 仅 git）](./009-harness-dsh-native.md)
- [010 — 评测指标口径（norm 去标点 + 派生指标重算 + 双轨展望）](./010-metric-caliber.md)
- [011 — OCR 评测锚点 = detector 对齐框 + GT 语义内容（86/101），废弃 GT 缩略 bbox](./011-ocr-eval-caliber.md)
- [012 — 代码结构重构：逻辑收敛进 src/amta 共享库，scripts 只留薄 CLI](./012-clean-architecture-refactor.md)
- [013 — 产物结构 rebaseline：per-work workspace + work_state（Touhou 同人志缩域）](./013-per-work-workspace-rebaseline.md)
- [014 — 翻译工位架构定稿：DeepSeek API 直调 + 双层护栏 + 分层 Loop](./014-translate-station-architecture.md)
- [015 — 依赖膨胀治理：vibe-check 式拦截 + uv 最小化解析](./015-dependency-bloat-governance.md)
- [016 — Translate Harness 对齐 GPT 设计：Guardrails 补全 / Eval 四维 / Tools / State 四层 / 验收阈值](./016-translate-harness-alignment.md)
- [017 — needs_review 工单机制：TicketStore 状态机 + 判例库回写（维修手册逻辑）](./017-needs-review-ticket-store.md)
- [018 — 流水线编排器：00_run_all + step tracing + LLM 观测（零依赖自造）](./018-pipeline-orchestrator.md)
- [019 — Stage 4-6 契约裁剪:category/sub_tier 契约 + 字段卫生](./019-contract-triage.md)
- [020 — Stage 4 inpaint 工位:koharu lama-manga 链路 + 探针定案](./020-stage4-inpaint-station.md)
- [021 — Stage 5 排版工位:自研 Pillow 引擎 + node_id 关联契约](./021-stage5-typeset-station.md)
- [022 — 审计探针结论（audit probe）](./022-audit-probe-conclusion.md)
- [023 — front3 重构](./023-front3-reconstruction.md)
- [024 — Stage 1-3 深接口改造:产物契约单一事实源 + 三深工位](./024-deep-interface-refactor.md)
- [025 — Agent 记忆机制:四层闭环（注入 + 打捞 + 护栏）](./025-agent-memory-mechanism.md)
- [026 — 记忆系统选型：不自造轮子，改用开源高星项目](./026-memory-system-build-vs-buy.md)
- [027 — 记忆层 v2：注入瘦身 + loop_state 接续 + MCP 字典](./027-memory-dictionary-mcp.md)
- [028 — Ralph Loop：外层循环 + 文件状态的无人值守开发循环](./028-ralph-loop-autonomous-development.md)
- [029 — Lama-Manga 本地推理 + 整页模式：替代 Koharu HTTP Inpaint](./029-lama-manga-local-inference.md)
