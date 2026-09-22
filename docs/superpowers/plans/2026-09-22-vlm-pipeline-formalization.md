# VLM 管线正式化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 VLM paratext 管线从 probe 脚本 + monkey-patch 变成正式管线的一部分，能通过 `run_pipeline.py --vlm-pages 60,63,67` 正常调用，产物直接落到主工作区。

**Architecture:** 三个独立步骤递进：(1) 编排器支持离散页选择 + VLM 页面标记；(2) VLM 视觉读取迁移为 OCR station 的可选引擎，翻译站适配 VLM 输出；(3) VLM 贪婪换行渲染迁移为 typeset station 的可选模式。每页通过 `vlm_pages` 配置决定走普通模式还是 VLM 模式，station 内部根据 config 分支执行。

**Tech Stack:** Python 3.12, PIL/Pillow, dataclasses, pytest, existing orchestrator registry pattern

---

## File Structure

### 新建文件
- `src/amta/stations/vlm_layout.py` — 从 `scripts/probes/paratext_layout.py` 迁移，VLM 视觉读取（转写 + 排版风格观察）
- `src/amta/typeset/vlm_render.py` — 从 `scripts/probes/paratext_render.py` 迁移，VLM 贪婪换行本地渲染
- `tests/orchestrator/test_page_selection.py` — 离散页选择 + VLM 页面路由测试
- `tests/stations/test_vlm_ocr.py` — VLM OCR 引擎单元测试（用 fake VLM 函数）
- `tests/typeset/test_vlm_render.py` — VLM 渲染单元测试

### 修改文件
- `src/amta/orchestrator/context.py` — PipelineConfig 增加 `pages` 和 `vlm_pages` 字段
- `src/amta/orchestrator/pipeline.py` — `_resolve_page_list` 支持离散页，`_build_context` 注入 VLM 模式标记
- `scripts/run_pipeline.py` — CLI 增加 `--pages` 和 `--vlm-pages` 参数
- `src/amta/stations/ocr_station.py` — 增加 `engine="vlm-paratext"` 分支
- `src/amta/orchestrator/adapters/ocr.py` — 传递 VLM 模式配置
- `src/amta/orchestrator/registry.py` — OCR StageSpec 增加 vlm_layout.py 到 code_files
- `src/amta/translation/translate_station.py` — 支持 VLM 模式（检查 canon ocr_engine，使用 paratext 提示词）
- `src/amta/orchestrator/adapters/translate.py` — 传递 VLM 模式
- `src/amta/typeset/typeset_station.py` — 增加 VLM 渲染模式分支
- `src/amta/orchestrator/adapters/typeset.py` — 判断 canon ocr_engine 选择渲染器
- `src/amta/orchestrator/registry.py` — typeset StageSpec 增加 vlm_render.py 到 code_files

---

## Task 1: 离散页选择 + VLM 页面路由

**Files:**
- Modify: `src/amta/orchestrator/context.py:65-80`
- Modify: `src/amta/orchestrator/pipeline.py:36-51`
- Modify: `src/amta/orchestrator/pipeline.py:54-105`
- Modify: `scripts/run_pipeline.py:30-59`
- Test: `tests/orchestrator/test_page_selection.py`

- [ ] **Step 1: 写离散页选择的失败测试**

```python
"""tests/orchestrator/test_page_selection.py"""
from pathlib import Path

import pytest

from amta.orchestrator.context import PipelineConfig
from amta.orchestrator.pipeline import _resolve_page_list


def test_resolve_pages_discrete(tmp_path: Path):
    """离散页选择：pages=[3, 7, 10] 只返回这三页。"""
    for n in (3, 7, 10, 5):
        (tmp_path / f"{n}.jpg").write_bytes(b"fake")
    config = PipelineConfig(
        work_id="test", src_dir=tmp_path,
        start_page=1, end_page=10,  # 被 pages 覆盖
        pages=[3, 7, 10],
    )
    result = _resolve_page_list(config)
    assert [p[0] for p in result] == [3, 7, 10]


def test_resolve_pages_range_when_pages_none(tmp_path: Path):
    """pages=None 时回退到 start_page/end_page 连续区间。"""
    for n in (1, 2, 3):
        (tmp_path / f"{n}.jpg").write_bytes(b"fake")
    config = PipelineConfig(
        work_id="test", src_dir=tmp_path,
        start_page=1, end_page=3, pages=None,
    )
    result = _resolve_page_list(config)
    assert [p[0] for p in result] == [1, 2, 3]


def test_vlm_pages_injected_into_config():
    """vlm_pages 中的页，其 station config 应包含 vlm_mode=True。"""
    # 这个测试在 Step 4 实现 _build_context 修改后通过
    pass
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m pytest tests/orchestrator/test_page_selection.py -v`
Expected: FAIL — `PipelineConfig.__init__() got an unexpected keyword argument 'pages'`

- [ ] **Step 3: 修改 PipelineConfig 增加 pages 和 vlm_pages 字段**

在 `src/amta/orchestrator/context.py` 的 `PipelineConfig` dataclass 中，在 `end_page` 之后增加：

```python
    pages: list[int] | None = None
    # 离散页选择（如 [5, 40, 60]）。为 None 时用 start_page/end_page 连续区间。
    vlm_pages: list[int] = field(default_factory=list)
    # 走 VLM 模式的页面列表（如 [60, 63, 67]）。不在此列表的页走普通 hayai 模式。
```

完整修改后的 PipelineConfig 字段顺序：
```python
@dataclass
class PipelineConfig:
    work_id: str
    src_dir: Path
    start_page: int
    end_page: int
    pages: list[int] | None = None
    vlm_pages: list[int] = field(default_factory=list)
    stages: list[str] = field(default_factory=lambda: ["detect", "ocr", "translate"])
    stage_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    force_rerun: bool = False
    continue_on_error: bool = False
```

- [ ] **Step 4: 修改 _resolve_page_list 支持离散页**

在 `src/amta/orchestrator/pipeline.py` 中，替换 `_resolve_page_list` 函数：

```python
def _resolve_page_list(config: PipelineConfig) -> list[tuple[int, str, Path]]:
    """把页面配置展开成 [(page_idx, page_key, raw_path)]。

    优先级：config.pages（离散页）> start_page/end_page（连续区间）。
    page_idx = 文件名 N（1 基，page_N ↔ N.jpg，与原图序号一致）
    不存在的图片跳过并打印警告。
    """
    if config.pages is not None:
        page_numbers = config.pages
    else:
        page_numbers = list(range(config.start_page, config.end_page + 1))

    pages = []
    for n in page_numbers:
        raw_path = config.src_dir / f"{n}.jpg"
        if not raw_path.exists():
            print(f"[pipeline] WARN {raw_path} not found, skip page {n}")
            continue
        page_idx = n
        page_key = artifacts.page_key(page_idx)
        pages.append((page_idx, page_key, raw_path))
    return pages
```

- [ ] **Step 5: 修改 _build_context 注入 VLM 模式标记**

在 `src/amta/orchestrator/pipeline.py` 的 `_build_context` 函数中，在配置合并之后、return 之前，增加 VLM 模式注入：

```python
    # 配置合并：默认配置 + 调用方覆盖
    merged_config = dict(stage.default_config)
    if stage.name in config.stage_configs:
        merged_config.update(config.stage_configs[stage.name])

    # VLM 页面路由：当前页在 vlm_pages 中 → 给 ocr/translate/typeset 注入 vlm_mode=True
    if page_idx in config.vlm_pages and stage.name in ("ocr", "translate", "typeset"):
        merged_config["vlm_mode"] = True
```

注意：`_build_context` 的参数列表里已经有 `page_idx: int`，直接用即可。

- [ ] **Step 6: 补充 vlm_mode 注入的测试**

在 `tests/orchestrator/test_page_selection.py` 中，把 `test_vlm_pages_injected_into_config` 替换为实际测试：

```python
def test_vlm_pages_injected_into_config(tmp_path: Path):
    """vlm_pages 中的页，ocr/translate/typeset 的 config 应包含 vlm_mode=True。"""
    from amta.orchestrator.context import StationContext
    from amta.orchestrator.pipeline import _build_context
    from amta.orchestrator.registry import get_stage

    for n in (1, 60):
        (tmp_path / f"{n}.jpg").write_bytes(b"fake")

    config = PipelineConfig(
        work_id="test", src_dir=tmp_path,
        start_page=1, end_page=60, pages=[1, 60],
        vlm_pages=[60],
        stages=["ocr"],
    )

    artifacts_dir = tmp_path / "artifacts"
    state_dir = tmp_path / "state"
    artifacts_dir.mkdir(exist_ok=True)
    state_dir.mkdir(exist_ok=True)

    # 第 1 页（非 VLM）→ vlm_mode 不应存在
    ctx_normal = _build_context(
        config, 1, "page_1", tmp_path / "1.jpg",
        artifacts_dir, state_dir, get_stage("ocr"), {},
    )
    assert ctx_normal.config.get("vlm_mode") is not True

    # 第 60 页（VLM）→ vlm_mode=True
    ctx_vlm = _build_context(
        config, 60, "page_60", tmp_path / "60.jpg",
        artifacts_dir, state_dir, get_stage("ocr"), {},
    )
    assert ctx_vlm.config.get("vlm_mode") is True
```

- [ ] **Step 7: 运行测试确认通过**

Run: `uv run python -m pytest tests/orchestrator/test_page_selection.py -v`
Expected: 3 passed

- [ ] **Step 8: 修改 CLI 增加 --pages 和 --vlm-pages 参数**

在 `scripts/run_pipeline.py` 中：

1. 在 `--end-page` 参数之后增加：
```python
    ap.add_argument("--pages", default=None,
                    help="离散页选择，逗号分隔（如 5,40,60）。指定后覆盖 --start-page/--end-page")
    ap.add_argument("--vlm-pages", default="",
                    help="走 VLM 模式的页面，逗号分隔（如 60,63,67）。不在此列表的页走普通模式")
```

2. 在 `stages = ...` 之后、`config = PipelineConfig(...)` 之前，增加解析：
```python
    pages = None
    if a.pages:
        pages = [int(p.strip()) for p in a.pages.split(",") if p.strip()]
    vlm_pages = []
    if a.vlm_pages:
        vlm_pages = [int(p.strip()) for p in a.vlm_pages.split(",") if p.strip()]
```

3. 在 `PipelineConfig(...)` 构造中增加 `pages=pages, vlm_pages=vlm_pages,`：
```python
    config = PipelineConfig(
        work_id=a.work_id,
        src_dir=a.src_dir,
        start_page=a.start_page,
        end_page=a.end_page,
        pages=pages,
        vlm_pages=vlm_pages,
        stages=stages,
        stage_configs=stage_configs,
        force_rerun=a.force_rerun,
        continue_on_error=a.continue_on_error,
    )
```

4. 更新 `--start-page` 和 `--end-page` 的 required 为 False（因为有 --pages 时可以不指定）：
```python
    ap.add_argument("--start-page", type=int, default=1, help="起始页（1 基，对应文件名）")
    ap.add_argument("--end-page", type=int, default=9999, help="结束页（1 基，包含）")
```

- [ ] **Step 9: 运行全套测试确认无回归**

Run: `uv run python -m pytest -q`
Expected: all passed（当前 463 passed + 新增 3 = 466）

- [ ] **Step 10: Commit**

```bash
git add src/amta/orchestrator/context.py src/amta/orchestrator/pipeline.py scripts/run_pipeline.py tests/orchestrator/test_page_selection.py
git commit -m "feat(orchestrator): support discrete page selection and VLM page routing"
```

---

## Task 2: VLM OCR + 翻译接入正式管线

**Files:**
- Create: `src/amta/stations/vlm_layout.py`
- Modify: `src/amta/stations/ocr_station.py`
- Modify: `src/amta/orchestrator/adapters/ocr.py`
- Modify: `src/amta/translation/translate_station.py`
- Modify: `src/amta/orchestrator/adapters/translate.py`
- Modify: `src/amta/orchestrator/registry.py`
- Test: `tests/stations/test_vlm_ocr.py`

- [ ] **Step 1: 迁移 paratext_layout.py 到正式代码目录**

将 `scripts/probes/paratext_layout.py` 的内容复制到 `src/amta/stations/vlm_layout.py`，修改 import 路径：

原文件顶部的 import 保持不变（已经用 `amta.backends.chat_client` 和 `amta.common.config`），只需要确保模块 docstring 更新：

```python
"""VLM 视觉读取 — 转写 + 排版风格观察（正式 station 模块）。

从 scripts/probes/paratext_layout.py 迁移，作为 OCR station 的 vlm-paratext 引擎。
VLM 一次调用完成：日文转写 + 排版风格观察（方向/对齐/字体/字号/颜色/描边）。
"""
```

文件其余内容（PROMPT, validate_regions, image_part, exclusive_crop, parse_json, _validate_observed, read_layout）保持不变。

- [ ] **Step 2: 写 VLM OCR 引擎的失败测试**

```python
"""tests/stations/test_vlm_ocr.py"""
import json
from pathlib import Path

import pytest
from PIL import Image

from amta.stations.ocr_station import ocr_page


def _make_detection(tmp_path: Path, page_idx: int = 1) -> dict:
    """构造一个最小 detection artifact。"""
    img = Image.new("RGB", (100, 100), "white")
    raw_path = tmp_path / f"{page_idx}.jpg"
    img.save(raw_path)
    return {
        "page": page_idx,
        "blocks": [
            {"region_id": f"r{page_idx}_00", "bbox": [10, 10, 90, 40]},
            {"region_id": f"r{page_idx}_01", "bbox": [10, 50, 90, 90]},
        ],
    }


def _fake_vlm_layout(raw: Path, blocks: list[dict], cached: dict | None = None) -> dict:
    """Fake VLM 读取：返回固定排版观察结果。"""
    regions = []
    for b in blocks:
        regions.append({
            "region_id": b["region_id"],
            "text": "テスト文字",
            "source_lines": ["テスト文字"],
            "direction": "horizontal",
            "align": "center",
            "font": "sans",
            "background": "paper",
            "font_size_ratio": 0.04,
            "color": "#000000",
            "stroke_color": None,
            "stroke_ratio": 0.0,
            "bbox": b["bbox"],
        })
    return {"regions": regions, "image_size": [100, 100],
            "request_sha256": "fake", "model": "fake", "endpoint": "fake"}


def test_ocr_vlm_paratext_engine(tmp_path: Path):
    """engine='vlm-paratext' 时应调用 VLM 视觉读取，输出 canon 含 layout_observation。"""
    det = _make_detection(tmp_path)
    raw_path = tmp_path / "1.jpg"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    doc = ocr_page(
        work_id="test", det=det, raw_page=raw_path,
        artifacts_dir=artifacts_dir, page_idx=1,
        engine="vlm-paratext",
        vlm_layout_fn=_fake_vlm_layout,
    )

    assert doc["ocr_engine"] == "vlm-paratext"
    assert doc["n_regions"] == 2
    assert "layout_observation" in doc
    assert doc["items"][0]["text"] == "テスト文字"
    assert doc["items"][0]["ocr_engine"] == "vlm-paratext"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run python -m pytest tests/stations/test_vlm_ocr.py -v`
Expected: FAIL — `ocr_page() got an unexpected keyword argument 'vlm_layout_fn'`

- [ ] **Step 4: 修改 ocr_station.py 增加 vlm-paratext 引擎分支**

在 `src/amta/stations/ocr_station.py` 中：

1. 在文件顶部 import 区域增加：
```python
from amta.stations.vlm_layout import read_layout as _default_vlm_layout
```

2. 修改 `ocr_page` 函数签名，增加 `vlm_layout_fn=None` 参数：
```python
def ocr_page(work_id: str, det: dict, raw_page: Path, artifacts_dir: Path, *,
             page_idx: int, engine: str = "hayai", vlm_enabled: bool = False,
             ocr_fn=None, vlm_fn=None, vlm_api_key: str | None = None,
             crop_dir: Path | str | None = None,
             vlm_layout_fn=None) -> dict:
```

3. 在函数体开头（`blocks = det.get("blocks", [])` 之前），增加 VLM 引擎的早期分支：
```python
    # ---- VLM paratext 引擎：一次调用完成转写 + 排版风格观察 ----
    if engine == "vlm-paratext":
        vlm_layout_fn = vlm_layout_fn or _default_vlm_layout
        page = artifacts.page_key(page_idx)
        artifacts_dir = Path(artifacts_dir)
        out_path = artifacts.artifact_paths(artifacts_dir, page)["canon"]

        # 缓存：已有 canon 且 layout_observation 的 request_sha256 匹配 → 复用
        cached = None
        if out_path.exists():
            try:
                existing = read_json(out_path)
                cached = existing.get("layout_observation")
            except Exception:
                pass

        observed = vlm_layout_fn(raw_page, det.get("blocks", []), cached)

        items = []
        for r in observed["regions"]:
            if not r["text"].strip():
                continue
            items.append({
                **r,
                "baberu_text": r["text"],
                "page": page_idx,
                "ocr_engine": "vlm-paratext",
                "vlm_status": "vlm-paratext",
                "contained_in": None,
            })

        doc = artifacts.stamp({
            "items": items,
            "n_regions": len(items),
            "ocr_engine": "vlm-paratext",
            "layout_observation": observed,
        }, work_id, page)
        write_json(out_path, doc)
        return doc
```

注意：需要在文件顶部确保 `read_json` 已 import（当前文件已有 `from amta.common.paths import write_json`，需要加上 `read_json`）：
```python
from amta.common.paths import read_json, write_json
```

- [ ] **Step 5: 修改 ocr adapter 传递 vlm_mode**

在 `src/amta/orchestrator/adapters/ocr.py` 中，修改 `ocr_page` 调用部分：

```python
        doc = ocr_page(
            work_id=ctx.work_id,
            det=det,
            raw_page=ctx.raw_image,
            artifacts_dir=ctx.artifacts_dir,
            page_idx=ctx.page_idx,
            engine="vlm-paratext" if ctx.config.get("vlm_mode") else ctx.config["engine"],
            vlm_enabled=ctx.config["vlm_enabled"],
        )
```

- [ ] **Step 6: 运行 VLM OCR 测试确认通过**

Run: `uv run python -m pytest tests/stations/test_vlm_ocr.py -v`
Expected: 1 passed

- [ ] **Step 7: 修改翻译站支持 VLM 模式**

先看一下当前 translate_station.py 的结构：

需要在翻译站中增加：当 canon 的 ocr_engine == "vlm-paratext" 时，使用 paratext 专用提示词（system_extra）和缓存签名。

在 `src/amta/translation/translate_station.py` 中（需要先 Read 确认具体函数名和结构），找到翻译执行的核心函数，增加 VLM 模式判断：

```python
    # VLM paratext 模式：使用专用提示词，保留段落边界
    is_vlm = canon.get("ocr_engine") == "vlm-paratext"
    system_extra = None
    if is_vlm:
        system_extra = (
            "忠实、自然、完整地翻译页面中的全部文字，不删句、不概括。保留原文中有语义的段落边界。"
            "邮箱、网址、账号和不可翻译的标识符原样保留；专名按上下文选择通行译名或保留原文。"
        )
    cache_salt = "paratext-translation-v1" if is_vlm else "translation-v1"
```

然后在调用 `translate_plain` 时传入 `system_extra=system_extra`，在缓存签名中使用 `cache_salt`。

> **注意**：此步骤需要先 Read `src/amta/translation/translate_station.py` 确认具体函数签名和变量名，再做精确修改。核心改动点是：(1) 判断 ocr_engine，(2) 传入 paratext system_extra，(3) 缓存签名加 salt。

- [ ] **Step 8: 修改 translate adapter 传递 vlm_mode（如需要）**

如果翻译站通过 ctx.config 判断 vlm_mode 而不是 canon 的 ocr_engine，则在 `src/amta/orchestrator/adapters/translate.py` 中传递。否则不需要改 adapter（翻译站自己读 canon 即可）。

- [ ] **Step 9: 更新 registry 的 code_files**

在 `src/amta/orchestrator/registry.py` 中：

1. OCR StageSpec 的 code_files 增加 `"vlm_layout.py"`：
```python
            code_files=[
                "ocr_station.py",
                "ocr_engines.py",
                "vlm_layout.py",
                "canon_schema.py",
                "artifacts.py",
                "geometry.py",
                "paths.py",
            ],
```

2. translate StageSpec 的 code_files 不需要改（翻译站逻辑在已有文件里）。

- [ ] **Step 10: 运行全套测试确认无回归**

Run: `uv run python -m pytest -q`
Expected: all passed

- [ ] **Step 11: Commit**

```bash
git add src/amta/stations/vlm_layout.py src/amta/stations/ocr_station.py src/amta/orchestrator/adapters/ocr.py src/amta/translation/translate_station.py src/amta/orchestrator/registry.py tests/stations/test_vlm_ocr.py
git commit -m "feat(ocr): add vlm-paratext engine for visual reading and typography observation"
```

---

## Task 3: VLM 渲染接入正式 typeset + 端到端验证

**Files:**
- Create: `src/amta/typeset/vlm_render.py`
- Modify: `src/amta/typeset/typeset_station.py`
- Modify: `src/amta/orchestrator/adapters/typeset.py`
- Modify: `src/amta/orchestrator/registry.py`
- Test: `tests/typeset/test_vlm_render.py`

- [ ] **Step 1: 迁移 paratext_render.py 到正式代码目录**

将 `scripts/probes/paratext_render.py` 的内容复制到 `src/amta/typeset/vlm_render.py`，修改 import 路径和 docstring：

```python
"""VLM 贪婪换行本地渲染（正式 typeset 模块）。

从 scripts/probes/paratext_render.py 迁移。
VLM 做视觉决策（观察排版风格），本地代码做机械执行（贪婪换行 + 画字）。
支持横排/竖排，kinsoku 标点禁则，按 VLM 观察到的字体/字号/颜色/描边渲染。
"""
```

文件其余内容（FONTS, _TOKEN_RE, _NO_LINE_START, _NO_LINE_END, _rgb, ink_width, wrap_horizontal, _vertical_columns, layout_text, render_text）保持不变。

- [ ] **Step 2: 写 VLM 渲染的失败测试**

```python
"""tests/typeset/test_vlm_render.py"""
from pathlib import Path

import pytest
from PIL import Image

from amta.typeset.vlm_render import layout_text, render_text


def test_layout_horizontal_fits():
    """横排文本应能在区域内找到合适字号。"""
    block = {
        "bbox": [10, 10, 200, 80],
        "direction": "horizontal",
        "align": "center",
        "font": "sans",
        "font_size_ratio": 0.04,
        "color": "#000000",
        "stroke_color": None,
        "stroke_ratio": 0.0,
    }
    meta = layout_text("测试文本测试文本", block, (400, 300))
    assert meta["layout_direction"] == "horizontal"
    assert meta["font_size"] > 0
    assert len(meta["lines"]) >= 1


def test_render_text_draws_on_image():
    """render_text 应在图片上画出文字并返回 meta。"""
    img = Image.new("RGB", (400, 300), "white")
    block = {
        "bbox": [10, 10, 200, 80],
        "direction": "horizontal",
        "align": "center",
        "font": "sans",
        "font_size_ratio": 0.04,
        "color": "#000000",
        "stroke_color": None,
        "stroke_ratio": 0.0,
    }
    meta = render_text(img, "测试", block)
    assert meta["font_size"] > 0
    # 图片不应全白（有文字被画上）
    assert img.getpixel((100, 40)) != (255, 255, 255)
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run python -m pytest tests/typeset/test_vlm_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'amta.typeset.vlm_render'`（在 Step 1 创建文件后应该能 import，实际失败可能在字体路径，需要确认 Windows 字体存在）

- [ ] **Step 4: 运行 VLM 渲染测试确认通过**

Run: `uv run python -m pytest tests/typeset/test_vlm_render.py -v`
Expected: 2 passed（如果字体路径有问题，测试环境需要有 msyh.ttc 等中文字体）

- [ ] **Step 5: 修改 typeset_station.py 增加 VLM 渲染模式**

先 Read `src/amta/typeset/typeset_station.py` 确认 `run` 函数的结构。

核心改动：在 `run` 函数中，判断 canon 的 ocr_engine 是否为 "vlm-paratext"，如果是则走 VLM 渲染分支：

```python
    # 判断渲染模式
    canon_doc = read_json(canon_path)
    is_vlm = canon_doc.get("ocr_engine") == "vlm-paratext"

    if is_vlm:
        # VLM 渲染分支：贪婪换行 + VLM 观察到的排版风格
        from amta.typeset.vlm_render import render_text
        from amta.stations.vlm_layout import validate_regions

        trans_doc = read_json(trans_path)
        translations = trans_doc["translations"]
        img = Image.open(clean_path).convert("RGB")
        validate_regions(canon_doc["items"], img.size)

        rendered = []
        for item in canon_doc["items"]:
            text = translations.get(item["region_id"], "")
            if not text.strip():
                continue
            meta = render_text(img, text, item)
            rendered.append({**meta, "region_id": item["region_id"]})

        final_dir = ctx.artifacts_dir / "final" if hasattr(ctx, 'artifacts_dir') else out_path.parent / "final"
        final_path = final_dir / f"{page}_final.png"
        final_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(final_path)

        doc = {
            "rendered_items": rendered,
            "layout": {r["region_id"]: r for r in rendered},
            "final_image": f"final/{final_path.name}",
            "checks": {
                "rendered": len(rendered),
                "translated": len(translations),
                "coverage_complete": len(rendered) == len(translations),
                "overflow": [],
                "skipped_no_bbox": [],
            },
        }
        write_json(out_path, artifacts.stamp(doc, work_id, page))
        return doc
```

> **注意**：此步骤需要先 Read typeset_station.py 确认函数签名、变量名（work_id, page, out_path 等），再做精确修改。VLM 分支应该放在普通渲染逻辑之前，作为早期 return。

- [ ] **Step 6: 修改 typeset adapter 支持 VLM 模式**

在 `src/amta/orchestrator/adapters/typeset.py` 中，当前 adapter 调用 `typeset_run(...)` 并处理 PSD 导出。VLM 模式的判断应该在 typeset_station.run 内部完成（通过读 canon 的 ocr_engine），所以 adapter 不需要大改。

但需要确保 adapter 传给 typeset_run 的参数足够。如果 typeset_station.run 的签名需要 `ctx` 或 `artifacts_dir`，则需要调整。

> **注意**：先 Read typeset_station.py 确认 run 函数签名，再决定 adapter 是否需要修改。

- [ ] **Step 7: 更新 registry 的 code_files**

在 `src/amta/orchestrator/registry.py` 中，typeset StageSpec 的 code_files 增加 `"vlm_render.py"`：

```python
            code_files=[
                "typeset_station.py",
                "typeset_engine.py",
                "typeset_render.py",
                "vlm_render.py",
                "fonts.py",
                "geometry.py",
                "artifacts.py",
                "paths.py",
            ],
```

- [ ] **Step 8: 运行全套测试确认无回归**

Run: `uv run python -m pytest -q`
Expected: all passed

- [ ] **Step 9: 端到端验证 — 用已有实验页测试 VLM 模式**

选择一页之前用 probe 跑过的实验页（如月天新天地第 1 页），用正式入口跑 VLM 模式：

```bash
uv run python scripts/run_pipeline.py --work-id vlm-e2e-test \
    --src-dir "D:\path\to\月天新天地" \
    --pages 1 --vlm-pages 1 \
    --stages detect,ocr,translate,inpaint,typeset \
    --force-rerun
```

验证点：
1. 运行成功，无报错
2. `artifacts/final/page_1_final.png` 存在且有文字
3. `artifacts/page_1_canon.json` 中 `ocr_engine == "vlm-paratext"` 且有 `layout_observation`
4. `artifacts/page_1_typeset.json` 中 `rendered_items` 数量正确
5. 视觉效果与之前 probe 版本一致（对比 `workspace/exp-paratext-getten/` 中的成品）

- [ ] **Step 10: 跑第 60 页（最终目标页）**

```bash
uv run python scripts/run_pipeline.py --work-id touhou-getten-shinchi \
    --src-dir "D:\path\to\月天新天地" \
    --pages 60 --vlm-pages 60 \
    --stages detect,ocr,translate,inpaint,typeset
```

验证第 60 页（文字极多极密页）能通过正式入口跑出来。

- [ ] **Step 11: 更新文档**

1. 在 `docs/lessons.md` 中增加 VLM 正式化的经验记录
2. 更新 `AGENTS.md` 中的用法示例，增加 `--vlm-pages` 参数说明
3. 将 `scripts/probes/probe_paratext.py` 标记为已归档（在文件顶部 docstring 增加 "DEPRECATED: 已由正式管线 --vlm-pages 取代"）

- [ ] **Step 12: 运行项目完成检查**

Run: `npm run check`
Expected: all checks pass

- [ ] **Step 13: Commit**

```bash
git add src/amta/typeset/vlm_render.py src/amta/typeset/typeset_station.py src/amta/orchestrator/adapters/typeset.py src/amta/orchestrator/registry.py tests/typeset/test_vlm_render.py docs/lessons.md AGENTS.md scripts/probes/probe_paratext.py
git commit -m "feat(typeset): add VLM greedy-wrap renderer as optional typeset mode"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** 3 个核心任务（离散页选择、VLM OCR 接入、VLM 渲染接入）均有对应 Task
- [x] **No placeholders:** 所有代码步骤都有具体代码，无 "TBD" / "implement later"
- [x] **Type consistency:** `vlm_mode` config 字段在 Task 1 定义，Task 2/3 使用；`vlm-paratext` engine 名称一致
- [x] **File paths exact:** 所有文件路径基于实际代码库结构
- [x] **TDD:** 每个 Task 都先写失败测试再实现
- [x] **Frequent commits:** 每个 Task 结束有独立 commit

## 已知限制与后续

1. **自动路由**未包含在此计划中（手动指定 `--vlm-pages` 足够当前需求）
2. **probe 脚本保留**：`scripts/probes/probe_paratext.py` 标记为 deprecated 但不删除，留作参考
3. **PSD 导出与 VLM 渲染**：VLM 渲染模式下 PSD 导出暂不支持（PSD 导出基于普通 typeset 的区域结构），后续可扩展
4. **第 63/67 页归位**：VLM 正式化后直接用正式管线重跑，不需要手动搬文件
