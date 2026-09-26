# PSD Photoshop Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a Photoshop-compatible layered PSD whose full clean page and editable bubble text layers are visibly rendered by an independent PSD editor.

**Architecture:** Keep PhotoshopAPI as the writer, correct the clean image layer's center coordinates, and lock the PSD geometry with an independent `psd-tools` regression test. Verify the real artifact structurally, through an independent raster render, and by opening it in Photopea with browser automation.

**Tech Stack:** Python 3.12, PhotoshopAPI 0.9.1, psd-tools 1.19.0, Pillow, pytest, agent-browser/Photopea

---

### Task 1: Lock the full-canvas clean-layer contract

**Files:**
- Modify: `tests/test_psd_export.py`

- [ ] **Step 1: Write the failing independent-reader test**

Add this test after `test_export_page_psd_layers_visible_and_correct_order`:

```python
def test_export_page_psd_clean_layer_covers_canvas(tmp_path):
    """回归：clean 像素层必须覆盖完整画布，不能以画布原点作为中心。"""
    from psd_tools import PSDImage

    art = _make_artifacts(tmp_path)
    out = tmp_path / "page_1.psd"
    export_page_psd(art, "page_1", out)

    psd = PSDImage.open(out)
    clean_layers = [layer for layer in psd if layer.kind == "pixel" and layer.name.startswith("clean ")]
    assert len(clean_layers) == 1
    clean = clean_layers[0]
    left, top, right, bottom = clean.bbox
    assert left == 0 and top == 0
    assert right >= psd.width and bottom >= psd.height
    assert clean.visible
    assert clean.opacity == 255
    assert clean.fill_opacity == 255
    assert clean.has_pixels()
```

- [ ] **Step 2: Run the test and verify the expected red signal**

Run:

```powershell
uv run python -m pytest tests/test_psd_export.py::test_export_page_psd_clean_layer_covers_canvas -v
```

Expected: FAIL because the actual bounds are `(-100, -75, 100, 75)`, proving the test catches the reported off-canvas bug.

### Task 2: Center the clean image layer on the document canvas

**Files:**
- Modify: `src/amta/typeset/psd_export.py:257`
- Test: `tests/test_psd_export.py`

- [ ] **Step 1: Make the minimal production change**

Replace the clean-layer constructor with:

```python
bg_layer = psapi.ImageLayer_8bit(
    bg_data,
    f"clean page {page_num}",
    width=width,
    height=height,
    pos_x=width / 2,
    pos_y=height / 2,
)
```

- [ ] **Step 2: Run the focused test and verify green**

Run:

```powershell
uv run python -m pytest tests/test_psd_export.py::test_export_page_psd_clean_layer_covers_canvas -v
```

Expected: PASS with independent-reader bounds starting at `(0, 0)` and covering the entire canvas, including odd canvas sizes.

- [ ] **Step 3: Run the complete PSD test module**

Run:

```powershell
uv run python -m pytest tests/test_psd_export.py -v
```

Expected: 8 passed.

### Task 3: Regenerate and structurally inspect the real PSD

**Files:**
- Regenerate: `workspace/psd-verify/artifacts/psd/page_1.psd` (ignored runtime artifact)

- [ ] **Step 1: Regenerate the real artifact through the supported exporter**

Run:

```powershell
$env:PYTHONPATH="src"
uv run python -c "from pathlib import Path; from amta.typeset.psd_export import export_page_psd; export_page_psd(Path(r'workspace\psd-verify\artifacts'), 'page_1', Path(r'workspace\psd-verify\artifacts\psd\page_1.psd'))"
```

Expected: command exits 0 and rewrites `page_1.psd`.

- [ ] **Step 2: Verify the real document through an independent reader**

Run a `uv run python` probe that opens the PSD with `psd_tools.PSDImage` and asserts:

```python
assert psd.size == (2243, 3465)
left, top, right, bottom = clean.bbox
assert left == 0 and top == 0
assert right >= psd.width and bottom >= psd.height
assert clean.visible and clean.opacity == 255 and clean.fill_opacity == 255
assert len([layer for layer in psd if layer.kind == "type"]) == 4
```

Expected: all assertions pass and the probe prints the five layer names and bounds.

- [ ] **Step 3: Produce an independent visual rendering**

Run:

```powershell
uv run psd-tools export "workspace\psd-verify\artifacts\psd\page_1.psd" "$env:TEMP\amta-page-1-independent.png"
```

Expected: command exits 0 and creates a non-empty PNG. Open that PNG with the local visual inspection tool and confirm that the full manga page is visible.

### Task 4: Open the PSD in a real PSD editor and visually inspect it

**Files:**
- Capture: `workspace/psd-verify/artifacts/psd/page_1-photopea.png` only if the capture belongs with ignored runtime artifacts

- [ ] **Step 1: Confirm browser automation supports local file upload**

Run:

```powershell
agent-browser --help
```

Expected: the CLI exposes file upload support. If direct upload is unavailable, use Photopea's documented URL/API loading mechanism without changing the PSD.

- [ ] **Step 2: Open Photopea and load the generated PSD**

Use a headed `agent-browser` session to open `https://www.photopea.com/`, upload the absolute PSD path, and wait for parsing to finish.

Expected: Photopea shows a `2243 x 3465` document rather than an empty checkerboard. If Cloudflare blocks automated access after attempts with both a clean automation profile and the local Chrome profile, record the editor check as environment-blocked and retain the independent PSD render plus clean-layer render as the visual evidence; do not claim Photopea or Adobe verification.

- [ ] **Step 3: Inspect the canvas and layer panel**

Capture a full screenshot and verify visually:

- the clean manga page fills the canvas;
- four text layers appear separately from the clean layer;
- multiple translated texts are visible at their intended regions;
- toggling the clean layer changes the canvas background;
- toggling an individual text layer changes only that translated bubble text.

- [ ] **Step 4: Compare against the known final PNG**

Open `workspace/psd-verify/artifacts/final/page_1_final.png` with the local visual tool and compare it with the Photopea screenshot. The content must be the same page with the same four translations; small font-engine metric differences are acceptable, but missing page content, missing text, off-canvas layers, or an empty checkerboard are failures.

### Task 5: Final verification and repository handoff

**Files:**
- Verify: `src/amta/typeset/psd_export.py`
- Verify: `tests/test_psd_export.py`
- Verify: `docs/superpowers/specs/2026-09-26-psd-photoshop-visibility-design.md`
- Verify: `docs/superpowers/plans/2026-09-26-psd-photoshop-visibility.md`

- [ ] **Step 1: Run the fast repository gate**

Run:

```powershell
uv run python scripts/fastcheck.py --quick
```

Expected: exit 0.

- [ ] **Step 2: Run deterministic tests**

Run:

```powershell
uv run python -m pytest -q
```

Expected: exit 0 with no failures.

- [ ] **Step 3: Re-read the acceptance criteria**

Confirm every criterion in `docs/superpowers/specs/2026-09-26-psd-photoshop-visibility-design.md` has fresh command or screenshot evidence. Do not claim Adobe Photoshop verification because Photoshop is not installed in this environment.

- [ ] **Step 4: Finish through the repository's single supported workflow**

First inspect `git status --short`. If unrelated user-owned changes would be swept into the finish commit, do not overwrite, delete, move, or commit them; report that repository finalization is blocked while preserving the verified implementation. Otherwise run:

```powershell
npm run finish -- "fix(typeset): position PSD clean layer on canvas"
```

Expected: the full repository checks pass and the focused PSD fix is committed through the supported workflow.
