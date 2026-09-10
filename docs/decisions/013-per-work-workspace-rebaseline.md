# 013 — 产物结构 rebaseline：per-work workspace + work_state（Touhou 同人志缩域）

## Context

- 评测已完成（ADR-011/010）：**OCR 引擎定案 For-Manga（86 对齐框 CER 0.062/EM 0.779）**。这是已证实的"事实底座"，不推翻。
- 但当前产物结构是 **benchmark 工具层**：`output/data/*.json` 平铺 + `output/reports/*.html` 报表，为"逐页评测"服务，**不是翻译产品**——没有跨页状态、没有共享先验、每本子之间无隔离。
- 用户引入 reference（touhou_doujin_first_principles_dikw.html）的第一性原理/DIKW 设计：把"通用漫画翻译器"收缩成**可验证的 Touhou 同人志翻译系统**；核心 = `Touhou Canon prior + 当前 Doujin Work State + 当前页 Evidence` 三层输入，交给 Agent（DeepSeek）判断已知/未知、按需检索、翻译、更新状态。
- 用户定案：评测 OK 保留，**产物结构需结构化调整**（grill 落点 A）。

## Decision

**每本同人志一个工作区**（文件即状态，砍 DB/Vector/Event Graph/Memory Service）：

```
workspace/<work_id>/                # work_id = 单本子唯一 slug，如 touhou_doujin_001
├── raw/                            # 源页图（本子未翻译原图）
├── artifacts/                      # 单页/整本确定性产物
│   ├── detection.json              # TextBoxes（detector 并集，全尺寸可靠坐标）
│   ├── ocr_candidates.json         # OCR 候选（可多候选）
│   ├── canon_text.json             # OCR Arbitration 定案文本
│   ├── translation.json            # 翻译结果（DeepSeek）
│   ├── mask.png / cleaned.png / final.png
│   └── ...
└── state/                          # 本子的活状态（逐页生长）
    ├── touhou_knowledge.json       # 共享 Touhou canon prior（curated，跨本子复用）
    ├── work_state.json             # 当前本子状态（characters/terms/relationships/scene/context/open_questions）
    └── open_questions.json         # 未决问题（待后续证据确认/推翻）
```

关键语义：
1. **三层上下文分离**：`touhou_knowledge`（stable prior）与 `work_state`（当前本子，可变）**不混表**——同人志可改变人物关系/性格/语气，canon 只是 prior 不是本子真相。优先级：当前页直接证据 ＞ work_state ＞ canon prior ＞ LLM 猜测。
2. **work_state 逐页生长**，不从开局构建完美世界模型；第一版不做 Character DB / Relationship DB / Event Graph / Vector DB / Memory Service。
3. **Evidence tracking**：状态条目带 `status ∈ {confirmed, inferred, candidate}` + `source`（页码）——让 Agent 知道哪些是证据确认的事实、哪些只是当前信念。
4. **新证据可修正旧状态**（补传旧页/乱序页 → reconciliation/out-of-order mode）。
5. **单页可运行**：无历史也能翻译，完整本子连续阅读是增强不是前提。
6. 范围 **缩域 Touhou 同人志**：短、角色集小、共享 IP 先验 → 三层切片检索，不一口气塞整个 Wiki。

## Consequences

- ✅ 产物从"逐页 benchmark 报表"转向"每本子一个工作区"，为 Agent 翻译层（DeepSeek 判断+状态更新）提供唯一落盘形态。
- ✅ benchmark 事实底座（For-Manga 定案、指标口径）不变，`output/` 旧评测数据保留供引用，逐步迁移到新结构。
- ⚠️ 这是**方向性 rebaseline**（原"第一里程碑 Benchmark A/B/C"仍成立，但产出的目标是翻译产品状态，不是报表）。
- ⚠️ 翻译层归属（DeepSeek 会话翻译 vs koharu 内 llm）是下游决策，本 ADR 不锁定，先定产物结构。
- 代码落点：`src/amta/workstate.py`（workspace 布局 + 三文件空 schema + init/update/validate）+ `tests/test_workstate.py`。
