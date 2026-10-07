# OCR Confidence Guard + DP Break Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two regressions found on tagatame p32-41: (1) OCR confidence filter kills real main-engine bubbles because the documented "tiled-only" guard was never implemented; (2) DP break function actively rewards putting commas at column ends, forcing the column-end mask to clean up after it.

**Architecture:**
- OCR: add the missing `source_engines` gate to `_should_filter_by_conf` so the 0.4 threshold only applies to tiled-secondary boxes, exactly as the docstring already claims. Main-engine boxes are never filtered.
- DP: remove the `cost -= 50` reward for breaking after strong punctuation entirely. The DP keeps only physical kinsoku constraints (no punctuation at line start, no open bracket at line end, no Latin token split) + packing to fill columns. The column-end comma mask stays as a render-time safety net.

**Tech Stack:** Python 3.12, pytest, Pillow. Entry point `uv run python`.

---

## Background (what's broken, one paragraph each)

### Bug 1: OCR confidence filter kills main-engine bubbles

`src/amta/stations/ocr_station.py` documents that the 0.4 first-token-confidence filter applies ONLY to boxes whose `source_engines == ["rtdetr-v2-tiled"]` (the tiled secondary detector). The docstring even gives examples of main-engine boxes that must NOT be filtered (rare kanji, digit misread). But the actual implementation at lines 62-75 never reads `source_engines` — the `b` parameter is accepted and ignored. Today tiling is off by default, so every box is `["rtdetr-v2"]`, yet the filter still fires on any box with `first_token_conf < 0.4`.

Evidence: `output/tagatame-p32-41/_dropped/p33_r01.png` (「ええ／分かってるわよ」), `p33_r02.png` (「たく／ミイラ取りが…」), `p40_r06.png` (「っはァ！！」) — three real dialogue bubbles, all killed by this filter.

### Bug 2: DP actively puts commas at column ends

`src/amta/typeset/typeset_engine.py` `break_lines()` has a cost term `if text[j-1] in strong_break: cost -= 50`. This reward tells the DP "prefer to cut right after a comma/period". That is exactly what pushes commas to column ends, which then forces `column_end_pause_mask` to hide them. The user's Bitter Lesson call: this is a hand-tuned aesthetic knob (why 50? why not 30?) that encodes a preference (commas at column end look fine) that the project has since decided is wrong. Remove the reward. The mask stays as a safety net; we do NOT delete it yet.

---

## File Structure

- Modify: `src/amta/stations/ocr_station.py` — add source_engines gate in `_should_filter_by_conf`.
- Modify: `src/amta/typeset/typeset_engine.py` — remove the `cost -= 50` strong-break reward line.
- Create: `tests/test_ocr_conf_guard.py` — regression tests for the source_engines gate.
- Modify: `tests/test_vertical_wrap_balance.py` — update `test_comma_is_strong_break_point` (it locks in the old behavior we are removing).
- Modify: `tests/test_column_end_pause.py` — re-baseline the exact-column assertions in the page4 real-fixture tests if the DP produces different columns after removing the reward.

---

## Task 1: Branch + OCR confidence gate

**Files:**
- Modify: `src/amta/stations/ocr_station.py:62-75`
- Create: `tests/test_ocr_conf_guard.py`

- [ ] **Step 1: Create the branch**

```bash
cd "E:\manga translator agent"
git checkout -b fix/ocr-conf-guard-and-dp-break-cleanup
```

- [ ] **Step 2: Write the failing regression tests**

Create `tests/test_ocr_conf_guard.py`:

```python
"""OCR confidence 过滤门回归测试：只砍瓦片副引擎纯新增框，主引擎框永不砍。

背景：_should_filter_by_conf 的 docstring 说"只对 source_engines==['rtdetr-v2-tiled']
的框过滤"，但实现一度漏掉了 source_engines 检查，导致主引擎真气泡（p33_r01/r02）
因首字 conf<0.4 被误杀。这些测试锁住"主引擎框不被砍"这一契约。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.stations.ocr_station import _should_filter_by_conf


def test_main_engine_box_with_low_conf_is_kept():
    """主引擎框（source_engines=['rtdetr-v2']）首字 conf=0.2 也不能砍。

    这是 p33_r01「ええ/分かってるわよ」的回归：当时首字 conf<0.4 被误杀。
    """
    row = {"first_token_conf": 0.2, "avg_conf": 0.5, "low_ratio": 0.3}
    box = {"source_engines": ["rtdetr-v2"]}
    should_drop, reason = _should_filter_by_conf(row, box)
    assert should_drop is False, f"主引擎框不该被砍: {reason}"


def test_main_engine_overlap_box_is_kept():
    """主副重叠框（source_engines 含 rtdetr-v2-tiled 但不止它）也不砍。"""
    row = {"first_token_conf": 0.1, "avg_conf": 0.3, "low_ratio": 0.9}
    box = {"source_engines": ["rtdetr-v2", "rtdetr-v2-tiled"]}
    should_drop, _ = _should_filter_by_conf(row, box)
    assert should_drop is False


def test_tiled_only_box_with_low_conf_is_dropped():
    """瓦片副引擎纯新增框（source_engines==['rtdetr-v2-tiled']）conf<0.4 仍然砍。"""
    row = {"first_token_conf": 0.2, "avg_conf": 0.3, "low_ratio": 0.9}
    box = {"source_engines": ["rtdetr-v2-tiled"]}
    should_drop, reason = _should_filter_by_conf(row, box)
    assert should_drop is True
    assert "0.4" in reason or "conf" in reason


def test_tiled_only_box_with_high_conf_is_kept():
    """瓦片副引擎框 conf 正常时保留。"""
    row = {"first_token_conf": 0.9, "avg_conf": 0.8, "low_ratio": 0.1}
    box = {"source_engines": ["rtdetr-v2-tiled"]}
    should_drop, _ = _should_filter_by_conf(row, box)
    assert should_drop is False


def test_no_source_engines_field_defaults_to_keep():
    """旧 box 没有 source_engines 字段时，按主引擎对待（不误砍）。"""
    row = {"first_token_conf": 0.1, "avg_conf": 0.2, "low_ratio": 0.9}
    box = {}
    should_drop, _ = _should_filter_by_conf(row, box)
    assert should_drop is False
```

- [ ] **Step 3: Run tests, verify the main-engine test fails**

```bash
uv run python -m pytest tests/test_ocr_conf_guard.py -v
```

Expected: `test_main_engine_box_with_low_conf_is_kept` FAILS (current code drops it), others may pass or fail depending.

- [ ] **Step 4: Add the source_engines gate**

In `src/amta/stations/ocr_station.py`, replace `_should_filter_by_conf` (lines 62-75) with:

```python
def _should_filter_by_conf(row: dict, b: dict) -> tuple[bool, str]:
    """Q3 OCR confidence 过滤判断。只对瓦片副引擎纯新增框做过滤。

    背景：3个已知假框全是副引擎新增框（瓦片化捡杂质），主引擎框假阳性率极低。
    只对副引擎纯新增框（source_engines == ["rtdetr-v2-tiled"]）做 first_token_conf
    < 0.4 过滤，避免误伤主引擎框中首字识别错误的真实文字（如生僻汉字"嫦"、
    数字"八"被误读）。

    2026-10-07 修复：此前实现漏了 source_engines 判断，b 参数被接收但未使用，
    导致瓦片副引擎关闭后主引擎真气泡（tagatame p33_r01/r02）被误杀。现在补上。

    Returns:
        (是否过滤, 过滤原因)
    """
    # 第一道门：只有瓦片副引擎纯新增框才谈得上过滤
    source_engines = b.get("source_engines") or []
    if source_engines != ["rtdetr-v2-tiled"]:
        return False, ""
    # 第二道门：瓦片副引擎纯新增框首字 conf 低 → 过滤
    first_conf = row.get("first_token_conf", 1.0)
    if first_conf < OCR_CONF_THRESHOLD:
        return True, f"first_conf={first_conf:.4f}<{OCR_CONF_THRESHOLD}"
    return False, ""
```

- [ ] **Step 5: Run tests, verify all pass**

```bash
uv run python -m pytest tests/test_ocr_conf_guard.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Run existing OCR station tests to confirm no regression**

```bash
uv run python -m pytest tests/test_ocr_station.py tests/test_quality_audit.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/amta/stations/ocr_station.py tests/test_ocr_conf_guard.py
git commit -m "fix(ocr): scope 0.4 conf filter to tiled-secondary boxes only (tagatame p33 regression)"
```

---

## Task 2: Remove DP strong-break reward

**Files:**
- Modify: `src/amta/typeset/typeset_engine.py:159-161`
- Modify: `tests/test_vertical_wrap_balance.py:55-59`
- Modify: `tests/test_column_end_pause.py:100-140` (re-baseline if DP output changes)

- [ ] **Step 1: Run the existing break-line tests to see current baseline**

```bash
uv run python -m pytest tests/test_break_lines.py tests/test_vertical_wrap_balance.py tests/test_column_end_pause.py tests/test_column_end_pause_edge_cases.py tests/test_column_end_pause_render.py -v
```

Expected: all PASS. Note the exact columns produced by `test_real_page4_r03` and `test_real_page4_r01` — we will compare after the change.

- [ ] **Step 2: Remove the strong-break reward**

In `src/amta/typeset/typeset_engine.py`, find lines 159-161:

```python
            # 强断点奖励：标点后断行
            if j > 0 and text[j - 1] in strong_break:
                cost -= 50
```

Delete these three lines entirely. Also remove the now-unused `strong_break = set("，。！？、；：")` on line 113.

After deletion, the cost block (around lines 152-158) reads:

```python
            prev_cost, _ = dp[j]
            if prev_cost == INF:
                continue
            # 成本：行数最少（主目标）→ 行长均衡（次目标）
            cost = prev_cost + 10000  # 每多一行 +10000（主目标）
            # 行长均衡：当前行越接近 max_chars 越好
            cost += abs(col_len - max_chars) * 10
            # 短行惩罚：任何行太短都罚（不只最后一行），末行罚更重。
            if col_len < max_chars // 2:
                cost += 500 if i == n else 200
```

Also update the docstring of `break_lines` (line 101) which currently says:

```
成本函数：列数最少 → 列长均衡 → 避免短尾 → 标点后断列有奖励。
```

Change it to:

```
成本函数：列数最少 → 列长均衡 → 避免短尾。
（2026-10-07 移除"标点后断列有奖励"：这是 hand-tuned 审美 knob，会主动把
逗号顶到列尾再让 mask 擦屁股。硬禁则已保证标点不顶列头，断点让算法自己找。）
```

- [ ] **Step 3: Run tests and see what breaks**

```bash
uv run python -m pytest tests/test_break_lines.py tests/test_vertical_wrap_balance.py tests/test_column_end_pause.py tests/test_column_end_pause_edge_cases.py tests/test_column_end_pause_render.py -v
```

Expected: some tests FAIL — specifically:
- `test_vertical_wrap_balance.py::test_comma_is_strong_break_point` (it asserts `cols[0].endswith("，")`, which is the behavior we are removing).
- Possibly `test_column_end_pause.py::test_real_page4_r03_column_end_comma_is_masked` and `test_real_page4_r01_column_end_comma_is_masked` if the DP now chooses different break points.

- [ ] **Step 4: Update `test_comma_is_strong_break_point` to assert the new behavior**

In `tests/test_vertical_wrap_balance.py`, replace the test (lines 55-59):

```python
    def test_comma_is_strong_break_point(self):
        """有逗号时优先在逗号后断。"""
        cols = wrap_vertical("那么，丰酱，去把羽毛给辉夜大人看看", 7)
        # 第一列应该在第一个逗号后结束
        assert cols[0].endswith("，"), f"第一列应在逗号后断: {cols}"
```

With:

```python
    def test_comma_not_forced_to_column_end(self):
        """2026-10-07：移除"标点后断列有奖励"后，DP 不再主动把逗号顶到列尾。

        逗号可以落在列中（后面跟字），由 column_end_pause_mask 兜底处理
        极少数仍落到列尾的情况。
        """
        cols = wrap_vertical("那么，丰酱，去把羽毛给辉夜大人看看", 7)
        joined = "".join(cols)
        assert joined == "那么，丰酱，去把羽毛给辉夜大人看看"
        # 不强制要求 cols[0].endswith("，")——这正是被移除的旧行为。
```

- [ ] **Step 5: Re-baseline the real-page4 fixture tests if needed**

Run:

```bash
uv run python -m pytest tests/test_column_end_pause.py::test_real_page4_r03_column_end_comma_is_masked tests/test_column_end_pause.py::test_real_page4_r01_column_end_comma_is_masked -v
```

If they FAIL, the error message will show the actual columns the DP now produces. Update the expected lists in those two tests (and in `test_mask_is_render_only_break_lines_output_untouched`) to match the new output. Keep the mask assertion (`_masked(columns)`) — the mask itself is unchanged and must still produce clean display columns.

If they PASS, do not touch them — that means removing the reward did not change these particular fixtures (the balance term alone already produced the same columns).

- [ ] **Step 6: Run the full typeset test suite**

```bash
uv run python -m pytest tests/test_break_lines.py tests/test_vertical_wrap_balance.py tests/test_column_end_pause.py tests/test_column_end_pause_edge_cases.py tests/test_column_end_pause_render.py tests/test_typeset_engine.py tests/typeset/ -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/amta/typeset/typeset_engine.py tests/test_vertical_wrap_balance.py tests/test_column_end_pause.py
git commit -m "refactor(typeset): drop strong-break reward from break_lines DP (Bitter Lesson cleanup)"
```

---

## Task 3: Rerun tagatame pages 33 and 38 from OCR onward

**Files:** none (runtime rerun).

- [ ] **Step 1: Identify the work-id for the tagatame-p32-41 run**

The workspace directory for this run is not under an obvious name. Before running, confirm the work-id with the user or locate it:

```powershell
# Look for the workspace whose detection/artifacts match pages 32-41
Get-ChildItem "E:\manga translator agent\workspace" -Directory | ForEach-Object {
  $det = Join-Path $_.FullName "artifacts\detection"
  if (Test-Path $det) {
    $n = (Get-ChildItem $det -Filter "*.json").Count
    if ($n -ge 9 -and $n -le 11) { "$($_.Name)  det=$n" }
  }
}
```

If no workspace is found (it was cleaned), ask the user for the `--work-id` and `--src-dir` used for the tagatame-p32-41 run.

- [ ] **Step 2: Rerun pages 33 and 38, stages ocr→translate→inpaint→typeset, force OCR**

Once work-id and src-dir are known:

```bash
cd "E:\manga translator agent"
uv run python scripts/run_pipeline.py --work-id <WORK_ID> --src-dir "<SRC_DIR>" \
    --pages 33,38 --stages ocr,translate,inpaint,typeset --force-rerun
```

`--pages 33,38` reruns only those two pages. `--force-rerun` forces OCR to re-run with the new filter gate (otherwise the old canon JSON would be reused).

Expected:
- OCR trace shows `n_blocks_conf_removed` = 0 or near 0 for main-engine boxes (the p33_r01/r02 bubbles are now kept).
- No "no valid bbox" errors.
- Translation, inpaint, typeset complete.

- [ ] **Step 3: Visual check the rendered pages**

Open the two output PNGs:

```powershell
explorer "E:\manga translator agent\output\tagatame-p32-41\0033.png"
explorer "E:\manga translator agent\output\tagatame-p32-41\0038.png"
```

Verify:
- The two previously-dropped bubbles (「ええ／分かってるわよ」 and 「たく／ミイラ取りが…」) now have Chinese translation rendered, no residual Japanese.
- Column breaks look natural; no comma floating alone at a column bottom that looks worse than before (the mask should catch any that slip through).

- [ ] **Step 4: If the visual is good, commit any regenerated artifacts note (docs only)**

```bash
git add docs/
git commit -m "docs: record tagatame p33/p38 post-fix verification"
```

(No artifacts are committed — they are gitignored.)

---

## Self-Review

**1. Spec coverage:**
- OCR source_engines gate → Task 1.
- Regression test for main-engine low-conf box kept → Task 1 Step 2.
- DP strong-break reward removed → Task 2 Step 2.
- Tests locking in old behavior updated → Task 2 Steps 4-5.
- Rerun p33/p38 → Task 3.
- Mask left in place as safety net (not deleted) → confirmed: Task 2 only touches break_lines, vertical_punct.py is untouched.

**2. Placeholder scan:** No TBDs. The work-id lookup in Task 3 Step 1 is a real operational step (the workspace was not pre-identified), with a concrete fallback (ask user).

**3. Type consistency:** `_should_filter_by_conf(row, b)` signature unchanged. `break_lines` signature unchanged. `strong_break` local variable removed; no other code references it (grep confirmed).
