# Pipeline Orchestrator 设计文档

**日期**: 2026-09-02
**分支**: feat/pipeline-orchestrator
**状态**: 接口已定义，前 3 阶段已适配，后续 3 阶段预留

---

## 1. 背景与问题

### 1.1 现状

当前管线有两条并行的执行路径：

| 路径 | 范围 | 断点续跑 | 阶段可插拔 | 后续阶段支持 |
|---|---|---|---|---|
| `00_run_all.py` | detect→ocr→translate→review→judge→inpaint→typeset | ✓ | ✓（--with-* 开关） | ✓（已有钩子） |
| `full_pipeline_11_20.py` | 仅 ocr→translate | ✗ | ✗（硬编码） | ✗ |

`00_run_all.py` 用 `subprocess` 调用各阶段脚本，每加一个阶段就要在编排器里加 ~20 行重复代码（断点检测、subprocess 调用、日志记录、错误处理）。

三个现有工位的函数签名完全不同：

```python
detect_page(work_id, raw_page, artifacts_dir, *, page_idx, client, host, port, out_path)
ocr_page(work_id, det, raw_page, artifacts_dir, *, page_idx, engine, vlm_enabled, ocr_fn, ...)
translate_page(work_id, canon, *, state_dir, page, mode, raw_image_path, llm_text, ...)
```

参数名不统一（`raw_page` vs `raw_image_path`），返回值都是裸 `dict`，没有统一的结果结构。

### 1.2 问题

1. **编排器与工位耦合**：编排器需要知道每个工位的脚本路径、CLI 参数、输出文件名
2. **新增阶段成本高**：每加一个阶段要改编排器 + 写脚本 + 处理重复逻辑
3. **两条路径并存**：`full_pipeline_11_20.py` 与 `00_run_all.py` 功能重复，维护成本翻倍
4. **后续阶段（inpaint/typeset/segment）未接入**：需要一个统一的接口来降低接入成本

---

## 2. 设计目标

### 2.1 核心目标

- **统一工位接口**：所有工位函数接受相同的输入结构，返回相同的输出结构
- **声明式阶段注册**：阶段之间的依赖关系用配置声明，编排器自动解析
- **编排器与工位解耦**：编排器只依赖工位接口，不依赖具体实现
- **后续阶段零改动接入**：新增 inpaint/typeset/segment 不需要改编排器

### 2.2 非目标

- 不重写现有工位的内部逻辑（detect_station / ocr_station / translate_station 保持不变）
- 不实现后续阶段的工位逻辑（只预留接口和 schema）
- 不做分布式执行 / 并行调度（YAGNI，当前线性管线够用）
- 不立即废弃 `00_run_all.py`（新旧并存一段时间，验证后再迁移）

---

## 3. 模块架构（codebase-design 词汇）

### 3.1 Module 划分

```
amta.orchestrator（深模块）
├── context.py      — 数据契约：StationContext / StationResult / PipelineConfig / PipelineResult
├── registry.py     — 阶段注册表：StageSpec + STAGES（声明式依赖）
├── pipeline.py     — 编排器核心：run_pipeline()（唯一公共入口）
└── adapters/       — 工位适配器：把统一接口桥接到现有工位
    ├── detect.py
    ├── ocr.py
    └── translate.py
```

### 3.2 Seam（接缝）位置

**主接缝**：在"阶段定义"和"执行逻辑"之间。

- 接缝一侧：`registry.py` 声明每个阶段的 `StageSpec`（工位函数是谁、依赖什么、产出什么、默认配置）
- 接缝另一侧：`pipeline.py` 的 `run_pipeline()` 遍历页面和阶段，调用工位函数

编排器只依赖 `StageSpec` 声明，不需要知道每个工位内部做什么。

**内部接缝**：在"统一工位接口"和"现有工位实现"之间。

- `adapters/` 里的每个适配器是一个 **Adapter**（codebase-design 术语）：在 seam 处满足统一接口，内部调用现有工位函数
- 现有工位是"大实现"，适配器是"小适配器"——现有工位不需要改，编排器也不需要知道现有工位的签名差异

### 3.3 Depth（深度）分析

**编排器的深度**：
- 外部接口：`run_pipeline(config: PipelineConfig) -> PipelineResult`（一个函数）
- 内部实现：页面循环、阶段循环、断点检测、上下文构建、上游依赖检查、日志追踪、错误处理、结果汇总（~200 行）
- 调用方学一个函数，就能用所有这些能力 → **深模块**

**工位适配器的深度**：
- 外部接口：`run(ctx: StationContext) -> StationResult`（一个函数）
- 内部实现：参数提取、调用现有工位、结果包装、异常捕获（~30 行每个）
- 浅但合理——适配器本来就应该薄，复杂度在现有工位里

### 3.4 Deletion test（删除测试）

> 想象删掉 orchestrator 模块，复杂度会消失吗？

不会。删掉之后：
- 断点续跑逻辑要回到每个脚本里
- 阶段依赖关系要硬编码在编排脚本里
- 日志追踪要重复实现
- 新增阶段要改 N 个地方

所以这个模块**有存在价值**，不是 pass-through。

### 3.5 Leverage（杠杆）与 Locality（局部性）

- **Leverage**：调用方构造一个 `PipelineConfig`，就能跑任意阶段组合，不需要知道断点怎么判断、上游产物怎么传递、日志怎么记录
- **Locality**：新增阶段的改动只发生在两个地方——写一个工位适配器 + 在 `registry.py` 加一行注册。编排器不需要改

---

## 4. 接口定义

### 4.1 工位侧接口

```python
@dataclass
class StationContext:
    """工位执行上下文 — 所有工位的统一输入。"""
    work_id: str
    page: str               # 页键，如 "page_11"（0 基）
    page_idx: int           # 页号整数，如 11
    raw_image: Path         # 原始图片路径
    artifacts_dir: Path     # 产物目录
    state_dir: Path         # 状态目录（work_state / pipeline_log / tickets）
    inputs: dict[str, Path] # 上游产物路径，按阶段名索引
    config: dict[str, Any]  # 本阶段配置

@dataclass
class StationResult:
    """工位执行结果 — 所有工位的统一输出。"""
    page: str
    stage: str
    status: str             # "ok" / "skipped" / "failed"
    output_artifact: Path | None
    duration_s: float
    error: str | None
    stats: dict[str, Any]   # 阶段特定统计（框数/区域数/译文数等）

# 工位函数签名
StationFn = Callable[[StationContext], StationResult]
```

### 4.2 编排器侧接口

```python
@dataclass
class PipelineConfig:
    work_id: str
    src_dir: Path
    start_page: int                     # 1 基（对应文件名）
    end_page: int                       # 1 基（包含）
    stages: list[str] = ["detect", "ocr", "translate"]
    stage_configs: dict[str, dict] = {}
    force_rerun: bool = False
    continue_on_error: bool = False

@dataclass
class PipelineResult:
    run_id: str
    work_id: str
    pages: list[str]
    stages: list[str]
    results: dict[str, dict[str, StationResult]]  # {page: {stage: result}}
    total_duration_s: float
    failed_pages: list[str]
    failed_step: dict | None

def run_pipeline(config: PipelineConfig) -> PipelineResult
```

### 4.3 阶段注册接口

```python
@dataclass
class StageSpec:
    name: str
    station: StationFn
    consumes: list[str]     # 依赖的上游阶段名
    produces: str           # 产出的产物类型名（对应 artifact_paths 的 key）
    default_config: dict
```

---

## 5. 阶段注册表

### 5.1 当前已实现阶段

| 阶段 | consumes | produces | 工位 | 状态 |
|---|---|---|---|---|
| detect | [] | detection | adapters/detect.py | ✓ 已适配 |
| ocr | [detect] | canon | adapters/ocr.py | ✓ 已适配 |
| translate | [ocr] | translation | adapters/translate.py | ✓ 已适配 |

### 5.2 后续预留阶段

| 阶段 | consumes | produces | 工位 | 状态 |
|---|---|---|---|---|
| inpaint | [detect] | inpaint | _not_implemented | 预留，依赖 inpaint_strategy.py（已有纯函数引擎） |
| typeset | [translate, inpaint] | typeset | _not_implemented | 预留，依赖 typeset_engine.py（已有纯函数引擎） |
| segment | [detect] | segment | _not_implemented | 预留，需求待确认 |

### 5.3 接入后续阶段的步骤

以 inpaint 为例：

1. 写 `src/amta/orchestrator/adapters/inpaint.py`，实现 `run(ctx: StationContext) -> StationResult`
   - 从 `ctx.inputs["detect"]` 读取 detection artifact
   - 调用 `inpaint_strategy.plan_inpaint()` + 实际擦除引擎
   - 产出 `{artifacts_dir}/{page}_inpaint.json`
   - 返回 `StationResult`
2. 在 `registry.py` 的 `_build_registry()` 中，把 `inpaint` 的 `station` 从 `_not_implemented("inpaint")` 换成 `inpaint_run`
3. 运行时在 `PipelineConfig.stages` 里加 `"inpaint"`

**编排器不需要改一行代码。**

---

## 6. 现有工位适配方案

### 6.1 适配原则

- **不修改现有工位**：`detect_station.detect_page` / `ocr_station.ocr_page` / `translate_station.translate_page` 保持不变
- **薄适配器**：每个适配器只做参数提取 + 调用 + 结果包装 + 异常捕获
- **配置映射**：`ctx.config` 里的键名与现有工位的参数名对齐

### 6.2 配置映射表

| 阶段 | ctx.config 键 | 现有工位参数 | 默认值 |
|---|---|---|---|
| detect | host | host | "127.0.0.1" |
| detect | port | port | 4000 |
| ocr | engine | engine | "auto" |
| ocr | vlm_enabled | vlm_enabled | False |
| translate | mode | mode | "minimal" |
| translate | vlm_enabled | vlm_enabled | True |

---

## 7. Artifact Schema 预留

在 `artifacts.py` 中新增三个 TypedDict（`total=False`，字段可选）：

- `InpaintArtifact`：clean_image, masks, plan
- `TypesetArtifact`：final_image, layout
- `SegmentArtifact`：segments

工位实现时填充具体字段，编排器不依赖这些字段（只依赖产物文件存在性做断点判断）。

---

## 8. 与现有代码的关系

### 8.1 `00_run_all.py`

- 新旧并存，不立即废弃
- `run_pipeline.py`（新 CLI）功能覆盖 `00_run_all.py` 的核心场景
- 验证稳定后，`00_run_all.py` 可以标记为 deprecated，最终删除
- `00_run_all.py` 独有的 semantic review / AI judge 功能，可以作为额外阶段注册到编排器

### 8.2 `full_pipeline_11_20.py`

- 功能完全被新编排器覆盖
- 建议直接废弃，用 `run_pipeline.py --start-page 11 --end-page 20` 替代
- 本次分支中不删除，等验证后清理

### 8.3 `pipeline.py`（旧）

- 旧的 `src/amta/pipeline.py` 只包含步骤常量和引擎依赖（FULL_STEPS, ENGINE_NEEDS 等）
- 与新编排器不冲突，旧常量保留供参考
- 未来可以考虑把旧常量迁移到 registry，但不是本次目标

---

## 9. 验证计划

### 9.1 单元测试

- [ ] `test_orchestrator_context.py`：StationContext / StationResult / PipelineConfig 构造
- [ ] `test_orchestrator_registry.py`：阶段注册表加载、未知阶段报错
- [ ] `test_orchestrator_pipeline.py`：用 fake 工位测试断点续跑、错误处理、页面循环
- [ ] `test_adapters_*.py`：每个适配器用 fake 工位函数测试参数映射和结果包装

### 9.2 集成验证

- [ ] 用 11-20 页跑 `run_pipeline.py --stages detect,ocr,translate`，与 `00_run_all.py` 结果对比
- [ ] 验证断点续跑：第二次运行所有阶段 skipped
- [ ] 验证 `--force-rerun`：强制重跑所有阶段
- [ ] 验证后续阶段占位：`--stages detect,ocr,translate,inpaint` 报清晰的"未实现"错误

### 9.3 验收标准

- 前 3 阶段输出与 `00_run_all.py` 完全一致（产物文件逐字节对比）
- 新增阶段不需要改 `pipeline.py`
- 所有工位返回统一的 `StationResult`
- 断点续跑、日志追踪、错误处理与旧版行为一致

---

## 10. 后续讨论（不在本次范围）

- 翻译质量提升：术语模块、上下文机制、VLM 校验的系统化设计（单独讨论）
- inpaint / typeset 工位的具体实现
- text segmentation 的需求定义（当前不清楚是哪种 segmentation）
- 编排器的并行执行（页面间并行 / 阶段间并行）
- 旧脚本（`00_run_all.py` / `full_pipeline_11_20.py`）的废弃时间表
