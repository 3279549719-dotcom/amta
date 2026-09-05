# Orchestrator 全阶段接线设计文档

**日期**: 2026-09-05
**分支**: 待创建（建议 `feat/orchestrator-full-stages`）
**状态**: 设计稿，待用户审阅
**前置文档**: [2026-09-02-pipeline-orchestrator-design.md](./2026-09-02-pipeline-orchestrator-design.md)、[ADR-029 lama-manga 本地推理](../decisions/029-lama-manga-local-inference.md)

---

## 1. 背景与问题

### 1.1 现状

Orchestrator（管线编排器）已于 2026-09-02 定义了统一工位接口（`StationContext` / `StationResult`）和声明式阶段注册（`StageSpec`），但目前只接好了 **ocr** 和 **translate** 两个工位。其余三个阶段均为占位符：

| 阶段 | registry 状态 | 实际逻辑位置 | 说明 |
|---|---|---|---|
| detect | `_not_implemented("detect")` | `scripts/01_detect.py` + `scripts/detect_rtdetr.py` | 旧适配器对着已删除的 `amta.detect_station` 写，从未可用 |
| inpaint | `_not_implemented("inpaint")` | `scripts/04_inpaint.py` | 仍在用 KoharuClient HTTP 调用，未切换到本地 LaMa |
| typeset | `_not_implemented("typeset")` | `scripts/05_typeset.py` | 纯本地渲染，无外部依赖 |
| segment | `_not_implemented("segment")` | 无 | 需求待确认，本次不涉及 |

结果：新编排器 `run_pipeline.py` 无法从原始图片跑端到端——detect 占位符返回 failed → ocr 报"上游阶段缺失" → 整条链断。旧路径 `00_run_all.py` 仍是唯一能跑全流程的入口。

### 1.2 问题

1. **detect/inpaint/typeset 逻辑散落在 `scripts/` 目录**，以 CLI 脚本形式存在，没有对应的 `src/amta/` 库函数。ocr 和 translate 已经抽成了 `ocr_station.py` / `translate_station.py`，但这三个没有跟上。
2. **inpaint 主工位未执行 ADR-029 决策**：ADR-029（2026-09-04）已明确用本地 lama-manga 替代 Koharu HTTP，`LocalLamaInpainter` 类已就绪且测试通过，但 `04_inpaint.py` 仍在调用 `KoharuClient`。
3. **新旧两条路径并存**，维护成本翻倍，且新编排器的架构优势（统一接口、声明式依赖、加阶段零改动编排器）无法发挥。

---

## 2. 设计目标

### 2.1 核心目标

- **detect/inpaint/typeset 抽成 `src/amta/` 库函数**，与 ocr_station / translate_station 对齐
- **写三个薄适配器**，把统一 `StationContext` 桥接到库函数
- **registry 占位符替换为真实适配器**，使 `run_pipeline.py` 能从原始图片跑通 detect→ocr→translate→inpaint→typeset 全五阶段
- **inpaint 同步切换到本地 lama-manga**（ADR-029），消除 Koharu HTTP 依赖

### 2.2 非目标

- 不重写各工位的内部算法（检测模型、inpaint 策略、排版引擎保持不变）
- 不立即删除 `00_run_all.py`（新旧并存，验证稳定后再废弃）
- 不实现 segment 阶段（需求待确认）
- 不做并行执行（当前线性管线够用）
- 不移植 `00_run_all.py` 的 `_ensure_terms()` / `_refresh_merged_translation()` 到 orchestrator（作为后续独立任务）

---

## 3. 模块架构

### 3.1 新增文件

```
src/amta/
├── detect_station.py       # 新增：从 scripts/01_detect.py + detect_rtdetr.py 抽取
├── inpaint_station.py      # 新增：从 scripts/04_inpaint.py 抽取，切换到 LocalLamaInpainter
├── typeset_station.py      # 新增：从 scripts/05_typeset.py 抽取
└── orchestrator/adapters/
    ├── detect.py           # 新增：detect 工位适配器
    ├── inpaint.py          # 新增：inpaint 工位适配器
    └── typeset.py          # 新增：typeset 工位适配器
```

### 3.2 修改文件

```
src/amta/orchestrator/registry.py    # detect/inpaint/typeset 三个占位符换真实适配器
scripts/01_detect.py                 # 改为 import detect_station.detect_page，保留 CLI 入口
scripts/04_inpaint.py                # 改为 import inpaint_station.run，保留 CLI 入口
scripts/05_typeset.py                # 改为 import typeset_station.run，保留 CLI 入口
```

### 3.3 Seam（接缝）位置

**主接缝**：在"库函数"和"适配器"之间，与现有 ocr/translate 模式一致。
- 接缝一侧：`detect_station.detect_page()` / `inpaint_station.run()` / `typeset_station.run()` —— 纯函数，接受明确参数，返回 dict
- 接缝另一侧：`adapters/detect.py` 等 —— 从 `StationContext` 提取参数，调用库函数，包装成 `StationResult`

**内部接缝（inpaint）**：在"inpaint 策略"和"推理引擎"之间。
- `inpaint_strategy.plan_inpaint()` 决定哪些框涂白、哪些框需要 inpaint（不变）
- `LocalLamaInpainter.inpaint(image, mask)` 执行实际推理（替换 KoharuClient）

---

## 4. detect_station 设计

### 4.1 模块内容

将 `scripts/01_detect.py` 的 `detect_page()` 函数和 `scripts/detect_rtdetr.py` 的 `RTDetrDetector` 类移到 `src/amta/detect_station.py`。

`scripts/detect_rtdetr.py` 是一个独立的 ONNX 检测器封装，约 100 行。移入后作为 `detect_station.py` 的内部实现（不单独成模块，因为只有 detect 用它）。

### 4.2 函数签名

```python
def detect_page(
    work_id: str,
    raw_page: Path,
    out_dir: Path,
    *,
    page_idx: int | None = None,
    conf_threshold: float = 0.7,
    out_path: Path | None = None,
) -> dict:
    """单页检测：RT-DETR-v2 → detection.json（doc 信封格式）。"""
```

签名与现有 `scripts/01_detect.py` 完全一致，零改动迁移。

### 4.3 输出格式

```python
{
    "work_id": str,
    "page": str,               # "page_11"
    "source_engines": ["rtdetr-v2"],
    "n_boxes": int,
    "per_engine_boxes": {"rtdetr-v2": int},
    "conf_threshold": float,
    "elapsed_s": float,
    "blocks": list[dict],      # 检测框列表
}
```

### 4.4 scripts/01_detect.py 变更

改为薄 CLI 包装：

```python
from amta.detect_station import detect_page

def main() -> int:
    # argparse 不变
    doc = detect_page(a.work_id, a.raw, a.out.parent, ...)
    print(...)
```

---

## 5. inpaint_station 设计

### 5.1 核心变更：Koharu → 本地 LaMa

当前 `04_inpaint.py` 的 inpaint 流程：
```
KoharuClient.create_project → import_page → run_inpaint(mask) → fetch_inpainted(WEBP) → 整页替换
```

新流程（ADR-029）：
```
LocalLamaInpainter(model_type="lama-manga").inpaint(image, mask) → 整页替换
```

`LocalLamaInpainter.inpaint(image, mask)` 接受 PIL Image 和 mask，返回 PIL Image。内部已实现整页推理（缩小到 1024 宽 → 推理 → 放大回原尺寸 → mask 羽化 alpha 混合），与 Koharu 参考实现对齐。

### 5.2 函数签名

```python
def run(
    work_id: str,
    det_path: Path,
    raw_page: Path,
    out_path: Path,
    clean_dir: Path | None = None,
    dry_run: bool = False,
    refine_mask: bool = False,
    inpaint_engine: str = "lama-manga",
) -> dict:
    """单页 inpaint：detection.json + raw → clean.png + inpaint.json。"""
```

参数变化：
- 移除 `host` / `port`（不再需要 Koharu 服务）
- `inpaint_engine` 默认值从 `"lama-manga"` 保持不变，但现在直接映射到 `LocalLamaInpainter(model_type=...)`
- 保留 `refine_mask`（框内精修 mask，Plan A）

### 5.3 执行流程

```
1. 读 detection.json → blocks
2. plan_inpaint(blocks) → 分类为 FILL_WHITE / INPAINT / SKIP
3. 如果有 INPAINT 框：
   a. 构建 mask（矩形或精修，refine_mask 控制）
   b. LocalLamaInpainter(model_type="lama-manga").inpaint(raw_img, mask) → inpainted_img
   c. 整页替换 img = inpainted_img
4. 对 FILL_WHITE 框重放涂白（保险）
5. 保存 clean.png 到 clean_dir/{page}_clean.png
6. 写 inpaint.json（含 clean_image 路径）
```

### 5.4 模型加载策略

`LocalLamaInpainter` 初始化会加载模型（约 195MB，CPU 推理）。在 orchestrator 中，每页都会调用适配器 → 每次都重新加载模型会非常慢。

**方案**：在 `inpaint_station.py` 模块级别缓存单例：

```python
_inpainter: LocalLamaInpainter | None = None

def _get_inpainter() -> LocalLamaInpainter:
    global _inpainter
    if _inpainter is None:
        _inpainter = LocalLamaInpainter(device="cpu", model_type="lama-manga")
    return _inpainter
```

这样 orchestrator 跑多页时只加载一次模型。旧 CLI 脚本单页运行时也只加载一次。

### 5.5 输出格式

```python
{
    "work_id": str,
    "page": str,
    "actions": list[dict],       # plan_inpaint 结果
    "checks": {
        "filled": int,
        "inpainted": int,
        "skipped": int,
        "size_ok": True,
        "refine_mask": bool,
        "inpaint_engine": "lama-manga",
        "pixel_diff_ratio": float,
    },
    "clean_image": str,          # clean.png 相对路径（typeset 用）
    "dry_run": bool,
    "generated_at": str,
}
```

新增 `clean_image` 字段（`InpaintArtifact` TypedDict 已预留），供 typeset 阶段读取 clean 图路径。

---

## 6. typeset_station 设计

### 6.1 模块内容

将 `scripts/05_typeset.py` 的 `run()` 函数移到 `src/amta/typeset_station.py`。逻辑不变：读 canon + translation + detection + clean 图 → 逐框渲染译文 → 保存 final.png + typeset.json。

### 6.2 函数签名

```python
def run(
    work_id: str,
    canon_path: Path,
    trans_path: Path,
    det_path: Path,
    clean_path: Path,
    out_path: Path,
    final_path: Path,
) -> dict:
    """单页排版：clean 图 + canon + translation + detection → final.png + typeset.json。"""
```

签名与现有 `scripts/05_typeset.py` 完全一致，零改动迁移。

### 6.3 依赖说明

typeset 需要四个输入：
- `canon_path`：来自 ocr 阶段
- `trans_path`：来自 translate 阶段
- `det_path`：来自 detect 阶段（用于 node_id → bbox 映射）
- `clean_path`：来自 inpaint 阶段（擦除后的底图）

在 orchestrator 的 `consumes` 声明中，typeset 依赖 `["translate", "inpaint"]`。det_path 通过 `ctx.inputs["detect"]` 获取（detect 是更早的阶段，其产物路径在 page_results 中可查）。

---

## 7. 适配器设计

三个适配器均遵循现有 ocr/translate 适配器的模式：

```python
def run(ctx: StationContext) -> StationResult:
    t0 = time.perf_counter()
    try:
        # 1. 从 ctx.inputs 取上游产物
        # 2. 从 ctx.config 读阶段配置
        # 3. 调用库函数
        # 4. 从 artifacts.artifact_paths 取输出路径
        # 5. 返回 StationResult(status="ok", output_artifact=..., stats={...})
    except Exception as e:
        return StationResult(status="failed", error=f"{type(e).__name__}: {str(e)[:200]}")
```

### 7.1 detect 适配器

```python
def run(ctx: StationContext) -> StationResult:
    # 无上游依赖（consumes=[]）
    # config: conf_threshold (默认 0.7)
    # 调用 detect_station.detect_page(work_id, raw_image, artifacts_dir, page_idx, conf_threshold)
    # 产出: artifacts_dir/{page}_detection.json
    # stats: n_boxes
```

### 7.2 inpaint 适配器

```python
def run(ctx: StationContext) -> StationResult:
    # 上游依赖: ctx.inputs["detect"] → detection.json
    # config: refine_mask (默认 False), inpaint_engine (默认 "lama-manga")
    # clean_dir = artifacts_dir / "clean"
    # 调用 inpaint_station.run(work_id, det_path, raw_image, out_path, clean_dir, refine_mask, engine)
    # 产出: artifacts_dir/{page}_inpaint.json + artifacts_dir/clean/{page}_clean.png
    # stats: filled, inpainted, skipped, pixel_diff_ratio
```

### 7.3 typeset 适配器

```python
def run(ctx: StationContext) -> StationResult:
    # 上游依赖: ctx.inputs["translate"] → translation.json
    #           ctx.inputs["inpaint"] → inpaint.json（从中读 clean_image 路径）
    #           det_path 通过 page_results["detect"].output_artifact 获取
    #           canon_path 通过 page_results["ocr"].output_artifact 获取
    # final_dir = artifacts_dir / "final"
    # 调用 typeset_station.run(work_id, canon_path, trans_path, det_path, clean_path, out_path, final_path)
    # 产出: artifacts_dir/{page}_typeset.json + artifacts_dir/final/{page}_final.png
    # stats: n_rendered, n_skipped_no_bbox, n_overflow
```

**注意**：typeset 的 `consumes` 声明为 `["translate", "inpaint"]`，但它还需要 detect 和 ocr 的产物。orchestrator 的 `_build_context` 会把所有已完成阶段的 `output_artifact` 放进 `page_results`，适配器可以直接从 `page_results` 中查找。但 `StationContext.inputs` 只包含 `consumes` 声明的阶段。

**解决方案**：在 typeset 适配器中，除了 `ctx.inputs`，还需要访问 detect 和 ocr 的产物路径。由于适配器函数签名只接受 `ctx: StationContext`，我们有两个选择：

- **方案 A（推荐）**：把 typeset 的 `consumes` 改为 `["detect", "ocr", "translate", "inpaint"]`，这样四个上游产物都进 `ctx.inputs`。虽然 typeset 的直接逻辑依赖是 translate + inpaint，但它确实需要 detect 和 ocr 的产物，声明全部依赖更诚实。
- **方案 B**：适配器从 `ctx.artifacts_dir` 按命名约定自己拼路径（`{page}_detection.json`、`{page}_canon.json`），不依赖 inputs。但这样绕过了 orchestrator 的依赖检查机制。

**采用方案 A**：typeset 的 `consumes = ["detect", "ocr", "translate", "inpaint"]`。

---

## 8. Registry 更新

`registry.py` 的 `_build_registry()` 中，三个占位符替换为：

```python
from .adapters.detect import run as detect_run
from .adapters.inpaint import run as inpaint_run
from .adapters.typeset import run as typeset_run

"detect": StageSpec(
    name="detect",
    station=detect_run,
    consumes=[],
    produces="detection",
    default_config={"conf_threshold": 0.7},
),
"inpaint": StageSpec(
    name="inpaint",
    station=inpaint_run,
    consumes=["detect"],
    produces="inpaint",
    default_config={"refine_mask": False, "inpaint_engine": "lama-manga"},
),
"typeset": StageSpec(
    name="typeset",
    station=typeset_run,
    consumes=["detect", "ocr", "translate", "inpaint"],
    produces="typeset",
    default_config={},
),
```

`segment` 保持占位符不变。

---

## 9. Artifact 路径确认

`artifacts.artifact_paths(artifacts_dir, page)` 已包含以下键（`src/amta/artifacts.py:114`）：

| key | 路径 | 用途 |
|---|---|---|
| `detection` | `{artifacts_dir}/{page}_detection.json` | detect 产出 |
| `canon` | `{artifacts_dir}/{page}_canon.json` | ocr 产出 |
| `translation` | `{artifacts_dir}/{page}_translation.json` | translate 产出 |
| `inpaint` | `{artifacts_dir}/{page}_inpaint.json` | inpaint 产出 |
| `typeset` | `{artifacts_dir}/{page}_typeset.json` | typeset 产出 |

clean 图和 final 图不在 `artifact_paths` 中，分别存放在：
- `{artifacts_dir}/clean/{page}_clean.png`
- `{artifacts_dir}/final/{page}_final.png`

这与 `00_run_all.py` 当前的约定一致（`_out(ws_root, "clean")` / `_out(ws_root, "final")`）。

---

## 10. 与旧代码的关系

### 10.1 scripts/01_detect.py / 04_inpaint.py / 05_typeset.py

抽取后，这三个脚本改为薄 CLI 包装，import 对应的 `*_station` 模块。保留 CLI 入口是为了：
- 单阶段调试时可以直接跑
- `00_run_all.py` 继续通过 subprocess 调用它们（旧路径不受影响）

### 10.2 scripts/detect_rtdetr.py

内容移入 `src/amta/detect_station.py` 后，原文件可以删除。但为了不破坏可能的其他引用，先保留并加 deprecation 注释，验证无引用后再删。

### 10.3 00_run_all.py

**本次不修改、不废弃。** 旧路径继续可用。新编排器跑通并验证稳定后，再单独做废弃工作（需要先移植 `_ensure_terms()` 和 `_refresh_merged_translation()`）。

---

## 11. 验证计划

### 11.1 单元测试

- `test_detect_station.py`：detect_page 输出格式、conf_threshold 生效
- `test_inpaint_station.py`：用小图验证 clean 图产出、pixel_diff_ratio > 0、dry_run 不写图
- `test_typeset_station.py`：用 fake canon/trans/det/clean 验证 final 图产出
- `test_orchestrator_adapters.py`：三个适配器用 fake 工位函数验证参数映射和结果包装

### 11.2 集成验证（按阶段递进）

1. **detect→ocr→translate**：用 1 张测试图跑 `run_pipeline.py --stages detect,ocr,translate`，与 `00_run_all.py` 输出对比（detection.json / canon.json / translation.json 逐字段对比）
2. **+inpaint**：加 `--stages detect,ocr,translate,inpaint`，验证 clean.png 产出且 pixel_diff_ratio > 0
3. **+typeset**：加 `--stages detect,ocr,translate,inpaint,typeset`，验证 final.png 产出
4. **断点续跑**：第二次运行所有阶段 skipped
5. **--force-rerun**：强制重跑所有阶段

### 11.3 验收标准

- 五阶段从原始图片端到端跑通，无外部服务依赖（Koharu 不需要启动）
- detect/ocr/translate 产物与旧 `00_run_all.py` 一致
- inpaint 使用本地 lama-manga，clean 图无噪点、无白色方框
- typeset final.png 有译文渲染
- 断点续跑、force_rerun、错误处理行为正确
- pyright src 0 errors，ruff 0 errors

---

## 12. 后续（不在本次范围）

1. **移植 `_ensure_terms()`**：术语预扫描作为 orchestrator 的一个 hook 或前置阶段
2. **移植 `_refresh_merged_translation()`**：跨页翻译合并，供前页上下文注入
3. **废弃 `00_run_all.py`**：上述两项移植完成 + 端到端对比验证后，标记 deprecated
4. **segment 阶段**：需求待确认
5. **旧脚本清理**：`scripts/detect_rtdetr.py` 删除、`scripts/01_detect.py` 等确认无其他引用后精简

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| lama-manga 模型路径硬编码（`D:\我的汉化\workflow\koharu_data\...`） | 换机器就跑不了 | `LocalLamaInpainter` 已支持 `model_path` 参数，orchestrator config 可覆盖；后续考虑模型路径配置化 |
| inpaint 模型加载慢（CPU，约 195MB） | 首页慢 | 模块级单例缓存，多页只加载一次 |
| detect 抽取时 ONNX 模型路径变化 | detect 失败 | `RTDetrDetector` 内部的模型路径逻辑保持不变，整体迁移 |
| typeset 需要 4 个上游产物，consumes 声明变长 | 依赖检查更严格 | 方案 A 已处理，声明全部依赖 |
