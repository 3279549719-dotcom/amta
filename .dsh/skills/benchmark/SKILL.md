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
- 真假判定 + 类别判定 = describe_image 逐 crop（VLM 当标注 oracle）；**内容 GT（OCR 真值文本）必须用整页枚举清单（recall_gt.json 方式）**——per-crop 独立标注不可直接当正式 GT（实测 25/126 行丢字符/缺字/把装饰数字当文本，见 L13）
- 人工仅抽查「detector 分歧 / VLM 低置信」子集

## Benchmark A — 检测（四 detector 同页对比）

- steps: `DETECTOR_STEPS`（pp-doclayout-v3 / comic-text-detector / anime-text / comic-text-bubble-detector）
- 指标：框内对白/框外对白/SFX/背景文字 四类 Recall + Precision
- 背景：`pp-doclayout-v3` 是文档模型，框外字漏检嫌疑元凶；`ctd_seg` 只细化已有框

### Benchmark A 实测结论（单翼 1-10 页）

- **precision = 0.963**（160 候选，6 个非文字假框；假框多为 `!?` 反应符号/纯画面）
- **recall = 0.98**（101 GT 检出 99；框内/框外对白 1.0，SFX 0.941，bg_text 0.909）
- **漏检集中在**：英文背景字（"Welcome Hall!"）+ 个别 SFX 拟声字 → 正是框外字痛点
- **koharu 无 SFX 专用引擎**（4 个 detector 均非 SFX 专用），漏检仅 1/17 → 结论**不加** SFX 专用检测

### ⚠️ 关键坑：describe_image 整页坐标不可靠

describe_image 看**整页大图**返回的坐标是**错的**（裁剪验证为空白/位置漂移）。**不能用它做像素级 IoU 对齐**。
→ recall 改用**内容级匹配**：GT 整页枚举文字内容清单，detector 并集框裁图+VLM 识别内容，同页字符重合度≥0.6 判定"检出"。
- 文件：`output/data/recall_gt.json`（GT）、`output/data/recall_detections.json`（4 detector 框）、`output/data/recall_ocr.json`（并集框识别内容）、`output/data/recall_result.json`（结果）
- 脚本：`scripts/recall_detect.py` / `recall_crop.py` / `recall_score.py`（共享库 `src/amta/metrics.py`、`src/amta/geometry.py`）

## Benchmark B — OCR（三模型同框对比 + 词典校正）

- steps: `manga-ocr` / `paddle-ocr-vl-1.5` / `mit48px-ocr`（needs TextBoxes）
- 指标：按人名/专名/拟声词/竖排/艺术字分类 CER + Exact Match + confidence
- 词典校正验证：豊姫→星姬 案例（编辑距离 + 候选 → VLM 复核 → DeepSeek 判定）

### 方法论要点

- **测纯识别能力**：OCR 只能识别「被框出的字」。要测 OCR 本身准不准，必须避开 detector 漏框干扰，否则算不清是 OCR 差还是 detector 差。
- **路2（本项目采用）**：跑 detector+OCR 流水线，OCR 识别 detector 框出的文字，与 GT 内容匹配算 CER/EM。因 detector recall 高（0.98），漏框干扰小，实用。
- **unmatched 行先归因再下结论**：分类为 GT 噪声/错误、GT 空（误检框）、仅标点差异的口径误判——不能直接当 OCR 失败（实测 27 行 = 19 GT 噪声 + 3 GT 空 + 5 口径误判，page_8_u06/u14 是 GT 丢 ～ 的匹配误判，OCR 才对）

### Benchmark B 实测结论（paddle-manga，QA 修正后口径）

- 现行 norm（去全部标点）重算：ALL CER 0.316→0.121 / EM 0.516→0.770（32 行 0→1，无 1→0）
- 排除 unmatched（27 行归因后）99 行：**CER 0.035 / EM 0.869**（For-Manga 真实水平）
- 三处修正：union 去重漏竖排碎片框（48 行重复，L12）· GT 25 行不可靠待对齐 recall_gt.json（L13）· 报告误标 GT bbox（L15）

## Benchmark C — Inpainting（mask + lama-manga）

- 区域级 VLM 评分（1-5 + 痕迹/破坏/残留分类，结构化 JSON 入 results/）
- 困难区域样本：复杂背景 / 人物头发 / 速度线 / 建筑 / 网点
- 注意：CPU 上只有 lama-manga 现实可行

## 报告输出

- `output/data/benchmark_a.json` / `b` / `c`（recall/precision/CER/EM/评分）；HTML 报表在 `output/reports/`
- 每项 FAIL 需定位到具体模块
- 叠加框必须标注来源：**detector 检出 union 框**（含误检，126）≠ **GT bbox**（recall_gt，101 条）；标题/图例写真实数据源，不得误标 "GT bbox"（L15）

## 命令（已实现 scripts/benchmark.py）

两阶段工具（oracle=describe_image 在会话内，非 Python 调用）：
- `npm run prescreen -- <源图目录>` → 四 detector 并集出 crop + `output/data/label_manifest.json`
- 我对每 crop 调 describe_image 标注 → 写 labels JSON
- `npm run ingest:a -- <labels.json>` → 算指标 → `output/data/benchmark_a.json`
- `npm run bench:a -- <源图目录>` = prescreen（`b`/`c` 同理，先 A 的并集 crops）
- `--all` 链式占位

指标：`detection_precision`（并集检出假框率）+ 四类分布（dialogue_in/out/sfx/bg_text）；框外漏检（真 recall）需人工抽查 detector 均漏区域。

### recall 脚本（内容级）

- `python scripts/recall_detect.py <源图目录> <页数>` → 4 detector 探测 → `output/data/recall_detections.json`
- `python scripts/recall_crop.py <源图目录>` → 并集框裁图 → `output/recall_crops/` + `output/data/recall_crop_manifest.json`
- 对并集框裁图调 describe_image 识别内容 → 合并成 `output/data/recall_ocr.json`
- `python scripts/recall_score.py` → 内容级匹配算 recall → `output/data/recall_result.json`
