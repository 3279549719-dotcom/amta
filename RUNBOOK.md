# RUNBOOK — 环境清单与已知坑

> **本文件不放命令。** 命令的唯一归属是 `CLAUDE.md` 的关键入口表（它们是活指针，会随代码更新）。
> 这里只放**环境事实**（模型在哪、源图在哪）和**坑**——这两类东西不会因为重构而失效。
>
> 训条：**任何写进本文档的路径，都必须先 `Test-Path` 核实过。** 2026-09-12 体检时
> 本文档有 13 条路径/命令指向已删除的东西（编号脚本、重构前的扁平模块路径），
> 全部是"当时写对了、后来没人跟"造成的。**手写的路径清单必然腐烂**——
> 所以命令一概不写在这里，只写在 CLAUDE.md（那里有守卫盯着，见 `tests/test_reference_integrity.py` 的 S4）。

---

## 一、模型清单（全部经 Test-Path 核实，2026-09-12）

### 检测层

| 模型 | 路径 | 备注 |
|---|---|---|
| **RT-DETR-v2**（主线） | `models/CTBD/detector.onnx` | 单检测器 |
| Comic Text Detector | `models/CTD/comictextdetector.pt.onnx` | 旧方案留存 |

### OCR 层

| 模型 | 路径 | 备注 |
|---|---|---|
| Baberu OCR | `models/baberu-ocr/onnx` | ONNX，CPU 快路径 |
| HayaiOCR v2.1 | `E:\models\hayai-ocr-v2` | **全局路径**，不受 worktree 影响 |
| PaddleOCR-VL-For-Manga | `models/paddle-manga` | GGUF |
| PaddleOCR-VL-1.6 | `models/paddle-vl16` | GGUF |

### Inpaint / 术语

| 组件 | 路径 |
|---|---|
| lama-manga 权重 | `models/big-lama.pt` |
| 术语主词典 | `data/thbwiki_master_dict.json` |

---

## 二、源图清单

| work_id | 源图路径 | 文件名规则 |
|---|---|---|
| touhou-single-wing | `D:\我的汉化\汉化作品\东方\单翼停留之地\` | `N.jpg`（1 基，与 `--start-page/--end-page` 对齐） |
| touhou-getten-shinchi | `D:\我的汉化\汉化作品\东方\月天新地_单页\` | `N.jpg`（1–67，跨页已按日漫右→左顺序拆分） |

> 新增作品时在此表追加一行。work_id 用英文短横线命名。

---

## 三、已知坑（跑之前看一眼）

1. **worktree 里没有 `models/`**——`models/` 被 gitignore，在 worktree 里跑 detect 会找不到权重。
   `fastcheck` 的 ROOT 检查会拦这个（它断言 `models/CTBD/detector.onnx` 与 `models/big-lama.pt` 存在）。

2. **`ocr_engines.ocr_batch()` 的引擎默认值是 `baberu`，不是 hayai**。
   不显式传 `engine=` 就会静默走 baberu。走 `ocr_station` 则默认已是 hayai。
   （这不是 bug，是历史默认值——但静默降级很难发现，所以记在这里。）

3. **Hayai 的模型在全局路径 `E:\models\hayai-ocr-v2`**，不在仓库内。换机器必须重新放。

4. **一律用 `uv run python`，禁止裸 `python`。**
   `uv` 环境里有 ruff 0.16.6 / pytest 9.1.1；全局 Python 的版本可能不同，
   会出现"同一条命令两个判定"（L26 的老账）。`package.json` 的脚本已全部对齐 `uv run python`。

5. **koharu v0.59.1 已退出主链路**（ADR-029）。仅存 legacy 客户端（`src/amta/backends/koharu_client.py`）
   与启动脚本，不要在主线路上依赖它。现管线全本地，只有 translate 阶段需要 LLM API（ADR-014）。

---

## 四、产物目录约定

```
workspace/<work_id>/
├── raw/                        # 源图副本
├── artifacts/                  # 各阶段产物（canon / detection / inpaint / typeset / final ...）
└── state/work_state.json       # 术语表（pre_scan 写入）

output/                         # 运行产物（gitignored）
├── data/                       # 入库的 benchmark / label JSON
├── reports/                    # HTML 报表
└── logs/  tmp/
```

> 查产物**不要翻目录**，用 `artifact.py query`（见 CLAUDE.md 关键入口表）。

---

*最后更新：2026-09-12。代码级路径以 `src/amta/common/paths.py` 为准。*
