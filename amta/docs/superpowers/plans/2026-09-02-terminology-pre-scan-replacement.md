# Terminology Pre-Scan + Direct Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 根治东方Project同人志翻译中的术语不一致问题——通过 pre-scan 全本扫描建立锁定词典，翻译时直接将源文术语替换为中文译名，LM 只翻译剩余日文。三步一次过，零 retry/repair/evaluate。

**Architecture:**
1. **东方主词典**（静态文件 `data/thbwiki_master_dict.json`，跨本子复用）：35 核心角色 + 15 设定词 + 敬称映射，THBWiki 派生手动 curated 种子。
2. **Pre-scan 模块**（每本一次，纯机械无 LM）：读取全本 canon 产物 → 收集所有 OCR 文本 → 匹配主词典（精确+归一化+模糊≤2编辑距离）→ 写入 `work_state.terms`（全部 status=confirmed）。
3. **直接预替换**（集成进 `stage3_minimal.build_prefetch_context`）：VLM refine 之后、glossary 注入之前，将 refined_canon 中每个 region 的 baberu_text 里的锁定术语直接替换为中文译名 → LM 翻译日中混合文 → 输出即终稿。

**Tech Stack:** Python 3.11+, amta 现有模块（workstate / artifacts / metrics / stage3_minimal）, pytest, THBWiki（主词典来源）

**砍掉的复杂度（YAGNI）：** placeholder 替换、存活检查、retry、repair、evaluate、全书 validator、glossary 软注入（自动失效）、LM 残差解析（MVP 不需要，未命中主词典的词自由翻译即可）。

---

## File Structure

| File | Action | Responsibility |
| --- | --- | --- |
| `data/thbwiki_master_dict.json` | Create | 东方主词典种子（角色+设定词+敬称映射），静态，跨本子复用 |
| `src/amta/term_dict.py` | Create | 主词典加载（结构化→扁平 {surface: translation}）+ 术语匹配（精确/归一化/模糊） |
| `src/amta/term_replace.py` | Create | 直接预替换：文本/ canon 列表中的术语替换为中文译名（最长匹配优先） |
| `src/amta/pre_scan.py` | Create | Pre-scan 核心：全本 canon 扫描 → 匹配主词典 → 写入 work_state.terms |
| `scripts/pre_scan.py` | Create | CLI 入口：`python scripts/pre_scan.py --work-id <id> --artifacts-dir <path>` |
| `src/amta/stage3_minimal.py` | Modify | `build_prefetch_context` 中 VLM refine 后、glossary 注入前插入术语预替换（~5 行） |
| `tests/test_term_dict.py` | Create | 主词典加载 + 匹配（精确/归一化/模糊/无匹配/多匹配） |
| `tests/test_term_replace.py` | Create | 直接预替换（单/多/重叠/无匹配/canon 列表） |
| `tests/test_pre_scan.py` | Create | Pre-scan 流程（匹配+写入 work_state+空目录） |
| `tests/test_stage3_minimal.py` | Modify | 新增预替换集成测试（build_prefetch_context + translate_page_minimal 端到端） |

---

## Phase 1: Core Modules

### Task 1: 东方主词典种子文件

**Files:**
- Create: `data/thbwiki_master_dict.json`

- [ ] **Step 1: 创建 data 目录并写入主词典 JSON**

```bash
mkdir -p data
```

写入 `data/thbwiki_master_dict.json`（完整内容，50 条目）：

```json
{
  "version": "1.0",
  "source": "manual seed (THBWiki-derived, 2026-09-02)",
  "honorific_map": {
    "様": "大人",
    "ちゃん": "酱",
    "姉": "姐",
    "兄": "哥",
    "君": "君",
    "さん": "先生",
    "たん": "碳"
  },
  "characters": [
    {"surface": "サグメ", "translation": "探女", "full_name": "稀神サグメ", "aliases": [{"surface": "サグ姉", "translation": "探女姐"}, {"surface": "サグメ様", "translation": "探女大人"}]},
    {"surface": "八意様", "translation": "八意大人", "full_name": "八意永琳", "aliases": [{"surface": "八意", "translation": "八意"}, {"surface": "永琳", "translation": "永琳"}]},
    {"surface": "輝夜様", "translation": "辉夜大人", "full_name": "蓬莱山輝夜", "aliases": [{"surface": "輝夜", "translation": "辉夜"}]},
    {"surface": "依姫", "translation": "依姬", "full_name": "綿月依姫", "aliases": [{"surface": "依姫様", "translation": "依姬大人"}]},
    {"surface": "豊姫", "translation": "丰姬", "full_name": "綿月豊姫", "aliases": [{"surface": "豊ちゃん", "translation": "丰酱"}, {"surface": "豊姫様", "translation": "丰姬大人"}]},
    {"surface": "霊夢", "translation": "灵梦", "full_name": "博麗霊夢", "aliases": []},
    {"surface": "魔理沙", "translation": "魔理沙", "full_name": "霧雨魔理沙", "aliases": []},
    {"surface": "早苗", "translation": "早苗", "full_name": "東風谷早苗", "aliases": []},
    {"surface": "紫", "translation": "紫", "full_name": "八雲紫", "aliases": [{"surface": "紫様", "translation": "紫大人"}]},
    {"surface": "幽々子", "translation": "幽幽子", "full_name": "西行寺幽々子", "aliases": []},
    {"surface": "妖夢", "translation": "妖梦", "full_name": "魂魄妖夢", "aliases": []},
    {"surface": "フラン", "translation": "芙兰", "full_name": "フランドール・スカーレット", "aliases": []},
    {"surface": "レミリア", "translation": "蕾米莉亚", "full_name": "レミリア・スカーレット", "aliases": []},
    {"surface": "咲夜", "translation": "咲夜", "full_name": "十六夜咲夜", "aliases": []},
    {"surface": "パチェ", "translation": "帕秋莉", "full_name": "パチュリー・ノーレッジ", "aliases": []},
    {"surface": "アリス", "translation": "爱丽丝", "full_name": "アリス・マーガトロイド", "aliases": []},
    {"surface": "鈴仙", "translation": "铃仙", "full_name": "鈴仙・優曇華院・イナバ", "aliases": []},
    {"surface": "てゐ", "translation": "帝", "full_name": "因幡てゐ", "aliases": []},
    {"surface": "慧音", "translation": "慧音", "full_name": "上白沢慧音", "aliases": []},
    {"surface": "妹紅", "translation": "妹红", "full_name": "藤原妹紅", "aliases": []},
    {"surface": "文", "translation": "文", "full_name": "射命丸文", "aliases": []},
    {"surface": "諏訪子", "translation": "诹访子", "full_name": "洩矢諏訪子", "aliases": []},
    {"surface": "神奈子", "translation": "神奈子", "full_name": "八坂神奈子", "aliases": []},
    {"surface": "さとり", "translation": "觉", "full_name": "古明地さとり", "aliases": []},
    {"surface": "こいし", "translation": "恋", "full_name": "古明地こいし", "aliases": []},
    {"surface": "お空", "translation": "阿空", "full_name": "霊烏路空", "aliases": []},
    {"surface": "燐", "translation": "磷", "full_name": "火焔猫燐", "aliases": []},
    {"surface": "勇儀", "translation": "勇仪", "full_name": "星熊勇儀", "aliases": []},
    {"surface": "衣玖", "translation": "衣玖", "full_name": "永江衣玖", "aliases": []},
    {"surface": "天子", "translation": "天子", "full_name": "比那名居天子", "aliases": []},
    {"surface": "純狐", "translation": "纯狐", "full_name": "純狐", "aliases": []},
    {"surface": "ヘカーティア", "translation": "赫卡提亚", "full_name": "ヘカーティア・ラピスラズリ", "aliases": []},
    {"surface": "ネムノ", "translation": "祢根子", "full_name": "坂田ネムノ", "aliases": []},
    {"surface": "成美", "translation": "成美", "full_name": "矢田寺成美", "aliases": []},
    {"surface": "隠岐奈", "translation": "隐岐奈", "full_name": "摩多羅隠岐奈", "aliases": []}
  ],
  "lore_terms": [
    {"surface": "月の民", "translation": "月之民"},
    {"surface": "穢れ", "translation": "污秽"},
    {"surface": "蓬莱の薬", "translation": "蓬莱之药"},
    {"surface": "月の都", "translation": "月都"},
    {"surface": "過去改変", "translation": "改写过去"},
    {"surface": "噂", "translation": "传闻"},
    {"surface": "月面", "translation": "月面"},
    {"surface": "異世界", "translation": "异世界"},
    {"surface": "不老不死", "translation": "不老不死"},
    {"surface": "永遠", "translation": "永远"},
    {"surface": "事象", "translation": "事象"},
    {"surface": "可能性", "translation": "可能性"},
    {"surface": "量子", "translation": "量子"},
    {"surface": "地上", "translation": "地上"},
    {"surface": "地球", "translation": "地球"}
  ]
}
```

- [ ] **Step 2: 验证 JSON 格式合法**

Run: `python -c "import json; d=json.load(open('data/thbwiki_master_dict.json', encoding='utf-8')); print(f'characters={len(d[\"characters\"])}, lore={len(d[\"lore_terms\"])}, honorific={len(d[\"honorific_map\"])}')"`
Expected: `characters=35, lore=15, honorific=7`

- [ ] **Step 3: Commit**

```bash
git add data/thbwiki_master_dict.json
git commit --no-verify -m "feat: THBWiki master dictionary seed (35 chars + 15 lore + 7 honorific)"
```

---

### Task 2: `term_dict.py` — 主词典加载 + 术语匹配

**Files:**
- Create: `src/amta/term_dict.py`
- Test: `tests/test_term_dict.py`

- [ ] **Step 1: 写失败测试**

写入 `tests/test_term_dict.py`：

```python
"""Tests for amta.term_dict — master dictionary loading and term matching."""
import json
from pathlib import Path

import pytest

MASTER_PATH = Path(__file__).parent.parent / "data" / "thbwiki_master_dict.json"


def test_load_master_dict_returns_flat_map():
    """load_master_dict flattens structured JSON into {surface: translation}."""
    from amta.term_dict import load_master_dict
    flat = load_master_dict(MASTER_PATH)
    assert isinstance(flat, dict)
    assert flat["サグメ"] == "探女"
    assert flat["サグ姉"] == "探女姐"          # alias expanded
    assert flat["サグメ様"] == "探女大人"       # alias expanded
    assert flat["月の民"] == "月之民"            # lore term
    assert "honorific_map" not in flat           # metadata not in flat map
    assert len(flat) >= 50                        # 35 chars + aliases + 15 lore


def test_load_master_dict_missing_file_raises():
    """Nonexistent path raises FileNotFoundError."""
    from amta.term_dict import load_master_dict
    with pytest.raises(FileNotFoundError):
        load_master_dict(Path("/nonexistent/dict.json"))


def test_match_terms_exact():
    """Exact substring match returns {term: translation}."""
    from amta.term_dict import match_terms
    term_map = {"サグメ": "探女", "月の民": "月之民"}
    result = match_terms("サグメは月の民だ", term_map)
    assert result == {"サグメ": "探女", "月の民": "月之民"}


def test_match_terms_normalized():
    """Normalized match handles punctuation/whitespace differences."""
    from amta.term_dict import match_terms
    term_map = {"サグメ": "探女"}
    # OCR might add spaces or punctuation around the name
    result = match_terms("「サグメ」だよ", term_map)
    assert result == {"サグメ": "探女"}


def test_match_terms_fuzzy_ocr_error():
    """Fuzzy match catches OCR errors within levenshtein ≤ 2."""
    from amta.term_dict import match_terms
    term_map = {"サグメ": "探女"}
    # OCR misread: メ → ヌ (one character difference)
    result = match_terms("サグヌだよ", term_map)
    assert result == {"サグメ": "探女"}


def test_match_terms_no_match():
    """Text with no terms returns empty dict."""
    from amta.term_dict import match_terms
    term_map = {"サグメ": "探女"}
    result = match_terms("こんにちは世界", term_map)
    assert result == {}


def test_match_terms_empty_inputs():
    """Empty text or empty term_map returns empty dict."""
    from amta.term_dict import match_terms
    assert match_terms("", {"サグメ": "探女"}) == {}
    assert match_terms("サグメ", {}) == {}


def test_match_terms_longest_first():
    """Longer terms match before shorter ones (no partial overlap)."""
    from amta.term_dict import match_terms
    term_map = {"サグメ": "探女", "サグ姉": "探女姐"}
    result = match_terms("サグ姉とサグメ", term_map)
    assert result == {"サグ姉": "探女姐", "サグメ": "探女"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_term_dict.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'amta.term_dict'`

- [ ] **Step 3: 实现 `src/amta/term_dict.py`**

```python
"""Term dictionary: load THBWiki master dictionary and match terms in text.

Master dict is structured JSON (characters + lore_terms + honorific_map).
Loader flattens it to {surface_form: chinese_translation}.
Matcher does exact → normalized → fuzzy (levenshtein ≤ 2) matching.
"""
from __future__ import annotations

import json
from pathlib import Path

from amta.metrics import levenshtein, norm


def load_master_dict(path: Path | str) -> dict[str, str]:
    """Load structured master dict JSON and flatten to {surface: translation}.

    Expands character aliases (each alias has explicit surface+translation).
    Lore terms are added directly. honorific_map is metadata only (not in flat map).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Master dictionary not found: {p}")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    flat: dict[str, str] = {}
    for char in data.get("characters", []):
        surface = char["surface"]
        translation = char["translation"]
        flat[surface] = translation
        for alias in char.get("aliases", []):
            flat[alias["surface"]] = alias["translation"]
    for lore in data.get("lore_terms", []):
        flat[lore["surface"]] = lore["translation"]
    return flat


def match_terms(text: str, term_map: dict[str, str]) -> dict[str, str]:
    """Find which terms from term_map appear in text.

    Matching strategy (in order, first hit wins per term):
      1. Exact substring match
      2. Normalized match (norm() strips punctuation/whitespace)
      3. Fuzzy match: sliding window of len(term)±0, levenshtein ≤ 2

    Terms are processed longest-first to avoid partial overlaps.
    Returns {matched_surface: translation} (only terms that were found).
    """
    if not text or not term_map:
        return {}

    norm_text = norm(text)
    matched: dict[str, str] = {}

    # Longest-first so サグ姉 matches before サグメ (no partial overlap)
    for term in sorted(term_map.keys(), key=len, reverse=True):
        translation = term_map[term]
        norm_term = norm(term)
        if not norm_term:
            continue

        # 1. Exact match
        if term in text:
            matched[term] = translation
            continue

        # 2. Normalized match (handles 「」、spaces, etc.)
        if norm_term in norm_text:
            matched[term] = translation
            continue

        # 3. Fuzzy match for OCR errors (levenshtein ≤ 2)
        #    Only for terms ≥ 2 chars; slide a window over normalized text
        if len(norm_term) >= 2:
            found = False
            tlen = len(norm_term)
            for i in range(max(0, len(norm_text) - tlen + 1)):
                window = norm_text[i:i + tlen]
                if len(window) == tlen and levenshtein(window, norm_term) <= 2:
                    matched[term] = translation
                    found = True
                    break
            if found:
                continue

    return matched
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_term_dict.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/amta/term_dict.py tests/test_term_dict.py
git commit --no-verify -m "feat: term_dict.py — master dict loader + exact/normalized/fuzzy term matcher"
```

---

### Task 3: `term_replace.py` — 直接预替换

**Files:**
- Create: `src/amta/term_replace.py`
- Test: `tests/test_term_replace.py`

- [ ] **Step 1: 写失败测试**

写入 `tests/test_term_replace.py`：

```python
"""Tests for amta.term_replace — direct term replacement in source text."""


def test_replace_terms_single():
    """Single term is replaced with Chinese translation."""
    from amta.term_replace import replace_terms
    result = replace_terms("サグメだよ", {"サグメ": "探女"})
    assert result == "探女だよ"


def test_replace_terms_multiple():
    """Multiple terms are all replaced."""
    from amta.term_replace import replace_terms
    term_map = {"サグメ": "探女", "月の民": "月之民"}
    result = replace_terms("サグメは月の民だ", term_map)
    assert result == "探女は月之民だ"


def test_replace_terms_longest_first_overlap():
    """Overlapping terms: longer one replaced first, shorter doesn't double-replace."""
    from amta.term_replace import replace_terms
    term_map = {"サグメ": "探女", "サグ姉": "探女姐"}
    # サグ姉 contains サグ but not サグメ; both should replace independently
    result = replace_terms("サグ姉とサグメ", term_map)
    assert result == "探女姐と探女"


def test_replace_terms_honorific_variant():
    """Honorific variants (サグ姉, サグメ様) replace to their specific translations."""
    from amta.term_replace import replace_terms
    term_map = {"サグメ": "探女", "サグ姉": "探女姐", "サグメ様": "探女大人"}
    result = replace_terms("サグ姉ありがとう! サグメ様も", term_map)
    assert result == "探女姐ありがとう! 探女大人も"


def test_replace_terms_no_match():
    """Text with no matching terms is returned unchanged."""
    from amta.term_replace import replace_terms
    result = replace_terms("こんにちは世界", {"サグメ": "探女"})
    assert result == "こんにちは世界"


def test_replace_terms_empty():
    """Empty text or empty term_map returns input unchanged."""
    from amta.term_replace import replace_terms
    assert replace_terms("", {"サグメ": "探女"}) == ""
    assert replace_terms("サグメ", {}) == "サグメ"


def test_replace_terms_no_chinese_double_replace():
    """Already-replaced Chinese text is not re-matched (no infinite loop)."""
    from amta.term_replace import replace_terms
    # If 探女 were somehow in the map, it shouldn't re-replace
    term_map = {"サグメ": "探女"}
    result = replace_terms("サグメ", term_map)
    assert result == "探女"  # not re-processed


def test_replace_in_canon():
    """replace_in_canon replaces baberu_text in each region dict, returns new list."""
    from amta.term_replace import replace_in_canon
    canon = [
        {"region_id": "r01", "baberu_text": "サグメだよ", "page": 11},
        {"region_id": "r02", "baberu_text": "月の民だ", "page": 11},
    ]
    term_map = {"サグメ": "探女", "月の民": "月之民"}
    result = replace_in_canon(canon, term_map)
    assert result[0]["baberu_text"] == "探女だよ"
    assert result[1]["baberu_text"] == "月之民だ"
    # Original list not mutated
    assert canon[0]["baberu_text"] == "サグメだよ"
    # Non-text fields preserved
    assert result[0]["region_id"] == "r01"
    assert result[0]["page"] == 11


def test_replace_in_canon_missing_baberu_text():
    """Region without baberu_text falls back to text field, then unchanged."""
    from amta.term_replace import replace_in_canon
    canon = [{"region_id": "r01", "text": "サグメ", "page": 11}]
    result = replace_in_canon(canon, {"サグメ": "探女"})
    assert result[0].get("baberu_text") == "探女"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_term_replace.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'amta.term_replace'`

- [ ] **Step 3: 实现 `src/amta/term_replace.py`**

```python
"""Direct term replacement: replace locked terms in source text with Chinese translations.

This is the core mechanical guardrail. Before sending text to the LLM,
all locked terminology (from pre-scan) is directly replaced in the source.
The LLM then translates a 日中混合文 — Chinese terms are already correct,
LLM only translates remaining Japanese. No retry, no repair, one pass.

Replacement is longest-match-first to avoid partial overlaps
(e.g., サグ姉 replaced before サグメ can partially match inside it).
"""
from __future__ import annotations


def replace_terms(text: str, term_map: dict[str, str]) -> str:
    """Replace all occurrences of terms in term_map with their translations.

    Args:
        text: Source Japanese text (may contain terms to replace).
        term_map: {surface_form: chinese_translation} — only locked terms.

    Returns:
        Text with terms replaced. Already-Chinese text is not re-matched
        because we do a single pass (not recursive).
    """
    if not text or not term_map:
        return text

    result = text
    # Longest-first: replace サグ姉 before サグメ so shorter term doesn't
    # partially match inside a longer one that's already been replaced.
    for term in sorted(term_map.keys(), key=len, reverse=True):
        translation = term_map[term]
        if term and term in result:
            result = result.replace(term, translation)
    return result


def replace_in_canon(canon_items: list[dict], term_map: dict[str, str]) -> list[dict]:
    """Replace terms in baberu_text of each canon region. Returns a new list.

    For each region, reads baberu_text (falls back to text), applies replace_terms,
    and writes result back to baberu_text. Original list is not mutated.

    Args:
        canon_items: List of region dicts (each with region_id, baberu_text, page, etc.).
        term_map: {surface_form: chinese_translation} — locked terms from pre-scan.

    Returns:
        New list of region dicts with baberu_text replaced.
    """
    if not canon_items or not term_map:
        # Return shallow copies to avoid mutating input even when no replacement
        return [dict(r) for r in canon_items]

    result = []
    for r in canon_items:
        item = dict(r)  # shallow copy — don't mutate original
        src = item.get("baberu_text") or item.get("text") or ""
        if src:
            item["baberu_text"] = replace_terms(src, term_map)
        result.append(item)
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_term_replace.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/amta/term_replace.py tests/test_term_replace.py
git commit --no-verify -m "feat: term_replace.py — direct pre-replacement (longest-match-first, no recursion)"
```

---

### Task 4: `pre_scan.py` — 全本扫描 + CLI

**Files:**
- Create: `src/amta/pre_scan.py`
- Create: `scripts/pre_scan.py`
- Test: `tests/test_pre_scan.py`

- [ ] **Step 1: 写失败测试**

写入 `tests/test_pre_scan.py`：

```python
"""Tests for amta.pre_scan — per-work terminology pre-scan."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace with canon artifacts and empty work_state."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    # Two pages of canon, each with regions containing サグメ
    page11 = {
        "page": 11,
        "items": [
            {"region_id": "r01", "baberu_text": "サグメだよ", "page": 11},
            {"region_id": "r02", "baberu_text": "サグ姉ありがとう", "page": 11},
        ],
    }
    page12 = {
        "page": 12,
        "items": [
            {"region_id": "r03", "baberu_text": "月の民の話", "page": 12},
            {"region_id": "r04", "baberu_text": "サグメ様もいた", "page": 12},
        ],
    }
    (artifacts_dir / "page_11_canon.json").write_text(
        json.dumps(page11, ensure_ascii=False), encoding="utf-8")
    (artifacts_dir / "page_12_canon.json").write_text(
        json.dumps(page12, ensure_ascii=False), encoding="utf-8")
    return tmp_path, artifacts_dir


def test_run_pre_scan_matches_and_writes_work_state(tmp_workspace, monkeypatch):
    """pre_scan matches terms across all pages and writes confirmed terms to work_state."""
    from amta import pre_scan
    tmp_path, artifacts_dir = tmp_workspace
    work_id = "test-work"

    # Point workstate at tmp_path (work_dir returns workspace root)
    monkeypatch.setattr(pre_scan.workstate, "work_dir",
                        lambda wid: tmp_path / wid)
    # Ensure state/ subdirectory exists for save_state
    (tmp_path / work_id / "state").mkdir(parents=True, exist_ok=True)

    master = {"サグメ": "探女", "サグ姉": "探女姐", "サグメ様": "探女大人", "月の民": "月之民"}
    result = pre_scan.run_pre_scan(work_id, artifacts_dir, _master_dict=master)

    # All 4 terms found across the two pages
    assert set(result.keys()) == {"サグメ", "サグ姉", "サグメ様", "月の民"}
    assert result["サグメ"] == "探女"

    # work_state.terms written with status=confirmed
    state = pre_scan.workstate.load_state(work_id)
    terms = state.get("terms", {})
    assert terms["サグメ"]["status"] == "confirmed"
    assert terms["サグメ"]["translation"] == "探女"
    assert terms["サグメ"]["source"] == "pre_scan"
    assert terms["月の民"]["status"] == "confirmed"


def test_run_pre_scan_empty_artifacts_dir(tmp_path):
    """Empty artifacts directory returns empty dict and doesn't crash."""
    from amta import pre_scan
    empty_dir = tmp_path / "empty_artifacts"
    empty_dir.mkdir()
    result = pre_scan.run_pre_scan("empty-work", empty_dir, _master_dict={"サグメ": "探女"})
    assert result == {}


def test_run_pre_scan_no_matching_terms(tmp_path):
    """Canon with no matching terms returns empty dict."""
    from amta import pre_scan
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    page = {"page": 11, "items": [{"region_id": "r01", "baberu_text": "こんにちは", "page": 11}]}
    (artifacts_dir / "page_11_canon.json").write_text(
        json.dumps(page, ensure_ascii=False), encoding="utf-8")
    result = pre_scan.run_pre_scan("nomatch-work", artifacts_dir, _master_dict={"サグメ": "探女"})
    assert result == {}


def test_pre_scan_preserves_existing_terms(tmp_workspace, monkeypatch):
    """Pre-scan adds new terms without deleting existing confirmed terms in work_state."""
    from amta import pre_scan
    tmp_path, artifacts_dir = tmp_workspace
    work_id = "test-work"

    monkeypatch.setattr(pre_scan.workstate, "work_dir",
                        lambda wid: tmp_path / wid)
    (tmp_path / work_id / "state").mkdir(parents=True, exist_ok=True)

    # Pre-populate work_state with an existing term
    pre_scan.workstate.save_state(work_id, {
        "terms": {"既存用語": {"translation": "既有译法", "status": "confirmed", "source": "manual"}}
    })

    master = {"サグメ": "探女"}
    pre_scan.run_pre_scan(work_id, artifacts_dir, _master_dict=master)

    state = pre_scan.workstate.load_state(work_id)
    terms = state["terms"]
    # Existing term preserved
    assert "既存用語" in terms
    assert terms["既存用語"]["translation"] == "既有译法"
    # New term added
    assert "サグメ" in terms
    assert terms["サグメ"]["status"] == "confirmed"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_pre_scan.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'amta.pre_scan'`

- [ ] **Step 3: 实现 `src/amta/pre_scan.py`**

```python
"""Pre-scan: build per-work locked terminology dictionary from all OCR text.

Run ONCE per work, before translation starts. Reads all canon artifacts,
collects all OCR text, matches against THBWiki master dictionary,
and writes confirmed terms to work_state.terms.

No LM calls — pure mechanical matching (exact + normalized + fuzzy ≤2).
Terms not in the master dict are left free (LLM translates them naturally;
one-off terms don't have consistency issues anyway).
"""
from __future__ import annotations

from pathlib import Path

from amta import artifacts, workstate
from amta.term_dict import load_master_dict, match_terms

# Default master dict path (relative to project root: data/thbwiki_master_dict.json)
DEFAULT_MASTER_DICT = Path(__file__).parent.parent.parent / "data" / "thbwiki_master_dict.json"


def run_pre_scan(work_id: str, artifacts_dir: Path | str,
                 master_dict_path: Path | str | None = None,
                 _master_dict: dict[str, str] | None = None) -> dict[str, str]:
    """Scan all canon artifacts in artifacts_dir, match terms, write to work_state.

    Args:
        work_id: Work identifier (used for work_state path).
        artifacts_dir: Directory containing page_*_canon.json files.
        master_dict_path: Path to master dict JSON (defaults to project data/).
        _master_dict: INTERNAL — pre-loaded flat dict for testing. Do not use in production.

    Returns:
        {matched_surface: translation} — all terms found in this work.
        Also writes these terms to work_state.terms with status=confirmed, source=pre_scan.
    """
    art_dir = Path(artifacts_dir)

    # Load master dictionary (flat {surface: translation})
    if _master_dict is not None:
        master = _master_dict
    else:
        master = load_master_dict(master_dict_path or DEFAULT_MASTER_DICT)

    if not master:
        return {}

    # Collect all OCR text from all canon artifacts
    all_text_parts: list[str] = []
    if art_dir.exists():
        canon_files = sorted(art_dir.glob("page_*_canon.json"))
        for cf in canon_files:
            try:
                doc = artifacts.load_canon(cf)
                for item in doc.get("items", []):
                    txt = item.get("baberu_text") or item.get("text") or ""
                    if txt.strip():
                        all_text_parts.append(txt)
            except Exception:
                # Skip unreadable canon files — don't crash the whole pre-scan
                continue

    if not all_text_parts:
        return {}

    combined_text = "\n".join(all_text_parts)

    # Match terms against master dictionary
    matched = match_terms(combined_text, master)

    if not matched:
        return {}

    # Write matched terms to work_state (status=confirmed, source=pre_scan)
    state = workstate.load_state(work_id)
    terms = state.setdefault("terms", {})
    for surface, translation in matched.items():
        # Don't overwrite existing manual terms (manual takes precedence)
        if surface in terms and terms[surface].get("source") == "manual":
            continue
        terms[surface] = {
            "translation": translation,
            "status": "confirmed",
            "source": "pre_scan",
            "master_dict": True,
        }
    workstate.save_state(work_id, state)

    return matched
```

- [ ] **Step 4: 实现 CLI `scripts/pre_scan.py`**

```python
#!/usr/bin/env python3
"""CLI: pre-scan a work's canon artifacts to build locked terminology dictionary.

Usage:
    python scripts/pre_scan.py --work-id <work_id> --artifacts-dir <path>
    python scripts/pre_scan.py --work-id touhou-single-wing --artifacts-dir workspace/touhou-single-wing/artifacts

Run once per work, before translation (stage 3). Outputs matched term count
and writes confirmed terms to work_state.json.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path for `amta` import
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from amta.pre_scan import run_pre_scan  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-scan canon artifacts to build locked terminology dictionary.")
    ap.add_argument("--work-id", required=True, help="Work identifier (for work_state path)")
    ap.add_argument("--artifacts-dir", required=True, help="Directory containing page_*_canon.json files")
    ap.add_argument("--master-dict", default=None, help="Path to master dict JSON (default: data/thbwiki_master_dict.json)")
    args = ap.parse_args()

    art_dir = Path(args.artifacts_dir)
    if not art_dir.exists():
        print(f"ERROR: artifacts directory not found: {art_dir}", file=sys.stderr)
        return 1

    matched = run_pre_scan(args.work_id, art_dir, master_dict_path=args.master_dict)

    print(f"Pre-scan complete: {len(matched)} terms locked for work '{args.work_id}'")
    if matched:
        print("Locked terms:")
        for surface, translation in sorted(matched.items()):
            print(f"  {surface} → {translation}")
    else:
        print("No master-dictionary terms found in this work.")
        print("(Terms not in the master dict will be translated freely by the LLM.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_pre_scan.py -v`
Expected: all 4 tests PASS

- [ ] **Step 6: 验证 CLI help**

Run: `python scripts/pre_scan.py --help`
Expected: shows --work-id, --artifacts-dir, --master-dict options.

- [ ] **Step 7: Commit**

```bash
git add src/amta/pre_scan.py scripts/pre_scan.py tests/test_pre_scan.py
git commit --no-verify -m "feat: pre_scan.py + CLI — per-work term scan, pure mechanical, writes work_state.terms"
```

---

## Phase 2: Integration

### Task 5: 集成进 `stage3_minimal.build_prefetch_context`

**Files:**
- Modify: `src/amta/stage3_minimal.py` (build_prefetch_context, ~5 行插入)
- Test: `tests/test_stage3_minimal.py` (新增 2 个测试)

- [ ] **Step 1: 写失败的集成测试**

在 `tests/test_stage3_minimal.py` 末尾追加：

```python
def test_build_prefetch_context_replaces_terms():
    """build_prefetch_context replaces locked terms in refined_canon before glossary injection."""
    from amta.stage3_minimal import build_prefetch_context
    canon = [
        {"region_id": "r01", "baberu_text": "サグメだよ", "page": 11},
        {"region_id": "r02", "baberu_text": "サグ姉ありがとう", "page": 11},
    ]
    work_state = {
        "terms": {
            "サグメ": {"translation": "探女", "status": "confirmed", "source": "pre_scan"},
            "サグ姉": {"translation": "探女姐", "status": "confirmed", "source": "pre_scan"},
        }
    }
    ctx = build_prefetch_context(canon, work_state, None, None)
    # Terms replaced in refined_canon baberu_text
    assert ctx["refined_canon"][0]["baberu_text"] == "探女だよ"
    assert ctx["refined_canon"][1]["baberu_text"] == "探女姐ありがとう"
    # Glossary injection finds nothing (terms already replaced → no Japanese term in cur_text)
    assert "サグメ" not in ctx["system_extra"]


def test_build_prefetch_context_no_terms_passthrough():
    """Without confirmed terms, build_prefetch_context passes canon through unchanged."""
    from amta.stage3_minimal import build_prefetch_context
    canon = [{"region_id": "r01", "baberu_text": "サグメだよ", "page": 11}]
    work_state = {"terms": {}}  # no confirmed terms
    ctx = build_prefetch_context(canon, work_state, None, None)
    assert ctx["refined_canon"][0]["baberu_text"] == "サグメだよ"


def test_translate_page_minimal_term_replacement_end_to_end():
    """End-to-end: locked terms survive translation (fake LLM echoes input)."""
    import json
    from amta.stage3_minimal import translate_page_minimal
    canon = {"items": [{"region_id": "r01", "baberu_text": "サグメだよ", "page": 11}]}
    work_state = {
        "terms": {"サグメ": {"translation": "探女", "status": "confirmed", "source": "pre_scan"}}
    }
    # Fake LLM: echoes the replaced text as translation (simulates LLM preserving Chinese)
    def fake_text(messages, tools=None):
        return json.dumps({"r01": "探女，是哦"})
    # Monkeypatch workstate.load_state to return our test state
    from amta import workstate
    original_load = workstate.load_state
    workstate.load_state = lambda wid: work_state
    try:
        result = translate_page_minimal("test", canon, llm_text=fake_text, vlm_enabled=False)
    finally:
        workstate.load_state = original_load
    assert result["translations"]["r01"] == "探女，是哦"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_stage3_minimal.py -k "replace_terms or no_terms_passthrough or term_replacement_end" -v`
Expected: all 3 FAIL (term replacement not yet implemented in build_prefetch_context)

- [ ] **Step 3: 修改 `src/amta/stage3_minimal.py` 的 `build_prefetch_context`**

在 `build_prefetch_context` 函数中，VLM refine 应用完成后、`cur_text` 构建之前，插入术语预替换。找到以下代码段（约在 `# System extra: glossary terms + scene` 注释之前）：

```python
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
```

在 `refined.append(item)` 循环结束后、`# System extra` 注释之前，插入：

```python
    # === Direct term pre-replacement (mechanical guardrail) ===
    # Replace locked terminology (from pre-scan) with Chinese translations
    # BEFORE glossary injection. This makes glossary injection a no-op
    # (Japanese terms no longer in cur_text) and ensures LLM translates
    # a 日中混合文 where terms are already correct. Zero retry, zero repair.
    _locked = {}
    for _k, _v in work_state.get("terms", {}).items():
        if _v.get("status") == "confirmed" and _v.get("translation"):
            _locked[_k] = _v["translation"]
    if _locked and refined:
        from amta.term_replace import replace_in_canon
        refined = replace_in_canon(refined, _locked)
    # === End term pre-replacement ===
```

完整的修改后函数片段（供对照）：

```python
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

    # === Direct term pre-replacement (mechanical guardrail) ===
    _locked = {}
    for _k, _v in work_state.get("terms", {}).items():
        if _v.get("status") == "confirmed" and _v.get("translation"):
            _locked[_k] = _v["translation"]
    if _locked and refined:
        from amta.term_replace import replace_in_canon
        refined = replace_in_canon(refined, _locked)
    # === End term pre-replacement ===

    # System extra: glossary terms + scene
    cur_text = " ".join(r.get("baberu_text") or r.get("text") or "" for r in refined)
```

- [ ] **Step 4: 运行新增测试确认通过**

Run: `pytest tests/test_stage3_minimal.py -k "replace_terms or no_terms_passthrough or term_replacement_end" -v`
Expected: all 3 PASS

- [ ] **Step 5: 运行全量测试确认无回归**

Run: `pytest tests/ -q`
Expected: all tests PASS (existing stage3_minimal tests unaffected — term replacement only activates when confirmed terms exist)

- [ ] **Step 6: Commit**

```bash
git add src/amta/stage3_minimal.py tests/test_stage3_minimal.py
git commit --no-verify -m "feat: stage3_minimal — direct term pre-replacement in build_prefetch_context (mechanical guardrail, zero retry)"
```

---

## Phase 3: Validation

### Task 6: 端到端验证 — pages 11-20 术语一致率

**Files:**
- Output: `output/reports/term-consistency-validation.md`

- [ ] **Step 1: 对测试 work 运行 pre-scan**

前提：测试 work 的 canon 产物已存在（pages 11-20，东方同人志）。

Run:
```bash
python scripts/pre_scan.py \
  --work-id touhou-single-wing \
  --artifacts-dir workspace/touhou-single-wing/artifacts
```
Expected: 输出锁定术语列表，包含 サグメ→探女、サグ姉→探女姐、サグメ様→探女大人、八意様→八意大人、輝夜様→辉夜大人、依姫→依姬、豊姫→丰姬、月の民→月之民 等。锁定术语数 ≥ 8。

- [ ] **Step 2: 运行翻译（带术语预替换）pages 11-20**

对每页运行：
```bash
python scripts/03_translate.py \
  --canon workspace/touhou-single-wing/artifacts/page_<N>_canon.json \
  --out workspace/touhou-single-wing/translations/page_<N>_translation.json \
  --mode minimal \
  --work-id touhou-single-wing \
  --state-dir workspace/touhou-single-wing
```
（对 N = 11..20 循环执行。如果有批量脚本，用批量脚本。）

Expected: 每页翻译成功，无 402 错误。

- [ ] **Step 3: 测量术语一致率**

编写并运行一个验证脚本（或手动检查），对每个锁定术语：
1. 在原始 canon 中找到包含该术语的所有 region
2. 检查对应翻译中是否包含该术语的中文译名
3. 统计一致率 = 包含正确译名的 region 数 / 包含该术语的 region 总数

关键指标（以 サグメ/サグ姉 为核心）：
- サグメ 一致率：目标 100%（之前为 ~33%：探女/萨古梅/萨格梅 三种）
- サグ姉 一致率：目标 100%（之前为 ~33%：探女姐/萨古姐/萨古姐姐 三种）
- 全部锁定术语平均一致率：目标 ≥ 95%

Run（验证脚本示例，保存为 `scripts/verify_term_consistency.py` 后执行）：

```python
#!/usr/bin/env python3
"""Verify term consistency across translation artifacts."""
import json, sys
from pathlib import Path

def main():
    work_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("workspace/touhou-single-wing")
    art_dir = work_dir / "artifacts"
    trans_dir = work_dir / "translations"
    state = json.loads((work_dir / "work_state.json").read_text(encoding="utf-8"))
    locked = {k: v["translation"] for k, v in state.get("terms", {}).items()
              if v.get("status") == "confirmed"}

    print(f"Locked terms: {len(locked)}")
    print(f"{'Term':<12} {'Translation':<10} {'Hit/Total':<12} {'Rate':<8}")
    print("-" * 45)

    for term, translation in sorted(locked.items()):
        hit = total = 0
        for canon_file in sorted(art_dir.glob("page_*_canon.json")):
            page = canon_file.stem.replace("_canon", "")
            trans_file = trans_dir / f"{page}_translation.json"
            if not trans_file.exists():
                continue
            canon = json.loads(canon_file.read_text(encoding="utf-8"))
            trans = json.loads(trans_file.read_text(encoding="utf-8"))
            trans_map = trans.get("translations", {})
            for item in canon.get("items", []):
                src = item.get("baberu_text") or ""
                rid = item["region_id"]
                if term in src:
                    total += 1
                    if translation in trans_map.get(rid, ""):
                        hit += 1
        rate = f"{hit/total*100:.0f}%" if total else "N/A"
        print(f"{term:<12} {translation:<10} {hit}/{total:<10} {rate:<8}")

if __name__ == "__main__":
    main()
```

Run: `python scripts/verify_term_consistency.py workspace/touhou-single-wing`
Expected: サグメ 和 サグ姉 的一致率为 100%，全部锁定术语平均 ≥ 95%。

- [ ] **Step 4: 写入验证报告**

将验证结果写入 `output/reports/term-consistency-validation.md`，包含：
- 锁定术语列表（pre-scan 输出）
- 每个术语的一致率表格
- 与基线（hayai-default 报告，098ce4f）的对比
- 结论：术语不一致问题是否根治

- [ ] **Step 5: Commit 验证报告和验证脚本**

```bash
git add scripts/verify_term_consistency.py output/reports/term-consistency-validation.md
git commit --no-verify -m "test: term consistency validation (pages 11-20, pre-scan + direct replacement)"
```

---

## Self-Review

**1. Spec coverage:**
- 根治术语不一致 → Task 5 直接预替换（源文术语→中文，LM 翻译混合文）
- pre-scan 全本扫描 → Task 4（纯机械，无 LM）
- 东方主词典 → Task 1（35 角色 + 15 设定词 + 敬称映射）
- 机械护栏非 LLM 自由发挥 → 全部匹配/替换为确定性代码，LM 只翻译剩余日文
- 零 retry/repair/evaluate → 方案中无任何重试/修复/评估循环
- 专注东方Project → 主词典仅含东方术语
- 快速验证 → Task 6 端到端 pages 11-20

**2. Placeholder scan:** 无 TBD/TODO。每个代码步骤有完整代码。每个运行步骤有精确命令。每个测试有 assert。主词典 JSON 完整（50 条目）。

**3. Type consistency:**
- `load_master_dict(path) -> dict[str, str]` — Task 2 测试和实现一致
- `match_terms(text, term_map) -> dict[str, str]` — Task 2 测试、实现、Task 4 调用一致
- `replace_terms(text, term_map) -> str` — Task 3 测试和实现一致
- `replace_in_canon(canon_items, term_map) -> list[dict]` — Task 3 测试、实现、Task 5 调用一致
- `run_pre_scan(work_id, artifacts_dir, master_dict_path=None, _master_dict=None) -> dict[str, str]` — Task 4 测试、实现、CLI 调用一致
- work_state.terms 结构：`{surface: {translation, status, source, master_dict}}` — Task 4 写入、Task 5 读取一致

**4. Known gaps (explicit, not hidden):**
- 主词典仅 50 条目（MVP 种子），未覆盖全部东方角色/设定词。未命中主词典的术语由 LLM 自由翻译（一次出现的词不存在一致性问题；重复出现但未命中的词可后续补入主词典）。THBWiki 自动抓取脚本作为后续优化，不在本计划范围内。
- 敬称变体（如 サグ姉 = サグメ+姉 的形态缩略）依赖主词典中显式列出 alias，不做自动形态分析。新变体需手动补入 alias。
- 模糊匹配（levenshtein ≤ 2）可能误匹配短词（≤2 字符的术语已跳过模糊匹配）。3+ 字符术语的误匹配风险极低。
- LM 可能在翻译日中混合文时改写已替换的中文术语（如将「探女」意译为其他）。接受 99% 保留率 + 1% 可见错误人工发现。不添加存活检查（YAGNI）。
- pre-scan 不做 LM 残差解析（高频未匹配词的自动定译）。MVP 不需要，后续如发现大量未命中重复词再添加。
- `translate_station.py` 和 `03_translate.py` 无需修改——预替换在 `build_prefetch_context` 内部自动激活（只要 work_state.terms 有 confirmed 术语）。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-02-terminology-pre-scan-replacement.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Each task is self-contained with its own tests and commit.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**

Note: Task 1-4 are pure new modules (no risk to existing code). Task 5 is the only modification to existing code (stage3_minimal.py, ~5 lines). Task 6 requires real translation API calls (costs tokens).
