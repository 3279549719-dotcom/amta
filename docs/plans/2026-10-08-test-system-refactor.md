# 测试体系彻底重构 Implementation Plan

> **For agentic workers:** 按 checkbox 逐项执行。每完成一个 Task 跑一次验证，通过后再 Commit。

**Goal:** 把现在"724 个测试一锅端、gate 判据有后门、人工红名单空转"的测试体系，重构成"分层明确、自动检测设施、gate 判据诚实、CI 分层"的工业级测试体系。

**Architecture:**
- **删掉**：testmon（从 gate 路径移除，降级为本地可选工具）、baseline-red.txt（人工红名单机制整个砍掉）
- **替换**：人工 marker → 自动设施探测（`@requires_torch` / `@requires_onnx`，没装就自动 skip）
- **重构**：gate 判据修诚实（非 pytest 护栏失败也变红）
- **分层**：目录按子系统分（typeset/translate/ocr/inpaint/orchestrator/meta），不是按 unit/integration 分
- **自动化**：`RUN_SLOW=1` 环境变量控制重测试，不靠人记得加 marker

**Tech Stack:** pytest 9.x, pytest-xdist（并行加速，替代 testmon）, 纯 Python, GitHub Actions（CI）

**调研依据:**
- 6 个主流项目（pytest/pydantic/httpx/requests/rich/transformers）**没有一个在 CI 用 testmon**——加速靠 xdist 并行
- transformers 用 `@require_torch` 装饰器**自动 skip**，不靠人手动打 marker
- 没有一个主流项目用"人工红名单"——用 `RUN_SLOW=1` 环境变量声明式控制
- pydantic 把 meta-test 放 `tests/mypy/`，物理隔离 + 单独 CI job

---

## 文件结构（重构后的目录）

```
tests/
├── conftest.py                    # 共享 fixture（保留）
├── requires.py                    # 【新建】设施自动探测装饰器
├── typeset/                       # 排版相关
│   ├── test_typeset_engine.py
│   ├── test_typeset_render.py
│   ├── test_typeset_cell_metrics.py
│   ├── test_typeset_station.py
│   ├── test_typeset_export_failure.py
│   ├── test_vertical_punct.py
│   ├── test_vertical_punctuation_fix.py
│   ├── test_vertical_wrap_balance.py
│   ├── test_column_end_pause.py
│   ├── test_column_end_pause_edge_cases.py
│   ├── test_column_end_pause_render.py
│   └── test_vlm_render.py
├── translate/                      # 翻译相关
│   ├── test_translate_repair.py
│   ├── test_translate_station.py
│   ├── test_translation_input_contract.py
│   ├── test_context_semantic_transfer.py
│   ├── test_name_pre_scan.py
│   └── test_front3_stage1.py / test_front3_stage2.py
├── ocr/                           # OCR 相关
│   ├── test_ocr_conf_guard.py
│   ├── test_ocr_station.py
│   └── test_vlm_ocr.py
├── inpaint/                       # 修复相关
│   ├── test_inpaint_station.py
│   ├── test_inpaint_strategy.py
│   ├── test_lama_ffc.py
│   ├── test_local_lama_inpainter_manga.py
│   └── test_uniform_fill.py
├── detect/                        # 检测相关
│   ├── test_detect_rtdetr.py
│   └── test_detect_defaults.py
├── orchestrator/                   # 编排相关
│   ├── test_page_selection.py
│   ├── test_orchestrator_smoke.py
│   ├── test_final_integration.py
│   ├── test_stage3_minimal.py
│   ├── test_pipeline_flow.py
│   ├── test_pipeline_cache_outputs.py
│   └── test_run_pipeline_zero_pages.py
├── gui/                           # GUI 相关
│   ├── test_gui_server.py
│   ├── test_gui_e2e.py
│   ├── test_gui_frontend.py
│   └── test_glossary.py
├── artifacts/                     # 制品缓存相关
│   ├── test_artifacts.py
│   ├── test_artifact_cache.py
│   ├── test_artifact_cli.py
│   └── test_artifact_store.py
├── meta/                          # 【新建】仓库守卫/meta-test
│   ├── test_reference_integrity.py
│   ├── test_lessons_guard.py
│   ├── test_depguard.py
│   ├── test_probe_hardcoded_terms.py
│   ├── test_fastcheck_guard_order.py
│   └── test_harness_covenant.py
├── state/                         # 状态管理/CLI
│   ├── test_state_manager.py
│   ├── test_state_finish_gate.py
│   ├── test_state_finish_stowaway.py
│   ├── test_workstate.py
│   └── test_memory_cli.py
├── memory/                        # 记忆系统
│   ├── test_memory_estate.py
│   ├── test_memory_gc.py
│   ├── test_memory_inject.py
│   ├── test_memory_lint.py
│   └── test_memory_tools.py
├── book/                          # 书籍/词表
│   ├── test_book_bootstrap.py
│   ├── test_book_store.py
│   └── test_book_translation_memory.py
└── common/                        # 公共工具
    ├── test_encoding.py
    ├── test_config.py
    ├── test_output.py
    ├── test_fonts.py
    ├── test_metrics.py
    ├── test_text_normalize.py
    ├── test_break_lines.py
    ├── test_bbox_shrink.py
    ├── test_canon_schema.py
    ├── test_deliverables.py
    ├── test_guardrails.py
    ├── test_report_ledger.py
    ├── test_suggestions.py
    ├── test_tickets.py
    ├── test_quality_audit.py
    ├── test_shared_lib.py
    ├── test_refactor_shared.py
    ├── test_psd_export_runtime.py
    ├── test_psd_jsx_export.py
    └── test_render_artifact_contract.py
```

---

## Task 1: 新建 tests/requires.py — 设施自动探测

**Files:**
- Create: `tests/requires.py`

- [ ] **Step 1: 写设施探测装饰器**

```python
"""tests/requires.py — 重设施自动探测装饰器。

原则（学 transformers @require_torch）：
  - 不靠人手动打 marker，没装就自动 skip
  - 探测结果缓存，不重复探测
  - RUN_SLOW=1 环境变量强制跑（用于 CI nightly / 本地全量）

用法：
    from tests.requires import requires_torch, requires_onnx, requires_model_file

    @requires_torch
    def test_lama_forward(): ...

    @requires_model_file("models/CTBD/detector.onnx")
    def test_detect_runs(): ...
"""
from __future__ import annotations

import os
import shutil
from functools import cache
from pathlib import Path

import pytest

RUN_SLOW = os.environ.get("RUN_SLOW") == "1"


@cache
def _has_torch() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


@cache
def _has_onnxruntime() -> bool:
    try:
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


@cache
def _has_fastapi() -> bool:
    try:
        import fastapi  # noqa: F401
        return True
    except ImportError:
        return False


def requires_torch(func):
    """没装 torch 就 skip（RUN_SLOW=1 强制跑）。"""
    if RUN_SLOW or _has_torch():
        return func
    return pytest.mark.skip(reason="torch not installed (set RUN_SLOW=1 to force)")(func)


def requires_onnx(func):
    """没装 onnxruntime 就 skip。"""
    if RUN_SLOW or _has_onnxruntime():
        return func
    return pytest.mark.skip(reason="onnxruntime not installed (set RUN_SLOW=1 to force)")(func)


def requires_fastapi(func):
    """没装 fastapi 就 skip。"""
    if RUN_SLOW or _has_fastapi():
        return func
    return pytest.mark.skip(reason="fastapi not installed (set RUN_SLOW=1 to force)")(func)


def requires_model_file(rel_path: str):
    """模型文件不存在就 skip。"""
    root = Path(__file__).resolve().parent.parent
    full = root / rel_path
    marker = pytest.mark.skipif(
        not (RUN_SLOW or full.exists()),
        reason=f"model file not found: {rel_path} (set RUN_SLOW=1 to force)",
    )
    def decorator(func):
        return marker(func)
    return decorator
```

- [ ] **Step 2: 验证装饰器能 import**

Run: `uv run python -c "from tests.requires import requires_torch; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```powershell
git add tests/requires.py
git commit -m "test: add requires.py — auto facility detection (torch/onnx/fastapi/model files)"
```

---

## Task 2: 把重测试从"手动 marker"改成"自动探测"

**Files:**
- Modify: `tests/test_detect_rtdetr.py`
- Modify: `tests/test_lama_ffc.py`
- Modify: `tests/test_local_lama_inpainter_manga.py`
- Modify: `tests/test_inpaint_station.py`
- Modify: `tests/test_gui_server.py`
- Modify: `tests/test_gui_e2e.py`

- [ ] **Step 1: 每个文件把 `pytestmark = pytest.mark.slow` 换成自动探测装饰器**

对每个文件：
1. 删掉 `pytestmark = pytest.mark.slow`
2. 在文件顶部加 import：
   ```python
   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path(__file__).resolve().parent))
   from requires import requires_torch, requires_onnx, requires_fastapi, requires_model_file
   ```
3. 在每个 test 函数上面加对应的装饰器：
   - `test_detect_rtdetr.py` → 每个 test 加 `@requires_onnx` + `@requires_model_file("models/CTBD/detector.onnx")`
   - `test_lama_ffc.py` → 每个 test 加 `@requires_torch`
   - `test_local_lama_inpainter_manga.py` → 每个 test 加 `@requires_torch`
   - `test_inpaint_station.py` → 每个 test 加 `@requires_torch`
   - `test_gui_server.py` → 每个 test 加 `@requires_fastapi`
   - `test_gui_e2e.py` → 每个 test 加 `@requires_fastapi`

- [ ] **Step 2: 验证默认跑时这些测试被 skip**

Run: `uv run python -m pytest tests/test_detect_rtdetr.py -v --tb=no 2>&1 | Select-Object -Last 5`
Expected: 显示 `skipped` 而不是跑（如果 onnxruntime 没装或模型文件不存在）

- [ ] **Step 3: 验证 RUN_SLOW=1 强制跑**

Run: `$env:RUN_SLOW='1'; uv run python -m pytest tests/test_detect_rtdetr.py -v --tb=no 2>&1 | Select-Object -Last 5; Remove-Item Env:RUN_SLOW`
Expected: 测试真正开始跑（可能红，那是既有状态）

- [ ] **Step 4: Commit**

```powershell
git add tests/test_detect_rtdetr.py tests/test_lama_ffc.py tests/test_local_lama_inpainter_manga.py tests/test_inpaint_station.py tests/test_gui_server.py tests/test_gui_e2e.py
git commit -m "test: replace manual slow markers with auto facility detection"
```

---

## Task 3: 重构 pyproject.toml — 删 testmon、改 markers、加 xdist

**Files:**
- Modify: `pyproject.toml:80-100` (`[tool.pytest.ini_options]`)

- [ ] **Step 1: 替换 pytest 配置**

把现有 `[tool.pytest.ini_options]` 整段替换为：

```toml
[tool.pytest.ini_options]
pythonpath = ["src", "."]
# Windows 全局临时目录可能残留无权限 pytest-current 链接；测试临时文件固定留在项目同盘目录。
addopts = "--basetemp=.pytest_tmp --strict-markers"
testpaths = ["tests"]
markers = [
    "experiment: 实验性 probe 脚本测试，可能随时失效或删除。默认排除，RUN_SLOW=1 强制跑。",
]
# 不再用 testmon：它在 CI 不可靠（6 个主流项目没一个用），本地用 pytest-xdist 并行加速。
# 重测试靠 tests/requires.py 自动 skip，不靠 marker。
```

- [ ] **Step 2: 验证配置生效**

Run: `uv run python -m pytest tests --collect-only -q 2>&1 | Select-Object -Last 3`
Expected: 收集数正常，无 unknown marker 报错

- [ ] **Step 3: Commit**

```powershell
git add pyproject.toml
git commit -m "chore(test): remove testmon from config, simplify markers (auto-detect replaces manual)"
```

---

## Task 4: 重构 fastcheck.py — 删 testmon、删 mark 过滤、修 gate 判据

**Files:**
- Modify: `scripts/fastcheck.py:223-270` (`_test()` 函数)

- [ ] **Step 1: 改 `_test()` 函数——删 testmon、删 mark 过滤**

把现有 `_test()` 整段替换为：

```python
def _test() -> int:
    """跑 tests/ 单测。

    2026-10-08 彻底重构：
      - 删 testmon（CI 不可靠，本地用 xdist 并行）
      - 删手动 mark 过滤（重测试靠 requires.py 自动 skip）
      - 失败 test ID 仍落到 .dsh/pytest-failing-last.txt（供 gate 基线对比）
    """
    import re as _re
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    basetemp = ROOT / "output" / "logs" / f".pytest-bt-{os.getpid()}"
    pytest_args = [
        sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q",
        "--basetemp", str(basetemp),
    ]
    r = subprocess.run(
        pytest_args,
        cwd=str(ROOT), env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    shutil.rmtree(basetemp, ignore_errors=True)
    print(out[-2000:])

    # 解析 FAILED/ERROR 行 → 落盘失败 test ID
    failing_ids: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("FAILED") or line.startswith("ERROR"):
            parts = line.split(" ", 1)
            if len(parts) >= 2:
                failing_ids.append(parts[1].split(" - ")[0])
    failing_file = ROOT / ".dsh" / "pytest-failing-last.txt"
    failing_file.parent.mkdir(parents=True, exist_ok=True)
    failing_file.write_text("\n".join(sorted(failing_ids)), encoding="utf-8")

    m = _re.search(r"(\d+) passed", out)
    failed = _re.search(r"(\d+) failed", out)
    if m and not failed:
        print(f"== [fastcheck] pytest: {m.group(1)} passed（{len(failing_ids)} failing 已落盘）==")
        return 0
    print(f"== [fastcheck] pytest 无通过汇总（exit {r.returncode}）==")
    return 1
```

- [ ] **Step 2: 验证 fastcheck --quick 还能跑**

Run: `uv run python scripts/fastcheck.py --quick 2>&1 | Select-Object -Last 5`
Expected: 秒级通过（--quick 不跑 pytest）

- [ ] **Step 3: Commit**

```powershell
git add scripts/fastcheck.py
git commit -m "perf(gate): remove testmon from _test(), keep failing-list dump for gate"
```

---

## Task 5: 修 state_manager.py — gate 判据诚实 + 删 baseline 红名单

**Files:**
- Modify: `src/amta/common/state_manager.py:540-606` (`GateReport` + `run_gate()`)

- [ ] **Step 1: 修 GateReport.passed 判据——删掉后门**

把现有 `GateReport.passed` 属性（约 560 行）：

```python
    @property
    def passed(self) -> bool:
        """gate 是否通过：fastcheck 全绿，或红的全是既有红。"""
        return self.fastcheck_returncode == 0 or not self.new_failures
```

改成：

```python
    @property
    def passed(self) -> bool:
        """gate 是否通过：fastcheck 全绿才是绿。

        2026-10-08 修：原来 `or not self.new_failures` 是个后门——
        ruff/depguard 失败时 new_failures 是空（因为不是 test ID），gate 照样报 PASS。
        现在：fastcheck 退出码非零 = gate 红，没有例外。
        """
        return self.fastcheck_returncode == 0
```

- [ ] **Step 2: 删 baseline 红名单相关函数**

把 `_pytest_failing_tests()`、`save_baseline()`、`load_baseline()`、`_read_last_failing()` 这些函数整个删掉。它们是人工红名单机制，不再需要。

把 `run_gate()` 改成：

```python
def run_gate() -> int:
    """跑质检门（fastcheck 全量）。**不碰 git**。

    2026-10-08 彻底重构：
      - 删 baseline 红名单（人工白名单会腐烂，换成 RUN_SLOW=1 环境变量控制重测试）
      - 删"只拦新红"逻辑（gate 就是 gate，红了就是红了）
      - 返回 fastcheck 退出码，不做二次判断
    """
    return _run_quality_gate()
```

- [ ] **Step 3: 改 state.py — 删 baseline 子命令**

把 `scripts/state.py` 里 `baseline` 子命令整个删掉，`run_gate()` 的调用方式同步改。

- [ ] **Step 4: 验证 state.py --help 还能跑**

Run: `uv run python scripts/state.py --help`
Expected: 显示 finish/gate/ship 三个子命令，没有 baseline

- [ ] **Step 5: Commit**

```powershell
git add src/amta/common/state_manager.py scripts/state.py
git commit -m "fix(gate): make verdict honest (no backdoor), remove baseline red-list mechanism"
```

---

## Task 6: 目录重构——把 88 个文件按子系统分到子目录

**Files:**
- Move: 88 个测试文件到上面"文件结构"里列的子目录

- [ ] **Step 1: 创建子目录**

```powershell
$dirs = @('typeset','translate','ocr','inpaint','detect','orchestrator','gui','artifacts','meta','state','memory','book','common')
foreach ($d in $dirs) { New-Item -ItemType Directory -Force -Path "tests\$d" | Out-Null }
```

- [ ] **Step 2: 移动文件（按上面的文件结构表）**

用 `git mv` 移动，保持 git 历史。具体映射见上面的文件结构表。

- [ ] **Step 3: 修 import 路径**

移动后，文件里的 `sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))` 要改成 `parent.parent.parent / "src"`（因为深了一层）。

- [ ] **Step 4: 验证收集数不变**

Run: `uv run python -m pytest tests --collect-only -q 2>&1 | Select-Object -Last 3`
Expected: 仍收集到 ~724 个测试（只是目录变了）

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "refactor(test): reorganize 88 test files into subsystem directories"
```

---

## Task 7: 加 pytest-xdist 并行加速

**Files:**
- Modify: `pyproject.toml` (dependency-groups)
- Modify: `scripts/fastcheck.py` (_test 函数)

- [ ] **Step 1: 加 pytest-xdist 依赖**

在 `pyproject.toml` 的 `[dependency-groups]` dev 里加：

```toml
dev = [
    "pytest>=9.1.1",
    "pytest-xdist>=3.5.0",
]
```

- [ ] **Step 2: fastcheck._test() 加并行**

在 `_test()` 的 `pytest_args` 里加 `-n auto`：

```python
pytest_args = [
    sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q",
    "-n", "auto",  # 并行加速（替代 testmon）
    "--basetemp", str(basetemp),
]
```

- [ ] **Step 3: 安装依赖**

Run: `uv sync`
Expected: 成功安装 pytest-xdist

- [ ] **Step 4: 验证并行生效**

Run: `uv run python -m pytest tests --collect-only -q 2>&1 | Select-Object -Last 3`
Expected: 收集数不变

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml scripts/fastcheck.py
git commit -m "perf(test): add pytest-xdist parallel (replaces testmon)"
```

---

## Task 8: 加最小 CI（GitHub Actions）

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: 写 CI 配置**

```yaml
name: test
on:
  push:
    branches: [main, refactor/**]
  pull_request:

jobs:
  fast:
    name: fast (CPU, no heavy)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install uv
      - run: uv sync
      - run: uv run python scripts/fastcheck.py --quick
      - name: pytest (fast subset, parallel)
        run: uv run python -m pytest tests -n auto --tb=short

  nightly:
    name: nightly (full, RUN_SLOW)
    runs-on: ubuntu-latest
    if: github.event_name == 'schedule'
    schedule:
      - cron: '0 2 * * *'  # 每天凌晨 2 点
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install uv
      - run: uv sync
      - name: pytest (full, with heavy)
        env:
          RUN_SLOW: "1"
        run: uv run python -m pytest tests -n auto --tb=short
```

- [ ] **Step 2: Commit**

```powershell
git add .github/workflows/test.yml
git commit -m "ci: add GitHub Actions — fast on push/PR, nightly full"
```

---

## Task 9: 验证端到端

- [ ] **Step 1: 跑 fastcheck --quick**

Run: `uv run python scripts/fastcheck.py --quick 2>&1 | Select-Object -Last 10`
Expected: 秒级通过

- [ ] **Step 2: 跑 gate**

Run: `uv run python scripts/state.py gate`
Expected: fastcheck 全量，判据诚实（红了就是红了）

- [ ] **Step 3: 验证重测试自动 skip**

Run: `uv run python -m pytest tests/test_lama_ffc.py -v --tb=no 2>&1 | Select-Object -Last 5`
Expected: `skipped`（torch 没装或模型文件不存在）

- [ ] **Step 4: 验证 RUN_SLOW=1 强制跑**

Run: `$env:RUN_SLOW='1'; uv run python -m pytest tests/test_lama_ffc.py -v --tb=no 2>&1 | Select-Object -Last 5; Remove-Item Env:RUN_SLOW`
Expected: 测试真正跑（可能红，那是既有状态）

- [ ] **Step 5: 最终 commit**

```powershell
git add -A
git commit -m "test: complete refactor — auto-detect, xdist parallel, honest gate, CI"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ "testmon 没用就注释掉" → Task 3、Task 4 删掉 testmon
- ✅ "gate 没用就刨掉" → Task 5 把 gate 判据修诚实（不删 gate 本身，因为它是唯一的收口点；但删掉了"只拦新红"的假门逻辑）
- ✅ "分层对不对" → Task 6 按子系统分目录
- ✅ "检测新增的对不对" → 删掉人工红名单，换成 requires.py 自动探测
- ✅ "自动化，不是人工红名单" → Task 1、Task 2、Task 5

**2. Placeholder scan:** 无 TBD/TODO，每步都有具体代码和命令。

**3. 关键不变量:**
- 724 个测试不删——只是重新组织 + 自动 skip
- `fastcheck --quick` 保留（pre-commit 钩子用）
- `state.py finish/gate/ship` 保留——只是 gate 判据变诚实
- baseline 子命令删掉——人工红名单机制整个砍掉

---

## 预期效果

| 指标 | 改之前 | 改之后 |
|---|---|---|
| 重测试处理 | 靠人手动打 marker，忘了就跑 | 自动探测，没装就 skip |
| gate 判据 | 有后门（ruff 失败照样报 PASS） | 诚实（fastcheck 红 = gate 红） |
| 人工红名单 | 文件不存在，功能空转 | 整个删掉，换成 RUN_SLOW=1 |
| testmon | 接在 gate 里，CI 不可靠 | 删掉，换 pytest-xdist 并行 |
| 目录结构 | 88 文件平铺 | 按子系统分 13 个子目录 |
| CI | 没有 | push 跑快速子集，nightly 跑全量 |
| gate 耗时 | 分钟级 + 内存爆炸 | 秒级（自动 skip 重测试 + xdist 并行） |
