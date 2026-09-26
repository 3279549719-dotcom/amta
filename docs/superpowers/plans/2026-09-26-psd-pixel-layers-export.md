# PSD Pixel Layers Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the editable-text-layer PSD export with a pixel-layer PSD export that guarantees 1:1 visual consistency with the typeset final image.

**Architecture:** PSD contains 1 clean background pixel layer + N text pixel layers (one per translated bubble). Each text layer is rendered by calling the same `typeset_render.render_item()` function onto a transparent RGBA canvas, then placed as an `ImageLayer_8bit`. This eliminates the dual-render-path problem: the PSD text and the final PNG text are produced by identical code with identical parameters.

**Tech Stack:** Python 3.12, PhotoshopAPI 0.9.1 (ImageLayer only, no TextLayer), Pillow, pytest.

---

### Task 1: Create new branch and reset PSD export module

**Files:**
- Modify: `src/amta/typeset/psd_export.py` (full rewrite)
- Modify: `tests/test_psd_export.py` (rewrite tests)

- [ ] **Step 1: Create new branch from main**

```bash
cd "E:\manga translator agent"
git checkout main
git checkout -b feat/psd-pixel-layers
```

Expected: on new branch `feat/psd-pixel-layers`, clean working tree from main.

- [ ] **Step 2: Rewrite psd_export.py with pixel-layer architecture**

Replace the entire contents of `src/amta/typeset/psd_export.py` with:

```python
"""PSD 导出 — 干净底图 + 像素文字层（与成品图 1:1 一致）。

每个 PSD 包含：
- 1 个干净底图层（clean page N）
- N 个文字像素层（每个翻译框一个，透明背景）

文字层通过调用 typeset_render.render_item() 在透明 RGBA 画布上渲染，
与成品图 final.png 使用完全相同的渲染函数和参数，确保视觉 100% 一致。
不再使用 PhotoshopAPI 的 TextLayer（可编辑文字层），避免字体引擎数据
不兼容导致的空白/占位符/大小偏移问题。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from amta.common.paths import read_json


def _pil_to_numpy_chw(img: Image.Image) -> np.ndarray:
    """PIL RGBA Image → numpy (4, H, W) uint8，PhotoshopAPI ImageLayer 期望格式。"""
    arr = np.array(img.convert("RGBA"), dtype=np.uint8)
    return np.ascontiguousarray(np.transpose(arr, (2, 0, 1)))


def _render_text_layer(
    clean_img: Image.Image,
    item: dict,
    text: str,
    font_path: str,
) -> Image.Image:
    """在透明背景上渲染单条文字，返回 RGBA Image（与画布同尺寸）。

    调用与成品图完全相同的 typeset_render.render_item()，
    确保 PSD 文字层和 final.png 中的文字 1:1 一致。
    """
    from amta.typeset.typeset_render import render_item

    # 创建透明画布（与干净底图同尺寸）
    canvas = Image.new("RGBA", clean_img.size, (0, 0, 0, 0))

    # 估算 bbox：以 anchor_pos 为中心，font_size 为基准估算范围
    font_size = float(item.get("font_size", 24))
    anchor = item.get("anchor_pos", [0, 0])
    lines = item.get("lines") or [text]
    max_line_len = max(len(ln) for ln in lines) if lines else len(text)
    num_lines = len(lines)

    if item.get("layout_direction") == "vertical":
        half_w = max(num_lines * font_size * 1.2, font_size)
        half_h = max(max_line_len * font_size * 1.2, font_size)
    else:
        half_w = max(max_line_len * font_size * 1.2, font_size)
        half_h = max(num_lines * font_size * 1.5, font_size)

    bbox = [
        int(anchor[0] - half_w),
        int(anchor[1] - half_h),
        int(anchor[0] + half_w),
        int(anchor[1] + half_h),
    ]

    # 调用与成品图相同的渲染函数
    render_item(
        canvas,
        text,
        font_path,
        bbox,
        stroke=int(item.get("rendered_stroke", 0)),
        color=tuple(int(item.get("rendered_color", "#000000")[i:i+2], 16) for i in (1, 3, 5)),
        preferred_direction=item.get("layout_direction"),
        base_size=int(font_size),
    )

    return canvas


_FONT_PATH_MAP: dict[str, str] = {
    "msyh.ttc": r"C:\Windows\Fonts\msyh.ttc",
    "msyhbd.ttc": r"C:\Windows\Fonts\msyhbd.ttc",
    "simkai.ttf": r"C:\Windows\Fonts\simkai.ttf",
    "simhei.ttf": r"C:\Windows\Fonts\simhei.ttf",
    "simsun.ttc": r"C:\Windows\Fonts\simsun.ttc",
}


def _resolve_font_path(font_family: str) -> str:
    """字体文件名 → 系统字体绝对路径。"""
    if font_family in _FONT_PATH_MAP:
        return _FONT_PATH_MAP[font_family]
    # 未映射的尝试在系统字体目录查找
    candidate = Path(r"C:\Windows\Fonts") / font_family
    if candidate.exists():
        return str(candidate)
    return _FONT_PATH_MAP["msyh.ttc"]  # fallback 微软雅黑


def export_page_psd(
    artifacts_dir: Path,
    page_key: str,
    output_path: Path,
) -> Path:
    """为单页生成 PSD 文件（干净底图 + N 个像素文字层）。

    artifacts_dir: 工作区的 artifacts 目录
    page_key: 页面键，如 "page_5"
    output_path: 输出 PSD 路径
    """
    import photoshopapi as psapi

    # 1. 读取干净底图
    inpaint_doc = read_json(artifacts_dir / "inpaint" / f"{page_key}.json")
    clean_rel = inpaint_doc.get("clean_image", "")
    if not clean_rel:
        raise ValueError(f"inpaint/{page_key}.json 缺少 clean_image 字段")
    clean_path = artifacts_dir / clean_rel
    if not clean_path.exists():
        raise FileNotFoundError(f"干净底图不存在: {clean_path}")
    clean_img = Image.open(clean_path).convert("RGB")
    width, height = clean_img.size

    # 2. 读取翻译文字
    trans_doc = read_json(artifacts_dir / "translation" / f"{page_key}.json")
    translations: dict[str, str] = trans_doc.get("translations", {})

    # 3. 读取排版数据
    typeset_doc = read_json(artifacts_dir / "typeset" / f"{page_key}.json")
    items = typeset_doc.get("rendered_items", [])

    # 4. 创建 PSD 文档
    doc = psapi.LayeredFile_8bit(psapi.enum.ColorMode.rgb, width, height)

    # 5. 每个文字区域一个像素文字层（先添加，位于上层）
    for item in items:
        rid = item.get("region_id", "")
        text = translations.get(rid, "")
        if not text:
            continue

        layer_name = f"{rid}: {text[:30]}" if rid else f"text: {text[:30]}"
        font_path = _resolve_font_path(item.get("font_family", "msyh.ttc"))

        # 在透明背景上渲染文字（与成品图相同的渲染函数）
        text_layer_img = _render_text_layer(clean_img, item, text, font_path)

        # 转为像素图层
        text_data = _pil_to_numpy_chw(text_layer_img)
        layer_width = width + width % 2
        layer_height = height + height % 2
        if (layer_width, layer_height) != (width, height):
            padded = Image.new("RGBA", (layer_width, layer_height), (0, 0, 0, 0))
            padded.paste(text_layer_img, (0, 0))
            text_data = _pil_to_numpy_chw(padded)

        text_layer = psapi.ImageLayer_8bit(
            text_data,
            layer_name,
            width=layer_width,
            height=layer_height,
            pos_x=layer_width // 2,
            pos_y=layer_height // 2,
        )
        text_layer.fill = 1.0
        doc.add_layer(text_layer)

    # 6. 添加干净底图层（最后添加，位于最下层）
    layer_width = width + width % 2
    layer_height = height + height % 2
    if (layer_width, layer_height) != (width, height):
        padded = Image.new("RGB", (layer_width, layer_height))
        padded.paste(clean_img, (0, 0))
        bg_img = padded
    else:
        bg_img = clean_img
    bg_data = _pil_to_numpy_chw(bg_img)
    page_num = page_key.replace("page_", "")
    bg_layer = psapi.ImageLayer_8bit(
        bg_data,
        f"clean page {page_num}",
        width=layer_width,
        height=layer_height,
        pos_x=layer_width // 2,
        pos_y=layer_height // 2,
    )
    bg_layer.fill = 1.0
    doc.add_layer(bg_layer)

    # 7. 写入 PSD
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.write(output_path)

    return output_path
```

- [ ] **Step 3: Rewrite tests in tests/test_psd_export.py**

Replace the entire test file with:

```python
"""PSD 像素图层导出测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pytest
from PIL import Image

from amta.typeset.psd_export import export_page_psd

pytest.importorskip("photoshopapi", reason="PhotoshopAPI not installed")


def _make_artifacts(tmp_path: Path) -> Path:
    """构建最小 artifacts 目录。"""
    art = tmp_path / "artifacts"
    for sub in ["inpaint", "clean", "translation", "typeset"]:
        (art / sub).mkdir(parents=True)

    Image.new("RGB", (200, 150), (240, 240, 240)).save(art / "clean" / "page_1_clean.png")
    (art / "inpaint" / "page_1.json").write_text(
        json.dumps({"page": "page_1", "clean_image": "clean/page_1_clean.png"}), encoding="utf-8")
    (art / "translation" / "page_1.json").write_text(
        json.dumps({"page": "page_1", "translations": {"r00": "你好世界", "r01": "竖排文字"}}),
        encoding="utf-8")
    (art / "typeset" / "page_1.json").write_text(json.dumps({
        "page": "page_1",
        "rendered_items": [
            {"region_id": "r00", "font_family": "msyh.ttc", "font_size": 20,
             "layout_direction": "horizontal", "lines": ["你好世界"],
             "anchor_pos": [100, 40], "rendered_color": "#000000", "rendered_stroke": 0},
            {"region_id": "r01", "font_family": "msyh.ttc", "font_size": 16,
             "layout_direction": "vertical", "lines": ["竖排", "文字"],
             "anchor_pos": [100, 100], "rendered_color": "#FF0000", "rendered_stroke": 2},
        ],
    }), encoding="utf-8")
    return art


def test_export_page_psd_creates_file(tmp_path):
    """端到端：生成的 PSD 文件存在且非空。"""
    art = _make_artifacts(tmp_path)
    out = tmp_path / "page_1.psd"
    result = export_page_psd(art, "page_1", out)
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_export_page_psd_layer_count_and_order(tmp_path):
    """PSD 包含 1 底图 + N 文字层，底图在最下层。"""
    import photoshopapi as psapi

    art = _make_artifacts(tmp_path)
    out = tmp_path / "page_1.psd"
    export_page_psd(art, "page_1", out)

    doc = psapi.LayeredFile_8bit.read(out)
    # 2 个文字层 + 1 个底图层 = 3
    assert len(doc.layers) == 3

    # 所有图层 fill=1.0
    for layer in doc.layers:
        assert layer.fill == 1.0

    # 最下层是底图
    assert doc.layers[-1].name.startswith("clean ")

    # 前两层是文字层（ImageLayer，不是 TextLayer）
    for layer in doc.layers[:2]:
        assert isinstance(layer, psapi.ImageLayer_8bit)
        assert not isinstance(layer, psapi.TextLayer_8bit)


def test_export_page_psd_clean_layer_covers_canvas(tmp_path):
    """底图层必须覆盖完整画布。"""
    from psd_tools import PSDImage

    art = _make_artifacts(tmp_path)
    out = tmp_path / "page_1.psd"
    export_page_psd(art, "page_1", out)

    psd = PSDImage.open(out)
    clean_layers = [l for l in psd if l.kind == "pixel" and l.name.startswith("clean ")]
    assert len(clean_layers) == 1
    left, top, right, bottom = clean_layers[0].bbox
    assert left == 0 and top == 0
    assert right >= psd.width and bottom >= psd.height


def test_export_page_psd_text_layers_have_pixels(tmp_path):
    """文字层必须包含非透明像素（文字确实被渲染了）。"""
    import photoshopapi as psapi

    art = _make_artifacts(tmp_path)
    out = tmp_path / "page_1.psd"
    export_page_psd(art, "page_1", out)

    doc = psapi.LayeredFile_8bit.read(out)
    text_layers = [l for l in doc.layers if not l.name.startswith("clean ")]
    assert len(text_layers) == 2

    for layer in text_layers:
        # 提取图层像素数据，检查 alpha 通道有非零值
        img = layer.image
        arr = np.array(img)
        if arr.shape[2] >= 4:
            alpha = arr[:, :, 3]
            assert alpha.max() > 0, f"Layer {layer.name!r} has no visible pixels"


def test_export_page_psd_missing_clean_raises(tmp_path):
    """inpaint.json 缺少 clean_image 时应抛错。"""
    art = tmp_path / "artifacts"
    for sub in ["inpaint", "translation", "typeset"]:
        (art / sub).mkdir(parents=True)
    (art / "inpaint" / "page_1.json").write_text(json.dumps({"page": "page_1"}), encoding="utf-8")
    (art / "translation" / "page_1.json").write_text(json.dumps({"translations": {}}), encoding="utf-8")
    (art / "typeset" / "page_1.json").write_text(json.dumps({"rendered_items": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="clean_image"):
        export_page_psd(art, "page_1", tmp_path / "page_1.psd")
```

- [ ] **Step 4: Run tests**

```bash
cd "E:\manga translator agent"
uv run python -m pytest tests/test_psd_export.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/amta/typeset/psd_export.py tests/test_psd_export.py
git commit -m "feat(typeset): pixel-layer PSD export for 1:1 consistency with final image"
```

---

### Task 2: Regenerate real artifact and visually verify

**Files:**
- Regenerate: `workspace/psd-verify/artifacts/psd/page_1.psd`

- [ ] **Step 1: Regenerate the real PSD**

```bash
cd "E:\manga translator agent"
$env:PYTHONPATH="src"
uv run python -c "from pathlib import Path; from amta.typeset.psd_export import export_page_psd; export_page_psd(Path(r'workspace\psd-verify\artifacts'), 'page_1', Path(r'workspace\psd-verify\artifacts\psd\page_1.psd'))"
```

Expected: command exits 0, file rewritten.

- [ ] **Step 2: Verify with psd-tools**

```bash
uv run python -c "
from psd_tools import PSDImage
psd = PSDImage.open(r'workspace\psd-verify\artifacts\psd\page_1.psd')
print(f'Canvas: {psd.size}')
for layer in psd:
    print(f'  {layer.name!r}: kind={layer.kind}, bbox={layer.bbox}, visible={layer.visible}')
"
```

Expected: 5 layers (4 text + 1 clean), all pixel layers, clean layer covers canvas.

- [ ] **Step 3: Composite render and visually compare with final.png**

```bash
uv run psd-tools export "workspace\psd-verify\artifacts\psd\page_1.psd" "$env:TEMP\psd_pixel_composite.png"
```

Then open both `$env:TEMP\psd_pixel_composite.png` and `workspace\psd-verify\artifacts\final\page_1_final.png` with the visual tool and confirm:
- clean page is identical
- all 4 text bubbles appear at the same positions with the same sizes
- text rendering matches (same font, same size, same color)

- [ ] **Step 4: Open in Photoshop for user verification**

```powershell
Start-Process "E:\manga translator agent\workspace\psd-verify\artifacts\psd\page_1.psd"
```

Ask user to confirm: clean background visible, 4 text layers visible and correctly positioned, text size matches final.png.

---

### Task 3: Update orchestrator adapter and docs

**Files:**
- Modify: `src/amta/orchestrator/adapters/typeset.py` (if it references PSD export behavior)
- Modify: `docs/decisions/` (add ADR noting the switch from editable text to pixel layers)

- [ ] **Step 1: Check orchestrator adapter for PSD-related assumptions**

```bash
cd "E:\manga translator agent"
grep -rn "psd_export\|export_psd\|TextLayer" src/amta/orchestrator/
```

If the adapter assumes editable text layers or references removed functions, update accordingly. The `export_page_psd` signature is unchanged, so likely no changes needed.

- [ ] **Step 2: Run full test suite**

```bash
uv run python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs(typeset): ADR for pixel-layer PSD export approach"
```

---

### Task 4: Final verification and finish

- [ ] **Step 1: Run repository checks**

```bash
npm run check
```

Expected: exit 0 (or report pre-existing unrelated failures verbatim).

- [ ] **Step 2: Run finish workflow**

```bash
npm run finish -- "feat(typeset): pixel-layer PSD export for 1:1 visual consistency"
```

Expected: full checks pass, changes committed.

- [ ] **Step 3: Deliver summary to user**

Confirm: PSD now contains 1 clean layer + 4 pixel text layers, visually identical to final.png, opens correctly in Photoshop with correct text size and position.
