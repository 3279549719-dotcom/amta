# Short Vocalization Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate recognizable, narratively meaningful short vocalizations while preserving empty translations for pure punctuation and genuinely unreadable OCR.

**Architecture:** Narrow the existing translation system prompt without changing the one-call array contract, artifact schema, retry policy, or downstream filtering. Prove the policy with mock-LLM contract tests, then use p64 as the sole live development page before unlocking p52 and p43 as hidden validation pages.

**Tech Stack:** Python 3.12, pytest, existing AMTA pipeline/artifact/report CLIs, DeepSeek-compatible chat API.

---

### Task 1: Lock the prompt boundary with failing tests

**Files:**
- Modify: `tests/test_stage3_minimal.py`
- Modify: `tests/test_inpaint_station.py`

- [ ] **Step 1: Add a prompt-policy regression test**

Add this test to `tests/test_stage3_minimal.py`:

```python
def test_prompt_translates_narrative_vocalizations_but_allows_noise_to_stay_empty():
    from amta.translation.translate import translate_plain

    captured = {}
    canon = [
        {"region_id": "voice", "baberu_text": "短促な声"},
        {"region_id": "punct", "baberu_text": "……"},
        {"region_id": "noise", "baberu_text": "�※�"},
    ]

    def fake_llm(messages, tools=None):
        captured["system"] = messages[0]["content"]
        return json.dumps({"translations": ["短促发声", "", ""]})

    result = translate_plain(canon, fake_llm, context_enabled=False)

    assert result == {"voice": "短促发声", "punct": "", "noise": ""}
    system = captured["system"]
    assert "呻吟、喊叫、笑声、叹息、哼声、感叹词" in system
    assert "承担人物表达或叙事作用的拟声" in system
    assert "保留人物语气、情绪和强弱" in system
    assert "拟声词、或没有实际语义" not in system
    assert "完全是标点符号" in system
    assert "乱码、无法识别的字符" in system
```

- [ ] **Step 2: Add an inpaint preservation regression test**

Add `import json` and this test to `tests/test_inpaint_station.py`:

```python
def test_empty_translation_is_not_inpainted(tmp_path):
    from amta.inpaint.inpaint_station import run

    raw_path = tmp_path / "1.jpg"
    Image.new("RGB", (32, 32), "white").save(raw_path)
    det_path = tmp_path / "page_1_detection.json"
    det_path.write_text(json.dumps({
        "page": "page_1",
        "image_meta": {"width": 32, "height": 32},
        "blocks": [{"region_id": "r00", "bbox": [2, 2, 20, 20]}],
    }), encoding="utf-8")
    trans_path = tmp_path / "page_1_translation.json"
    trans_path.write_text(json.dumps({
        "translations": {"r00": "   "},
    }), encoding="utf-8")

    doc = run(
        "test", det_path, raw_path, tmp_path / "page_1_inpaint.json",
        dry_run=True, trans_path=trans_path,
    )

    assert doc["actions"] == []
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```powershell
uv run python -m pytest tests/test_stage3_minimal.py::test_prompt_translates_narrative_vocalizations_but_allows_noise_to_stay_empty tests/test_inpaint_station.py::test_empty_translation_is_not_inpainted -q
```

Expected: the prompt-policy test fails because the current system prompt still says all onomatopoeia may be empty; the inpaint test passes if the existing safety contract is intact.

### Task 2: Make the minimal production change

**Files:**
- Modify: `src/amta/translation/translate.py:22-36`
- Test: `tests/test_stage3_minimal.py`
- Test: `tests/test_inpaint_station.py`

- [ ] **Step 1: Narrow `_SYSTEM_PROMPT`**

Replace the blanket onomatopoeia exclusion with category-level guidance equivalent to:

```python
"如果某条输入完全是标点符号（如一整串省略号、句点堆叠），"
"对应位置输出空字符串。\n"
"可识别、可发音且承担人物表达或叙事作用的内容必须翻译，"
"包括人声、呻吟、喊叫、笑声、叹息、哼声、感叹词，"
"以及承担人物表达或叙事作用的拟声；翻译时保留人物语气、情绪和强弱。"
```

Keep the existing unreadable-OCR clause unchanged. Do not add pages, region IDs, Japanese examples, dictionaries, retries, or post-processing.

- [ ] **Step 2: Run focused tests and verify GREEN**

Run:

```powershell
uv run python -m pytest tests/test_stage3_minimal.py tests/test_translate_station.py tests/test_guardrails.py tests/test_inpaint_station.py -q
```

Expected: all selected tests pass; the batch test still observes exactly one LLM call.

- [ ] **Step 3: Run the quick repository check**

Run:

```powershell
npm run check
```

Expected: compile, Ruff, Pyright, root, and environment checks pass.

### Task 3: Run the p64 development gate

**Files:**
- Runtime artifacts only: `workspace/touhou-getten-shinchi/`

- [ ] **Step 1: Confirm the registered source directory and current p64 artifacts**

The project runbook registers `D:\我的汉化\汉化作品\东方\月天新地_单页` and `64.jpg` has been confirmed present. Run `artifact.py query` for p64 before invalidation to capture the baseline artifact timestamps and paths.

- [ ] **Step 2: Invalidate only p64 and rerun the supported pipeline**

Run:

```powershell
uv run python scripts/artifact.py invalidate --work-id touhou-getten-shinchi --page 64
uv run python scripts/run_pipeline.py --work-id touhou-getten-shinchi --src-dir "D:\我的汉化\汉化作品\东方\月天新地_单页" --start-page 64 --end-page 64 --stages detect,ocr,translate,inpaint,typeset
```

Record the translate call count and stage durations from the pipeline log. Expected first candidate: one translation call for the page.

- [ ] **Step 3: Inspect p64 translation and visual output**

Use `artifact.py query` to resolve translation, clean, typeset, and final artifacts. Confirm r08 is non-empty and contextually natural, the other eight translations have not materially regressed, and the source text was replaced with readable Chinese.

- [ ] **Step 4: Generate the p64 report**

Run:

```powershell
uv run python scripts/gen_report.py --work-id touhou-getten-shinchi --src-dir "D:\我的汉化\汉化作品\东方\月天新地_单页" --pages 64-64
```

If p64 fails, state one falsifiable hypothesis and perform at most two further single-variable experiments. Do not unlock p52 or p43 before p64 passes.

### Task 4: Run hidden validation only after p64 passes

**Files:**
- Runtime artifacts only: `workspace/touhou-getten-shinchi/`

- [ ] **Step 1: Invalidate and rerun p52 and p43 for the first time**

Use the same supported `artifact.py invalidate` and full dependency-ordered `run_pipeline.py` commands for pages 52 and 43.

- [ ] **Step 2: Validate the pre-registered regions**

Confirm p52 r01 and p43 r04 are non-empty, natural Chinese vocalizations and are rendered. Do not assess or modify p43 detection, p52's unrelated layout behavior, or any p62 artifact.

- [ ] **Step 3: Reject sample-specific rescue if either hidden page fails**

If either hidden sample remains empty, mark the prompt-only candidate insufficient and return to a general semantic-rescue design. Do not add vocabulary mappings or page branches.

### Task 5: Document and close the loop

**Files:**
- Create: `docs/decisions/036-short-vocalization-translation-loop.md`
- Modify only if a genuinely reusable new lesson exists: `docs/lessons.md`

- [ ] **Step 1: Record the experiment**

Document the root cause, exact prompt policy, RED/GREEN evidence, p64 result, hidden validation result, model call count, stage durations, visual report location, and whether any experiment was rejected.

- [ ] **Step 2: Run final verification**

Run:

```powershell
uv run python -m pytest -q
```

Then run the repository finish gate. Because the shared hooksPath defect is already evidenced and explicitly out of scope, if `state.py finish` again checks the wrong worktree, preserve the full-gate output and use one documented `git commit --no-verify` rather than reopening hook work.

- [ ] **Step 3: Commit the verified implementation**

Commit message:

```text
fix(translation): preserve meaningful short vocalizations
```
