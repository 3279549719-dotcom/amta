# AMTA — Automation Manga Translate Agent

自动化漫画翻译 Agent（会话驱动版）。

## 架构（本地执行器与可选远程模型）

```
DSH 会话（我）= 单 LLM Agent（导演）
  ├── 决策：规划 / 翻译判断 / 修复决策 / 验收
  ├── 眼睛：describe_image（Vision QA）
  └── 手：amta Python 执行器（本仓库）
        └── 统一入口 scripts/run_pipeline.py（detect → ocr → translate → inpaint → typeset）
```

- **执行边界**：默认 detect/OCR/inpaint/typeset 本地执行；translate 和显式选择的 VLM OCR 调用 API，后者会发送整页与裁图。PSD 导出使用本机 Photoshop。
- **translate 阶段用 DeepSeek API**（`.env` 的 CHAT_* 配置，ADR-014）
- **koharu v0.59.1 已退出主链路**——legacy 客户端（`src/amta/backends/koharu_client.py`、`scripts/start_koharu.ps1`）仅作历史保留，不要在主线路上依赖它
- **产物结构**：per-work workspace（`workspace/<work_id>/`，ADR-013）
- **环境自检门卫**：`scripts/run_pipeline.py` 启动时自动检查代理 / 模型 / `.env` / ROOT 路径，不通过直接报错，不需要人工检查环境
- **模型推理设备自动检测**（`cuda if available else cpu`），不硬编码设备
- **唯一入口三个**：跑管线 `scripts/run_pipeline.py`、看现状 `scripts/peek.py`、找产物 `scripts/artifact.py`
- 细节（接口、流程、坑全表）→ `CLAUDE.md`；决策索引 → `docs/decisions/README.md`

## 管线阶段

```
detect → ocr → translate → inpaint → typeset
```

阶段名以 `scripts/run_pipeline.py --help` 为准（现为 `detect,ocr,translate,inpaint,typeset,segment`）。
跑下游阶段必须带上所有上游依赖阶段（跑 typeset 必须含 detect,ocr,translate,inpaint），未变更的阶段由 artifact_cache 自动跳过。

## 目录

```
amta/                        # 本仓库根
├── src/amta/                # 纯库包（可被 import，脚本的上游）
│                            #   模块地图见 docs/module-map.md —— 由 `scripts/peek.py --index`
│                            #   自动生成、永远与代码同步；README 不再手抄模块清单
├── scripts/                 # 可执行入口（薄 CLI，只做参数解析与落盘，逻辑在 src/amta）
│   ├── archive/             # 退役脚本
│   └── probes/              # 一次性实验脚本
├── tests/                   # 确定性单测（fastcheck 的一步）
├── docs/                    # 坑库 lessons / 决策 ADR / 生成物模块地图
├── context/                 # <作品>.story.json / cast 种子
├── workspace/               # per-work 同人志工作区（ADR-013）
├── testsets/                # benchmark 测试集（页面不入库）
├── output/                  # 运行产物（gitignored）
│   ├── data/                # 入库的 benchmark/label/recall JSON
│   ├── reports/             # HTML 报表
│   ├── recall_crops/ ocr_frag/ labels_frag/   # 裁剪 / 片段产物
│   └── logs/ tmp/           # 日志 / 临时
├── models/                  # 本地模型权重（gitignored）
└── .dsh/skills/             # 按需加载技能（DSH 原生技能根）
```

## GUI

启动本地 Web GUI：

```bash
uv run python scripts/run_gui.py
```

浏览器自动打开 `http://127.0.0.1:8000`。

- 拖入一张或多张漫画页图片
- 选择 **Default**（hayai OCR）或 **VLM**（Qwen VLM，适合文字密集页）
- 点击 **Translate**
- 翻译完成后点击 **Export** 下载 PNG

需要 `.env` 配置 `CHAT_API_KEY`（DeepSeek 翻译），VLM 模式还需 `DASHSCOPE_API_KEY`（千问 VLM）。
