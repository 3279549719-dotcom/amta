# Book-Level Glossary Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move translation glossary (人名 + 术语) from per-work-id to per-book, keyed by src_dir path hash, so debugging with new work-ids never loses confirmed names again.

**Architecture:** Add a book-level store at `workspace/_books/<sha1(src_dir)>/glossary.json`. On first run of a book, run an LLM name-extraction pass over all OCR text, pop a GUI confirmation dialog, then lock the confirmed glossary as hard pre-dict replacement. On subsequent runs (any work-id), detect existing glossary and skip extraction. Katakana normalization added to `norm()` so OCR surface variants auto-hit.

**Tech Stack:** Python 3.12, existing `amta.guards.term_replace` (pre-dict), `amta.guards.pre_scan` (OCR text collection), existing FastAPI GUI.

---

## File Structure

**Create:**
- `src/amta/common/book_store.py` — book_id derivation + book-level glossary read/write
- `src/amta/guards/name_pre_scan.py` — LLM-based whole-book katakana name extraction
- `tests/test_book_store.py` — book_id derivation + glossary persistence tests
- `tests/test_name_pre_scan.py` — name extraction prompt + parsing tests

**Modify:**
- `src/amta/common/metrics.py` — add katakana→hiragana + small-kana normalization to `norm()`
- `src/amta/common/workstate.py` — `load_decisions` / `record_decisions` delegate to book_store when book_id is available
- `src/amta/translation/stage3_minimal.py` — merge book-level glossary into pre-dict locked terms
- `src/amta/gui/server.py` — add glossary GET/POST endpoints
- `src/amta/gui/static/index.html` — add glossary confirmation page
- `scripts/run_pipeline.py` — derive book_id from src_dir, detect existing glossary

---

### Task 1: Katakana normalization in `norm()`

**Files:**
- Modify: `src/amta/common/metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_metrics.py`:

```python
from amta.common.metrics import norm

def test_norm_normalizes_katakana_to_hiragana():
    assert norm("スーさん") == norm("すーさん")

def test_norm_normalizes_small_kana():
    assert norm("スーサン") == norm("スーさん")  # ン vs ん after hiragana conv
    assert norm("ット") == norm("ツト")  # small tsu → big tsu

def test_norm_still_strips_punctuation():
    assert norm("「スーさん」") == norm("スーさん")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_metrics.py -v`
Expected: FAIL — `スーさん` != `すーさん` after current norm()

- [ ] **Step 3: Implement normalization**

Modify `src/amta/common/metrics.py`, add a `_normalize_kana()` helper and call it inside `norm()`:

```python
def _normalize_kana(s: str) -> str:
    """Katakana → hiragana, small kana → big kana. So スーさん and すーさん
    and スーサン all normalize to the same string."""
    out = []
    for ch in s:
        code = ord(ch)
        # Katakana range U+30A0–U+30FF → hiragana U+3040–U+309F by subtracting 0x60
        if 0x30A1 <= code <= 0x30F6:
            ch = chr(code - 0x60)
        # Small kana → big kana (mapping table)
        small_to_big = {
            "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お",
            "っ": "つ", "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ゎ": "わ",
        }
        ch = small_to_big.get(ch, ch)
        out.append(ch)
    return "".join(out)


def norm(s: str) -> str:
    """Normalize: strip punctuation/whitespace, unify kana scripts."""
    s = _NORM_RE.sub("", s or "")
    s = _normalize_kana(s)
    return s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/amta/common/metrics.py tests/test_metrics.py
git commit -m "feat(metrics): normalize katakana→hiragana and small→big kana in norm()"
```

---

### Task 2: Book-level glossary store

**Files:**
- Create: `src/amta/common/book_store.py`
- Test: `tests/test_book_store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_book_store.py`:

```python
import json
from pathlib import Path
from amta.common.book_store import book_id_from_src_dir, load_glossary, save_glossary

def test_book_id_is_stable_for_same_path(tmp_path: Path):
    src = tmp_path / "my_book"
    src.mkdir()
    id1 = book_id_from_src_dir(str(src))
    id2 = book_id_from_src_dir(str(src))
    assert id1 == id2

def test_book_id_differs_for_different_paths(tmp_path: Path):
    a = tmp_path / "book_a"; a.mkdir()
    b = tmp_path / "book_b"; b.mkdir()
    assert book_id_from_src_dir(str(a)) != book_id_from_src_dir(str(b))

def test_save_and_load_glossary_roundtrip(tmp_path: Path, monkeypatch):
    # Redirect WORKSPACE to tmp
    import amta.common.book_store as bs
    monkeypatch.setattr(bs, "WORKSPACE_ROOT", tmp_path / "workspace")
    bid = "testbook123"
    glossary = {"スーさん": "苏桑", "風見幽香": "风见幽香"}
    save_glossary(bid, glossary)
    loaded = load_glossary(bid)
    assert loaded == glossary

def test_load_glossary_missing_returns_empty(tmp_path: Path, monkeypatch):
    import amta.common.book_store as bs
    monkeypatch.setattr(bs, "WORKSPACE_ROOT", tmp_path / "workspace")
    assert load_glossary("nonexistent") == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_book_store.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement book_store.py**

Create `src/amta/common/book_store.py`:

```python
"""Book-level glossary store: keyed by src_dir path hash, shared across all work-ids.

This is the "熟客档案" — regardless of which work-id (seat) you sit at,
the book's confirmed glossary follows the source image folder.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from amta.common.paths import ROOT

# workspace/_books/<book_id>/
WORKSPACE_ROOT = ROOT / "workspace"
BOOKS_DIR = "books"


def book_id_from_src_dir(src_dir: str | Path) -> str:
    """Derive a stable book fingerprint from the source image directory path.

    Uses realpath (resolves symlinks/..) then sha1 — so renaming the folder
    breaks the fingerprint, but normal operation (same folder, multiple work-ids)
    stays stable.
    """
    real = Path(src_dir).resolve()
    return hashlib.sha1(str(real).encode("utf-8")).hexdigest()[:16]


def _book_dir(book_id: str) -> Path:
    d = WORKSPACE_ROOT / BOOKS_DIR / book_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def glossary_path(book_id: str) -> Path:
    return _book_dir(book_id) / "glossary.json"


def meta_path(book_id: str) -> Path:
    return _book_dir(book_id) / "meta.json"


def load_glossary(book_id: str) -> dict[str, str]:
    """Load confirmed glossary {surface: translation}. Missing → empty dict."""
    p = glossary_path(book_id)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_glossary(book_id: str, glossary: dict[str, str]) -> Path:
    """Write confirmed glossary to disk."""
    p = glossary_path(book_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)
    return p


def save_meta(book_id: str, src_dir: str | Path) -> None:
    """Record source path + timestamp for traceability."""
    import datetime
    p = meta_path(book_id)
    data = {
        "src_dir": str(Path(src_dir).resolve()),
        "created_at": datetime.datetime.now().isoformat(),
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def has_glossary(book_id: str) -> bool:
    """True if a confirmed glossary already exists for this book."""
    return glossary_path(book_id).exists()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_book_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/amta/common/book_store.py tests/test_book_store.py
git commit -m "feat(book-store): add book-level glossary store keyed by src_dir hash"
```

---

### Task 3: LLM-based whole-book name pre-scan

**Files:**
- Create: `src/amta/guards/name_pre_scan.py`
- Test: `tests/test_name_pre_scan.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_name_pre_scan.py`:

```python
from amta.guards.name_pre_scan import build_extraction_prompt, parse_extraction_response

def test_prompt_asks_for_json_array():
    text = "スーさんがやってきた。風見幽香もいる。"
    prompt = build_extraction_prompt(text)
    assert "JSON" in prompt
    assert "surface" in prompt
    assert "translation" in prompt

def test_parse_extraction_response_valid():
    raw = '{"names": [{"surface": "スーさん", "translation": "苏桑"}, {"surface": "風見幽香", "translation": "风见幽香"}]}'
    result = parse_extraction_response(raw)
    assert result == {"スーさん": "苏桑", "風見幽香": "风见幽香"}

def test_parse_extraction_response_empty():
    raw = '{"names": []}'
    assert parse_extraction_response(raw) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_name_pre_scan.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement name_pre_scan.py**

Create `src/amta/guards/name_pre_scan.py`:

```python
"""Whole-book katakana name extraction via LLM (one-time pre-scan).

Runs ONCE per book (when no glossary.json exists yet). Feeds all OCR text
to the LLM and asks for a JSON array of {surface, translation} for every
katakana name / recurring honorific term. The result is then shown in the
GUI for human confirmation before being locked as hard pre-dict.

Note: currently extracts katakana names only. Ordinary vocabulary extraction
is a reserved extension point — the parse function already accepts any
{surface, translation} pair, so adding vocab later is just a prompt change.
"""
from __future__ import annotations

import json
import re


EXTRACTION_PROMPT = """以下是一本东方Project同人志的全部OCR文本。请提取其中所有片假名人名、固定称呼（包括"さん"、"ちゃん"等敬称结尾的称呼）。

要求：
1. 只提取人名和固定称呼，不要提取普通词汇、招式名、地名
2. 每个人名给出你建议的中文译名
3. 以 JSON 格式返回，不要有其他文字

返回格式：
{{"names": [{{"surface": "日文原文", "translation": "建议中文译名"}}]}}

OCR文本：
{text}
"""


def build_extraction_prompt(all_ocr_text: str) -> str:
    """Build the LLM prompt for name extraction."""
    return EXTRACTION_PROMPT.format(text=all_ocr_text)


def parse_extraction_response(raw: str) -> dict[str, str]:
    """Parse LLM JSON response into {surface: translation} dict.

    Tolerates markdown code fences. Returns empty dict on parse failure.
    """
    # Strip code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
    names = data.get("names", [])
    result = {}
    for item in names:
        surface = (item.get("surface") or "").strip()
        translation = (item.get("translation") or "").strip()
        if surface and translation:
            result[surface] = translation
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_name_pre_scan.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/amta/guards/name_pre_scan.py tests/test_name_pre_scan.py
git commit -m "feat(name-pre-scan): add LLM-based whole-book katakana name extraction"
```

---

### Task 4: Wire book-level glossary into pre-dict

**Files:**
- Modify: `src/amta/translation/stage3_minimal.py:245-257`

- [ ] **Step 1: Modify build_prefetch_context to merge book glossary**

In `src/amta/translation/stage3_minimal.py`, inside `build_prefetch_context`, before the existing `_locked` block, add:

```python
    # === Book-level glossary: merge confirmed names into locked terms ===
    from amta.common.book_store import load_glossary
    book_glossary = {}
    # TODO(book_id): book_id will be passed in once run_pipeline derives it.
    # For now, we read from a convention: work_state carries a book_id field
    # that run_pipeline sets on init.
    book_id = work_state.get("book_id")
    if book_id:
        book_glossary = load_glossary(book_id)
    # === End book-level glossary merge ===
```

Then change the `_locked` dict construction to also include book_glossary:

```python
    _locked = {}
    for _k, _v in work_state.get("terms", {}).items():
        if _v.get("status") == "confirmed" and _v.get("translation"):
            _locked[_k] = _v["translation"]
    # Book-level glossary overrides — these are human-confirmed names
    _locked.update(book_glossary)
```

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `uv run python -m pytest tests/test_stage3_minimal.py -v`
Expected: PASS (book_id missing → book_glossary empty → no behavior change)

- [ ] **Step 3: Commit**

```bash
git add src/amta/translation/stage3_minimal.py
git commit -m "feat(translate): merge book-level confirmed glossary into pre-dict locked terms"
```

---

### Task 5: run_pipeline.py — derive book_id, detect existing glossary

**Files:**
- Modify: `scripts/run_pipeline.py`

- [ ] **Step 1: Add book_id derivation at startup**

In `scripts/run_pipeline.py`, after parsing args and before running stages, add:

```python
from amta.common.book_store import book_id_from_src_dir, has_glossary, save_meta

book_id = book_id_from_src_dir(args.src_dir)
save_meta(book_id, args.src_dir)
print(f"[book] book_id={book_id} (src_dir={args.src_dir})")

if has_glossary(book_id):
    print(f"[book] existing glossary found, skipping pre-scan")
else:
    print(f"[book] no glossary yet — first run: will trigger name pre-scan")
```

Also write `book_id` into work_state so stage3_minimal can read it:

```python
from amta.common import workstate
ws = workstate.load_state(args.work_id)
ws["book_id"] = book_id
workstate.save_state(args.work_id, ws)
```

- [ ] **Step 2: Test with existing work-id**

Run: `uv run python scripts/run_pipeline.py --work-id tagatame-p33-p38-fix --src-dir D:\pages --start-page 38 --end-page 38 --stages translate`
Expected: prints `book_id=...` and `existing glossary found` (or `no glossary yet`)

- [ ] **Step 3: Commit**

```bash
git add scripts/run_pipeline.py
git commit -m "feat(pipeline): derive book_id from src_dir, detect existing glossary"
```

---

### Task 6: GUI glossary confirmation endpoints

**Files:**
- Modify: `src/amta/gui/server.py`

- [ ] **Step 1: Add GET /api/glossary and POST /api/glossary**

Add to `src/amta/gui/server.py`:

```python
from amta.common.book_store import load_glossary, save_glossary, book_id_from_src_dir
from amta.guards.name_pre_scan import build_extraction_prompt, parse_extraction_response

@app.get("/api/glossary")
def get_glossary(work_id: str):
    """Return the confirmed glossary for this work's book."""
    # Derive book_id from work_id's src_dir (stored in work_state)
    from amta.common import workstate
    ws = workstate.load_state(work_id)
    book_id = ws.get("book_id")
    if not book_id:
        return {"glossary": {}, "book_id": None}
    return {"glossary": load_glossary(book_id), "book_id": book_id}


@app.post("/api/glossary")
def save_glossary_endpoint(req: dict):
    """Save confirmed glossary (user edited in GUI)."""
    work_id = req.get("work_id", "")
    glossary = req.get("glossary", {})
    if not work_id or not isinstance(glossary, dict):
        raise HTTPException(status_code=400, detail="work_id and glossary required")
    from amta.common import workstate
    ws = workstate.load_state(work_id)
    book_id = ws.get("book_id")
    if not book_id:
        raise HTTPException(status_code=400, detail="no book_id in work_state")
    save_glossary(book_id, glossary)
    return {"ok": True, "count": len(glossary)}
```

- [ ] **Step 2: Start GUI and test endpoints**

Run: `uv run python -m amta.gui.server`
Then curl:
- `GET /api/glossary?work_id=tagatame-p33-p38-fix` → returns `{"glossary": {}, "book_id": "..."}`
- `POST /api/glossary` with body `{"work_id": "tagatame-p33-p38-fix", "glossary": {"スーさん": "苏桑"}}` → returns `{"ok": true, "count": 1}`

- [ ] **Step 3: Commit**

```bash
git add src/amta/gui/server.py
git commit -m "feat(gui): add glossary GET/POST endpoints"
```

---

### Task 7: Run name pre-scan on the tagatame book

**Files:**
- No code changes — this is the operational step.

- [ ] **Step 1: Run full OCR on tagatame pages (if not already done)**

We need all OCR text collected. Use existing pipeline to run detect+ocr on all pages:

```bash
uv run python scripts/run_pipeline.py --work-id tagatame-prescan --src-dir "D:\我的汉化\汉化作品\东方\タガタメ" --start-page 1 --end-page 64 --stages detect,ocr
```

- [ ] **Step 2: Collect all OCR text and run LLM name extraction**

Write a one-off probe script `scripts/probes/prescan_tagatame_names.py`:

```python
"""One-off: extract katakana names from all tagatame OCR text via LLM."""
import sys
from pathlib import Path

from amta.stores import artifacts
from amta.backends.chat_client import text_chat
from amta.common.chat_config import get_chat_config
from amta.guards.name_pre_scan import build_extraction_prompt, parse_extraction_response
from amta.common.book_store import book_id_from_src_dir, save_glossary, save_meta

SRC_DIR = r"D:\我的汉化\汉化作品\东方\タガタメ"
WORKSPACE = Path("workspace/tagatame-prescan")

def main():
    # Collect all OCR text
    art_dir = WORKSPACE / "artifacts"
    store = artifacts.ArtifactStore(art_dir)
    all_text = []
    for k in store.pages("canon"):
        p = store.resolve("canon", k)
        if p is None:
            continue
        doc = artifacts.load_canon(p)
        for item in doc.get("items", []):
            txt = item.get("baberu_text") or item.get("text") or ""
            if txt.strip():
                all_text.append(txt)
    combined = "\n".join(all_text)
    print(f"Collected {len(combined)} chars of OCR text")

    # LLM extraction
    cfg = get_chat_config()
    prompt = build_extraction_prompt(combined)
    resp = text_chat(cfg["base_url"], cfg["model"], [{"role": "user", "content": prompt}],
                     api_key=cfg["api_key"], temperature=0.1,
                     response_format={"type": "json_object"})
    names = parse_extraction_response(resp)
    print(f"Extracted {len(names)} names:")
    for s, t in names.items():
        print(f"  {s} → {t}")

    # Save to book-level store (as draft — user will confirm in GUI)
    bid = book_id_from_src_dir(SRC_DIR)
    save_meta(bid, SRC_DIR)
    save_glossary(bid, names)
    print(f"Saved to book_id={bid}")

if __name__ == "__main__":
    main()
```

Run it:
```bash
uv run python scripts/probes/prescan_tagatame_names.py
```

Expected: prints ~10-20 katakana names with suggested translations, saves to `workspace/_books/<book_id>/glossary.json`.

- [ ] **Step 3: Verify the extracted names look right**

Open `workspace/_books/<book_id>/glossary.json`, eyeball the list. Edit any wrong translations directly in the JSON (this is your "GUI confirmation" for now — the GUI page comes in Task 8).

- [ ] **Step 4: Re-run p38 and verify consistency**

```bash
uv run python scripts/run_pipeline.py --work-id tagatame-p38-verify --src-dir "D:\我的汉化\汉化作品\东方\タガタメ" --start-page 38 --end-page 38 --stages translate,inpaint,typeset
```

Expected: p38 now renders `スーさん` as "苏桑" (not "Suu小姐").

- [ ] **Step 5: Commit the probe script**

```bash
git add scripts/probes/prescan_tagatame_names.py
git commit -m "chore(probes): one-off tagatame name pre-scan script"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** katakana norm (Task 1), book-level store (Task 2), name pre-scan (Task 3), pre-dict integration (Task 4), pipeline wiring (Task 5), GUI endpoints (Task 6), real-world test on tagatame (Task 7).
- [x] **No placeholders:** every code step has actual code.
- [x] **Type consistency:** `book_id` is a string, `glossary` is `dict[str,str]`, function names match across tasks.
- [x] **Reserved extension point:** Task 3 extracts names only; vocabulary extraction is a prompt change later, no code change needed.
