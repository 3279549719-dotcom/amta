---
name: oracle-label
description: VLM 当标注 oracle——用 describe_image 逐 crop 判真假/分类/评分，产出结构化 labels JSON 供 benchmark ingest。Benchmark A/B/C 与 Vision QA 共用的核心方法论。
---

# VLM Oracle 标注（oracle-label）

## 何时用

- 需要给 crop（检测框裁剪 / OCR 框 / inpaint 区域）打标的任何 benchmark 或 QA 步骤。
- 判定标准是「看图判断」而非确定性计算 → 交给 describe_image（VLM 当独立 grader/oracle）。

## 核心原则

1. **describe_image 是会话内工具，不是 Python 调用** → benchmark.py 只产出待标 crop + manifest，标注由 Agent 逐 crop 完成。
2. **零人工全量标注**：VLM 全覆盖；人工仅抽查「detector 分歧 / VLM 低置信」子集。
3. **候选真值 = 4 detector 并集**：都漏的不计入分母，属工具能力边界。

## Benchmark A — 检测框 4 类判定

输入：`output/crops/*.png` + `output/data/label_manifest.json`
对每个 crop 调 describe_image，prompt 要求返回结构化判定：
- `is_text`: bool（该框内是否真是漫画文字）
- `cls`: `dialogue_in`（框内对白）/ `dialogue_out`（框外对白）/ `sfx`（拟声词）/ `bg_text`（背景文字，如招牌/题字）
- `confidence`: low / medium / high（VLM 自身把握度，low 留待人工抽查）

输出：`output/data/labels_a.json`，形如：
```json
[{"id": "page_0_cand00", "is_text": true, "cls": "dialogue_in", "confidence": "high"}]
```

然后 `npm run ingest:a -- output/data/labels_a.json` → `output/data/benchmark_a.json`
指标：`detection_precision`（并集假框率）+ 四类分布 share。

## Benchmark B — OCR 框分类

输入：同一并集 crops。先跑三 OCR 引擎拿每框文本，再对每框 describe_image 判文本内容作真值。
- `cls`: 人名 / 专名 / 拟声词 / 竖排 / 艺术字
- 词典校正验证：豊姫→星姬（编辑距离 + 候选 → VLM 复核 → LLM 判定）

## Benchmark C — Inpaint 区域评分

输入：inpaint 前后区域图（patch 前原区域 vs 擦除后）。
describe_image 判：
- `score`: 1-5（1=破坏/明显痕迹，5=干净无痕）
- `artifact`: none / residue（残留）/ damage（破坏）/ trace（痕迹）
- `confidence`

## Vision QA（生产阶段复用）

同套 VLM oracle 逻辑用于类型排字后质检 → 失败回修（Repair Loop）。规则一致，只是场景换成渲染图。

## 效率指引

- 160 框级标注量大 → 可用 subagent 分片并行（每片 ~20 crops），各自写 labels 片段再合并。
- 低置信 / 分歧条目汇总成人工抽查清单，只抽查这部分。
- 严格按 manifest 的 `id` 对齐，避免漏标/错位。
