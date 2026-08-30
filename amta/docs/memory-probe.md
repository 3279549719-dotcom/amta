# 冷启动探针（记忆活性体检，audit 期执行）

## 方法
在仓库根新开一个 Claude Code 会话（不口头提醒任何背景），依次问三题，核对回答是否引用正确来源。

| # | 问题 | PASS 标准 |
|---|---|---|
| 1 | "这个项目上次做到哪了？接下来该干嘛？" | 回答含 recent.md/now.md 的具体内容（如 context-semantic-transfer 状态） |
| 2 | "pytest 全 PASS 但退出码 1，怎么回事？" | 引用 L19（teardown 噪音 / 看 N passed 汇总行） |
| 3 | "为什么 koharu 的 paddle OCR 引擎不能用？" | 引用 L9 / ADR-008（llama.cpp b8935 MTMD 初始化失败，走独立 llama-server） |

## 判定
- 3/3 PASS = 记忆机制有效；≤1 PASS = 失效，先跑 `python scripts/memory_status.py` 排查注入与地产健康。
- 探针结果记入当次 audit 报告（docs/decisions/022 的 audit probe 流程追加本节）。
