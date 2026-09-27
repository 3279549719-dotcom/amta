# 交付物文件名随原图 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户在 GUI 上传 `封面.png`、`02.png` 后，下载到的成品就叫 `封面.png/psd`、`02.png/psd`，而不是 `gui-<时间戳>_1.png`，方便按原序校对归类。

**Architecture:** 内部产物继续用稳定页号 `page_N`（缓存/报告不动），只在两个薄接缝加名：①上传时把 `{页号: 原图stem}` 写进 `workspace/<work_id>/input_manifest.json`；②下载时读它，把 FileResponse 的 `filename=` 换成原图 stem。老工作区没有 manifest 时回退到页号本身。新增纯函数模块 `common/deliverables.py`，GUI server 只做两行调用。

**Tech Stack:** Python 3.12 / FastAPI FileResponse / 现有 `uv run python -m pytest`。

---

## 文件结构

- **Create** `src/amta/common/deliverables.py` — 纯函数：sanitize_stem / write_input_manifest / load_stems / deliverable_stem。零 FastAPI 依赖，可独立单测。
- **Create** `tests/test_deliverables.py` — 上述纯函数的 TDD 测试。
- **Modify** `src/amta/gui/server.py` — ①upload 收集原图名并写 manifest；②export_png / export_psd 用 deliverable_stem 命名。
- **Modify** `tests/test_gui_server.py` — 上传写 manifest、下载文件名用原图名的端到端断言。

**不改的东西：** `page_N_final.png` / `page_N.psd` 内部路径、缓存指纹、报告命名、CLI 入口——一律不动。

---

### Task 1: 纯函数命名模块 `common/deliverables.py`

**Files:**
- Create: `src/amta/common/deliverables.py`
- Test: `tests/test_deliverables.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_deliverables.py
from __future__ import annotations

from amta.common.deliverables import (
    deliverable_stem,
    load_stems,
    sanitize_stem,
    write_input_manifest,
)


def test_sanitize_stem_strips_extension_and_illegal_chars():
    assert sanitize_stem("封面.png") == "封面"
    assert sanitize_stem("a<b>c:d?e/f.png") == "a_b_c_d_e_f"
    assert sanitize_stem("   ") == "page"


def test_write_and_load_manifest_roundtrip(tmp_path):
    write_input_manifest(tmp_path, ["封面.png", "02.jpg", "cover.PNG"])
    assert load_stems(tmp_path) == {1: "封面", 2: "02", 3: "cover"}


def test_duplicate_stems_get_suffix(tmp_path):
    write_input_manifest(tmp_path, ["untitled.png", "untitled.jpg", "untitled.png"])
    assert load_stems(tmp_path) == {1: "untitled", 2: "untitled_2", 3: "untitled_3"}


def test_deliverable_stem_falls_back_to_page_number_when_no_manifest(tmp_path):
    assert deliverable_stem(tmp_path, 7) == "7"


def test_deliverable_stem_uses_original_name(tmp_path):
    write_input_manifest(tmp_path, ["封面.png"])
    assert deliverable_stem(tmp_path, 1) == "封面"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_deliverables.py -q`
Expected: FAIL — `ModuleNotFoundError: amta.common.deliverables`

- [ ] **Step 3: 写最小实现**

```python
# src/amta/common/deliverables.py
"""交付物命名：内部用 page_N 编号，对外下载时用原图文件名。

入库（上传）时把 {1-based 页号: 去重后的原图 stem} 写进
workspace/<work_id>/input_manifest.json；导出（下载）时读它，把 PNG/PSD
命名成用户投喂的原名。没有 manifest 的老工作区回退到页号本身。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_MANIFEST_NAME = "input_manifest.json"
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_stem(name: str) -> str:
    """原图文件名 → 安全的交付 stem；去扩展名、替换非法字符、空则回退。"""
    stem = Path(name).stem.strip()
    stem = _ILLEGAL.sub("_", stem).strip(" .")
    return stem or "page"


def write_input_manifest(work_dir: Path, source_names: list[str]) -> Path:
    """记录 {1-based 页号: 去重后的原图 stem}。source_names 按上传顺序。"""
    used: dict[str, int] = {}
    pages: list[dict] = []
    for n, raw in enumerate(source_names, start=1):
        stem = sanitize_stem(raw)
        count = used.get(stem, 0) + 1
        used[stem] = count
        unique = stem if count == 1 else f"{stem}_{count}"
        pages.append({"n": n, "stem": unique, "source_name": raw})
    path = work_dir / _MANIFEST_NAME
    path.write_text(
        json.dumps({"pages": pages}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_stems(work_dir: Path) -> dict[int, str]:
    """读 manifest → {页号: stem}；文件缺失/损坏返回 {}。"""
    path = work_dir / _MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[int, str] = {}
    for entry in doc.get("pages", []):
        n, stem = entry.get("n"), entry.get("stem")
        if isinstance(n, int) and isinstance(stem, str) and stem:
            out[n] = stem
    return out


def deliverable_stem(work_dir: Path, page_num: int) -> str:
    """对外下载用的文件名 stem：优先 manifest 里的原图名，否则用页号。"""
    return load_stems(work_dir).get(page_num) or str(page_num)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_deliverables.py -q`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/amta/common/deliverables.py tests/test_deliverables.py
git commit -m "feat(deliverables): add input manifest + deliverable naming helpers"
```

---

### Task 2: 上传时记录原图名

**Files:**
- Modify: `src/amta/gui/server.py`（import 区 + `upload_images`）
- Test: `tests/test_gui_server.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_gui_server.py` 末尾追加：

```python
def test_upload_writes_input_manifest_with_original_names(tmp_path: Path) -> None:
    from io import BytesIO

    def _png() -> bytes:
        buf = BytesIO()
        Image.new("RGB", (5, 5), "white").save(buf, "PNG")
        return buf.getvalue()

    resp = client.post(
        "/api/upload",
        files=[
            ("files", ("cover.png", _png(), "image/png")),
            ("files", ("02.png", _png(), "image/png")),
        ],
        data={"work_id": "naming"},
    )
    assert resp.status_code == 200
    manifest = tmp_path / "workspace" / "naming" / "input_manifest.json"
    import json
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    assert [p["stem"] for p in doc["pages"]] == ["cover", "02"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_gui_server.py::test_upload_writes_input_manifest_with_original_names -q`
Expected: FAIL — `input_manifest.json` 不存在（FileNotFoundError）

- [ ] **Step 3: 改 upload_images**

在 `src/amta/gui/server.py` 顶部 import 区加一行（紧挨现有 `from amta.common.paths import ROOT`）：

```python
from amta.common.deliverables import deliverable_stem, write_input_manifest
```

把 `upload_images` 里保存循环和返回值改成：

```python
    input_dir = _workspace_path(work_id, "input")
    if input_dir.exists():
        shutil.rmtree(input_dir)
    input_dir.mkdir(parents=True, exist_ok=True)
    source_names: list[str] = []
    for i, f in enumerate(files, start=1):
        content = await f.read()
        # 统一转存为 .jpg（管线只认 .jpg）；同时记住原图名用于交付命名
        pil_img = Image.open(BytesIO(content)).convert("RGB")
        dest = input_dir / f"{i}.jpg"
        pil_img.save(dest, "JPEG")
        source_names.append(f.filename or f"{i}.jpg")
    write_input_manifest(_workspace_dir(work_id), source_names)
    return {
        "work_id": work_id,
        "src_dir": str(input_dir),
        "page_count": len(source_names),
        "pages": list(range(1, len(source_names) + 1)),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_gui_server.py::test_upload_writes_input_manifest_with_original_names -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/amta/gui/server.py tests/test_gui_server.py
git commit -m "feat(gui): record original upload filenames in input manifest"
```

---

### Task 3: 下载文件名用原图名

**Files:**
- Modify: `src/amta/gui/server.py`（`export_png` / `export_psd`）
- Test: `tests/test_gui_server.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_gui_server.py` 末尾追加：

```python
def test_export_png_uses_original_filename(tmp_path: Path) -> None:
    from io import BytesIO

    def _png() -> bytes:
        buf = BytesIO()
        Image.new("RGB", (5, 5), "white").save(buf, "PNG")
        return buf.getvalue()

    client.post(
        "/api/upload",
        files=[("files", ("cover.png", _png(), "image/png"))],
        data={"work_id": "naming"},
    )
    final = tmp_path / "workspace" / "naming" / "artifacts" / "final"
    final.mkdir(parents=True)
    Image.new("RGB", (5, 5), "white").save(final / "page_1_final.png")

    resp = client.get("/api/export/naming/1/png")
    assert resp.status_code == 200
    assert "cover.png" in resp.headers["content-disposition"]


def test_export_png_falls_back_to_page_number_without_manifest(tmp_path: Path) -> None:
    final = tmp_path / "workspace" / "oldwork" / "artifacts" / "final"
    final.mkdir(parents=True)
    Image.new("RGB", (5, 5), "white").save(final / "page_3_final.png")
    resp = client.get("/api/export/oldwork/3/png")
    assert resp.status_code == 200
    assert "3.png" in resp.headers["content-disposition"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_gui_server.py::test_export_png_uses_original_filename -q`
Expected: FAIL — content-disposition 里是 `oldwork_1.png`（或 `naming_1.png`），不含 `cover.png`

- [ ] **Step 3: 改 export_png / export_psd 的 filename**

把 `export_png` 的 return 改成：

```python
    stem = deliverable_stem(_workspace_dir(work_id), int(page))
    return FileResponse(
        image_path, media_type="image/png", filename=f"{stem}.png"
    )
```

把 `export_psd` 的 return 改成：

```python
    stem = deliverable_stem(_workspace_dir(work_id), int(page))
    return FileResponse(
        psd_path,
        media_type="image/vnd.adobe.photoshop",
        filename=f"{stem}.psd",
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_gui_server.py -q`
Expected: all GUI server tests pass（含新增 2 个）

- [ ] **Step 5: 提交**

```bash
git add src/amta/gui/server.py tests/test_gui_server.py
git commit -m "feat(gui): name exported PNG/PSD after original upload filename"
```

---

### Task 4: 全量质检收尾

- [ ] **Step 1: 跑完整质检门**

Run: `uv run python scripts/state.py finish "feat(gui): deliverable PNG/PSD named after source image"`

Expected: ruff / pyright / pytest(全量) / depguard / module-map 全部 OK，自动落盘提交。若 module-map 因新增 `common/deliverables.py` 变化而刷新，属正常。

- [ ] **Step 2: 手动验收（可选，需真实上传）**

启动 GUI，上传 `封面.png` 与 `02.png`，跑完一页后点下载：
- PNG 下载文件名应为 `封面.png` / `02.png`（不是 `gui-<时间戳>_1.png`）；
- PSD 同理为 `封面.psd` / `02.psd`。

---

## 自审记录

- **Spec 覆盖：** 选 A（保留原图文件名）→ Task 1 写 manifest、Task 2 上传记录、Task 3 下载命名，全链路闭合。老工作区回退页号在 Task 1 纯函数 + Task 3 第二个测试里覆盖。
- **占位符扫描：** 无 TBD；每个改代码的步骤都给了完整代码块。
- **类型一致：** `write_input_manifest(work_dir, source_names)` / `deliverable_stem(work_dir, page_num)` 在 Task 1 定义、Task 2/3 调用签名一致；manifest 内字段 `n`/`stem`/`source_name` 三处一致。
- **明确不做（YAGNI）：** 不做整组 zip 打包（用户未确认）；不改内部 `page_N` 路径；CLI 路径天然回退到页号，无需写 manifest。
