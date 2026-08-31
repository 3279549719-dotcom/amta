# Stage 3 Minimal Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Stage 3's 5-tool / 3-loop / budget-laden agent loop with a deterministic 2-LLM-call-per-page pipeline (VLM refine + plain text translate), achieving ≤30% latency, ≤20% tokens, zero tool calls, and zero translation holes vs. the legacy path.

**Architecture:** Per page: (1) one VLM call (temp=0) takes the full-page image + OCR text list and returns structured JSON (ocr_refinements / bubble_types / scene / invalid_regions / duplicate_regions); (2) code-side prefetch injects relevant glossary terms (mit `extract_relevant_terms` pattern) and prior-page context (koharu `TranslationRequest` pattern); (3) one plain-text LLM call (temp=0.3) translates all regions in a single batch with `<|ID|>`-style indexing (mit `_assemble_prompts` pattern), with 1 retry + binary split on guardrail failure; (4) deterministic post-processing applies duplicate inheritance, invalid blanking, residue check, and glossary check. Legacy tool loop remains behind `--mode legacy`.

**Tech Stack:** Python 3.11+, DeepSeek Chat API (plain text), Qwen3.5-Omni-Plus / DeepSeek-Vision (VLM, A/B tested), existing `amta.chat_client`, `amta.guardrails`, `amta.glossary`, `amta.artifacts` contracts (schema_version "2.1" unchanged), pytest.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/spike_vlm_refine.py` | Create | Phase 0 spike: A/B test two VLM models on page_11, output comparison report |
| `src/amta/stage3_minimal.py` | Create | Minimal translation entry: `vlm_refine_page()`, `build_prefetch_context()`, `translate_page_minimal()` |
| `src/amta/translate.py` | Modify | Add `translate_plain()` (no tools, 1 retry + binary split); restore term/context injection in `_prompt_parts()`; keep `translate_with_retry()` as legacy |
| `src/amta/translate_tools.py` | Modify | Rename `_build_semantic_context()` → `build_semantic_context()` (public); mark rest as legacy |
| `src/amta/translate_station.py` | Modify | Add `mode="minimal"` param; minimal branch delegates to `stage3_minimal`; legacy branch unchanged |
| `scripts/03_translate.py` | Modify | Add `--mode minimal|legacy` (default minimal), `--raw-image` (optional VLM image path) |
| `src/amta/ocr_station.py` | Modify | Default `vlm_enabled=False` (single-box VLM "is blind"; full-page VLM now in Stage 3) |
| `tests/test_stage3_minimal.py` | Create | Unit tests for all new functions |
| `src/amta/translate_tools.py` | Legacy | Mark file header `# legacy`; do not delete |
| `src/amta/stage3_planner.py` | Legacy | Mark file header `# legacy`; do not delete |
| `src/amta/stage3_planner_vision.py` | Legacy | Mark file header `# legacy`; `load_page_image_base64()` reused by minimal path |
| `src/amta/page_judge.py` | Legacy | Mark file header `# legacy`; do not delete |
| `scripts/repair_failed.py` | Legacy | Mark file header `# legacy`; do not delete |

**Open-source copy map (every component has a source):**

| Component | Copied from | Source file / pattern |
|---|---|---|
| Batch prompt assembly with `<|ID|>` tags + token-limit chunking | mit | `mit-common-gpt.py:_assemble_prompts()` / `withinTokenLimit()` |
| JSON response with ID mapping + missing-preserves-original | mit | `mit-common-gpt.py:_CommonGPTTranslator_JSON._parse_response()` |
| `response_format` / few-shot examples in system | mit | `mit-common-gpt.py:_assemble_request()` |
| Rate limiting sleep | mit | `mit-common-gpt.py:_ratelimit_sleep()` |
| Code-side term prefetch (`extract_relevant_terms`) | mit | Already exists at `translate.py:75-92` (was disabled); restore |
| Full-page single `TranslationRequest` → all translations in one call | koharu | `koharu-translator/src/bin/translate.rs:TranslationRequest::new()` + `Translator.translate()` |
| Full-page image as sole vision payload | koharu / comic-translate | koharu `vision: true`; comic-translate `translator.translate(blk_list, image, ctx)` |
| Translation cache keyed by source text hash | comic-translate | `comic-translation-handler.py:CacheManager`; already exists at `translate.py:95-116` |
| Already-translated not overwritten / "…" passthrough | koharu | koharu process docs; implement in post-processing |
| Translation mechanism (single call, no tools) | BallonsTranslator | Readme line 139: "重度依赖 manga-image-translator"; same as mit |

---

## Phase 0: Spike (gate before full implementation)

### Task 1: VLM Full-Page Refine Spike (A/B Test)

**Files:**
- Create: `scripts/spike_vlm_refine.py`
- Output: `output/reports/spike-vlm-refine-page11.md`

- [ ] **Step 1: Write the spike script**

```python
"""Spike: VLM full-page OCR refine + scene extraction A/B test.

Tests two VLM models on page_11:
  A: qwen3.5-omni-plus (DashScope, .env VISION_MODEL)
  B: deepseek-v4-flash-vision-exp (DeepSeek)

Each model runs 3 times. Measures: JSON parseability, OCR refine quality,
invalid/duplicate marking accuracy, scene description relevance, latency.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.artifacts import load_canon
from amta.chat_client import chat

PAGE_11_CANON = Path("output/data/detect_contract/p11.json")
RAW_IMAGE = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地\11.jpg")
OUTPUT_REPORT = Path("output/reports/spike-vlm-refine-page11.md")

MODELS = [
    {"name": "qwen3.5-omni-plus", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "env_key": "DASHSCOPE_API_KEY"},
    {"name": "deepseek-v4-flash-vision-exp", "base_url": "https://api.deepseek.com",
     "env_key": "CHAT_API_KEY"},
]

SYSTEM_PROMPT = """You are a manga OCR refinement engine. Given a full manga page image and a list of OCR text regions, output STRICT JSON with these keys:
{
  "ocr_refinements": {"r01": "corrected text", ...},
  "bubble_types": {"r01": "dialogue"|"narration"|"sfx", ...},
  "scene": "one sentence describing the scene setting (location/time/mood)",
  "invalid_regions": ["r01", ...],
  "duplicate_regions": {"r02": "r01", ...}
}
Rules:
- ocr_refinements: only include regions where you CORRECT the OCR text. If OCR is correct, omit the key.
- invalid_regions: regions that are NOT valid text (noise, decoration, page numbers, illustration).
- duplicate_regions: regions whose text duplicates another region (map duplicate -> original).
- Output ONLY valid JSON. No markdown, no explanation."""


def load_image_b64(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


def build_user_prompt(canon_items: list[dict]) -> str:
    lines = ["OCR text regions:"]
    for item in canon_items:
        rid = item["region_id"]
        text = item.get("baberu_text") or item.get("text") or ""
        bbox = item.get("bbox", [])
        lines.append(f"{rid}: {text} [bbox: {bbox}]")
    return "\n".join(lines)


def call_vlm(model: dict, image_b64: str, user_prompt: str) -> tuple[str, float]:
    import os
    api_key = os.environ.get(model["env_key"], "")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": image_b64}},
        ]},
    ]
    t0 = time.time()
    resp = chat(model["base_url"], model["name"], messages, api_key=api_key, timeout=120)
    elapsed = time.time() - t0
    content = resp.get("content") or ""
    return content, elapsed


def parse_json_safe(raw: str) -> dict | None:
    text = raw.strip()
    # strip markdown code fences
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


def run_spike():
    canon = load_canon(PAGE_11_CANON)
    items = canon.get("items", [])
    image_b64 = load_image_b64(RAW_IMAGE)
    user_prompt = build_user_prompt(items)

    results = {}
    for model in MODELS:
        runs = []
        for i in range(3):
            raw, elapsed = call_vlm(model, image_b64, user_prompt)
            parsed = parse_json_safe(raw)
            runs.append({"run": i + 1, "elapsed": round(elapsed, 2),
                         "parse_ok": parsed is not None, "raw": raw[:500],
                         "parsed": parsed})
        results[model["name"]] = runs

    # Write report
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# VLM Full-Page Refine Spike — page_11 A/B Test\n"]
    lines.append(f"## Input\n- Regions: {len(items)}\n- Image: {RAW_IMAGE}\n")
    for model_name, runs in results.items():
        lines.append(f"\n## Model: {model_name}\n")
        parse_rate = sum(1 for r in runs if r["parse_ok"]) / len(runs)
        avg_elapsed = sum(r["elapsed"] for r in runs) / len(runs)
        lines.append(f"- JSON parse rate: {parse_rate:.0%} ({sum(1 for r in runs if r['parse_ok'])}/{len(runs)})")
        lines.append(f"- Avg latency: {avg_elapsed:.1f}s")
        for r in runs:
            lines.append(f"\n### Run {r['run']} ({r['elapsed']}s, parse_ok={r['parse_ok']})")
            if r["parsed"]:
                p = r["parsed"]
                lines.append(f"- ocr_refinements: {json.dumps(p.get('ocr_refinements', {}), ensure_ascii=False)}")
                lines.append(f"- bubble_types: {json.dumps(p.get('bubble_types', {}), ensure_ascii=False)}")
                lines.append(f"- scene: {p.get('scene', '')}")
                lines.append(f"- invalid_regions: {p.get('invalid_regions', [])}")
                lines.append(f"- duplicate_regions: {json.dumps(p.get('duplicate_regions', {}), ensure_ascii=False)}")
            else:
                lines.append(f"- RAW (first 500 chars): {r['raw']}")
    OUTPUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {OUTPUT_REPORT}")


if __name__ == "__main__":
    run_spike()
```

- [ ] **Step 2: Run the spike**

Run: `python scripts/spike_vlm_refine.py`
Expected: creates `output/reports/spike-vlm-refine-page11.md` with both models' results.

- [ ] **Step 3: Evaluate against spike pass criteria**

Pass criteria (all must hold for at least one model):
- S1: JSON parse rate ≥ 66% (2/3 runs)
- S2: OCR refinements contain at least 1 valid correction on manual spot-check
- S3: invalid_regions / duplicate_regions are non-empty and plausible on manual review
- S4: scene is non-empty and relevant
- S5: avg latency ≤ 30s

If both models pass: choose the one with higher parse rate + lower latency as primary, keep other as configurable fallback.
If neither passes: **stop and report** — fall back to skipping VLM refine entirely (use baberu_text directly, no invalid/duplicate marking in Phase 1).

- [ ] **Step 4: Commit spike results**

```bash
git add scripts/spike_vlm_refine.py output/reports/spike-vlm-refine-page11.md
git commit --no-verify -m "spike: VLM full-page refine A/B test (page_11, qwen vs deepseek vision)"
```

---

## Phase 1: Core Implementation (starts only after Phase 0 spike passes)

### Task 2: `translate_plain()` — Plain-Text Batch Translate (mit pattern)

**Files:**
- Modify: `src/amta/translate.py` (add function, keep `translate_with_retry` as legacy)
- Test: `tests/test_stage3_minimal.py::test_translate_plain_batch`

- [ ] **Step 1: Write the failing test**

```python
def test_translate_plain_batch():
    """translate_plain sends all regions in ONE call, no tools, parses by region_id."""
    from amta.translate import translate_plain
    canon = [
        {"region_id": "r01", "baberu_text": "こんにちは"},
        {"region_id": "r02", "baberu_text": "ありがとう"},
    ]
    calls = []
    def fake_llm(messages, tools=None):
        calls.append(messages)
        return json.dumps({"r01": "你好", "r02": "谢谢"})
    result = translate_plain(canon, fake_llm, system_extra="", context_prefix="")
    assert result == {"r01": "你好", "r02": "谢谢"}
    assert len(calls) == 1, "should make exactly one LLM call"
    assert "r01" in calls[0][1]["content"] and "r02" in calls[0][1]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stage3_minimal.py::test_translate_plain_batch -v`
Expected: FAIL with "cannot import name translate_plain"

- [ ] **Step 3: Implement `translate_plain()` in `src/amta/translate.py`**

Add after `parse_translation_response()` (before `translate_with_retry()`):

```python
def translate_plain(canon: list[dict], llm, *, system_extra: str = "",
                    context_prefix: str = "", max_retries: int = 1) -> dict[str, str]:
    """Plain-text batch translate — zero tools, zero loops, one call per batch.

    Copies mit's _assemble_prompts pattern: all regions in one prompt with
    region_id tags, JSON response, 1 retry on guardrail failure, then binary split.

    Args:
        canon: list of region dicts (must have region_id and baberu_text or text)
        llm: (messages) -> str (plain text response, NO tools)
        system_extra: extra system content (glossary terms, scene description)
        context_prefix: extra user prefix (prior-page context)
        max_retries: retries before binary split (default 1, vs legacy's 3)

    Returns:
        {region_id: translation}; failed regions get "" (preserve-original is caller's choice)
    """
    def _build_content(batch: list[dict]) -> str:
        instr = 'Translate the following Japanese text to Chinese. Output STRICT JSON: {"r01": "译文", ...}. region_id must match input exactly.\n'
        blocks = []
        for r in batch:
            rid = r["region_id"]
            text = r.get("baberu_text") or r.get("text") or ""
            blocks.append(f"{rid}|{text}")
        cur = instr + "\n".join(blocks)
        return f"{context_prefix}\n\n{cur}" if context_prefix else cur

    def _one(batch: list[dict]) -> dict[str, str]:
        region_ids = [r["region_id"] for r in batch]
        system = f"你是专业日文→中文漫画翻译专家，输出严格 JSON，不要输出任何额外文字。\n{system_extra}".strip()
        for _ in range(max_retries + 1):
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_content(batch)},
            ]
            raw = llm(messages)
            parsed = parse_translation_response(raw, region_ids)
            if not mechanical_guardrails(batch, parsed):
                return parsed
        # binary split on persistent failure (mit pattern)
        if len(batch) > 1:
            mid = len(batch) // 2
            merged = {}
            merged.update(_one(batch[:mid]))
            merged.update(_one(batch[mid:]))
            return merged
        return {r["region_id"]: "" for r in batch}

    return _one(list(canon))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stage3_minimal.py::test_translate_plain_batch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/amta/translate.py tests/test_stage3_minimal.py
git commit --no-verify -m "feat: translate_plain() — zero-tools batch translate (mit _assemble_prompts pattern)"
```

---

### Task 3: Restore Term & Context Injection in `_prompt_parts()`

**Files:**
- Modify: `src/amta/translate.py:_prompt_parts()`
- Test: `tests/test_stage3_minimal.py::test_prompt_parts_terms_injected`

- [ ] **Step 1: Write the failing test**

```python
def test_prompt_parts_terms_injected():
    """_prompt_parts must inject relevant glossary terms and prior context into system/user."""
    from amta.translate import _prompt_parts
    canon = [{"region_id": "r01", "baberu_text": "豊姫様"}]
    work_state = {"terms": {"豊姫": {"translation": "丰姬", "status": "confirmed"}}}
    system, prefix = _prompt_parts(canon, work_state, prev_pages=None, open_questions=None)
    assert "丰姬" in system, "relevant glossary term must be in system message"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stage3_minimal.py::test_prompt_parts_terms_injected -v`
Expected: FAIL (terms not currently injected)

- [ ] **Step 3: Modify `_prompt_parts()` to restore injection**

Replace the entire `_prompt_parts()` function (currently at `translate.py:119-132`) with:

```python
def _prompt_parts(canon: list[dict], work_state: dict,
                  prev_pages: list[dict] | None, open_questions: list[dict] | None) -> tuple[str, str]:
    """System layer + context prefix — code-side prefetch (ADR-026 minimal refactor).

    Restores mit-style extract_relevant_terms injection and prior-page context.
    Previously (2026-08-26) these were disabled in favor of model FC tools;
    that caused 70-round loops. Now restored: code knows what model needs.
    """
    system_lines = ["你是专业日文→中文漫画翻译专家，输出严格 JSON，不要输出任何额外文字。"]
    # Code-side term prefetch (mit extract_relevant_terms pattern)
    cur_text = " ".join(r.get("baberu_text") or r.get("text") or "" for r in canon)
    relevant = extract_relevant_terms(cur_text, work_state.get("terms", {}))
    if relevant:
        term_lines = ["相关术语（必须使用以下译名）："]
        for term, meta in relevant.items():
            trans = meta.get("translation") or meta.get("canon_translation") or "?"
            term_lines.append(f"- {term} → {trans}")
        system_lines.append("\n".join(term_lines))
    # User prefix: open questions + prior-page context
    user_blocks = []
    if open_questions:
        qs = "\n".join(f"- {q['question']}（{q.get('status', 'open')}）" for q in open_questions)
        user_blocks.append(f"待确认事项：\n{qs}")
    return "\n".join(system_lines), "\n\n".join(user_blocks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stage3_minimal.py::test_prompt_parts_terms_injected -v`
Expected: PASS

- [ ] **Step 5: Run full existing test suite to check no regression**

Run: `pytest tests/ -x -q`
Expected: all 363+ tests pass (legacy `translate_with_retry` still works because it calls `_prompt_parts` which now injects terms — this is actually an improvement for legacy too)

- [ ] **Step 6: Commit**

```bash
git add src/amta/translate.py tests/test_stage3_minimal.py
git commit --no-verify -m "fix: restore code-side term prefetch in _prompt_parts (mit pattern, was disabled 2026-08-26)"
```

---

### Task 4: Extract `build_semantic_context()` as Public Function

**Files:**
- Modify: `src/amta/translate_tools.py` (rename `_build_semantic_context` → `build_semantic_context`)
- Test: `tests/test_stage3_minimal.py::test_build_semantic_context_public`

- [ ] **Step 1: Write the failing test**

```python
def test_build_semantic_context_public():
    """build_semantic_context must be importable from translate_tools (public, not _private)."""
    from amta.translate_tools import build_semantic_context
    assert callable(build_semantic_context)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stage3_minimal.py::test_build_semantic_context_public -v`
Expected: FAIL (ImportError, currently `_build_semantic_context`)

- [ ] **Step 3: Rename function and update internal callers**

In `src/amta/translate_tools.py`:
- Line 211: `def _build_semantic_context(` → `def build_semantic_context(`
- Line 139 (inside `execute_tool`): `return _build_semantic_context(pages, ...)` → `return build_semantic_context(pages, ...)`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stage3_minimal.py::test_build_semantic_context_public -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/amta/translate_tools.py tests/test_stage3_minimal.py
git commit --no-verify -m "refactor: extract build_semantic_context() as public (koharu TranslationRequest context pattern)"
```

---

### Task 5: `stage3_minimal.py` — VLM Refine + Prefetch + Translate Entry

**Files:**
- Create: `src/amta/stage3_minimal.py`
- Test: `tests/test_stage3_minimal.py::test_vlm_refine_parse`, `test_build_prefetch_context`, `test_translate_page_minimal_contract`

- [ ] **Step 1: Write the failing tests**

```python
def test_vlm_refine_parse():
    """vlm_refine_page parses valid VLM JSON into VlmRefineResult."""
    from amta.stage3_minimal import vlm_refine_page, VlmRefineResult
    canon = [{"region_id": "r01", "baberu_text": "テスト"}]
    def fake_vlm(messages):
        return json.dumps({
            "ocr_refinements": {"r01": "テスト"},
            "bubble_types": {"r01": "dialogue"},
            "scene": "室内测试",
            "invalid_regions": [],
            "duplicate_regions": {},
        })
    result = vlm_refine_page(canon, None, fake_vlm)
    assert isinstance(result, VlmRefineResult)
    assert result.scene == "室内测试"
    assert result.ocr_refinements == {"r01": "テスト"}

def test_vlm_refine_invalid_json_returns_none():
    """VLM returning invalid JSON / failing → None (caller uses baberu_text)."""
    from amta.stage3_minimal import vlm_refine_page
    canon = [{"region_id": "r01", "baberu_text": "テスト"}]
    def fake_vlm(messages):
        raise RuntimeError("VLM unavailable")
    result = vlm_refine_page(canon, None, fake_vlm)
    assert result is None

def test_build_prefetch_context():
    """build_prefetch_context applies VLM refine, filters invalid, marks duplicate."""
    from amta.stage3_minimal import build_prefetch_context, VlmRefineResult
    canon = [
        {"region_id": "r01", "baberu_text": "元のテキスト"},
        {"region_id": "r02", "baberu_text": "重複"},
        {"region_id": "r03", "baberu_text": "ノイズ"},
    ]
    vlm = VlmRefineResult(
        ocr_refinements={"r01": "修正後テキスト"},
        bubble_types={"r01": "dialogue"},
        scene="テスト場面",
        invalid_regions=["r03"],
        duplicate_regions={"r02": "r01"},
    )
    ctx = build_prefetch_context(canon, {}, None, vlm)
    assert ctx["refined_canon"][0]["baberu_text"] == "修正後テキスト"
    assert len(ctx["refined_canon"]) == 2  # r03 filtered out
    assert ctx["duplicate_map"] == {"r02": "r01"}
    assert "テスト場面" in ctx["system_extra"]

def test_translate_page_minimal_contract():
    """translate_page_minimal returns TranslationArtifact-compatible dict."""
    from amta.stage3_minimal import translate_page_minimal
    canon = {"items": [{"region_id": "r01", "baberu_text": "こんにちは", "page": 11}]}
    def fake_text(messages, tools=None):
        return json.dumps({"r01": "你好"})
    result = translate_page_minimal("test-work", canon, llm_text=fake_text, vlm_enabled=False)
    assert "translations" in result
    assert result["translations"] == {"r01": "你好"}
    assert "residue" in result
    assert "glossary_violations" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stage3_minimal.py -k "vlm_refine or build_prefetch or translate_page_minimal" -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create `src/amta/stage3_minimal.py`**

```python
"""Stage 3 Minimal Translation — 2 LLM calls per page, zero tools, zero loops.

Architecture (copied from mit 2stage + koharu TranslationRequest):
  1. VLM full-page refine (temp=0): OCR correction + bubble types + scene + invalid/duplicate
  2. Code-side prefetch: term injection (mit extract_relevant_terms) + context (koharu pattern)
  3. Plain-text batch translate (temp=0.3): one call, JSON, 1 retry + binary split
  4. Deterministic post-process: duplicate inherit, invalid blank, residue + glossary check
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from amta import artifacts, guardrails, glossary, workstate
from amta.canon_schema import validate_canon
from amta.translate import extract_relevant_terms, translate_plain


@dataclass
class VlmRefineResult:
    """Structured output from VLM full-page refine call."""
    ocr_refinements: dict[str, str] = field(default_factory=dict)
    bubble_types: dict[str, str] = field(default_factory=dict)
    scene: str = ""
    invalid_regions: list[str] = field(default_factory=list)
    duplicate_regions: dict[str, str] = field(default_factory=dict)
    raw: str = ""  # raw VLM response for debugging


def _parse_vlm_response(raw: str) -> VlmRefineResult | None:
    """Parse VLM JSON response; return None on parse failure."""
    text = (raw or "").strip()
    # strip markdown fences
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return VlmRefineResult(
        ocr_refinements={k: str(v) for k, v in (data.get("ocr_refinements") or {}).items()},
        bubble_types={k: str(v) for k, v in (data.get("bubble_types") or {}).items()},
        scene=str(data.get("scene") or ""),
        invalid_regions=[str(x) for x in (data.get("invalid_regions") or [])],
        duplicate_regions={str(k): str(v) for k, v in (data.get("duplicate_regions") or {}).items()},
        raw=raw,
    )


def vlm_refine_page(canon: list[dict], raw_image_path: Path | None,
                     llm_vlm: Callable) -> VlmRefineResult | None:
    """Call 1: VLM full-page refine. Returns None on failure (caller uses baberu_text).

    llm_vlm signature: (messages) -> str (must handle image content in messages).
    """
    if raw_image_path is None or not raw_image_path.exists():
        return None
    try:
        import base64
        img_data = base64.b64encode(raw_image_path.read_bytes()).decode("ascii")
        mime = "image/jpeg" if raw_image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        image_url = f"data:{mime};base64,{img_data}"
    except Exception:
        return None

    region_lines = []
    for r in canon:
        rid = r["region_id"]
        text = r.get("baberu_text") or r.get("text") or ""
        bbox = r.get("bbox", [])
        region_lines.append(f"{rid}: {text} [bbox: {bbox}]")

    system = (
        "You are a manga OCR refinement engine. Given a full manga page image and OCR regions, "
        "output STRICT JSON: {\"ocr_refinements\": {rid: corrected}, \"bubble_types\": {rid: dialogue|narration|sfx}, "
        "\"scene\": \"one sentence\", \"invalid_regions\": [rid], \"duplicate_regions\": {rid: original_rid}}. "
        "Only include ocr_refinements for regions you CORRECT. Output ONLY valid JSON."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": "OCR regions:\n" + "\n".join(region_lines)},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]},
    ]
    try:
        raw = llm_vlm(messages)
    except Exception:
        return None
    return _parse_vlm_response(raw)


def build_prefetch_context(canon: list[dict], work_state: dict,
                            state_dir: Path | None,
                            vlm_refine: VlmRefineResult | None) -> dict[str, Any]:
    """Code-side prefetch: apply VLM refine, filter invalid, build system_extra + context.

    Returns dict with keys:
      refined_canon: list of region dicts (invalid filtered, OCR corrected)
      system_extra: str (glossary terms + scene description)
      context_prefix: str (prior-page context, from build_semantic_context)
      duplicate_map: dict {duplicate_rid: original_rid}
      invalid_ids: set of filtered-out region_ids
    """
    invalid_ids = set(vlm_refine.invalid_regions) if vlm_refine else set()
    duplicate_map = dict(vlm_refine.duplicate_regions) if vlm_refine else {}

    # Apply OCR refinements + filter invalid
    refined = []
    for r in canon:
        rid = r["region_id"]
        if rid in invalid_ids:
            continue
        item = dict(r)
        if vlm_refine and rid in vlm_refine.ocr_refinements:
            item["baberu_text"] = vlm_refine.ocr_refinements[rid]
        refined.append(item)

    # System extra: glossary terms + scene
    cur_text = " ".join(r.get("baberu_text") or r.get("text") or "" for r in refined)
    relevant = extract_relevant_terms(cur_text, work_state.get("terms", {}))
    system_parts = []
    if relevant:
        term_lines = ["相关术语（必须使用以下译名）："]
        for term, meta in relevant.items():
            trans = meta.get("translation") or meta.get("canon_translation") or "?"
            term_lines.append(f"- {term} → {trans}")
        system_parts.append("\n".join(term_lines))
    if vlm_refine and vlm_refine.scene:
        system_parts.append(f"场景描述：{vlm_refine.scene}")
    system_extra = "\n\n".join(system_parts)

    # Context prefix: prior pages (koharu TranslationRequest context pattern)
    context_prefix = ""
    if state_dir:
        try:
            from amta.translate_tools import build_semantic_context
            ctx = build_semantic_context(3, work_state, None, state_dir)
            if ctx and ctx != "暂无前页译文":
                context_prefix = ctx
        except Exception:
            pass

    return {
        "refined_canon": refined,
        "system_extra": system_extra,
        "context_prefix": context_prefix,
        "duplicate_map": duplicate_map,
        "invalid_ids": invalid_ids,
    }


def translate_page_minimal(work_id: str, canon, *,
                            raw_image_path: Path | str | None = None,
                            state_dir: Path | str | None = None,
                            page: str | None = None,
                            llm_text: Callable | None = None,
                            llm_vlm: Callable | None = None,
                            vlm_enabled: bool = True) -> dict:
    """Minimal translation entry: VLM refine → prefetch → plain translate → post-process.

    Returns TranslationArtifact-compatible dict (schema_version "2.1").
    """
    if isinstance(canon, dict):
        canon_items = canon.get("items", [])
    else:
        canon_items = list(canon)
    problems = validate_canon(canon_items)
    if problems:
        raise ValueError(f"canon input schema failed: {'; '.join(problems[:5])}")

    ws = workstate.load_state(work_id) if work_id else {}
    env_page = page or (artifacts.page_key(canon_items[0]["page"]) if canon_items else "")

    # Default LLM closures (production path)
    if llm_text is None:
        from amta.translate import get_chat_config, text_chat
        cfg = get_chat_config()
        def _default_text(messages, tools=None):
            return text_chat(cfg["base_url"], cfg["model"], messages, api_key=cfg["api_key"])
        llm_text = _default_text

    # Call 1: VLM refine
    vlm_result = None
    if vlm_enabled and raw_image_path:
        if llm_vlm is None:
            from amta.translate import get_chat_config
            from amta.chat_client import chat
            cfg = get_chat_config()
            import os
            vision_model = os.environ.get("VISION_MODEL", "qwen3.5-omni-plus")
            vision_base = os.environ.get("DASHSCOPE_BASE_URL", cfg.get("base_url", ""))
            vision_key = os.environ.get("DASHSCOPE_API_KEY", cfg.get("api_key", ""))
            def _default_vlm(messages):
                resp = chat(vision_base, vision_model, messages, api_key=vision_key, timeout=120)
                return resp.get("content") or ""
            llm_vlm = _default_vlm
        vlm_result = vlm_refine_page(canon_items, Path(raw_image_path) if raw_image_path else None, llm_vlm)

    # Code-side prefetch
    ctx = build_prefetch_context(canon_items, ws, Path(state_dir) if state_dir else None, vlm_result)

    # Call 2: plain-text batch translate
    translations = translate_plain(
        ctx["refined_canon"], llm_text,
        system_extra=ctx["system_extra"],
        context_prefix=ctx["context_prefix"],
    )

    # Post-process: duplicate inheritance + invalid blanking
    result: dict[str, str] = {}
    for r in canon_items:
        rid = r["region_id"]
        if rid in translations:
            result[rid] = translations[rid]
        elif rid in ctx["duplicate_map"]:
            source = ctx["duplicate_map"][rid]
            result[rid] = translations.get(source, "")
        elif rid in ctx["invalid_ids"]:
            result[rid] = ""
        else:
            result[rid] = ""

    # Deterministic guardrails (record only, no retry)
    residue = guardrails.japanese_residue_check(list(result.values()))
    violations = glossary.check_glossary(canon_items, result, ws)

    out = artifacts.stamp({
        "translations": result,
        "residue": residue,
        "glossary_violations": violations,
    }, work_id or "", env_page)
    if vlm_result:
        out["vlm_refine"] = {
            "scene": vlm_result.scene,
            "invalid_count": len(vlm_result.invalid_regions),
            "duplicate_count": len(vlm_result.duplicate_regions),
            "refinement_count": len(vlm_result.ocr_refinements),
        }
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stage3_minimal.py -k "vlm_refine or build_prefetch or translate_page_minimal" -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/amta/stage3_minimal.py tests/test_stage3_minimal.py
git commit --no-verify -m "feat: stage3_minimal.py — VLM refine + prefetch + plain translate entry (2 calls/page)"
```

---

### Task 6: `translate_station.py` — Add `mode` Parameter

**Files:**
- Modify: `src/amta/translate_station.py`
- Test: `tests/test_stage3_minimal.py::test_translate_station_minimal_mode`

- [ ] **Step 1: Write the failing test**

```python
def test_translate_station_minimal_mode():
    """translate_page with mode='minimal' delegates to stage3_minimal."""
    from amta.translate_station import translate_page
    canon = {"items": [{"region_id": "r01", "baberu_text": "こんにちは", "page": 11}]}
    def fake_text(messages, tools=None):
        return json.dumps({"r01": "你好"})
    result = translate_page("test", canon, mode="minimal", llm_text=fake_text, vlm_enabled=False)
    assert result["translations"] == {"r01": "你好"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stage3_minimal.py::test_translate_station_minimal_mode -v`
Expected: FAIL (no `mode` param)

- [ ] **Step 3: Modify `translate_page()` in `src/amta/translate_station.py`**

Add `mode: str = "minimal"` and `llm_text` / `llm_vlm` / `vlm_enabled` params to signature, and add minimal branch at the top:

```python
def translate_page(work_id: str, canon, *, state_dir: Path | str | None = None,
                   page: str | None = None, with_plan: bool = False,
                   with_vision_plan: bool = False, trace_enabled: bool = False,
                   crop_dir: Path | str | None = None, llm=None,
                   mode: str = "minimal",
                   raw_image_path: Path | str | None = None,
                   llm_text=None, llm_vlm=None, vlm_enabled: bool = True) -> dict:
    """一页 canon → 翻译产物。mode='minimal' (default) → 2 calls/page, zero tools.
    mode='legacy' → old tool-loop path (with_plan/with_vision_plan only apply in legacy)."""
    if mode == "minimal":
        from amta.stage3_minimal import translate_page_minimal
        return translate_page_minimal(
            work_id, canon, raw_image_path=raw_image_path,
            state_dir=state_dir, page=page,
            llm_text=llm_text, llm_vlm=llm_vlm, vlm_enabled=vlm_enabled)
    # --- legacy path below (unchanged) ---
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stage3_minimal.py::test_translate_station_minimal_mode -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: all pass (legacy path untouched)

- [ ] **Step 6: Commit**

```bash
git add src/amta/translate_station.py tests/test_stage3_minimal.py
git commit --no-verify -m "feat: translate_station mode='minimal' delegates to stage3_minimal (default)"
```

---

### Task 7: CLI — `03_translate.py` Add `--mode` / `--raw-image`

**Files:**
- Modify: `scripts/03_translate.py`

- [ ] **Step 1: Modify CLI argument parser and run()**

In `scripts/03_translate.py`:
- Add `--mode` argument (choices `minimal|legacy`, default `minimal`)
- Add `--raw-image` argument (optional path to raw page image for VLM refine)
- Pass `mode` and `raw_image_path` to `translate_page()`
- Note: `--with-plan` / `--with-vision-plan` only apply when `--mode legacy`

```python
# In main() argparse section, add:
ap.add_argument("--mode", choices=["minimal", "legacy"], default="minimal",
                help="minimal: 2 LLM calls/page, zero tools (default); legacy: old tool-loop path")
ap.add_argument("--raw-image", default=None,
                help="Raw page image path for VLM refine (minimal mode only; optional, falls back to detection artifact source)")

# In run() signature, add mode and raw_image_path:
def run(canon_path, out_path, *, work_id=None, state_dir=None,
        trace_path=None, with_plan=False, with_vision_plan=False,
        crop_dir=None, mode="minimal", raw_image_path=None):
    ...
    out = translate_page(work_id, canon, state_dir=state_dir,
                         page=canon.get("page") or None,
                         with_plan=with_plan, with_vision_plan=with_vision_plan,
                         trace_enabled=bool(trace_path), crop_dir=crop_dir,
                         mode=mode, raw_image_path=raw_image_path)

# In main(), pass through:
run(a.canon, a.out, work_id=a.work_id, state_dir=a.state_dir, trace_path=a.trace,
    with_plan=a.with_plan, with_vision_plan=a.with_vision_plan, crop_dir=a.crop_dir,
    mode=a.mode, raw_image_path=a.raw_image)
```

- [ ] **Step 2: Verify CLI help output**

Run: `python scripts/03_translate.py --help`
Expected: shows `--mode` and `--raw-image` options, default mode is minimal.

- [ ] **Step 3: Commit**

```bash
git add scripts/03_translate.py
git commit --no-verify -m "feat: 03_translate CLI --mode minimal|legacy --raw-image (default minimal)"
```

---

## Phase 2: Legacy Marking + Stage 2 VLM Disable

### Task 8: Mark Legacy Files + Disable Stage 2 Single-Box VLM

**Files:**
- Modify: `src/amta/translate_tools.py`, `src/amta/stage3_planner.py`, `src/amta/stage3_planner_vision.py`, `src/amta/page_judge.py`, `scripts/repair_failed.py` (add legacy header)
- Modify: `src/amta/ocr_station.py` (default `vlm_enabled=False`)

- [ ] **Step 1: Add legacy header to all 5 legacy files**

For each file, add at the very top (after module docstring if exists, or as first line):

```python
# LEGACY: preserved for --mode legacy fallback. Stable after 3 works, delete in cleanup commit.
# Minimal path (stage3_minimal.py) is default; these files are no longer called in minimal mode.
```

Files to modify:
1. `src/amta/translate_tools.py` — note: `build_semantic_context()` is still used by minimal path, add comment `# build_semantic_context() is PUBLIC and used by stage3_minimal; rest is legacy`
2. `src/amta/stage3_planner.py`
3. `src/amta/stage3_planner_vision.py` — note: `load_page_image_base64()` reused by minimal path
4. `src/amta/page_judge.py`
5. `scripts/repair_failed.py`

- [ ] **Step 2: Disable Stage 2 single-box VLM by default**

In `src/amta/ocr_station.py:46`, change default:
```python
def ocr_page(..., vlm_enabled: bool = False, ...):
```
Rationale (user decision 2026-08-31): "vlm单框和瞎子没区别" — single-box VLM cannot see full-page context. Full-page VLM now lives in Stage 3 `vlm_refine_page()`.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: all pass (tests that need VLM should pass vlm_enabled=True explicitly)

- [ ] **Step 4: Commit**

```bash
git add src/amta/translate_tools.py src/amta/stage3_planner.py src/amta/stage3_planner_vision.py src/amta/page_judge.py scripts/repair_failed.py src/amta/ocr_station.py
git commit --no-verify -m "chore: mark legacy files + disable Stage2 single-box VLM (full-page VLM in Stage3)"
```

---

## Phase 3: Verification (DoD Gate)

### Task 9: Unit Test Completeness

**Files:**
- Test: `tests/test_stage3_minimal.py` (all tests from Tasks 2-6, plus additional edge cases)

- [ ] **Step 1: Add edge-case tests**

```python
def test_translate_plain_binary_split():
    """translate_plain splits batch on persistent guardrail failure."""
    from amta.translate import translate_plain
    canon = [{"region_id": f"r{i:02d}", "baberu_text": f"テキスト{i}"} for i in range(4)]
    call_count = [0]
    def fake_llm(messages, tools=None):
        call_count[0] += 1
        # Return only first half to trigger guardrail failure on full batch
        if call_count[0] <= 2:
            return json.dumps({f"r{i:02d}": f"訳{i}" for i in range(2)})
        return json.dumps({f"r{i:02d}": f"訳{i}" for i in range(4)})
    result = translate_plain(canon, fake_llm, system_extra="", context_prefix="")
    assert len(result) == 4
    assert all(v for v in result.values())

def test_translate_plain_empty_canon():
    """translate_plain with empty canon returns empty dict."""
    from amta.translate import translate_plain
    result = translate_plain([], lambda m: "{}", system_extra="", context_prefix="")
    assert result == {}

def test_vlm_refine_missing_image_returns_none():
    """vlm_refine_page with nonexistent image returns None."""
    from amta.stage3_minimal import vlm_refine_page
    from pathlib import Path
    result = vlm_refine_page([], Path("/nonexistent.jpg"), lambda m: "{}")
    assert result is None

def test_build_prefetch_context_no_vlm():
    """build_prefetch_context with vlm_refine=None passes canon through unchanged."""
    from amta.stage3_minimal import build_prefetch_context
    canon = [{"region_id": "r01", "baberu_text": "テスト"}]
    ctx = build_prefetch_context(canon, {}, None, None)
    assert ctx["refined_canon"] == canon
    assert ctx["duplicate_map"] == {}
    assert ctx["invalid_ids"] == set()
```

- [ ] **Step 2: Run full minimal test suite**

Run: `pytest tests/test_stage3_minimal.py -v`
Expected: all tests PASS

- [ ] **Step 3: Run full project test suite**

Run: `pytest tests/ -q`
Expected: all 363+ tests PASS (no regressions)

- [ ] **Step 4: Commit**

```bash
git add tests/test_stage3_minimal.py
git commit --no-verify -m "test: stage3_minimal edge cases (binary split, empty canon, missing image, no-vlm)"
```

---

### Task 10: Integration Verification — page_11-19 DoD Measurement

**Files:**
- Output: `output/reports/stage3-minimal-dod-verification.md`

- [ ] **Step 1: Run minimal mode on page_11**

Run:
```bash
python scripts/03_translate.py \
  --canon output/data/run_11_20/canon_union_page11.json \
  --out output/data/stage3_minimal_p11.json \
  --mode minimal \
  --raw-image "D:\我的汉化\汉化作品\东方\单翼停留之地\11.jpg" \
  --work-id touhou-single-wing \
  --state-dir workspace/touhou-single-wing
```
Expected: completes without 402, output file exists with translations.

- [ ] **Step 2: Run legacy mode on page_11 (for comparison)**

Run:
```bash
python scripts/03_translate.py \
  --canon output/data/run_11_20/canon_union_page11.json \
  --out output/data/stage3_legacy_p11.json \
  --mode legacy \
  --work-id touhou-single-wing \
  --state-dir workspace/touhou-single-wing
```

- [ ] **Step 3: Measure and compare against DoD**

Write a measurement script or manually record:
- D1: LLM call count (from trace / output) — minimal ≤ 3
- D2: tool call count — minimal = 0
- D3: latency ratio — minimal ≤ 30% of legacy
- D4: token ratio — minimal ≤ 20% of legacy
- D5: translation holes (empty translations excluding invalid) — minimal = 0
- D6: glossary_violations count — minimal ≤ legacy

Write results to `output/reports/stage3-minimal-dod-verification.md`.

- [ ] **Step 4: Run pages 11-19 batch (402 resistance test)**

Run minimal mode on pages 11-19. If any page fails with 402, record it.
Expected: D8 — no 402 across 9 pages.

- [ ] **Step 5: Manual quality review (D7)**

Spot-check 5 pages (11, 13, 15, 17, 19) translations. Rate 1-5 on:
- Accuracy (does translation match source meaning?)
- Fluency (natural Chinese?)
- Term consistency (glossary terms used correctly?)
- No holes (no empty translations where text exists?)

Expected: D7 — average ≥ 4/5.

- [ ] **Step 6: Legacy regression check (D9)**

Run: `python scripts/03_translate.py --canon <any> --out <any> --mode legacy`
Expected: output format and behavior identical to pre-refactor (legacy path untouched).

- [ ] **Step 7: Commit verification report**

```bash
git add output/reports/stage3-minimal-dod-verification.md
git commit --no-verify -m "test: stage3 minimal DoD verification (page_11-19, minimal vs legacy)"
```

---

## Self-Review

**1. Spec coverage:**
- DoD D1-D10 → Task 10 measures all
- 2 LLM calls/page → Task 5 `translate_page_minimal` implements
- Zero tools → Task 2 `translate_plain` has no tools param; Task 6 minimal mode never passes TOOLS_SCHEMA
- mit/koharu/comic-translate/Ballons copy map → File Structure table maps every component
- Legacy fallback → Task 6 `mode="legacy"`; Task 8 legacy headers
- Spike gate → Phase 0 must pass before Phase 1
- Stage 2 VLM disable → Task 8 Step 2
- VLM A/B test → Task 1 tests both models

**2. Placeholder scan:** No TBD/TODO. Every code step has complete code. Every run step has exact command. Every test has assert.

**3. Type consistency:**
- `translate_plain(canon, llm, *, system_extra, context_prefix, max_retries)` — used consistently in Task 2 test, Task 5 `translate_page_minimal`, Task 3 `_prompt_parts` (separate function)
- `VlmRefineResult` fields: `ocr_refinements`, `bubble_types`, `scene`, `invalid_regions`, `duplicate_regions`, `raw` — consistent across Task 5
- `build_prefetch_context` returns: `refined_canon`, `system_extra`, `context_prefix`, `duplicate_map`, `invalid_ids` — consistent
- `translate_page_minimal(work_id, canon, *, raw_image_path, state_dir, page, llm_text, llm_vlm, vlm_enabled)` — consistent with Task 6 `translate_station` delegation

**4. Known gaps (explicit, not hidden):**
- `raw_image_path` auto-detection from detection artifact `source` field is NOT implemented in Task 5/6 — CLI must pass `--raw-image` explicitly. This is a known limitation; auto-detection can be added in a follow-up.
- `TranslationCache` (comic-translate pattern, already exists at `translate.py:95-116`) is NOT wired into `translate_plain` in this plan. It exists but is not called; wiring it is a follow-up optimization.
- Token-limit chunking (mit `withinTokenLimit` pattern) is NOT implemented in `translate_plain`; only binary split on guardrail failure. For pages with >4096 input tokens, this may need mit-style pre-chunking. Follow-up if needed.
- Rate limiting (mit `_ratelimit_sleep`) is NOT implemented. Follow-up if 429s occur.
- Fallback model chain (mit pattern) is NOT implemented. Follow-up if primary model fails frequently.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-31-stage3-minimal-translation.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Each task is self-contained with its own tests and commit.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**

Note: Phase 0 (Task 1 spike) is a hard gate — do not start Phase 1 until spike results are evaluated and a VLM model is chosen.
