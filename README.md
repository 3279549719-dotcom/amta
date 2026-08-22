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
├── src/
│   ├── koharu_client.py    # Koharu REST API 封装（建项目/传图/流水线/轮询/场景/mask/导出）
│   ├── pipeline.py         # 流水线步骤常量 + 引擎 DAG 知识
│   ├── benchmark.py        # Benchmark A/B/C 脚本
│   └── story_memory.py     # Story Memory 读写（Phase 2）
├── context/                # <作品>.story.json / cast 种子
├── testsets/               # benchmark 测试集（页面 + 结果）
├── output/                 # benchmark 报告
└── scripts/
    ├── start_koharu.ps1    # 启动 koharu headless
    └── smoke_test.py       # API 冒烟测试
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
