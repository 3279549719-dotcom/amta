# HTML 报告工具 — 深接口设计

**日期**: 2026-09-02
**分支**: feat/report-tool（基于 feat/simplify-pipeline-conf07）
**状态**: 已批准，待实现

## 1. 问题

仓库里已有 10+ 个报告脚本（gen_visual_report.py、gen_final_report.py、generate_visual_report.py、archive/ 下十几个），每个都是一次性平脚本：硬编码路径、硬编码阶段、硬编码 HTML。加一个新阶段（如未来的 segment / mask / typeset）就要重写整份脚本。变化点（阶段数据）和不变点（报告骨架）焊死在一起。

## 2. 第一性原理

剥掉所有样式和装饰，一份漫画管线报告**只能是**：

1. **一页原图**（物理锚点）
2. **这页上每个文本框在各阶段的产出**

即：报告 = 原图 + 区域×阶段矩阵。原图是锚，文本框是行，阶段是列。

## 3. 架构：一刀切开不变和变化

```
┌──────────────────────────────────────────────┐
│  报告引擎（不变，深模块）                       │
│  · 跨阶段区域对齐（region_id → bbox IoU 回退）  │
│  · 图层叠加合成                                │
│  · 表格布局 / HTML 壳 / CSS                    │
│  · 统计汇总 / 校验 / 可观测返回                 │
├──────────────────────────────────────────────┤ ← seam
│  阶段适配器（变化，可插拔）                     │
│  detect / ocr / filter / translate /          │
│  segment / mask / typeset …                   │
│  每个只负责：我有什么数据 + 怎么画一格           │
└──────────────────────────────────────────────┘
```

引擎永远不改。加阶段 = 写一个 StageOutput 适配器，往引擎里一塞。

## 4. 数据模型

### 4.1 StageOutput（阶段输出，自描述）

```python
@dataclass
class StageOutput:
    key: str                           # 唯一标识，如 "detect"
    label: str                         # 表头显示名，如 "检测框"
    cells: dict[str, Any]              # region_id → 该阶段数据
    render_cell: Callable              # 表格格子渲染函数（有默认）
    render_overlay: Callable | None    # 可选：在原图上画图层
    page_artifact: Any = None          # 可选：页级产物（mask图、final图路径）
```

### 4.2 PageReport（一页报告的全部输入）

```python
@dataclass
class PageReport:
    page_idx: int
    raw_image: str | Path              # 原图路径（构造时校验存在）
    stages: list[StageOutput]          # 顺序 = 表格列顺序
```

构造时校验：raw_image 存在、stages 非空、key 不重复。不合法直接 ValueError。

### 4.3 ReportResult（可观测返回）

```python
@dataclass
class ReportResult:
    html: str                          # 自包含 HTML（最终产物）
    page_idx: int
    stages_rendered: list[str]         # 实际渲染了哪些阶段
    regions_total: int                 # 并集区域数
    regions_aligned: int               # 跨阶段成功对齐的区域数
    regions_dropped: list[str]         # 因数据缺失被丢弃的区域
    warnings: list[str]                # 渲染期警告
    render_time_ms: float              # 渲染耗时
```

不返回裸字符串。调用方可以直接 inspect：哪些阶段渲染了、对齐率多少、有没有警告。

## 5. 接口（深模块唯一入口）

```python
def render_report(page: PageReport) -> ReportResult:
    """吃一页结构化数据，吐报告结果。纯函数，零 IO，零副作用。"""
```

调用方不需要知道引擎怎么对齐框、怎么叠图、怎么拼 HTML。

## 6. 职责切分

| 模块 | 职责 | 碰 IO? |
|---|---|---|
| `report.engine.render_report` | 纯渲染：数据 → HTML | 否（纯函数） |
| `report.assembler.load_page_report` | 从 artifacts 读 JSON → 组装 PageReport | 是 |
| `scripts/gen_report.py` | CLI 薄壳：解析参数 → 调 assembler → 调 engine → 写文件 | 是 |

引擎可单测（构造 PageReport 断言 ReportResult）。换数据源只改 assembler。

## 7. 区域对齐策略

1. 优先用 region_id 精确匹配
2. 匹配不上的用 bbox IoU > 0.5 物理匹配（复用 05b6e99 已验证逻辑）
3. 仍匹配不上 → 该区域在缺失阶段显示 `(缺失)`，记入 warnings

## 8. 模块结构

```
src/amta/report/
├── __init__.py           # 暴露 render_report, PageReport, StageOutput, ReportResult
├── model.py              # 数据模型 + 构造校验
├── engine.py             # render_report 核心：对齐 + 叠图 + HTML 生成
├── assembler.py          # load_page_report: artifacts JSON → PageReport
├── align.py              # 区域对齐（region_id + bbox IoU）
└── stages/
    ├── detect.py         # 检测框适配器
    ├── ocr.py            # OCR 适配器
    ├── filter.py         # 筛选留痕适配器
    ├── translate.py      # 翻译适配器
    ├── segment.py        # 预留（空壳）
    ├── mask.py           # 预留（空壳）
    └── typeset.py        # 预留（空壳）

scripts/gen_report.py     # CLI: --work-id --src-dir --pages --out
```

## 9. CLI 用法

```bash
python scripts/gen_report.py \
    --work-id my-manga \
    --src-dir "D:\path\to\images" \
    --pages 1-5 \
    --out output/report.html
```

## 10. 每页布局

- 顶部：统计栏（检测框数 / OCR 区域数 / 译文数 / 残留 / 术语违例）
- 左侧：原图（可叠加各阶段图层：检测框、蒙版等）
- 右侧：阶段对照表（每框一行，每阶段一列）
- 加新阶段 = 表格自动多一列 + 图层自动多一层

## 11. 验收标准

1. `render_report` 是纯函数，可单测
2. 输入校验前置（构造时抛 ValueError，不拖到渲染中间）
3. 返回 ReportResult，warnings/对齐率可观测
4. 1–5 页端到端跑通：detect(conf=0.7) → ocr(baberu) → translate(单LLM) → 报告
5. 报告包含：原图+检测框标注、逐框 OCR、筛选留痕、译文
6. 预留 segment/mask/typeset 阶段槽位（数据结构支持，渲染器可后补）
7. 报告发布为公网链接，用户可直接打开查看
