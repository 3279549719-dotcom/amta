# Artifact Cache 增量构建模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现基于内容哈希的工件缓存机制，改了哪个阶段的代码/输入就只重跑那个阶段及下游，未变化的阶段直接复用已有artifact。

**Architecture:** 新增 `artifact_cache.py` 模块，核心是"指纹"机制——每个artifact旁边存一个 `.fingerprint` 文件，记录输入文件哈希、代码文件哈希、配置参数。运行前计算当前指纹，与已存指纹对比，一致则跳过。参考 Make/Snakemake/doit 的增量构建原理。

**Tech Stack:** Python 3.12, hashlib, json, pytest

**Worktree:** `E:\manga translator agent\amta-wt-artifact-cache` (branch: `feat/artifact-cache-incremental-build`)

---

## 文件结构

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/amta/artifact_cache.py` | 核心缓存模块：哈希计算、指纹存储、新鲜度检查、条件执行 |
| 新建测试 | `tests/test_artifact_cache.py` | 缓存模块单元测试 |
| 修改 | `src/amta/artifacts.py` | 增加 `fingerprint_path()` 辅助函数 |
| 文档 | `docs/debug/artifact-cache-design.md` | 设计说明与使用指南 |

---

### Task 1: Artifact Cache 核心模块

**Files:**
- Create: `src/amta/artifact_cache.py`
- Test: `tests/test_artifact_cache.py`

- [ ] **Step 1: 写失败测试 — 文件哈希计算**

创建 `tests/test_artifact_cache.py`：

```python
"""artifact_cache 模块测试 — 基于内容哈希的增量构建。"""
import json
import time
from pathlib import Path

import pytest


def test_compute_file_hash_deterministic(tmp_path):
    """同一文件内容哈希一致。"""
    from amta.artifact_cache import compute_file_hash
    f = tmp_path / "test.json"
    f.write_text('{"key": "value"}', encoding="utf-8")
    h1 = compute_file_hash(f)
    h2 = compute_file_hash(f)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_compute_file_hash_changes_with_content(tmp_path):
    """内容变化哈希变化。"""
    from amta.artifact_cache import compute_file_hash
    f = tmp_path / "test.json"
    f.write_text('{"key": "value"}', encoding="utf-8")
    h1 = compute_file_hash(f)
    f.write_text('{"key": "changed"}', encoding="utf-8")
    h2 = compute_file_hash(f)
    assert h1 != h2


def test_compute_code_hash_multiple_files(tmp_path):
    """多个代码文件合并哈希。"""
    from amta.artifact_cache import compute_code_hash
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo(): pass", encoding="utf-8")
    f2.write_text("def bar(): pass", encoding="utf-8")
    h1 = compute_code_hash([f1, f2])
    h2 = compute_code_hash([f1, f2])
    assert h1 == h2
    # 顺序不影响结果
    h3 = compute_code_hash([f2, f1])
    assert h1 == h3


def test_compute_config_hash():
    """配置字典哈希。"""
    from amta.artifact_cache import compute_config_hash
    cfg1 = {"font_size": 52, "direction": "vertical"}
    cfg2 = {"font_size": 52, "direction": "vertical"}
    cfg3 = {"font_size": 48, "direction": "vertical"}
    assert compute_config_hash(cfg1) == compute_config_hash(cfg2)
    assert compute_config_hash(cfg1) != compute_config_hash(cfg3)
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
uv run pytest tests/test_artifact_cache.py -v
```
Expected: FAIL（`ModuleNotFoundError: No module named 'amta.artifact_cache'`）

- [ ] **Step 3: 实现哈希计算核心函数**

创建 `src/amta/artifact_cache.py`：

```python
"""Artifact Cache — 基于内容哈希的增量构建模块。

核心原理（参考 Make/Snakemake/doit）：
每个 artifact 旁边存一个 .fingerprint 文件，记录：
  - 输入文件的哈希
  - 代码文件的哈希
  - 配置参数的哈希
运行前计算当前指纹，与已存指纹对比：
  - 一致 → 跳过，直接加载已有 artifact
  - 不一致 → 执行生成函数，保存新 artifact 和新指纹

使用方式：
    result = run_stage_if_needed(
        stage_name="typeset",
        page="page_11",
        input_files={"canon": canon_path, "translation": trans_path},
        code_files=["typeset_engine.py", "typeset_render.py"],
        config={"font_max": 52},
        output_path=typeset_path,
        generate_fn=lambda: run_typeset(...),
    )
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# 哈希计算
# ---------------------------------------------------------------------------

def compute_file_hash(path: Path | str) -> str:
    """计算单个文件的 sha256 哈希。"""
    path = Path(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def compute_code_hash(code_files: list[Path | str]) -> str:
    """计算多个代码文件的合并哈希（顺序无关）。"""
    hashes = sorted(compute_file_hash(f) for f in code_files if Path(f).exists())
    if not hashes:
        return "0" * 64
    combined = "|".join(hashes)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def compute_config_hash(config: dict[str, Any]) -> str:
    """计算配置字典的哈希（序列化后哈希）。"""
    if not config:
        return "0" * 64
    # sort_keys 确保顺序无关
    serialized = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_fingerprint(
    input_files: dict[str, Path | str],
    code_files: list[Path | str],
    config: dict[str, Any],
) -> dict[str, str]:
    """计算完整指纹：输入哈希 + 代码哈希 + 配置哈希。"""
    input_hashes = {
        name: compute_file_hash(path)
        for name, path in input_files.items()
        if Path(path).exists()
    }
    return {
        "input_hash": hashlib.sha256(
            "|".join(f"{k}={v}" for k, v in sorted(input_hashes.items())).encode("utf-8")
        ).hexdigest() if input_hashes else "0" * 64,
        "code_hash": compute_code_hash(code_files),
        "config_hash": compute_config_hash(config),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
uv run pytest tests/test_artifact_cache.py -v
```
Expected: 4 个测试全部 PASS

- [ ] **Step 5: Commit**

```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
git add src/amta/artifact_cache.py tests/test_artifact_cache.py
git commit -m "feat: artifact_cache核心哈希计算函数（文件/代码/配置指纹）"
```

---

### Task 2: 指纹存储与新鲜度检查

**Files:**
- Modify: `src/amta/artifact_cache.py`
- Test: `tests/test_artifact_cache.py`

- [ ] **Step 1: 写失败测试 — 指纹保存与加载**

在 `tests/test_artifact_cache.py` 末尾添加：

```python
def test_save_and_load_fingerprint(tmp_path):
    """指纹保存到 .fingerprint 文件，可加载。"""
    from amta.artifact_cache import save_fingerprint, load_fingerprint, fingerprint_path
    output = tmp_path / "result.json"
    output.write_text("{}", encoding="utf-8")
    fp = {"input_hash": "a" * 64, "code_hash": "b" * 64, "config_hash": "c" * 64}
    save_fingerprint(output, "typeset", "page_11", fp)
    fp_path = fingerprint_path(output)
    assert fp_path.exists()
    loaded = load_fingerprint(output)
    assert loaded["stage"] == "typeset"
    assert loaded["page"] == "page_11"
    assert loaded["input_hash"] == "a" * 64


def test_is_fresh_when_fingerprint_matches(tmp_path):
    """指纹匹配时 is_fresh 返回 True。"""
    from amta.artifact_cache import is_fresh, save_fingerprint, compute_fingerprint
    # 创建输入文件
    inp = tmp_path / "input.json"
    inp.write_text('{"data": 123}', encoding="utf-8")
    output = tmp_path / "result.json"
    output.write_text("{}", encoding="utf-8")
    # 保存指纹
    fp = compute_fingerprint({"input": inp}, [], {})
    save_fingerprint(output, "test", "page_1", fp)
    # 检查新鲜度
    assert is_fresh(output, {"input": inp}, [], {}) is True


def test_is_fresh_when_input_changes(tmp_path):
    """输入文件变化后 is_fresh 返回 False。"""
    from amta.artifact_cache import is_fresh, save_fingerprint, compute_fingerprint
    inp = tmp_path / "input.json"
    inp.write_text('{"data": 123}', encoding="utf-8")
    output = tmp_path / "result.json"
    output.write_text("{}", encoding="utf-8")
    fp = compute_fingerprint({"input": inp}, [], {})
    save_fingerprint(output, "test", "page_1", fp)
    # 修改输入
    inp.write_text('{"data": 456}', encoding="utf-8")
    assert is_fresh(output, {"input": inp}, [], {}) is False


def test_is_fresh_when_output_missing(tmp_path):
    """输出文件不存在时 is_fresh 返回 False。"""
    from amta.artifact_cache import is_fresh
    inp = tmp_path / "input.json"
    inp.write_text("{}", encoding="utf-8")
    output = tmp_path / "nonexistent.json"
    assert is_fresh(output, {"input": inp}, [], {}) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
uv run pytest tests/test_artifact_cache.py::test_save_and_load_fingerprint -v
```
Expected: FAIL（`save_fingerprint` 未定义）

- [ ] **Step 3: 实现指纹存储与新鲜度检查**

在 `src/amta/artifact_cache.py` 末尾添加：

```python
# ---------------------------------------------------------------------------
# 指纹存储
# ---------------------------------------------------------------------------

def fingerprint_path(output_path: Path | str) -> Path:
    """返回 artifact 对应的 .fingerprint 文件路径。"""
    output_path = Path(output_path)
    return output_path.with_suffix(output_path.suffix + ".fingerprint")


def save_fingerprint(
    output_path: Path | str,
    stage: str,
    page: str,
    fingerprint: dict[str, str],
) -> Path:
    """保存指纹到 .fingerprint 文件。"""
    output_path = Path(output_path)
    fp_path = fingerprint_path(output_path)
    doc = {
        "stage": stage,
        "page": page,
        "schema_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        **fingerprint,
    }
    fp_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return fp_path


def load_fingerprint(output_path: Path | str) -> dict[str, Any] | None:
    """加载指纹，文件不存在返回 None。"""
    fp_path = fingerprint_path(output_path)
    if not fp_path.exists():
        return None
    try:
        return json.loads(fp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def is_fresh(
    output_path: Path | str,
    input_files: dict[str, Path | str],
    code_files: list[Path | str],
    config: dict[str, Any],
) -> bool:
    """检查 artifact 是否新鲜（输入/代码/配置都没变）。"""
    output_path = Path(output_path)
    # 输出文件不存在 → 不新鲜
    if not output_path.exists():
        return False
    # 指纹文件不存在 → 不新鲜
    saved = load_fingerprint(output_path)
    if saved is None:
        return False
    # 计算当前指纹
    current = compute_fingerprint(input_files, code_files, config)
    # 对比三个哈希
    return (
        saved.get("input_hash") == current["input_hash"]
        and saved.get("code_hash") == current["code_hash"]
        and saved.get("config_hash") == current["config_hash"]
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
uv run pytest tests/test_artifact_cache.py -v
```
Expected: 8 个测试全部 PASS

- [ ] **Step 5: Commit**

```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
git add src/amta/artifact_cache.py tests/test_artifact_cache.py
git commit -m "feat: 指纹存储与新鲜度检查（save/load/is_fresh）"
```

---

### Task 3: 条件执行封装 run_stage_if_needed

**Files:**
- Modify: `src/amta/artifact_cache.py`
- Test: `tests/test_artifact_cache.py`

- [ ] **Step 1: 写失败测试 — 条件执行**

在 `tests/test_artifact_cache.py` 末尾添加：

```python
def test_run_stage_if_needed_skips_when_fresh(tmp_path):
    """输入未变时跳过执行，直接返回已有结果。"""
    from amta.artifact_cache import run_stage_if_needed
    inp = tmp_path / "input.json"
    inp.write_text('{"data": 123}', encoding="utf-8")
    output = tmp_path / "result.json"
    # 第一次运行
    call_count = 0
    def generate():
        nonlocal call_count
        call_count += 1
        output.write_text(f'{{"result": {call_count}}}', encoding="utf-8")
        return {"ran": True}
    result1 = run_stage_if_needed(
        stage_name="test", page="page_1",
        input_files={"input": inp}, code_files=[], config={},
        output_path=output, generate_fn=generate,
    )
    assert result1["cache_hit"] is False
    assert call_count == 1
    # 第二次运行（输入未变）
    result2 = run_stage_if_needed(
        stage_name="test", page="page_1",
        input_files={"input": inp}, code_files=[], config={},
        output_path=output, generate_fn=generate,
    )
    assert result2["cache_hit"] is True
    assert call_count == 1  # 没有再次调用


def test_run_stage_if_needed_reruns_when_input_changes(tmp_path):
    """输入变化时重新执行。"""
    from amta.artifact_cache import run_stage_if_needed
    inp = tmp_path / "input.json"
    inp.write_text('{"data": 123}', encoding="utf-8")
    output = tmp_path / "result.json"
    call_count = 0
    def generate():
        nonlocal call_count
        call_count += 1
        output.write_text(f'{{"result": {call_count}}}', encoding="utf-8")
    # 第一次
    run_stage_if_needed("test", "p1", {"input": inp}, [], {}, output, generate)
    assert call_count == 1
    # 修改输入后第二次
    inp.write_text('{"data": 456}', encoding="utf-8")
    run_stage_if_needed("test", "p1", {"input": inp}, [], {}, output, generate)
    assert call_count == 2  # 重新执行了


def test_run_stage_if_needed_returns_artifact(tmp_path):
    """返回值包含 artifact 内容和缓存状态。"""
    from amta.artifact_cache import run_stage_if_needed
    inp = tmp_path / "input.json"
    inp.write_text("{}", encoding="utf-8")
    output = tmp_path / "result.json"
    def generate():
        output.write_text('{"key": "value"}', encoding="utf-8")
    result = run_stage_if_needed("test", "p1", {"input": inp}, [], {}, output, generate)
    assert result["cache_hit"] is False
    assert result["output_path"] == str(output)
    assert result["stage"] == "test"
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
uv run pytest tests/test_artifact_cache.py::test_run_stage_if_needed_skips_when_fresh -v
```
Expected: FAIL（`run_stage_if_needed` 未定义）

- [ ] **Step 3: 实现条件执行封装**

在 `src/amta/artifact_cache.py` 末尾添加：

```python
# ---------------------------------------------------------------------------
# 条件执行封装
# ---------------------------------------------------------------------------

def run_stage_if_needed(
    stage_name: str,
    page: str,
    input_files: dict[str, Path | str],
    code_files: list[Path | str],
    config: dict[str, Any],
    output_path: Path | str,
    generate_fn: Callable[[], Any],
) -> dict[str, Any]:
    """条件执行：如果 artifact 新鲜则跳过，否则执行 generate_fn 并保存指纹。

    Args:
        stage_name: 阶段名称（如 "typeset", "translation"）
        page: 页码（如 "page_11"）
        input_files: 输入文件映射 {名称: 路径}
        code_files: 该阶段依赖的代码文件列表
        config: 配置参数字典
        output_path: 输出 artifact 路径
        generate_fn: 生成函数，无参数，执行后应在 output_path 生成 artifact

    Returns:
        {
            "cache_hit": bool,        # True=跳过，False=重新执行
            "stage": str,
            "page": str,
            "output_path": str,
        }
    """
    output_path = Path(output_path)

    # 检查是否新鲜
    if is_fresh(output_path, input_files, code_files, config):
        return {
            "cache_hit": True,
            "stage": stage_name,
            "page": page,
            "output_path": str(output_path),
        }

    # 不新鲜 → 执行生成
    generate_fn()

    # 生成后保存指纹
    fingerprint = compute_fingerprint(input_files, code_files, config)
    save_fingerprint(output_path, stage_name, page, fingerprint)

    return {
        "cache_hit": False,
        "stage": stage_name,
        "page": page,
        "output_path": str(output_path),
    }


# ---------------------------------------------------------------------------
# 批量工具
# ---------------------------------------------------------------------------

def invalidate_cache(output_path: Path | str) -> bool:
    """删除指定 artifact 的指纹文件，强制下次重跑。返回是否删除成功。"""
    fp_path = fingerprint_path(output_path)
    if fp_path.exists():
        fp_path.unlink()
        return True
    return False


def invalidate_cache_for_page(artifacts_dir: Path | str, page: str) -> int:
    """删除某页所有 artifact 的指纹，返回删除的指纹文件数。"""
    artifacts_dir = Path(artifacts_dir)
    count = 0
    for fp_path in artifacts_dir.glob(f"{page}_*.fingerprint"):
        fp_path.unlink()
        count += 1
    return count


def cache_status(artifacts_dir: Path | str) -> dict[str, int]:
    """统计缓存状态：总artifact数、有指纹的数、可统计的页数。"""
    artifacts_dir = Path(artifacts_dir)
    all_json = list(artifacts_dir.glob("*.json"))
    fingerprints = list(artifacts_dir.glob("*.fingerprint"))
    pages = set()
    for f in all_json:
        # page_11_typeset.json → page_11
        parts = f.stem.split("_")
        if len(parts) >= 2 and parts[0] == "page":
            pages.add(f"page_{parts[1]}")
    return {
        "total_artifacts": len(all_json),
        "cached_with_fingerprint": len(fingerprints),
        "pages_tracked": len(pages),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
uv run pytest tests/test_artifact_cache.py -v
```
Expected: 11 个测试全部 PASS

- [ ] **Step 5: Commit**

```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
git add src/amta/artifact_cache.py tests/test_artifact_cache.py
git commit -m "feat: run_stage_if_needed条件执行封装 + 批量缓存管理工具"
```

---

### Task 4: 集成到排版阶段（示范接入）

**Files:**
- Create: `examples/use_artifact_cache_typeset.py`
- Modify: `src/amta/artifacts.py`（增加辅助函数）

- [ ] **Step 1: 在 artifacts.py 增加 fingerprint_path 导出**

在 `src/amta/artifacts.py` 的 `artifact_paths()` 函数后添加：

```python
def fingerprint_paths(artifacts_dir: Path, page: str) -> dict[str, Path]:
    """返回各 artifact 对应的 fingerprint 文件路径。"""
    paths = artifact_paths(artifacts_dir, page)
    return {k: Path(str(v) + ".fingerprint") for k, v in paths.items()}
```

- [ ] **Step 2: 创建示范接入脚本**

创建 `examples/use_artifact_cache_typeset.py`：

```python
"""示范：如何在排版阶段使用 artifact_cache。

运行方式：
    uv run python examples/use_artifact_cache_typeset.py --pages 11 12 13 14 15

效果：
    - 第一次运行：执行排版，生成 typeset.json 和 .fingerprint
    - 第二次运行（输入未变）：跳过排版，直接用已有结果
    - 修改 typeset_engine.py 后运行：自动重跑排版
"""
import argparse
import sys
from pathlib import Path

# 确保 src 在路径中
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from amta.artifact_cache import run_stage_if_needed, cache_status
from amta.artifacts import artifact_paths


def run_typeset_for_page(art_dir: Path, page: str) -> None:
    """执行单页排版（简化版，实际应调用完整的 typeset_station）。"""
    from amta.typeset_render import render_item
    from amta.artifacts import load_canon, load_translation
    from PIL import Image
    import json

    canon = load_canon(art_dir / f"{page}_canon.json")
    trans = load_translation(art_dir / f"{page}_translation.json")
    clean_path = art_dir / "clean" / f"{page}_clean.png"
    clean_img = Image.open(clean_path)

    rendered = []
    for item in canon["items"]:
        rid = item["region_id"]
        text = trans["translations"].get(rid, "")
        if text:
            result = render_item(clean_img, text, "msyh.ttc", item["bbox"],
                                stroke=0, preferred_direction=None)
            result["region_id"] = rid
            rendered.append(result)

    # 保存最终图
    final_path = art_dir / "final" / f"{page}_final.png"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    clean_img.save(final_path)

    # 保存 typeset.json
    typeset_path = art_dir / f"{page}_typeset.json"
    doc = {
        "work_id": canon.get("work_id", ""),
        "page": page,
        "rendered_items": rendered,
        "final_image": f"final/{page}_final.png",
        "generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
    }
    typeset_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="示范：使用 artifact_cache 做增量排版")
    parser.add_argument("--pages", type=int, nargs="+", default=[11, 12, 13, 14, 15],
                       help="要处理的页码")
    parser.add_argument("--art-dir", type=str,
                       default="workspace/touhou-e2e-orchestrator/artifacts",
                       help="artifact 目录")
    args = parser.parse_args()

    art_dir = Path(args.art_dir)
    # 排版阶段依赖的代码文件
    code_files = [
        Path("src/amta/typeset_engine.py"),
        Path("src/amta/typeset_render.py"),
        Path("src/amta/artifacts.py"),
    ]

    cache_hits = 0
    cache_misses = 0

    for page_num in args.pages:
        page = f"page_{page_num}"
        paths = artifact_paths(art_dir, page)
        output_path = paths["typeset"]

        result = run_stage_if_needed(
            stage_name="typeset",
            page=page,
            input_files={
                "canon": paths["canon"],
                "translation": paths["translation"],
                "clean_image": art_dir / "clean" / f"{page}_clean.png",
            },
            code_files=code_files,
            config={"font_max": 52, "safe_ratio": 0.85},
            output_path=output_path,
            generate_fn=lambda p=page: run_typeset_for_page(art_dir, p),
        )

        if result["cache_hit"]:
            print(f"  {page}: CACHE HIT (跳过排版)")
            cache_hits += 1
        else:
            print(f"  {page}: CACHE MISS (执行排版)")
            cache_misses += 1

    print(f"\n统计: {cache_hits} 命中, {cache_misses} 未命中")
    print(f"缓存状态: {cache_status(art_dir)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 运行示范脚本验证**

```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
uv run python examples/use_artifact_cache_typeset.py --pages 11 12
```
Expected:
- 第一次运行：2 个 CACHE MISS（执行排版）
- 生成 `page_11_typeset.json.fingerprint` 和 `page_12_typeset.json.fingerprint`

再跑一次：
```powershell
uv run python examples/use_artifact_cache_typeset.py --pages 11 12
```
Expected:
- 第二次运行：2 个 CACHE HIT（跳过排版）
- 执行时间明显缩短

- [ ] **Step 4: 验证代码变化触发重跑**

```powershell
# 随便改一下 typeset_engine.py（加个注释）
echo "# test cache invalidation" >> src/amta/typeset_engine.py
uv run python examples/use_artifact_cache_typeset.py --pages 11
```
Expected: CACHE MISS（代码变了，重跑排版）

```powershell
# 恢复（去掉刚才加的注释）
# 用 git 恢复
git checkout src/amta/typeset_engine.py
uv run python examples/use_artifact_cache_typeset.py --pages 11
```
Expected: CACHE HIT（代码恢复了，指纹又匹配了）

- [ ] **Step 5: Commit**

```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
git add src/amta/artifacts.py examples/use_artifact_cache_typeset.py
git commit -m "feat: 集成示范脚本 + artifacts.py增加fingerprint_paths辅助函数"
```

---

### Task 5: 文档与全量测试

**Files:**
- Create: `docs/debug/artifact-cache-design.md`
- Test: 全量回归

- [ ] **Step 1: 写设计文档**

创建 `docs/debug/artifact-cache-design.md`：

```markdown
# Artifact Cache 增量构建 — 设计文档

## 问题
每次修改 pipeline 任一阶段的代码，都需要从头重跑整个 pipeline（detection → OCR → translation → inpaint → typeset），即使只改了排版引擎。LLM 调用耗时且花钱。

## 解决方案
基于内容哈希的增量构建（参考 Make/Snakemake/doit）：
- 每个 artifact 旁边存一个 `.fingerprint` 文件
- 指纹记录：输入文件哈希 + 代码文件哈希 + 配置哈希
- 运行前计算当前指纹，与已存指纹对比
- 一致 → 跳过，直接用已有 artifact
- 不一致 → 重跑该阶段，保存新指纹

## 核心 API
```python
from amta.artifact_cache import run_stage_if_needed

result = run_stage_if_needed(
    stage_name="typeset",
    page="page_11",
    input_files={"canon": canon_path, "translation": trans_path},
    code_files=["typeset_engine.py", "typeset_render.py"],
    config={"font_max": 52},
    output_path=typeset_path,
    generate_fn=lambda: run_typeset(...),
)
# result["cache_hit"] == True → 跳过
# result["cache_hit"] == False → 执行了
```

## 依赖传播
修改上游阶段会自动导致下游阶段缓存失效：
- 改了 translation.py → translation.json 重跑 → typeset 的输入变了 → typeset 也重跑
- 改了 typeset_engine.py → 只有 typeset 重跑，上游都跳过

## 文件结构
```
artifacts/
├── page_11_canon.json
├── page_11_canon.json.fingerprint   ← 新增
├── page_11_translation.json
├── page_11_translation.json.fingerprint  ← 新增
├── page_11_typeset.json
└── page_11_typeset.json.fingerprint  ← 新增
```

## 管理工具
- `invalidate_cache(output_path)` — 删除单个指纹，强制重跑
- `invalidate_cache_for_page(art_dir, page)` — 删除某页所有指纹
- `cache_status(art_dir)` — 统计缓存状态

## 参考项目
- Make — 经典构建工具，基于文件修改时间
- doit (pydoit) — Python 任务自动化，基于文件哈希
- Snakemake — 生物信息学流水线，DAG + 增量构建
- DVC — ML 实验版本控制，pipeline + 数据版本
```

- [ ] **Step 2: 运行全量测试回归**

```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
uv run pytest tests/ -q --ignore=tests/test_detect_rtdetr.py
```
Expected: 原有 375 passed + 新增 11 = 386 passed，0 failed（除 onnxruntime 相关的 3 个已有失败）

- [ ] **Step 3: 最终 Commit + 交接文档**

```powershell
cd E:\manga translator agent\amta-wt-artifact-cache
git add docs/debug/artifact-cache-design.md
git commit -m "docs: artifact-cache设计文档 + 全量测试通过"
```

创建交接文档 `docs/debug/artifact-cache-handoff-2026-09-05.md`，包含：
- 模块功能摘要
- 核心 API 说明
- 测试结果（新增11个测试，全量386 passed）
- 示范脚本路径
- 后续接入其他阶段的指引（detection/translation/inpaint 如何接入）

---

## 自检清单

- [x] **Spec覆盖**: 哈希计算 → Task 1；指纹存储 → Task 2；条件执行 → Task 3；集成示范 → Task 4；文档测试 → Task 5
- [x] **无占位符**: 所有步骤都有具体代码和命令
- [x] **类型一致**: `run_stage_if_needed` 参数顺序在测试和实现中一致
- [x] **向后兼容**: 新模块不修改现有代码，纯增量
- [x] **可测试**: 11个单元测试覆盖核心路径
