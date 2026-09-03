# RUNBOOK — amta 漫画翻译管线运维手册

> 跑管线前必读。所有模型路径、源图位置、启动命令、已知坑全在这。
> 代码级路径以 `src/amta/paths.py` 为准，本文档可能滞后。

---

## 一、模型清单

### 检测层（Detect）

| 模型 | 路径 | 用途 | 默认参数 | 调用入口 |
|---|---|---|---|---|
| **RT-DETR-v2**（主线） | `models/CTBD/detector.onnx` | 单检测器，高阈值干净框 | conf=0.7 | `scripts/01_detect.py` → `detectrtdetr.RTDetrDetector` |
| Comic Text Detector | `models/CTD/comictextdetector.pt.onnx` | 四并集之一（旧方案） | — | 旧 detect 管线 |
| pp-doclayout-v3 | 待补充 | 四并集之一（旧方案） | — | 旧 detect 管线 |
| anime-text | 待补充 | 四并集之一（旧方案） | — | 旧 detect 管线 |
| comic-text-bubble-detector | 待补充 | 四并集之一（旧方案） | — | 旧 detect 管线 |

### OCR 层

| 模型 | 路径 | 用途 | 调用入口 |
|---|---|---|---|
| **HayaiOCR v2.1**（主线） | `E:\models\hayai-ocr-v2`（全局路径，不受 worktree 影响） | 最新 OCR，日文识别 | `scripts/02_ocr.py --engine hayai` |
| Baberu OCR | `models/baberu-ocr/onnx/` | 旧 OCR，onnx 量化 | `scripts/02_ocr.py --engine baberu` |
| PaddleOCR-VL-For-Manga | `models/paddle-manga/`（GGUF） | VLM OCR 备选 | llama.cpp 加载 |
| PaddleOCR-VL-1.6 | `models/paddle-vl16/`（GGUF） | VLM OCR 备选 | llama.cpp 加载 |
| MangaOCR | 待补充 | 旧 OCR 备选 | `scripts/02_ocr.py --engine manga_ocr` |

### 翻译层

| 组件 | 路径 | 用途 |
|---|---|---|
| 术语主词典 | `data/thbwiki_master_dict.json` | THBWiki 东方术语日文→中文映射 |
| 术语匹配引擎 | `src/amta/term_dict.py` | 三级匹配（精确/前缀/包含） |
| 术语预替换 | `src/amta/term_replace.py` | 翻译前直接字符串替换 |
| 全本预扫描 | `scripts/pre_scan.py` | 扫描所有页 OCR，锁定实际出现的术语 |
| 翻译引擎 | `src/amta/stage3_minimal.py` | DeepSeek LLM 翻译，集成术语预替换 |

---

## 二、源图清单

| work_id | 源图路径 | 页数 | 文件名规则 | page_idx 映射 |
|---|---|---|---|---|
| touhou-single-wing | `D:\我的汉化\汉化作品\东方\单翼停留之地\` | 42 | `0.jpg` ~ `41.jpg` | page_N = (N+1).jpg |

> 新增作品时，在此表追加一行。work_id 用英文短横线命名。

---

## 三、启动命令

### 全管线（推荐）

```bash
# 跑 page_1 到 page_10（对应源图 2.jpg ~ 11.jpg）
py scripts/00_run_all.py --work-id <work_id> --start-page 1 --end-page 10
```

> 注意：00_run_all 当前**不会自动跑 pre_scan**。术语层生效需要先手动跑 pre_scan。

### 单阶段（调试用）

```bash
# 1. 检测（conf=0.7）
py scripts/01_detect.py --work-id <work_id> --raw <源图.jpg> --out <detection.json> --page-idx <N> --conf 0.7

# 2. OCR（hayai）
py scripts/02_ocr.py --work-id <work_id> --det <detection.json> --raw <源图.jpg> --out <canon.json> --page-idx <N> --engine hayai

# 3. 术语预扫描（全本跑一次即可，锁定术语写入 work_state）
py scripts/pre_scan.py --work-id <work_id> --artifacts-dir <artifacts目录> --master-dict data/thbwiki_master_dict.json

# 4. 翻译（自动从 work_state 读取锁定术语做预替换）
py scripts/03_translate.py --canon <canon.json> --out <translation.json> --work-id <work_id>
```

### 生成报告

```bash
# 用 amta.report 模块生成 HTML 报告（detect + ocr + translate 三阶段对比）
# 参考 .tmp_gen_full_report.py 的写法
```

---

## 四、已知坑（跑之前看一眼）

1. **worktree 里没有 models/**：models/ 被 gitignore，在 worktree 里跑 detect 会找不到 detector.onnx。detect 只能在主 checkout 跑；hayai 在 E:\models\ 全局路径不受影响。

2. **ocr_engines 函数级默认是 baberu**：`ocr_engines.ocr_batch(crops)` 不传 engine 会静默拿到 baberu（代码滞后）。必须显式传 `engine="hayai"`，或走 `ocr_station.ocr_page()`（默认已是 hayai）。

3. **旧 canon 无 ocr_engine 字段 = 8-27 旧产物**：旧 canon 是裸 list 格式，没有 ocr_engine 字段。00_run_all 检查到文件存在就会 skip OCR，导致用旧 baberu 产物跑翻译。**重跑前必须删旧 canon**。

4. **全局 Python 环境容易被 pip 搞乱**：transformers/tokenizers/networkx 等包版本冲突会导致 hayai 导入失败。如果 hayai import 报错，先检查包版本是否被改动过。

5. **00_run_all 不集成 pre_scan**：术语层不会自动生效。必须先手动跑 pre_scan 锁定术语，再跑翻译。

---

## 五、产物目录约定

```
workspace/<work_id>/
├── artifacts/
│   ├── page_<N>_detection.json   # 检测框
│   ├── page_<N>_canon.json        # OCR 文本（含 ocr_engine 字段）
│   └── page_<N>_translation.json  # 翻译结果（含 glossary_violations）
└── state/
    └── work_state.json             # 术语表（pre_scan 写入）
```

---

*最后更新：2026-09-03 | 以 src/amta/paths.py 代码为准*
