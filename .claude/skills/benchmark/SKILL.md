---
name: benchmark
description: Benchmark A/B/C——用数据钉死 koharu v0.59.1 的能力边界（检测 recall / OCR 精度 / inpaint 质量）。第一里程碑，四大痛点各有数据答案。
---

# Benchmark A/B/C

## 目标与成功标准

回答四大痛点：框外字漏多少（A）、OCR 错多少（B）、擦字行不行（C）、翻译上下文提升（D，后置）。
成功标准：**数据答案 + 失败可定位到具体模块**（detector/ocr/mask/inpaint）。

## 测试集（testsets/）

- 10-20 页真实页（轮子 output：单翼停留之地 41 页 / 灵梦和妹红 26 页 / 赚钱大法 5 页）
- 预筛：describe_image 选 4 类覆盖——框内对白 / 框外对白 / SFX / 背景文字
- 原图不入库（testsets/pages/ 已 gitignore）；`ground_truth/`、`results/` JSON 入库

## 方法论（零人工全量标注）

- 候选真值 = **4 detector 的并集**（都漏的不计入分母，属工具能力边界）
- 真假判定 + OCR 真值 = **describe_image 逐 crop**（VLM 当标注 oracle）
- 人工仅抽查「detector 分歧 / VLM 低置信」子集

## Benchmark A — 检测（四 detector 同页对比）

- steps: `DETECTOR_STEPS`（pp-doclayout-v3 / comic-text-detector / anime-text / comic-text-bubble-detector）
- 指标：框内对白/框外对白/SFX/背景文字 四类 Recall + Precision
- 背景：`pp-doclayout-v3` 是文档模型，框外字漏检嫌疑元凶；`ctd_seg` 只细化已有框

## Benchmark B — OCR（三模型同框对比 + 词典校正）

- steps: `manga-ocr` / `paddle-ocr-vl-1.5` / `mit48px-ocr`（needs TextBoxes）
- 指标：按人名/专名/拟声词/竖排/艺术字分类 CER + Exact Match + confidence
- 词典校正验证：豊姫→星姬 案例（编辑距离 + 候选 → VLM 复核 → DeepSeek 判定）

## Benchmark C — Inpainting（mask + lama-manga）

- 区域级 VLM 评分（1-5 + 痕迹/破坏/残留分类，结构化 JSON 入 results/）
- 困难区域样本：复杂背景 / 人物头发 / 速度线 / 建筑 / 网点
- 注意：CPU 上只有 lama-manga 现实可行

## 报告输出

- `output/benchmark_a.json` / `b` / `c`（recall/precision/CER/EM/评分）
- 每项 FAIL 需定位到具体模块

## 命令

## 命令（已实现 src/benchmark.py）

两阶段工具（oracle=describe_image 在会话内，非 Python 调用）：
- `npm run prescreen -- <源图目录>` → 四 detector 并集出 crop + `output/label_manifest.json`
- 我对每 crop 调 describe_image 标注 → 写 labels JSON
- `npm run ingest:a -- <labels.json>` → 算指标 → `output/benchmark_a.json`
- `npm run bench:a -- <源图目录>` = prescreen（`b`/`c` 同理，先 A 的并集 crops）
- `--all` 链式占位

指标：`detection_precision`（并集检出假框率）+ 四类分布（dialogue_in/out/sfx/bg_text）；框外漏检（真 recall）需人工抽查 detector 均漏区域。
