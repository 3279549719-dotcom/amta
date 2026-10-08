# 测试分层与增量门（Test Layering & Incremental Gate）实施 Plan

> **For agentic workers:** 按 checkbox 逐项执行。每完成一个 Task 跑一次验证，通过后再 Commit。

**Goal:** 让 `state.py gate` 从"每次冷跑 724 个测试、内存爆炸"变成"只跑受本次改动影响的、非重测试的那一小撮，秒级出结果"。

**Architecture:** 三件事——
1. **修双跑**：gate 现在跑两遍 pytest（fastcheck 一遍 + state_manager 又一遍无 testmon 的全量），改成 fastcheck 那遍把失败 ID 落盘，gate 直接读文件。
2. **Markers 分层**：给重 ML / 实验探针测试打 `@pytest.mark.slow` / `@pytest.mark.experiment`，gate 默认排除它们；baseline 仍全量记录红名单。
3. **清缓存**：删掉 `tests/__pycache__/` 里源码已不存在的孤儿 .pyc。

**Tech Stack:** pytest 9.x, pytest-testmon 2.x, pyproject.toml `[tool.pytest.ini_options]`, 纯 Python。

**参考成熟做法:**
- pytest 官方 markers 文档（`@pytest.mark.slow` + `-m "not slow"`）
- CI 分层：fast pipeline（unit only）vs nightly（full incl. integration）
- testmon = Test Impact Analysis，只跑受影响测试
- `--strict-markers` 防止拼错 marker 名

---

## 文件结构

| 文件 | 动作 | 责任 |
|---|---|---|
| `pyproject.toml` | 修改 | 注册 markers + `--strict-markers` |
| `scripts/fastcheck.py` | 修改 | `_test()` 加 `-m` 过滤 + 把失败 ID 写到 `.dsh/pytest-failing-last.txt` |
| `src/amta/common/state_manager.py` | 修改 | `run_gate()` 读文件而非重跑 pytest |
| `tests/test_detect_rtdetr.py` | 加 mark | `@pytest.mark.slow`（加载 onnx） |
| `tests/test_lama_ffc.py` | 加 mark | `@pytest.mark.slow`（加载 torch） |
| `tests/test_local_lama_inpainter_manga.py` | 加 mark | `@pytest.mark.slow` |
| `tests/test_final_integration.py` | 加 mark | `@pytest.mark.slow`（全管线） |
| `tests/test_orchestrator_smoke.py` | 加 mark | `@pytest.mark.slow` |
| `tests/test_stage3_minimal.py` | 加 mark | `@pytest.mark.slow` |
| `tests/test_paratext_experiment.py` | 加 mark | `@pytest.mark.experiment`（probe 实验） |
| `tests/test_probe_hardcoded_terms.py` | 加 mark | `@pytest.mark.experiment` |
| `tests/__pycache__/` | 删除 | 孤儿 .pyc |

---

## Task 1: pyproject.toml 注册 markers

**Files:**
- Modify: `pyproject.toml:80-87` (`[tool.pytest.ini_options]`)

- [ ] **Step 1: 在 `[tool.pytest.ini_options]` 里加 markers 注册**

把现有这段：
```toml
[tool.pytest.ini_options]
pythonpath = ["src", "."]
addopts = "--basetemp=.pytest_tmp"
testpaths = ["tests"]
```

改成：
```toml
[tool.pytest.ini_options]
pythonpath = ["src", "."]
addopts = "--basetemp=.pytest_tmp --strict-markers"
testpaths = ["tests"]
markers = [
    "slow: 重测试——加载 ML 模型（torch/onnx/lama）或跑全管线（>5s 或大内存）。gate 默认排除，baseline 仍跑。",
    "experiment: 实验性 probe 脚本测试，可能随时失效或删除。gate 默认排除。",
]
```

- [ ] **Step 2: 验证注册生效**

Run: `uv run python -m pytest tests --collect-only -q 2>&1 | Select-Object -Last 3`
Expected: 仍收集到 ~724 个测试，无 `unknown marker` 报错。

- [ ] **Step 3: Commit**

```powershell
git add pyproject.toml
git commit -m "chore(test): register slow/experiment markers with --strict-markers"
```

---

## Task 2: fastcheck._test() 落盘失败 ID + gate 排除重测试

**Files:**
- Modify: `scripts/fastcheck.py:223-255` (`_test()` 函数)

- [ ] **Step 1: 改 `_test()` 函数**

把现有 `_test()`（223–255 行）整段替换为：

```python
def _test() -> int:
    """跑 tests/ 单测（testmon 增量 + 默认排除 slow/experiment）。

    tests/ 是 pytest 风格（模块级 test_* 函数 + tmp_path/monkeypatch fixtures）。
    `unittest discover` 只收 TestCase 类会静默跳过模块级函数。
    Windows 下 pytest 尾部 PermissionError: pytest-current 是 tmp_path teardown 噪音，
    结果以汇总行 "N passed" 判定，不以 exit code 判定。

    2026-10-08 测试分层：
      - --testmon：只跑受本次 diff 影响的测试（首次建库后秒级）。
      - -m "not slow and not experiment"：gate 不跑重 ML / 实验 probe 测试。
      - 失败 test ID 落到 .dsh/pytest-failing-last.txt，供 state_manager.run_gate()
        直接读取做基线对比，不再第二遍冷跑 pytest（修复双跑 bug）。
    """
    import re as _re
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    basetemp = ROOT / "output" / "logs" / f".pytest-bt-{os.getpid()}"
    pytest_args = [
        sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q",
        "--testmon",
        "-m", "not slow and not experiment",
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

    # 解析 FAILED/ERROR 行 → 落盘失败 test ID，供 gate 基线对比
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

- [ ] **Step 2: 验证 fastcheck 能跑通**

Run: `uv run python scripts/fastcheck.py --quick`
Expected: 秒级通过（--quick 不跑 pytest，只验证编译/lint/typecheck）。

- [ ] **Step 3: Commit**

```powershell
git add scripts/fastcheck.py
git commit -m "perf(gate): fastcheck._test() 落盘失败 ID + gate 默认排除 slow/experiment"
```

---

## Task 3: state_manager.run_gate() 读文件而非重跑 pytest

**Files:**
- Modify: `src/amta/common/state_manager.py:587-606` (`run_gate()` 函数)
- Modify: `src/amta/common/state_manager.py:492-520` (`_pytest_failing_tests()` 函数——保留给 baseline 用)

- [ ] **Step 1: 加一个读文件的辅助函数**

在 `_pytest_failing_tests()` 函数后面（约 520 行后）加：

```python
def _read_last_failing() -> list[str]:
    """读 fastcheck._test() 落盘的失败 test ID 列表。

    gate 路径不再第二遍冷跑 pytest——fastcheck 那遍已经用 testmon 跑过了，
    失败 ID 就在 .dsh/pytest-failing-last.txt。
    文件不存在（比如直接跑 pytest 没经过 fastcheck）时返回空列表。
    """
    path = _BASELINE_RED_FILE.parent / "pytest-failing-last.txt"
    if not path.exists():
        return []
    return [
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
```

- [ ] **Step 2: 改 `run_gate()`**

把现有 `run_gate()`（587–606 行）整段替换为：

```python
def run_gate(*, capture_pytest: bool = True) -> GateReport:
    """跑质检门（fastcheck 全量），并对比基线红名单。**不碰 git**。

    2026-10-08 测试分层：
      fastcheck._test() 已经用 testmon 跑了增量 pytest，并把失败 ID 落到
      .dsh/pytest-failing-last.txt。这里**直接读文件**，不再第二遍冷跑 pytest。
      （修复：原来 gate 跑两遍 pytest——fastcheck 一遍 testmon + 又一遍无 testmon 全量。）
    """
    rc = _run_quality_gate()
    if not capture_pytest:
        return GateReport(fastcheck_returncode=rc, pytest_failing=[], baseline=load_baseline())
    failing = _read_last_failing()
    return GateReport(
        fastcheck_returncode=rc,
        pytest_failing=failing,
        baseline=load_baseline(),
    )
```

- [ ] **Step 3: 验证 state.py --help 还能跑**

Run: `uv run python scripts/state.py --help`
Expected: 正常打印子命令，无 import 错误。

- [ ] **Step 4: Commit**

```powershell
git add src/amta/common/state_manager.py
git commit -m "perf(gate): run_gate() 读落盘失败 ID，不再第二遍冷跑 pytest"
```

---

## Task 4: 给重测试打 @pytest.mark.slow

**Files:**
- Modify: `tests/test_detect_rtdetr.py`
- Modify: `tests/test_lama_ffc.py`
- Modify: `tests/test_local_lama_inpainter_manga.py`
- Modify: `tests/test_final_integration.py`
- Modify: `tests/test_orchestrator_smoke.py`
- Modify: `tests/test_stage3_minimal.py`

- [ ] **Step 1: 每个文件顶部加 import 和模块级 mark**

对上述每个文件，在文件最顶部（`from __future__` 之后、第一个 import 之前）加：

```python
import pytest

pytestmark = pytest.mark.slow
```

> **说明**：`pytestmark = pytest.mark.slow` 是模块级标记，给整个文件的所有测试打标，不用逐个函数加。

具体操作（每个文件都一样）：

1. 打开文件
2. 在 `from __future__ import annotations` 这一行**后面**插入：
   ```python
   import pytest

   pytestmark = pytest.mark.slow
   ```
3. 如果文件里已经有 `import pytest`，就只加 `pytestmark = pytest.mark.slow` 那一行，别重复 import。

- [ ] **Step 2: 验证这些测试在 gate 默认下被排除**

Run: `uv run python -m pytest tests --collect-only -q -m "not slow and not experiment" 2>&1 | Select-Object -Last 3`
Expected: 收集数明显少于 724（预期 ~680 左右），且无 unknown marker 报错。

- [ ] **Step 3: 验证 slow 测试仍能单独跑**

Run: `uv run python -m pytest tests/test_detect_rtdetr.py -m slow -q --tb=short 2>&1 | Select-Object -Last 5`
Expected: 正常收集并跑（可能红，那是既有状态，不影响 mark 是否生效）。

- [ ] **Step 4: Commit**

```powershell
git add tests/test_detect_rtdetr.py tests/test_lama_ffc.py tests/test_local_lama_inpainter_manga.py tests/test_final_integration.py tests/test_orchestrator_smoke.py tests/test_stage3_minimal.py
git commit -m "test: mark 6 个重 ML/全管线测试为 slow"
```

---

## Task 5: 给实验 probe 测试打 @pytest.mark.experiment

**Files:**
- Modify: `tests/test_paratext_experiment.py`
- Modify: `tests/test_probe_hardcoded_terms.py`

- [ ] **Step 1: 同 Task 4 的模式，加模块级 mark**

每个文件顶部加：
```python
import pytest

pytestmark = pytest.mark.experiment
```

- [ ] **Step 2: 验证排除生效**

Run: `uv run python -m pytest tests --collect-only -q -m "not slow and not experiment" 2>&1 | Select-Object -Last 3`
Expected: 收集数进一步减少。

- [ ] **Step 3: Commit**

```powershell
git add tests/test_paratext_experiment.py tests/test_probe_hardcoded_terms.py
git commit -m "test: mark paratext/hardcoded-terms probe 实验为 experiment"
```

---

## Task 6: 清理 tests/__pycache__ 孤儿 .pyc

**Files:**
- Delete: `tests/__pycache__/` 下源码已不存在的 .pyc

- [ ] **Step 1: 先列出哪些 .pyc 是孤儿（源码 .py 已不存在）**

Run:
```powershell
Get-ChildItem tests\__pycache__\*.pyc | ForEach-Object {
    $srcName = $_.Name -replace '\.cpython-\d+-pytest-\d+\.pyc$', '.py' -replace '\.cpython-\d+\.pyc$', '.py'
    $srcPath = "tests\$($srcName -replace '\.cpython-\d+.*$', '.py')"
    if (-not (Test-Path "tests\$srcName")) { "$($_.Name)  →  孤儿（tests\$srcName 不存在）" }
}
```

Expected: 列出 ~30 个孤儿（test_apply_revisions、test_audit_*、test_client_helpers 等）。

- [ ] **Step 2: 直接清空整个 tests/__pycache__**

> 最简单：整个目录删掉，pytest 下次跑会自动重建。源码在 tests/*.py，删缓存零风险。

```powershell
Remove-Item tests\__pycache__ -Recurse -Force
```

- [ ] **Step 3: 验证收集数没变**

Run: `uv run python -m pytest tests --collect-only -q 2>&1 | Select-Object -Last 3`
Expected: 仍收集到 ~724 个（缓存删了不影响收集，源码还在）。

- [ ] **Step 4: Commit**

```powershell
git add tests/__pycache__ 2>$null; git commit -m "chore: 清理 tests/__pycache__ 孤儿 .pyc" 2>&1
```
> 如果 __pycache__ 在 .gitignore 里（很可能），git add 会报错，那就不用 commit——它本来就不入库。

---

## Task 7: 端到端验证——跑 gate 确认快

- [ ] **Step 1: 先看基线（如果还没建）**

Run: `uv run python scripts/state.py baseline`
Expected: 跑一次全量 pytest（~2 分钟），把当前红名单存到 `.dsh/baseline-red.txt`。

- [ ] **Step 2: 跑 gate，计时**

Run:
```powershell
Measure-Command { uv run python scripts/state.py gate } | Select-Object TotalSeconds
```
Expected:
  - 比之前快很多（之前要跑两遍 pytest，现在只跑一遍 testmon 增量）
  - GATE REPORT 里 `pytest: N failing` 来自读文件，不是第二遍跑
  - 如果 N=0 且 fastcheck 全绿，verdict = PASS

- [ ] **Step 3: 确认失败 ID 文件被正确读写**

Run: `Get-Content .dsh\pytest-failing-last.txt`
Expected: 存在且内容是上次 gate 跑出来的失败 test ID 列表（可能为空，如果全绿）。

- [ ] **Step 4: 最终 commit（如果有改动）**

```powershell
git add -A
git commit -m "test: 分层完成——gate 增量秒级，slow/experiment 默认排除"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ "每次只跑新增的东西" → testmon 已经做了，这次确保它不被第二遍绕开
- ✅ "快速执行" → 双跑修复 + slow/experiment 排除
- ✅ "GitHub 成熟 template 参考" → markers + --strict-markers + CI tiering 模式
- ✅ "自己执行" → Task 1-7 全是可执行步骤

**2. Placeholder scan:** 无 TBD/TODO，每步都有具体代码和命令。

**3. 关键不变量:**
- `_pytest_failing_tests()` 函数**保留**——`save_baseline()` 还在用它跑全量记录红名单。只改了 `run_gate()` 不再调它。
- baseline 仍跑全量（不带 `-m` 过滤），确保红名单完整。
- gate 跑增量（testmon + mark 过滤），快。

---

## 预期效果

| 指标 | 改之前 | 改之后 |
|---|---|---|
| gate 跑 pytest 遍数 | 2 遍（1 testmon + 1 全量冷跑） | 1 遍（testmon 增量） |
| gate 默认跑的测试数 | 724 全量冷跑 | ~680 - testmon 只跑受影响子集 |
| 重 ML 模型加载 | 每次 gate 都加载 | 默认排除，手动 `-m slow` 才跑 |
| 内存占用 | 724 测试全加载 → 卡爆 | 只加载受影响的那几个模块 |
| gate 耗时 | 分钟级 + 内存爆炸 | 秒级~10s 级 |
