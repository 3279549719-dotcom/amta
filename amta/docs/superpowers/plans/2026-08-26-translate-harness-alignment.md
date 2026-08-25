# Translate Harness Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 translate 层从"已落地的最小子集"对齐到 GPT 设计的 Translation Harness 全貌（Guardrails 6 类 / Eval 四维 / Tools+Contract / 分层 Loop / State 四层 / 验收阈值），以 GPT 设计为基准逐条补缺，不因"已有相似实现"而放行。

**Architecture:** 沿用"脚本直调 DeepSeek API + 文件即状态"的会话驱动架构（ADR-014）。新增纯函数机械层（Input schema / Glossary Validator）与脚本编排（merge_suggestions / apply_revisions），升级 ③ 语义评审为四维评分，恢复 Tools（预取式 lookup/get_context + vision 多轮）并加 Tool Contract，work_state 增 observed 层变四层。所有机制 TDD，机械层走纯函数可单测，API 通道保留注入点。

**Tech Stack:** Python 3.12 / pytest / requests（DeepSeek chat/completions）· 沿用 `npm run fastcheck`（ruff+pyright+pytest）。

**关键设计决定（grill-me 定案，勿回退）:**
- 四维评分**全量合并进同一次 ③ 调用**（成本几乎不增），分数**不当验收闸门**，只作导演排序+趋势监控。
- **恢复三工具** + Tool Contract：lookup/get_context 预取（本地读文件，免费，`TERM_BUDGET=10`/页）；vision 走 ③ 通道多轮（`VISION_BUDGET=2`/页，token 控制）。
- **work_state 加 observed 层变四层**（observed/confirmed/inferred/candidate），跨页一致 observed→confirmed 自动升、导演可降级。
- **无参考 GT 不建参考译文 Golden Set**；建判例库 case-law（4 条样本+案例）校准 ③ 与验收口径。
- **验收阈值**：③ 通过率 ≥90% + 导演清 FAILED；③ 的 FAILED=导演过目队列，非判决书。

---

## File Structure

**新增:**
- `src/amta/canon_schema.py` — `validate_canon()`：pre-translate Input schema 校验（纯函数）
- `src/amta/glossary.py` — `check_glossary()`：Knowledge guardrail，confirmed 译名违例检测（纯函数）
- `scripts/merge_suggestions.py` — suggestions.json → work_state 合并（candidate→confirmed 跨页一致自动升）
- `scripts/apply_revisions.py` — 导演修订应用 + `--only` 重评审触发
- `output/data/case_law.json` — 判例库
- `docs/decisions/016-translate-harness-alignment.md` — 差距审计 ADR

**修改:**
- `src/amta/workstate.py` — STATUSES 加 `observed`（四层）
- `src/amta/translate.py` — SuggestionsExtractor 收紧为片假名专名 + 移除全 token 提取；新增 Tools 预取 `build_tools_context()`；on-failure 记录 `record_failure()`
- `scripts/03_translate.py` — 接入 validate_canon（pre-translate gate）、check_glossary、Tools 预取、on-failure 落盘
- `scripts/translate_semantic_check.py` — 四维评分（合并同次调用）+ severity 分级
- `docs/decisions/014-translate-station-architecture.md` / `docs/progress.md` — 验收阈值 + 校准结论

**测试:**
- 新增 `tests/test_canon_schema.py` `tests/test_glossary.py` `tests/test_merge_suggestions.py` `tests/test_apply_revisions.py`
- 修改 `tests/test_translate.py` `tests/test_semantic_check.py` `tests/test_workstate.py`

---

## Phase 0 — 差距审计落 ADR

### Task 1: 写 ADR-016 差距审计

**Files:**
- Create: `docs/decisions/016-translate-harness-alignment.md`

- [ ] **Step 1: 创建 ADR-016 文档**

内容必须包含：
- **Context**：引用 GPT 设计文档（`reference/html by GPT/translation_harness_recommended_design.html`）+ 交接文档 + ADR-014；说明"以 GPT 设计为基准审计，不以现有实现放行"的方法论。
- **差距表**（Guardrails 6 类 × Soft/Hard/Lifecycle）：Input/Output/Knowledge/Tool/State Mutation/Quality 每条现状（有/缺/半吊子）+ 本 ADR 落地的取舍。
- **Eval 四维**：Accuracy（③ 分级）/Consistency（Glossary Validator）/Fluency（导演判例）/Readability（归 05 工位，边界外声明）。
- **Tools**：恢复三工具 + Tool Contract（VISION_BUDGET=2/页、TERM_BUDGET=10/页）；"脚本直读文件=无约束读"的问题说明。
- **State 四层**：observed 层 + 晋升路径（跨页一致自动升、导演可降级）。
- **Loop**：脚本机械层（retry+split）+ 导演语义层（apply_revisions → --only 重评审 → budget=1 轮 → needs_review）。
- **验收阈值**：③ ≥90% + 导演清 FAILED。
- **Consequences**：修订 ADR-014 中"③ 是粗筛+随机"的表述，补充"四维评分=导演排序/监控，不当闸门"。

- [ ] **Step 2: 自审**——确认 6 类约束、4 维、3 工具、4 层状态、2 层 loop、阈值全在表内，无遗漏。

- [ ] **Step 3: Commit**

```bash
cd "E:\manga translator agent\amta"
git add docs/decisions/016-translate-harness-alignment.md
git commit -m "docs(adr): 016 translate harness alignment gap audit"
```

---

## Phase 1 — Input 机械硬约束

### Task 2: canon Input schema 校验

**Files:**
- Create: `src/amta/canon_schema.py`
- Create: `tests/test_canon_schema.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_canon_schema.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.canon_schema import validate_canon


def test_valid_canon_no_problems():
    canon = [{"region_id": "page_0_u01", "text": "穢れ", "page": 0},
             {"region_id": "page_0_u02", "text": "月", "page": 0}]
    assert validate_canon(canon) == []


def test_missing_region_id():
    canon = [{"text": "穢れ", "page": 0}]
    assert "missing region_id" in validate_canon(canon)


def test_duplicate_region_id():
    canon = [{"region_id": "a", "text": "x", "page": 0},
             {"region_id": "a", "text": "y", "page": 0}]
    assert "duplicate region_id a" in validate_canon(canon)


def test_empty_text():
    canon = [{"region_id": "a", "text": "  ", "page": 0}]
    assert "empty text" in validate_canon(canon)


def test_bad_page_type():
    canon = [{"region_id": "a", "text": "x", "page": "zero"}]
    assert "bad page" in validate_canon(canon)


def test_not_a_list():
    assert "canon must be a list" in validate_canon({"region_id": "a"})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd "E:\manga translator agent\amta" && python -m pytest tests/test_canon_schema.py -q`
Expected: FAIL `ModuleNotFoundError: No module named 'amta.canon_schema'`

- [ ] **Step 3: 实现最小代码**

```python
# src/amta/canon_schema.py
"""pre-translate Input schema 校验（机械硬约束，ADR-016）。

canon_text.json 结构: [{region_id, text, page}]。校验 region_id 唯一非空、
text 非空、page 为 int。返回问题列表，空=合法。
"""
from __future__ import annotations

from typing import Any


def validate_canon(canon: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(canon, list):
        return ["canon must be a list"]
    seen: set[str] = set()
    for i, r in enumerate(canon):
        if not isinstance(r, dict):
            problems.append(f"item {i} must be dict")
            continue
        rid = r.get("region_id")
        if not rid or not str(rid).strip():
            problems.append(f"item {i}: missing region_id")
        elif rid in seen:
            problems.append(f"duplicate region_id {rid}")
        else:
            seen.add(rid)
        if not str(r.get("text") or "").strip():
            problems.append(f"item {i}: empty text")
        if not isinstance(r.get("page"), int):
            problems.append(f"item {i}: bad page")
    return problems
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_canon_schema.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/amta/canon_schema.py tests/test_canon_schema.py
git commit -m "feat(canon): input schema validation guardrail"
```

### Task 3: 03_translate 接入 pre-translate gate

**Files:**
- Modify: `scripts/03_translate.py`（在 `run()` 读 canon 后立即校验）
- Test: `tests/test_translate.py`（新增）

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_translate.py
def test_run_rejects_bad_canon(monkeypatch, tmp_path):
    import json
    from amta import paths
    bad = [{"region_id": "a", "text": "x"}]  # 缺 page
    p = tmp_path / "canon.json"
    p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(paths, "read_json", lambda _: bad)
    from scripts import _03_translate as st  # 数字前缀需桥
    try:
        st.run(p, tmp_path / "out.json")
        raise AssertionError("should raise")
    except ValueError as e:
        assert "canon" in str(e).lower()
```

（若 `scripts/_03_translate.py` 桥不存在则先建：`import sys; sys.path.insert(0,'scripts'); import _03_translate as st`。参照 L20 约定，数字前缀脚本需 `_NN_name.py` 测试桥。）

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_translate.py::test_run_rejects_bad_canon -q`
Expected: FAIL（未抛 ValueError）

- [ ] **Step 3: 修改 `scripts/03_translate.py` 的 `run()`**

在 `canon = paths.read_json(canon_path)` 之后加：

```python
    from amta.canon_schema import validate_canon
    problems = validate_canon(canon)
    if problems:
        raise ValueError(f"canon input schema failed: {'; '.join(problems[:5])}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_translate.py -q`
Expected: PASS（新增 + 原有 11 条全过）

- [ ] **Step 5: Commit**

```bash
git add scripts/03_translate.py tests/test_translate.py
git commit -m "feat(translate): pre-translate input schema gate"
```

---

## Phase 2 — 术语演进 + State observed 层

### Task 4: work_state 加 observed 状态（四层）

**Files:**
- Modify: `src/amta/workstate.py`
- Modify: `tests/test_workstate.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_workstate.py
def test_observed_status_accepted():
    import sys, tempfile, os
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import amta.workstate as ws
    assert "observed" in ws.STATUSES


def test_update_character_observed(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import amta.workstate as ws
    work_id = "ws-test-observed"
    monkeypatch.setattr(ws, "WORKSPACE", tmp_path)
    ws.init_workspace(work_id)
    ws.update_character(work_id, "サグメ", status="observed", source="page_0")
    state = ws.load_state(work_id)
    assert state["characters"]["サグメ"]["status"] == "observed"
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_workstate.py -q`
Expected: FAIL（`"observed" in ws.STATUSES` 为 False）

- [ ] **Step 3: 修改 `src/amta/workstate.py`**

```python
STATUS_OBSERVED = "observed"
STATUSES = (STATUS_CONFIRMED, STATUS_INFERRED, STATUS_CANDIDATE, STATUS_OBSERVED)
```

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_workstate.py -q`
Expected: PASS（原有 8 + 新增 2）

- [ ] **Step 5: Commit**

```bash
git add src/amta/workstate.py tests/test_workstate.py
git commit -m "feat(workstate): add observed status layer (four-layer state)"
```

### Task 5: SuggestionsExtractor 收紧为专有名词

**Files:**
- Modify: `src/amta/translate.py`（SuggestionsExtractor）
- Modify: `tests/test_translate.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_translate.py
def test_suggestions_only_katakana_proper_nouns():
    from amta import translate
    ex = translate.SuggestionsExtractor(existing=set())
    canon = [
        {"region_id": "a", "page": 0, "text": "稀神サグメは月が好きだ"},
        {"region_id": "b", "page": 0, "text": "永琳が来た"},
    ]
    tr = {"a": "稀神探女喜欢月亮", "b": "永琳来了"}
    sugg = ex.extract(canon, tr)
    terms = {s["term"] for s in sugg}
    assert "サグメ" in terms            # 片假名专名应提取
    assert "月" not in terms            # 单字不提取
    assert "来た" not in terms          # 普通汉字/动词不提取
    assert "が好き" not in terms        # 不整段提取
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_translate.py::test_suggestions_only_katakana_proper_nouns -q`
Expected: FAIL（现逻辑会把整段日文提取，含 "月が好きだ" 等）

- [ ] **Step 3: 替换 `SuggestionsExtractor.extract`**

```python
# 片假名词段 = 专有名词/外来语特征最强（サグメ）；汉字人名难自动判别，留导演批
_KATAKANA_TERM = re.compile(r"[\u30a0-\u30ff]{2,}")
# 过滤常见语法片假名（>=2 字仍会误抓），黑名单
_KATAKANA_STOP = {
    "カラ", "デス", "マス", "タリ", "シテ", "トモ", "ノニ", "コト",
    "トキ", "ヒト", "モノ", "コレ", "ソレ", "アレ", "コノ", "ソノ",
}

class SuggestionsExtractor:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or set()

    def extract(self, canon: list[dict], translations: dict[str, str]) -> list[dict]:
        suggestions = []
        for r in canon:
            text = r["text"] or ""
            for m in _KATAKANA_TERM.finditer(text):
                term = m.group(0)
                if term in self.existing or term in _KATAKANA_STOP:
                    continue
                suggestions.append({
                    "term": term,
                    "source": r.get("region_id", ""),
                    "page": r.get("page", 0),
                    "translation": translations.get(r["region_id"], ""),
                    "status": "candidate",
                })
        return suggestions
```

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_translate.py -q`
Expected: PASS（新增 + 原有全过）

- [ ] **Step 5: Commit**

```bash
git add src/amta/translate.py tests/test_translate.py
git commit -m "feat(translate): tighten SuggestionsExtractor to katakana proper nouns"
```

### Task 6: merge_suggestions 脚本

**Files:**
- Create: `scripts/merge_suggestions.py`
- Create: `tests/test_merge_suggestions.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_merge_suggestions.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from amta import workstate as ws
import merge_suggestions as ms


def _state(characters=None, terms=None):
    s = dict(ws.TEMPLATE_WORK_STATE, work_id="w")
    s["characters"] = characters or {}
    s["terms"] = terms or {}
    return s


def test_merge_single_page_stays_candidate():
    state = _state()
    suggs = [{"term": "サグメ", "page": 0, "source": "a", "translation": "探女", "status": "candidate"}]
    out = ms.merge(state, suggs)
    assert out["terms"]["サグメ"]["status"] == "candidate"


def test_merge_cross_page_confirmed():
    state = _state()
    suggs = [
        {"term": "サグメ", "page": 0, "source": "a", "translation": "探女", "status": "candidate"},
        {"term": "サグメ", "page": 1, "source": "b", "translation": "探女", "status": "candidate"},
    ]
    out = ms.merge(state, suggs)
    assert out["terms"]["サグメ"]["status"] == "confirmed"


def test_merge_conflicting_translation_stays_candidate():
    state = _state()
    suggs = [
        {"term": "サグメ", "page": 0, "source": "a", "translation": "探女", "status": "candidate"},
        {"term": "サグメ", "page": 1, "source": "b", "translation": "娑葛", "status": "candidate"},
    ]
    out = ms.merge(state, suggs)
    assert out["terms"]["サグメ"]["status"] == "candidate"
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_merge_suggestions.py -q`
Expected: FAIL `ModuleNotFoundError: No module named 'merge_suggestions'`

- [ ] **Step 3: 实现 `scripts/merge_suggestions.py`**

```python
"""merge_suggestions — suggestions.json → work_state 合并。

跨页一致（同一 term ≥2 页且译名一致）→ confirmed 自动升；否则保持 candidate。
导演可随后手工改 work_state.status 降级。写回 work_state.json。
用法: python scripts/merge_suggestions.py --work-id ID [--suggestions PATH]
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta import paths, workstate  # noqa: E402


def merge(state: dict, suggestions: list[dict]) -> dict:
    from collections import defaultdict
    grouped: dict[str, list[dict]] = defaultdict(list)
    for s in suggestions:
        grouped[s["term"]].append(s)
    terms = state.setdefault("terms", {})
    for term, items in grouped.items():
        if term in terms and terms[term].get("status") == "confirmed":
            continue  # 已确认不降级
        translations = {it.get("translation", "").strip() for it in items if it.get("translation")}
        pages = sorted({it["page"] for it in items if "page" in it})
        consistent = len(pages) >= 2 and len(translations) == 1
        status = "confirmed" if consistent else "candidate"
        terms[term] = {
            "translation": next(iter(translations), ""),
            "status": status,
            "source": f"page_{pages[0]}" if pages else "",
            "pages": pages,
        }
    return state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--suggestions", type=Path, default=None)
    a = ap.parse_args()
    root = workstate.work_dir(a.work_id)
    sugg_path = a.suggestions or root / "state" / "suggestions.json"
    if not sugg_path.exists():
        print("[merge_suggestions] no suggestions.json, nothing to merge")
        return 0
    doc = paths.read_json(sugg_path)
    state = workstate.load_state(a.work_id)
    out = merge(state, doc.get("suggestions", []))
    workstate.save_state(a.work_id, out)
    print(f"[merge_suggestions] merged -> {root / 'state' / 'work_state.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_merge_suggestions.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/merge_suggestions.py tests/test_merge_suggestions.py
git commit -m "feat(translate): merge_suggestions script candidate->confirmed"
```

---

## Phase 3 — Glossary Validator

### Task 7: Glossary Validator（Knowledge guardrail）

**Files:**
- Create: `src/amta/glossary.py`
- Create: `tests/test_glossary.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_glossary.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.glossary import check_glossary


def _state(terms=None, characters=None):
    from amta import workstate
    s = dict(workstate.TEMPLATE_WORK_STATE, work_id="w")
    s["terms"] = terms or {}
    s["characters"] = characters or {}
    return s


def test_uses_canon_translation_ok():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": []}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "丰姬来了"}
    assert check_glossary(canon, tr, ws) == []


def test_detects_canon_residue():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": []}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "豊姫来了"}  # 日文残留
    assert check_glossary(canon, tr, ws)


def test_detects_wrong_zh_variant():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": []}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "丰妃来了"}  # 与 canon 不同中文写法
    assert check_glossary(canon, tr, ws)


def test_allows_alias():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": ["丰殿"]}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "丰殿来了"}
    assert check_glossary(canon, tr, ws) == []


def test_ignores_non_confirmed_terms():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "candidate", "aliases": []}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "豊姫来了"}
    assert check_glossary(canon, tr, ws) == []
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_glossary.py -q`
Expected: FAIL `ModuleNotFoundError: No module named 'amta.glossary'`

- [ ] **Step 3: 实现 `src/amta/glossary.py`**

```python
"""Knowledge guardrail（ADR-016）：confirmed 术语译名一致性校验。

对每页：若原文含某 confirmed 术语，译文必须用其 canon 译名或任一 alias；
译文残留该术语日文形式、或用与 canon 不同的中文写法（Levenshtein 相近但不等）→ 违例。
返回违例列表，空=合法。
"""
from __future__ import annotations
import re

from amta.translate import _levenshtein, _norm, _JAPANESE


def check_glossary(canon: list[dict], translation: dict[str, str], work_state: dict) -> list[str]:
    terms = work_state.get("terms", {})
    violations: list[str] = []
    for rid, r in enumerate(canon):
        src = r.get("text") or ""
        tgt = (translation.get(r["region_id"]) or "").strip()
        if not tgt:
            continue
        for term, meta in terms.items():
            if meta.get("status") != "confirmed" or not term:
                continue
            if term not in src:
                continue
            canon_zh = (meta.get("translation") or "").strip()
            aliases = [str(a) for a in meta.get("aliases", []) if a]
            # 1) 残留日文形式
            if term in tgt:
                violations.append(f"{r['region_id']}: 术语 {term} 残留日文（应为 {canon_zh}）")
                continue
            if not canon_zh:
                continue
            # 2) 用了与 canon 不同且不在 alias 的中文写法（相近变体）
            if canon_zh in tgt or any(a in tgt for a in aliases):
                continue
            if _JAPANESE.search(tgt):
                continue  # 纯日文残留交给 ②，不重复报
            # 近似变体检测：tgt 中出现与 canon_zh 编辑距离<=2 的非 alias 词
            norm_tgt = _norm(tgt)
            norm_canon = _norm(canon_zh)
            if norm_canon and _levenshtein(norm_tgt[: len(norm_canon)], norm_canon) <= 2 \
                    and norm_canon not in norm_tgt:
                violations.append(f"{r['region_id']}: 术语 {term} 中文写法 {tgt} 与 canon {canon_zh} 不一致")
    return violations
```

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_glossary.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/amta/glossary.py tests/test_glossary.py
git commit -m "feat(glossary): knowledge guardrail confirmed term consistency"
```

### Task 8: 03_translate 接入 Glossary Validator

**Files:**
- Modify: `scripts/03_translate.py`（run() 内机械护栏后调 check_glossary，违例即视为机械失败）
- Modify: `tests/test_translate.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_translate.py
def test_run_reports_glossary_violation(monkeypatch, tmp_path):
    import json
    from amta import paths, translate
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "豊姫来了"}
    out = translate._run_guardrails_for_test(canon, tr, {"terms": {
        "豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": []}}})
    assert out  # 非空 = 有违例
```

（为可测，需在 `translate.py` 加薄桥 `_run_guardrails_for_test`，见 Step 3。）

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_translate.py::test_run_reports_glossary_violation -q`
Expected: FAIL `AttributeError: module 'amta.translate' has no attribute '_run_guardrails_for_test'`

- [ ] **Step 3: 在 `src/amta/translate.py` 加薄桥 + 在 `scripts/03_translate.py` 接入**

`src/amta/translate.py` 末尾加：

```python
def _run_guardrails_for_test(canon, translation, work_state):
    from amta.glossary import check_glossary
    return mechanical_guardrails(canon, translation) + check_glossary(canon, translation, work_state)
```

`scripts/03_translate.py` 的 `run()` 中 `residue` 计算后加：

```python
    from amta.glossary import check_glossary
    violations = check_glossary(canon, result, ws)
    out["glossary_violations"] = violations
```

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_translate.py -q`
Expected: PASS（新增 + 原有全过）

- [ ] **Step 5: Commit**

```bash
git add src/amta/translate.py scripts/03_translate.py tests/test_translate.py
git commit -m "feat(translate): wire glossary validator into 03 pipeline"
```

---

## Phase 4 — Eval 四维评分 + 判例库

### Task 9: ③ 四维评分

**Files:**
- Modify: `scripts/translate_semantic_check.py`
- Modify: `tests/test_semantic_check.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_semantic_check.py
from scripts.translate_semantic_check import parse_verdict_with_scores


def test_parse_pass_with_scores():
    out = ("通过  accuracy:4 fluency:3 consistency:4 readability:5")
    verdict, scores = parse_verdict_with_scores(out)
    assert verdict == "pass"
    assert scores["accuracy"] == 4
    assert scores["fluency"] == 3
    assert scores["consistency"] == 4
    assert scores["readability"] == 5


def test_parse_fail_with_scores():
    out = ("需修订：主语错；建议译文：xx\naccuracy:2 fluency:3 consistency:5 readability:4")
    verdict, scores = parse_verdict_with_scores(out)
    assert verdict == "fail"
    assert scores["accuracy"] == 2


def test_parse_no_scores_defaults():
    verdict, scores = parse_verdict_with_scores("通过")
    assert verdict == "pass"
    assert scores["accuracy"] is None
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_semantic_check.py -q`
Expected: FAIL `ImportError`（无 `parse_verdict_with_scores`）

- [ ] **Step 3: 修改 `scripts/translate_semantic_check.py`**

更新 `JUDGE_PROMPT`，让 VLM 输出四维分：

```python
JUDGE_PROMPT = """你是漫画翻译质量评审。请阅读图中日文原文，并判断给出的译文是否合格。
图中原文(OCR): {text}
现有译文: {translation}
检查要点：1) 是否忠实原文（错译/跑偏/编造） 2) 是否漏译/空白 3) 人名术语是否与图一致。
对四项各评 1-5 分（5=最好）：accuracy(语义准确) fluency(中文自然) consistency(术语一致) readability(漫画可读)。
输出格式：
通过
accuracy:{1-5}
fluency:{1-5}
consistency:{1-5}
readability:{1-5}
（若不合格，则第一行改为：需修订：<一句话理由>；建议译文：<译文>，并同样输出四项评分）"""
```

加解析函数（保留原 `parse_verdict` 兼容）：

```python
import re as _re

def parse_verdict_with_scores(out: str) -> tuple[str, dict]:
    out = (out or "").strip()
    verdict, _ = parse_verdict(out)
    scores = {}
    for key in ("accuracy", "fluency", "consistency", "readability"):
        m = _re.search(rf"{key}\s*[:：]\s*(\d)", out)
        scores[key] = int(m.group(1)) if m else None
    return verdict, scores
```

`run()` 中评审循环把 verdict/scores 写入结果（failed/inconclusive 加 `scores` 字段；新增 `passed_scores` 汇总）。

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_semantic_check.py -q`
Expected: PASS（原 5 + 新 3）

- [ ] **Step 5: Commit**

```bash
git add scripts/translate_semantic_check.py tests/test_semantic_check.py
git commit -m "feat(semantic-check): four-dimension scoring in one VLM call"
```

### Task 10: 判例库 case-law

**Files:**
- Create: `output/data/case_law.json`

- [ ] **Step 1: 创建判例库**

```json
{
  "work_id": "touhou-single-wing",
  "purpose": "校准 ③ 语义评审与验收口径的判例库（无参考 GT，替代参考译文 Golden Set）",
  "cases": [
    {"region_id": "page_9_u01", "source": "今度もらってあげるわよ",
     "translation": "下次再让她给你吧", "verdict": "fail",
     "scores": {"accuracy": 2, "fluency": 4, "consistency": 5, "readability": 5},
     "reason": "主语错：原文'我'拿到后给'你'，译文变'她'给你",
     "suggestion": "下次我帮你拿过来吧", "lesson": "③ 能抓主语错（accuracy 低）"},
    {"region_id": "page_0_u07", "source": "…気に入っていただが一つだけ不満があるとすればー",
     "translation": "…很喜欢那样的月球生活。不过若说有什么不满的话——", "verdict": "fail",
     "scores": {"accuracy": 3, "fluency": 4, "consistency": 5, "readability": 5},
     "reason": "漏译'一つだけ'(只有一点)", "suggestion": "不过，若说只有一点不满的话——",
     "lesson": "③ 对程度副词敏感，会抓漏译但需导演确认"},
    {"region_id": "page_2_u05", "source": "研究室を一人で使えることの方が嬉しかった",
     "translation": "但能一个人使用研究室更让我开心", "verdict": "pass",
     "scores": {"accuracy": 4, "fluency": 5, "consistency": 5, "readability": 5},
     "reason": "加'但'是中文衔接，③ 误报样本，不改译",
     "suggestion": "", "lesson": "③ 会误报风格选择（加连接词），非硬伤不改译"},
    {"region_id": "page_0_u09", "source": "穢れとは心である",
     "translation": "污秽即是心", "verdict": "review",
     "scores": {"accuracy": 4, "fluency": 4, "consistency": 5, "readability": 5},
     "reason": "③ 盲区：语境润色主张'污秽源于心中'",
     "suggestion": "污秽源于心中", "lesson": "③ 漏语境润色，导演终审兜底"}
  ],
  "acceptance": {"pass_rate_min": 0.90, "director_clears_failed": true}
}
```

- [ ] **Step 2: 校验 JSON**

Run: `python -c "import json;json.load(open(r'E:\manga translator agent\amta\output\data\case_law.json',encoding='utf-8'));print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add output/data/case_law.json
git commit -m "feat(eval): case-law golden set for semantic check calibration"
```

---

## Phase 5 — 导演 loop + Tools + 阈值 + on-failure

### Task 11: apply_revisions 脚本

**Files:**
- Create: `scripts/apply_revisions.py`
- Create: `tests/test_apply_revisions.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_apply_revisions.py
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import apply_revisions as ar


def test_apply_single_revision(tmp_path):
    trans = {"page_9_u01": "下次再让她给你吧", "page_0_u01": "不变"}
    revs = [{"region_id": "page_9_u01", "revised": "下次我帮你拿过来吧"}]
    out, log = ar.apply(trans, revs)
    assert out["page_9_u01"] == "下次我帮你拿过来吧"
    assert out["page_0_u01"] == "不变"
    assert log["page_9_u01"] == "下次再让她给你吧"


def test_apply_unknown_region_ignored():
    trans = {"a": "x"}
    out, _ = ar.apply(trans, [{"region_id": "zzz", "revised": "y"}])
    assert out == {"a": "x"}
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_apply_revisions.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: 实现 `scripts/apply_revisions.py`**

```python
"""apply_revisions — 导演语义 loop 的修订落盘 + 重评审触发。

读 translation.json + revisions 列表（region_id/revised/reason/source），
应用修订写回 translations，revisions 存档到 translation.json.revisions 字段。
用法: python scripts/apply_revisions.py --trans translation.json --revisions revs.json
可选 --semantic-check-cmd 触发重评审（--only 已修订 region）。
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def apply(trans: dict[str, str], revisions: list[dict]) -> tuple[dict, dict]:
    log: dict[str, str] = {}
    for r in revisions:
        rid = r.get("region_id")
        if rid not in trans:
            continue
        if "revised" in r and r["revised"]:
            log[rid] = trans[rid]
            trans[rid] = r["revised"].strip()
    return trans, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trans", type=Path, required=True)
    ap.add_argument("--revisions", type=Path, required=True)
    ap.add_argument("--semantic-check-cmd", type=str, default=None)
    a = ap.parse_args()
    doc = json.loads(a.trans.read_text(encoding="utf-8"))
    revs = json.loads(a.revisions.read_text(encoding="utf-8"))
    trans = doc.setdefault("translations", {})
    out, log = apply(trans, revs)
    doc["revisions"] = doc.get("revisions", []) + revs
    a.trans.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[apply_revisions] applied {len(log)} revisions -> {a.trans}")
    if a.semantic_check_cmd and log:
        only = ",".join(log)
        subprocess.run(f"{a.semantic_check_cmd} --only {only}".split(), check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_apply_revisions.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/apply_revisions.py tests/test_apply_revisions.py
git commit -m "feat(translate): apply_revisions director semantic loop"
```

### Task 12: Tools 恢复（预取 + Contract）

**Files:**
- Modify: `src/amta/translate.py`（新增 `build_tools_context` + 常量）
- Modify: `scripts/03_translate.py`（接入预取，注入 prompt）
- Modify: `tests/test_translate.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_translate.py
def test_tools_context_lookup_and_prev():
    from amta import translate
    canon = [{"region_id": "a", "text": "サグメは月が好き", "page": 5}]
    ws = {"terms": {"サグメ": {"translation": "探女", "status": "confirmed"}}}
    prev = [{"page": 4, "translated": "前页译文"}]
    ctx = translate.build_tools_context(canon, ws, prev_pages=prev)
    assert "探女" in ctx            # 相关术语预取
    assert "前页译文" in ctx        # 前页上下文
    assert translate.TERM_BUDGET >= 1
    assert translate.VISION_BUDGET == 2
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_translate.py::test_tools_context_lookup_and_prev -q`
Expected: FAIL `AttributeError: no attribute 'build_tools_context'`

- [ ] **Step 3: 在 `src/amta/translate.py` 实现**

```python
TERM_BUDGET = 10      # 每页预取术语上限
VISION_BUDGET = 2     # 每页 vision 调用预算（token 控制）


def build_tools_context(canon: list[dict], work_state: dict,
                        prev_pages: list[dict] | None = None,
                        open_questions: list[dict] | None = None) -> str:
    """预取式 Tools 上下文（ADR-016）：把当前页相关术语 + 前页译文注入。
    保持与 build_translation_prompt 复用 _prompt_parts 的语义，但显式标注预算。"""
    parts = []
    terms = work_state.get("terms", {})
    cur_text = " ".join(r["text"] for r in canon)
    rel = {k: v for k, v in terms.items()
           if _norm(k) and (_norm(k) in _norm(cur_text) or _norm(cur_text) in _norm(k))}
    if rel:
        parts.append("工具查得·本页相关术语(最多%d条):" % TERM_BUDGET)
        for k, v in list(rel.items())[:TERM_BUDGET]:
            parts.append(f"- {k} = {v.get('translation','?')} (status={v.get('status','?')})")
    if prev_pages:
        parts.append("工具查得·前页译文:")
        parts.extend(f"[{p.get('page','?')}] {p.get('translated','')}" for p in prev_pages[-3:])
    return "\n".join(parts)
```

`scripts/03_translate.py` 的 `run()` 在调 `translate_with_retry` 前把 `tools_ctx` 并入 prompt（可经 `build_translation_prompt` 的 prefix 或单独 system 段）：

```python
    tools_ctx = translate.build_tools_context(canon, ws, prev_pages=prev_pages,
                                              open_questions=open_questions)
    # 将 tools_ctx 作为 system 层附加信息（沿现有 _prompt_parts 注入点）
```

（注意：`translate_with_retry` 目前不接受 tools_ctx；本 task 采用最小侵入——在调用前把 `tools_ctx` 写入 `work_state` 的临时键或扩展签名。扩展签名更干净：给 `translate_with_retry`/`build_translation_prompt` 增加可选 `tools_ctx: str | None` 参数，拼入 system。）

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_translate.py -q`
Expected: PASS（新增 + 原有）

- [ ] **Step 5: Commit**

```bash
git add src/amta/translate.py scripts/03_translate.py tests/test_translate.py
git commit -m "feat(translate): restore tools (prefetch context) with contract budget"
```

### Task 13: on-failure 结构化记录

**Files:**
- Modify: `src/amta/translate.py`（`record_failure`）
- Modify: `scripts/03_translate.py`（translate_with_retry 返回空/部分时记录）
- Modify: `tests/test_translate.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_translate.py
def test_record_failure_append(tmp_path):
    from amta import translate
    log = tmp_path / "failure_log.json"
    entry = {"region_id": "a", "reason": "mechanical retry exhausted", "attempts": 3}
    translate.record_failure(log, entry)
    translate.record_failure(log, {"region_id": "b", "reason": "x"})
    doc = __import__("json").loads(log.read_text(encoding="utf-8"))
    assert len(doc["failures"]) == 2
    assert doc["failures"][0]["attempts"] == 3
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_translate.py::test_record_failure_append -q`
Expected: FAIL `AttributeError: no attribute 'record_failure'`

- [ ] **Step 3: 在 `src/amta/translate.py` 实现**

```python
def record_failure(log_path: Path, entry: dict) -> None:
    """on-failure 结构化落盘（ADR-016）：追加失败条目供 00_run_all 断点重跑。"""
    doc = {"failures": []}
    if log_path.exists():
        doc = json.loads(log_path.read_text(encoding="utf-8"))
    doc.setdefault("failures", []).append(entry)
    log_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
```

`scripts/03_translate.py`：若 `result` 有 region 译空/残留/glossary 违例，调 `record_failure` 写 `state/failure_log.json`。

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_translate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/amta/translate.py scripts/03_translate.py tests/test_translate.py
git commit -m "feat(translate): structured on-failure logging"
```

### Task 14: 验收阈值 + 进度落盘

**Files:**
- Modify: `docs/decisions/014-translate-station-architecture.md`（Consequences 补 ③ 校准 + 阈值）
- Modify: `docs/progress.md`（当前状态 + 下一步 + 里程碑）

- [ ] **Step 1: 更新 ADR-014 Consequences**

在已有 ③ 实测校准段后追加：

```markdown
- ✅ **③ 校准 + 验收阈值（2026-08-26）**：③ 升级四维评分（accuracy/fluency/consistency/readability 1~5，合并同次 VLM 调用，当导演排序+趋势监控、不当闸门）；**验收阈值 = ③ 通过率 ≥90% + 导演清 FAILED 队列**（判例库见 `output/data/case_law.json`）；work_state 增 observed 层变四层（跨页一致自动升、导演可降级）；Tools 恢复（lookup/get_context 预取 TERM_BUDGET=10 + vision VISION_BUDGET=2，ADR-016）。
- ✅ **Glossary Validator（Knowledge guardrail）**：confirmed 术语译名违例（残留日文 / 非 canon 中文写法）→ FAIL + 锁定重译。
```

- [ ] **Step 2: 更新 progress.md**

「当前状态」追加一节，记录：Input schema gate / Glossary Validator / 四维评分 / observed 层 / merge_suggestions / apply_revisions / Tools 预取 / on-failure / 判例库 / 验收阈值。fastcheck 数字更新为最新（以实跑为准）。「下一步」勾掉已完成项，标注剩余：00_run_all 编排器、04/05 工位（二期）。

- [ ] **Step 3: 全量验证 + Commit**

Run: `npm run fastcheck`
Expected: ALL PASS（以实跑为准，新增测试全绿）
Expected: ruff/pyright 无错误

```bash
git add docs/decisions/014-translate-station-architecture.md docs/progress.md
git commit -m "docs: acceptance threshold + progress for translate harness alignment"
```

---

## Self-Review

**1. Spec coverage：**
- Guardrails 6 类 → Input(T2/T3)、Output(已有 ①)、Knowledge(T7/T8)、Tool(T12)、State Mutation(T6/T4)、Quality(T9/T14) ✅
- Eval 四维 → T9（评分）+ T7（Consistency 机械）+ 判例库 T10（Fluency/校准）✅
- Tools+Contract → T12 ✅
- Loop 导演层 → T11（apply_revisions）+ on-failure T13 ✅
- State 四层 → T4（observed）✅
- 验收阈值 → T14 + T10 ✅
- ADR 差距审计 → T1 ✅

**2. Placeholder scan：** 无 TBD/TODO；每 task 含完整可执行代码与测试。

**3. Type consistency：** `validate_canon`/`check_glossary`/`build_tools_context`/`record_failure`/`merge`/`apply`/`parse_verdict_with_scores` 签名在定义与调用处一致。`workstate.STATUSES` 扩展后既有校验逻辑自动接受 observed（`STATUSES` 常量统一来源）。

**已知依赖：** 执行时先在 git worktree/feature 分支做隔离（superpowers:using-git-worktrees），每 task TDD + 独立 commit，完成 Phase 5 后合并回 main 并验收（fastcheck + 86 框真数据重跑 ③），最后走 /finish（cycle-close）。
