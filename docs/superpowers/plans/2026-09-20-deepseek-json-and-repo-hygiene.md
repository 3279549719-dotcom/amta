# DeepSeek JSON and Repository Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ordinary DeepSeek Flash translation non-thinking and JSON-object constrained, fix uv's cross-drive cache failure, and remove committed pytest temporary output.

**Architecture:** Keep `chat_client` as the single HTTP seam and keep DeepSeek-specific translation policy in `stage3_minimal`. Change only the translation-domain response contract from a bare array to `{"translations": [...]}`; do not add provider classes or a Responses API adapter.

**Tech Stack:** Python 3.12, requests, pytest, uv, Git.

---

### Task 1: Lock the translation response contract

**Files:**
- Modify: `tests/test_stage3_minimal.py`
- Modify: `src/amta/translation/translate.py`

- [ ] Add tests asserting that `parse_translation_array` accepts `{"translations": [...]}` and rejects a bare array, a missing key, a non-list value, and a wrong-length list.
- [ ] Run `uv run python -m pytest tests/test_stage3_minimal.py -q` and verify the new contract test fails because the implementation still accepts a bare array.
- [ ] Update `_SYSTEM_PROMPT`, the user instruction, and `parse_translation_array` to require the object contract.
- [ ] Update existing fake LLM responses in `tests/test_stage3_minimal.py` to return the object contract.
- [ ] Re-run the focused test and verify it passes.

### Task 2: Lock DeepSeek request policy

**Files:**
- Modify: `tests/test_stage3_minimal.py`
- Modify: `src/amta/translation/stage3_minimal.py`

- [ ] Add a test that invokes the default LLM path and captures the keyword arguments passed to `text_chat`.
- [ ] Assert `response_format == {"type": "json_object"}`, `thinking == {"type": "disabled"}`, and the existing temperature remains `0.3`.
- [ ] Run the focused test and verify it fails because the two DeepSeek fields are absent.
- [ ] Add only those two keyword arguments to the default `text_chat` call.
- [ ] Re-run the focused test and verify it passes.

### Task 3: Fix uv cache locality

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`

- [ ] Add `cache-dir = ".uv-cache"` to the existing `[tool.uv]` table so the configured package index remains active.
- [ ] Add `/.uv-cache/` to `.gitignore`.
- [ ] Clear any shell-level `UV_CACHE_DIR` override and run `uv run python -c "print('ok')"`.
- [ ] Verify the command prints `ok` without `--no-cache` and `.uv-cache` remains ignored.

### Task 4: Remove pytest temporary output

**Files:**
- Delete: `.pytest_tmp/**`
- Modify: `.gitignore`
- Modify: `pyproject.toml`

- [ ] Add `/.pytest_tmp/` to `.gitignore`.
- [ ] Configure pytest `addopts = "--basetemp=.pytest_tmp"` so Windows test runs do not depend on the global temporary directory.
- [ ] Remove all tracked paths under `.pytest_tmp/`.
- [ ] Verify `git ls-files '.pytest_tmp/**'` returns no paths in the resulting tree.
- [ ] Verify all 25 files introduced under `scripts/probes/` remain present.

### Task 5: Full verification and finish

**Files:**
- Verify all files changed above.

- [ ] Run focused translation tests.
- [ ] Run the complete deterministic pytest suite.
- [ ] Run Ruff and Pyright through the repository quality workflow.
- [ ] Run the full repository finish workflow and inspect its Git diff/commit result.
- [ ] Confirm no source page, workspace artifact, report, model, credential, or probe was changed.
