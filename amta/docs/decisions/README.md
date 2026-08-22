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
