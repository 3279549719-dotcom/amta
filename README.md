# AMTA — Automation Manga Translate Agent

自动化漫画翻译 Agent（会话驱动版）。

## 架构（/grill-me 澄清会定案）

```
DSH 会话（我）= 单 LLM Agent（导演）
  ├── 决策：规划 / 翻译判断 / 修复决策 / 验收
  ├── 眼睛：describe_image（Vision QA）
  └── 手：amta Python 执行器（本仓库）
        └── koharu v0.59.1 headless（D:\我的汉化\workflow\bin\koharu.exe）
              REST /api/v1 + MCP /mcp，端口 4000
```

- 引擎基线：**本地 koharu v0.59.1 headless**（`--port 4000 --headless --cpu`）
- 翻译通道：**koharu 内翻译**（`llm` 引擎，Story Memory 经 `systemPrompt` 注入）
- 第一里程碑：**Benchmark A/B/C**（10-20 页，VLM 当标注 oracle）
- 算力约束：CPU-only（i5-1135G7 / Iris Xe），workers=1，inpainter 用 lama-manga

## 目录

```
amta/
├── src/amta/               # 纯库包（可被 import，脚本的上游）
│   ├── koharu_client.py    # Koharu REST API 封装（建项目/传图/流水线/轮询/场景/mask/导出）
│   ├── pipeline.py         # 流水线步骤常量 + 引擎 DAG 知识
│   ├── metrics.py          # 共享指标库：norm/levenshtein/cer/best_match/match_score
│   └── geometry.py         # 共享几何库：bbox/iou/union_boxes
├── scripts/                # 可执行入口（薄 CLI，import src/amta）
│   ├── benchmark.py        # Benchmark A/B/C（两阶段：emit crops → ingest 标注）
│   ├── ocr_detect.py / ocr_score.py      # Benchmark B（OCR 探测 + CER/EM 评分）
│   ├── recall_detect.py / recall_crop.py / recall_score.py  # recall 内容级匹配
│   ├── sfx_compare.py / merge_labels.py / baberu_ocr.py
│   ├── context7.py         # 文档查询（npm run ctx7:*）
│   ├── fastcheck.py / audit.py / smoke_test.py
│   └── start_koharu.ps1 / precheck.ps1 / install_hooks.ps1
├── tests/                  # 确定性单测（fastcheck 第 4 步）
├── docs/                   # progress / lessons / decisions（ADR-001..008）
├── context/                # <作品>.story.json / cast 种子（Phase 2）
├── testsets/               # benchmark 测试集（页面不入库）
├── output/                 # 运行产物（gitignored，除 data/ 白名单 JSON）
│   ├── data/               # 入库的 benchmark/label/recall JSON
│   ├── reports/            # HTML 报表（含原图+检测框+OCR 全文）
│   ├── crops/ recall_crops/ ocr_frag/ labels_frag/
│   └── logs/ tmp/
├── models/                 # 本地模型权重（gitignored：paddle-manga GGUF / llama-cpp / baberu-ocr）
└── .dsh/skills/             # 按需加载技能（DSH 原生技能根：benchmark/cycle-close/finisher/researcher/...）
```

## 引擎 DAG（v0.59.1 实证）

```
pp-doclayout-v3 / comic-text-detector / anime-text / comic-text-bubble-detector → TextBoxes
comic-text-detector-seg（needs TextBoxes）→ SegmentMask（像素级）
speech-bubble-segmentation → BubbleMask
manga-ocr / paddle-ocr-vl-1.5 / mit48px-ocr（needs TextBoxes）→ OcrText
llm（needs OcrText）→ Translations
lama-manga / flux2-klein / aot-inpainting（needs SegmentMask+BubbleMask）→ Inpainted
yuzumarker-font-detection（needs TextBoxes）→ FontPredictions
koharu-renderer（needs Inpainted+Translations+FontPredictions）→ FinalRender
```

框外字漏检根因：`pp-doclayout-v3` 是文档版面模型；`ctd_seg` 只细化已有框。
