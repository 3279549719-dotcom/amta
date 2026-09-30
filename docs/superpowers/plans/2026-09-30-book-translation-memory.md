# 书内翻译记忆 + 有界生成—验证—修复闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一本书内第一次做出的翻译决定被记住并强制复用到之后任何出现该表达的页面，并让"修复后仍是日文残留"的页面以机器可读的低置信度落盘而不是静默报 `ok`。

**Architecture:** 记忆挂在已有的 `workspace/<work-id>/state/work_state.json` 上，新增一个顶层键 `decisions`，不新建文件、不新建 store、不新建 CLI、不新增用户可见配置项。检索**不按页距**，而是拿本页 OCR 文本去已记录的表达里查；命中项作为"必须使用以下译名"注入。翻译调用同时返回本页新做的书内决定。残留非空时把残留清单回填、**只重问一次**；仍残留则写出 `low_confidence` 并继续出图（阶段仍 `ok`，不阻塞流水线）。最后把 `work_state.json` 纳入 translate 阶段的 fingerprint，修掉"改记忆后缓存照命中"这个已证实的活 bug。

**Tech Stack:** Python 3.12, pytest, ruff, pyright, 现有 AMTA orchestrator/stage registry/artifact 契约

**设计依据:** `docs/superpowers/specs/2026-09-30-book-translation-memory-design.md`

**已确认的决策（不要重新讨论）:**
- 只在 `work_state.json` 加键，**不新建** `translation_memory.json`
- 一次修复，**无分层、无升级到整页**
- **不新增**数值置信度阈值；`evidence.match` 只有 `"exact"` / `"model_judged"` 两值
- **不新增**页级状态枚举；低置信度 = `low_confidence` 数组非空
- **不写**乱序调和器、**不接** `suggestions.py`、**不删** 3 页上下文窗口
- 验收断言**机制**（第 8 页复用第 3 页的决定），**不断言**具体词 `迷幻菇`/`成瘾菇`
- **不修** `contains_japanese` 对 `・`/`ー` 的假阳性（方向相反的误报，记为已知约束）

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `src/amta/common/workstate.py` | 记忆的**唯一**归属：schema + 纯检索函数 + 幂等写回 | 修改 |
| `src/amta/translation/translate.py` | LLM 输出契约（译文 + 本页新决定）+ 一次修复调用 | 修改 |
| `src/amta/translation/stage3_minimal.py` | 编排：检索 → 注入 → 翻译 → 残留 → 修复 → 落盘 | 修改 |
| `src/amta/stores/artifacts.py` | `TranslationArtifact` 加 `low_confidence` / `memory_conflict` | 修改 |
| `src/amta/orchestrator/pipeline.py` | `_stage_input_files` 把 `work_state.json` 纳入 translate 输入 | 修改 |
| `src/amta/orchestrator/registry.py` | translate 的 `code_files` 补上新引入的模块 | 修改 |
| `src/amta/orchestrator/quality_audit.py` | 低置信度计入 `PageFlags`，进红榜 | 修改 |
| `tests/test_book_translation_memory.py` | 新增：记忆层全量测试 | 新建 |
| `tests/test_translate_repair.py` | 新增：一次修复 + 低置信度分支 | 新建 |
| `tests/test_stage3_minimal.py` | **只新增**两个测试（决定注入 / 不跨书串味）；既有断言一律不动 | 修改（仅追加） |
| `tests/test_workstate.py` | 新增 `validate_decisions` 断言 | 修改（仅追加） |
| `tests/test_artifact_cache.py` | 新增：`work_state.json` 触发 translate 失效 | 修改（仅追加） |
| `tests/test_quality_audit.py` | 新增：低置信度进红榜 | 修改（仅追加） |

**命令约定：** 所有 Python 走 `uv run python`（系统 Python 无依赖）。

---

### Task 1: 先写能复现缺陷的红测试（任务书硬要求：先红后绿）

**Files:**
- Create: `tests/test_book_translation_memory.py`
- Create: `tests/test_translate_repair.py`

- [ ] **Step 1: 写记忆层红测试**

创建 `tests/test_book_translation_memory.py`：

```python
"""书内翻译记忆：跨页检索、证据留痕、幂等、修订不丢证据。

这些测试在实现前必须全部失败（AttributeError / ImportError）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.common import workstate


def _ws(tmp_path, monkeypatch):
    """把 WORKSPACE 重定向到 tmp，避免污染中央 workspace/。"""
    monkeypatch.setattr(workstate, "WORKSPACE", tmp_path)
    workstate.init_workspace("w1")
    return tmp_path


def test_record_creates_tentative_decision_with_evidence(tmp_path, monkeypatch):
    _ws(tmp_path, monkeypatch)
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    d = workstate.load_decisions("w1")
    assert "ヤミツキ茸" in d
    e = d["ヤミツキ茸"]
    assert e["translation"] == "成瘾菇"
    assert e["status"] == "tentative"
    assert e["source"] == "translate"
    assert e["evidence"] == [
        {"page": 2, "region_id": "r05", "surface_seen": "ヤミツキ茸", "match": "exact"}
    ]


def test_retrieval_ignores_page_distance(tmp_path, monkeypatch):
    """第 3 页记的决定，第 8 页出现时必须命中——页距不存在。"""
    _ws(tmp_path, monkeypatch)
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    page8 = ["そろそろ消費者も現状のヤミツキ茸の合有量に物足りなさがくる頃だろう?"]
    hits = workstate.relevant_decisions("w1", page8)
    assert "ヤミツキ茸" in hits
    assert hits["ヤミツキ茸"]["translation"] == "成瘾菇"


def test_evidence_append_is_idempotent(tmp_path, monkeypatch):
    """同一 (surface, page, region_id) 跑两次，证据不得重复追加。"""
    _ws(tmp_path, monkeypatch)
    ev = {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
          "page": 2, "region_id": "r05", "match": "exact"}
    workstate.record_decisions("w1", [ev])
    workstate.record_decisions("w1", [ev])
    assert len(workstate.load_decisions("w1")["ヤミツキ茸"]["evidence"]) == 1


def test_revision_keeps_old_evidence(tmp_path, monkeypatch):
    _ws(tmp_path, monkeypatch)
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "迷幻菇", "surface_seen": "ヤミツキ茸",
         "page": 7, "region_id": "r00", "match": "exact"},
    ])
    e = workstate.load_decisions("w1")["ヤミツキ茸"]
    assert e["translation"] == "迷幻菇"          # 新证据生效
    assert len(e["evidence"]) == 2               # 旧证据不丢
    assert e["evidence"][0]["page"] == 2


def test_model_judged_variant_records_alias(tmp_path, monkeypatch):
    _ws(tmp_path, monkeypatch)
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ",
         "page": 7, "region_id": "r04", "match": "model_judged"},
    ])
    e = workstate.load_decisions("w1")["ヤミツキ茸"]
    assert "ヤミツキ" in e["aliases"]
    assert {x["match"] for x in e["evidence"]} == {"exact", "model_judged"}


def test_terms_take_precedence_and_conflict_is_surfaced(tmp_path, monkeypatch):
    """terms（人工/词典先验）优先于 decisions；冲突不覆盖、要被看见。"""
    _ws(tmp_path, monkeypatch)
    st = workstate.load_state("w1")
    st.setdefault("terms", {})["ヤミツキ茸"] = {
        "translation": "迷幻菇", "status": "confirmed", "source": "pre_scan"}
    workstate.save_state("w1", st)
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    hits, conflicts = workstate.relevant_decisions_with_conflicts("w1", ["ヤミツキ茸が"])
    assert hits["ヤミツキ茸"]["translation"] == "迷幻菇"     # terms 优先
    assert conflicts and conflicts[0]["surface"] == "ヤミツキ茸"


def test_corrupt_state_degrades_to_empty_without_raising(tmp_path, monkeypatch):
    _ws(tmp_path, monkeypatch)
    p = tmp_path / "w1" / "state" / "work_state.json"
    p.write_text("{ this is not json", encoding="utf-8")
    assert workstate.load_decisions("w1") == {}
```

- [ ] **Step 2: 写修复/低置信度红测试**

创建 `tests/test_translate_repair.py`：

```python
"""残留 → 一次修复 → 低置信度分支。全部用假 LLM，不烧 API。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.translation.stage3_minimal import translate_page_minimal

CANON = [
    {"region_id": "r00", "baberu_text": "殺虫剤も虫の抵抗に合わせて年々強力になるらしいぞ?",
     "page": 7, "vlm_status": "ok"},
    {"region_id": "r01", "baberu_text": "そろそろ消費者も現状のヤミツキ茸の合有量に物足りなさがくる頃だろう?",
     "page": 7, "vlm_status": "ok"},
]


def _state(tmp_path):
    d = tmp_path / "state"
    (d / "artifacts").mkdir(parents=True, exist_ok=True)
    return d


def test_residue_triggers_exactly_one_repair(tmp_path, monkeypatch):
    """第一次吐残留 → 恰好再问一次；第二次干净 → 无 low_confidence。"""
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        if len(calls) == 1:
            return '{"translations": ["杀虫剂也会随虫子抗药性变强哦?", "ヤミツキ茸的含有量"]}'
        return '{"translations": ["杀虫剂也会随虫子抗药性变强哦?", "成瘾菇的含有量"]}'

    out = translate_page_minimal("w1", CANON, state_dir=_state(tmp_path),
                                 page="page_7", llm_text=fake_llm)
    assert len(calls) == 2, "残留必须恰好触发一次修复调用"
    assert out["residue"] == []
    assert out["low_confidence"] == []
    assert "ヤミツキ茸" not in out["translations"]["r01"]


def test_residue_after_one_repair_sets_low_confidence(tmp_path, monkeypatch):
    """两次都残留 → 最佳译文继续出图 + 机器可读低置信度；不生成第三次调用。"""
    calls = []

    def always_residue(messages):
        calls.append(messages)
        return '{"translations": ["杀虫剂也会随虫子抗药性变强哦?", "ヤミツキ茸的含有量"]}'

    out = translate_page_minimal("w1", CANON, state_dir=_state(tmp_path),
                                 page="page_7", llm_text=always_residue)
    assert len(calls) == 2, "一次修复，不得无限重试"
    assert out["residue"], "修复后仍残留 → residue 非空"
    lc = out["low_confidence"]
    assert lc and lc[0]["region_id"] == "r01"
    assert lc[0]["reason"] == "residue_after_one_repair"
    assert "ヤミツキ茸" in out["translations"]["r01"], "仍输出最佳译文，不丢内容"


def test_clean_page_makes_only_one_call(tmp_path, monkeypatch):
    calls = []

    def clean(messages):
        calls.append(messages)
        return '{"translations": ["杀虫剂也会随虫子抗药性变强哦?", "成瘾菇的含有量"],' \
               ' "decisions": [{"surface": "ヤミツキ茸", "translation": "成瘾菇",' \
               ' "surface_seen": "ヤミツキ茸"}]}'

    out = translate_page_minimal("w1", CANON, state_dir=_state(tmp_path),
                                 page="page_7", llm_text=clean)
    assert len(calls) == 1, "干净页面必须仍然只有一次调用"
    assert out["low_confidence"] == []


def test_decisions_returned_by_translate_are_persisted(tmp_path, monkeypatch):
    from amta.common import workstate

    def with_decision(messages):
        return '{"translations": ["a", "b"], "decisions": [' \
               '{"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸"}]}'

    st = _state(tmp_path)
    monkeypatch.setattr(workstate, "WORKSPACE", tmp_path)
    translate_page_minimal("w1", CANON, state_dir=st, page="page_7", llm_text=with_decision)
    d = workstate.load_decisions("w1")
    assert d["ヤミツキ茸"]["translation"] == "成瘾菇"
    assert d["ヤミツキ茸"]["evidence"][0]["page"] == 7
```

- [ ] **Step 3: 运行，确认全红**

Run:
```powershell
uv run python -m pytest tests/test_book_translation_memory.py tests/test_translate_repair.py -q
```
Expected: 大量 FAIL / ERROR。`workstate` 没有 `record_decisions` / `load_decisions` / `relevant_decisions` / `relevant_decisions_with_conflicts`；翻译产物没有 `low_confidence` 键。**记录下这段红输出**（任务书要求"先红后绿"有证据）。

- [ ] **Step 4: 提交红测试**

```powershell
git add tests/test_book_translation_memory.py tests/test_translate_repair.py
git commit -m "test(translate): reproduce cross-page decision loss and silent residue in red"
```

---

### Task 2: 记忆层（`workstate.py`）

**Files:**
- Modify: `src/amta/common/workstate.py`
- Test: `tests/test_book_translation_memory.py`

- [ ] **Step 1: 在 `TEMPLATE_WORK_STATE` 加 `decisions` 键**

修改 `src/amta/common/workstate.py:46-54`，把模板改成：

```python
TEMPLATE_WORK_STATE: dict[str, Any] = {
    "work_id": "",
    "updated_page": 0,
    "characters": {},   # {名: {status, confidence?, source, aliases, role, notes}}
    "relationships": [],  # [{from, to, kind, status, source}]
    "terms": {},        # {术语: {translation, status, source}} — pre_scan/manual 锁定
    # 书内翻译决定（LLM 首次做出的译名）。与 terms 分离：terms 是词典/人工先验，
    # decisions 是模型暂定决定；检索时 terms 优先。
    "decisions": {},    # {norm(surface): {surface, translation, aliases, evidence, source, status, updated_page}}
    "current_scene": {"page": None, "location": None, "present": []},
    "recent_context": [],  # 最近 N 条对白 [{page, region, speaker, target, text}]
}
```

- [ ] **Step 2: 加记忆读取与检索函数**

在 `src/amta/common/workstate.py` 末尾（`validate_state` 之后）追加：

```python
# ---------------------------------------------------------------------------
# 书内翻译记忆（decisions）
# ---------------------------------------------------------------------------
# 设计约束（见 docs/superpowers/specs/2026-09-30-book-translation-memory-design.md）：
# - 不新建 store：记忆挂在已有的 work_state.json 上
# - 不设数值置信度阈值：evidence.match 只有 "exact" / "model_judged"
# - 不做模糊匹配：规范化后相等算命中，其余交给模型在本页判断
# - 幂等键 = (page, region_id)；重跑不得重复追加证据

DECISION_STATUSES = ("tentative", "confirmed")
MATCH_KINDS = ("exact", "model_judged")


def _decision_key(surface: str) -> str:
    """决定的权威键：规范化后的表面形（去标点/空白，保留假名汉字字母数字）。"""
    from amta.common.metrics import norm
    return norm(surface) or surface


def load_decisions(work_id: str) -> dict[str, Any]:
    """读 work_state.decisions。缺失/损坏 → 空 dict（降级不阻塞翻译）。"""
    try:
        return dict(load_state(work_id).get("decisions") or {})
    except Exception:
        return {}


def record_decisions(work_id: str, records: list[dict]) -> dict[str, Any]:
    """把本页新决定写回 work_state.decisions（幂等）。

    每条 record 需要: surface / translation / page / region_id；
    可选: surface_seen（默认取 surface）/ match（默认 "exact"）。

    - 首次出现 → status="tentative"，evidence=[本条]
    - 再次出现且同 (page, region_id) 已在 evidence 里 → 不追加（幂等）
    - 再次出现且译名不同 → 更新 translation（暂定决定可被新证据修订），旧证据保留
    - surface_seen != surface → 记入 aliases
    """
    state = load_state(work_id)
    decisions = state.setdefault("decisions", {})
    for rec in records:
        surface = (rec.get("surface") or "").strip()
        translation = (rec.get("translation") or "").strip()
        if not surface or not translation:
            continue
        key = _decision_key(surface)
        page = rec.get("page")
        region_id = rec.get("region_id") or ""
        seen = (rec.get("surface_seen") or surface).strip()
        match = rec.get("match") or "exact"
        if match not in MATCH_KINDS:
            match = "exact"

        entry = decisions.get(key)
        if entry is None:
            entry = {
                "surface": surface,
                "translation": translation,
                "aliases": [],
                "evidence": [],
                "source": "translate",
                "status": "tentative",
                "updated_page": page,
            }
            decisions[key] = entry
        else:
            entry["translation"] = translation      # 暂定决定可被新证据修订
            entry["updated_page"] = page
        if seen and seen != entry["surface"] and seen not in entry["aliases"]:
            entry["aliases"].append(seen)
        already = any(e.get("page") == page and e.get("region_id") == region_id
                      for e in entry["evidence"])
        if not already:
            entry["evidence"].append({
                "page": page, "region_id": region_id,
                "surface_seen": seen, "match": match,
            })
    save_state(work_id, state)
    return decisions


def _match_surfaces(decisions: dict, text: str) -> dict[str, dict]:
    """纯函数：哪些已记录的表达出现在 text 里。不做模糊匹配、不看页码。"""
    from amta.common.metrics import norm
    if not text:
        return {}
    ntext = norm(text)
    hits: dict[str, dict] = {}
    for entry in (decisions or {}).values():
        if not isinstance(entry, dict):
            continue
        candidates = [entry.get("surface") or ""] + list(entry.get("aliases") or [])
        for cand in candidates:
            ncand = norm(cand)
            if ncand and ncand in ntext:
                hits[entry.get("surface")] = entry
                break
    return hits


def relevant_decisions(work_id: str, src_texts: list[str]) -> dict[str, Any]:
    """检索：本页原文里出现了哪些已记录的书内表达。与页距无关。"""
    return _match_surfaces(load_decisions(work_id), " ".join(t or "" for t in src_texts))


def relevant_decisions_with_conflicts(
    work_id: str, src_texts: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """检索并解决 terms/decisions 优先级。

    terms（pre_scan/manual 先验）优先于 decisions（模型暂定）。
    同名不同译名 → 返回冲突条目（供产物落盘），**不覆盖任何一方**。
    """
    hits = relevant_decisions(work_id, src_texts)
    terms = load_state(work_id).get("terms", {}) or {}
    ntext = None
    from amta.common.metrics import norm
    ntext = norm(" ".join(t or "" for t in src_texts))

    resolved: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for surface, entry in hits.items():
        nsurf = norm(surface)
        term_entry = None
        for t_surface, t_meta in terms.items():
            if norm(t_surface) and norm(t_surface) in (ntext or ""):
                if norm(t_surface) == nsurf or nsurf in norm(t_surface):
                    term_entry = (t_surface, t_meta)
                    break
        if term_entry is None:
            resolved[surface] = entry
            continue
        t_surface, t_meta = term_entry
        t_trans = (t_meta or {}).get("translation") or (t_meta or {}).get("canon_translation")
        if t_trans and t_trans != entry.get("translation"):
            conflicts.append({
                "surface": surface,
                "terms_surface": t_surface,
                "terms_translation": t_trans,
                "decision_translation": entry.get("translation"),
            })
        resolved[t_surface] = {"surface": t_surface, "translation": t_trans,
                               "aliases": list(entry.get("aliases") or []),
                               "evidence": list(entry.get("evidence") or [])}
    return resolved, conflicts


def validate_decisions(state: dict[str, Any]) -> list[str]:
    """检查 decisions 结构，返回问题列表（空=合法）。"""
    problems: list[str] = []
    for key, entry in (state.get("decisions") or {}).items():
        if not isinstance(entry, dict):
            problems.append(f"decision {key!r} must be a dict")
            continue
        if entry.get("status") not in DECISION_STATUSES:
            problems.append(f"decision {key!r} invalid status {entry.get('status')!r}")
        if not entry.get("translation"):
            problems.append(f"decision {key!r} missing translation")
        if not isinstance(entry.get("evidence"), list):
            problems.append(f"decision {key!r} evidence must be a list")
    return problems
```

- [ ] **Step 3: 运行记忆层测试**

Run:
```powershell
uv run python -m pytest tests/test_book_translation_memory.py -q
```
Expected: 全 PASS（7 个）。若 `test_terms_take_precedence_and_conflict_is_surfaced` 失败，检查 `relevant_decisions_with_conflicts` 的 `nsurf in norm(t_surface)` 分支是否覆盖了 `ヤミツキ茸` 这个用例。

- [ ] **Step 4: 同步既有 workstate 测试并加 validate 断言**

在 `tests/test_workstate.py` 的 schema 断言处补上 `decisions` 键存在，并新增：

```python
def test_validate_decisions_rejects_bad_status(tmp_path, monkeypatch):
    from amta.common import workstate
    monkeypatch.setattr(workstate, "WORKSPACE", tmp_path)
    workstate.init_workspace("w1")
    problems = workstate.validate_decisions(
        {"decisions": {"x": {"status": "bogus", "translation": "y", "evidence": []}}})
    assert any("invalid status" in p for p in problems)
```

- [ ] **Step 5: 运行并提交**

Run:
```powershell
uv run python -m pytest tests/test_workstate.py tests/test_book_translation_memory.py -q
```
Expected: PASS

```powershell
git add src/amta/common/workstate.py tests/test_workstate.py
git commit -m "feat(translate): add per-book translation decision memory to work_state"
```

---

### Task 3: 记忆注入 + 翻译调用返回本页新决定

**Files:**
- Modify: `src/amta/translation/translate.py:101-185`
- Modify: `src/amta/translation/stage3_minimal.py:227-275`
- Test: `tests/test_translate_repair.py`, `tests/test_stage3_minimal.py`

- [ ] **Step 1: 让解析器同时取出译文与新决定**

在 `src/amta/translation/translate.py` 中，`parse_translation_array`（`:101-121`）**保持不变**（既有测试与契约依赖它）。在其后新增：

```python
def parse_decisions(raw: str) -> list[dict]:
    """从同一次回复里取本页新做的书内决定。

    契约：{"translations":[...], "decisions":[{"surface","translation","surface_seen"}]}
    decisions 是可选键；缺失/形状不对 → 返回 []（不报错、不重试）。
    模型自己判断"这算不算一个书内表达"——代码不筛类别、不写正则。
    """
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    raw_decisions = data.get("decisions")
    if not isinstance(raw_decisions, list):
        return []
    out: list[dict] = []
    for item in raw_decisions:
        if not isinstance(item, dict):
            continue
        surface = str(item.get("surface") or "").strip()
        translation = str(item.get("translation") or "").strip()
        if not surface or not translation:
            continue
        out.append({
            "surface": surface,
            "translation": translation,
            "surface_seen": str(item.get("surface_seen") or surface).strip(),
        })
    return out
```

- [ ] **Step 2: 给 `translate_plain` 加"同时回传决定"的兄弟函数（不改既有签名）**

在 `src/amta/translation/translate.py` 的 `translate_plain`（`:124`）之后新增。**不修改 `translate_plain` 本身**，既有 3 个测试保持绿：

```python
def translate_plain_with_decisions(canon: list[dict], llm, *, system_extra: str = "",
                                   context_prefix: str = "",
                                   context_enabled: bool = True) -> tuple[dict[str, str], list[dict], str]:
    """同 translate_plain 的一次调用，但额外回传本页新决定与原始回复。

    返回 (translations, decisions, raw_response)。
    长度不符/解析失败 → translations 全空、decisions 为空（不重试，语义同 translate_plain）。
    """
    if not canon:
        return {}, [], ""
    region_ids = [r["region_id"] for r in canon]
    system = f"{_SYSTEM_PROMPT}\n{system_extra}".strip()
    blocks = [r.get("baberu_text") or r.get("text") or "" for r in canon]
    instr = ('将以下日文漫画内容翻译成中文。'
             '输入为JSON数组，每个元素是一条待翻译文本；数组字符串内的\\n是块内换行，不是条目分隔。'
             '输出JSON对象，唯一键为translations；其值为数组，长度和顺序与输入一致。'
             '漫画口语化表达，句末尽量不要句号。\n'
             '如果本页出现了你首次确定的专有名词、自造词或反复出现的说法，'
             '额外给出 decisions 数组，每项为 {"surface": 原文表达, "translation": 你用的译名}。'
             '没有新表达就省略 decisions。\n')
    cur = instr + json.dumps(blocks, ensure_ascii=False)
    content = f"{context_prefix}\n\n{cur}" if context_enabled and context_prefix else cur
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": content}]
    raw = llm(messages)
    arr = parse_translation_array(raw, len(canon))
    if arr is None:
        return {r["region_id"]: "" for r in canon}, [], raw
    parsed = {rid: arr[i] for i, rid in enumerate(region_ids)}
    if mechanical_guardrails(canon, parsed):
        return {r["region_id"]: "" for r in canon}, [], raw
    return parsed, parse_decisions(raw), raw


def repair_with_residue_hint(canon: list[dict], translations: dict[str, str], llm, *,
                             system_extra: str = "") -> tuple[dict[str, str], list[dict]]:
    """一次有证据的修复：把残留清单回填给模型，只重问一次。

    只问残留的那些 region（其余保持原译文），返回 (更新后的 translations, decisions)。
    仍然残留不是本函数的失败——失败显化由调用方落 low_confidence。
    """
    residual_ids = [r["region_id"] for r in canon
                    if _has_residue(translations.get(r["region_id"], ""))]
    if not residual_ids:
        return dict(translations), []
    batch = [r for r in canon if r["region_id"] in residual_ids]
    region_ids = [r["region_id"] for r in batch]
    blocks = [r.get("baberu_text") or r.get("text") or "" for r in batch]
    system = f"{_SYSTEM_PROMPT}\n{system_extra}".strip()
    instr = ('上一次翻译里，下面这些条目未能翻译成中文，仍含有日文假名：\n'
             + "\n".join(f"- {translations.get(rid, '')}" for rid in region_ids)
             + '\n请重新翻译这些条目，输出JSON对象，唯一键为translations，'
               '其值为数组，长度和顺序与输入一致，全部使用中文字符。\n')
    content = instr + json.dumps(blocks, ensure_ascii=False)
    raw = llm([{"role": "system", "content": system},
               {"role": "user", "content": content}])
    arr = parse_translation_array(raw, len(batch))
    out = dict(translations)
    if arr is not None:
        for i, rid in enumerate(region_ids):
            out[rid] = arr[i]
    return out, parse_decisions(raw)


def _has_residue(text: str) -> bool:
    """与 guards.guardrails 同一判据，避免循环 import。"""
    from amta.common.metrics import contains_japanese
    return contains_japanese(text or "")
```

- [ ] **Step 3: 在 `stage3_minimal.py` 里把决定注入成"必须使用的译名"，并把 conflicts 塞进 ctx**

修改 `src/amta/translation/stage3_minimal.py` 的 `build_prefetch_context`（`:227-274`）。

**先改签名**（`work_id` 必须可选，默认 `None`，否则 `tests/test_stage3_minimal.py:106` / `:123` 两个既有调用会崩）：

```python
def build_prefetch_context(canon: list[dict], work_state: dict,
                           state_dir: Path | None, *,
                           work_id: str | None = None) -> dict[str, Any]:
```

在既有的 `refined` / `system_extra` 计算之后、`context_prefix` 之前，插入书内决定的检索与强制注入：

```python
    # === 书内翻译决定：以原文表达为键检索，命中项作为强制译名 ===
    # 与页距无关（不是"前 N 页"）。terms 优先于 decisions（见 workstate 文档）。
    memory_conflicts: list[dict] = []
    decision_hits: dict = {}
    if work_id:
        src_text = " ".join(r.get("baberu_text") or r.get("text") or "" for r in canon)
        decision_hits, memory_conflicts = workstate.relevant_decisions_with_conflicts(
            work_id, [src_text])
        if decision_hits:
            lines = ["本书内已确定的译名（必须使用，不得改写、不得保留日文）："]
            for _surface, _meta in decision_hits.items():
                if _meta.get("translation"):
                    lines.append(f"- {_surface} → {_meta['translation']}")
            system_parts.append("\n".join(lines))
            system_extra = "\n\n".join(system_parts)
```

然后把返回值扩成：

```python
    return {
        "refined_canon": refined,
        "system_extra": system_extra,
        "context_prefix": context_prefix,
        "memory_conflicts": memory_conflicts,
    }
```

并在 `translate_page_minimal`（`:319`）的调用处加上 `work_id=work_id`：

```python
    ctx = build_prefetch_context(canon_items, ws, Path(state_dir) if state_dir else None,
                                 work_id=work_id or None)
```

- [ ] **Step 4: 加一个新测试覆盖决定注入（既有测试无需改动）**

`tests/test_stage3_minimal.py:101-110` 的 `test_prompt_parts_terms_injected` **不需要改**：它调用 `build_prefetch_context(canon, work_state, None)`（不传 `work_id`），因此 `work_id=None` ⇒ 没有 `decisions` ⇒ `system_extra` 仍为空，原断言继续成立。Step 3 的签名改动必须保持这个默认行为。

在 `tests/test_stage3_minimal.py` **新增**：

```python
def test_book_decisions_injected_as_binding_rule(tmp_path, monkeypatch):
    """书内决定必须以"必须使用"级措辞进 system_extra（区别于走预替换的 terms）。"""
    from amta.common import workstate
    from amta.translation.stage3_minimal import build_prefetch_context

    monkeypatch.setattr(workstate, "WORKSPACE", tmp_path)
    workstate.init_workspace("w1")
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    canon = [{"region_id": "r00", "baberu_text": "ヤミツキ茸二倍だあああ!", "page": 7}]
    ctx = build_prefetch_context(canon, workstate.load_state("w1"), None, work_id="w1")
    assert "ヤミツキ茸 → 成瘾菇" in ctx["system_extra"]
    assert "必须使用" in ctx["system_extra"]
```

同时**必须**加一条反向测试，锁住"不同书不串味"这个契约（同一 `WORKSPACE` 下另一个 work-id 不得命中）：

```python
def test_decisions_do_not_leak_across_work_ids(tmp_path, monkeypatch):
    from amta.common import workstate
    from amta.translation.stage3_minimal import build_prefetch_context

    monkeypatch.setattr(workstate, "WORKSPACE", tmp_path)
    workstate.init_workspace("book-a")
    workstate.init_workspace("book-b")
    workstate.record_decisions("book-a", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    canon = [{"region_id": "r00", "baberu_text": "ヤミツキ茸二倍だあああ!", "page": 7}]
    ctx = build_prefetch_context(canon, workstate.load_state("book-b"), None, work_id="book-b")
    assert "成瘾菇" not in ctx["system_extra"]
```

- [ ] **Step 5: 运行并提交**

Run:
```powershell
uv run python -m pytest tests/test_stage3_minimal.py tests/test_translate_repair.py -q
```
Expected: `test_stage3_minimal.py` 全 PASS；`test_translate_repair.py` 中 `test_clean_page_makes_only_one_call` 与 `test_decisions_returned_by_translate_are_persisted` PASS，另两个仍 FAIL（修复逻辑在 Task 4）。

```powershell
git add src/amta/translation/translate.py src/amta/translation/stage3_minimal.py tests/test_stage3_minimal.py
git commit -m "feat(translate): inject per-book decisions as binding glossary and return new decisions"
```

---

### Task 4: 一次修复 + 低置信度落盘

**Files:**
- Modify: `src/amta/translation/stage3_minimal.py:333-363`
- Modify: `src/amta/stores/artifacts.py:71-78`
- Test: `tests/test_translate_repair.py`

- [ ] **Step 1: `TranslationArtifact` 加两个可选键**

修改 `src/amta/stores/artifacts.py:71-78`：

```python
class TranslationArtifact(TypedDict, total=False):
    work_id: str
    page: str
    schema_version: str
    generated_at: str
    translations: dict[str, str]
    residue: list[str]
    glossary_violations: list
    # 有界修复后仍残留 → 机器可读的低置信度证据（空列表 = 高置信度）。
    # 不引入页级状态枚举：页级状态由本数组是否为空静态推导。
    low_confidence: list
    # terms（词典/人工）与 decisions（模型暂定）同名不同译名时记录，不覆盖任何一方。
    memory_conflict: list
```

- [ ] **Step 2: 改 `translate_page_minimal` 的主体**

把 `src/amta/translation/stage3_minimal.py:333-363` 替换为：

```python
    translations: dict[str, str] = {}
    decisions: list[dict] = []
    if ctx["refined_canon"]:
        translations, decisions, _raw = translate_plain_with_decisions(
            ctx["refined_canon"], llm_text,
            system_extra=system_extra,
            context_prefix=ctx["context_prefix"],
            context_enabled=context_enabled,
        )

    result: dict[str, str] = {}
    for r in canon_items:
        rid = r["region_id"]
        result[rid] = translations.get(rid, "")

    # ---- 有界修复：残留非空 → 回填残留清单，只重问一次 ----
    repair_attempted = False
    residue = guardrails.japanese_residue_check(list(result.values()))
    if any(str(x).strip() for x in residue):
        repair_attempted = True
        repaired, repair_decisions = repair_with_residue_hint(
            ctx["refined_canon"], result, llm_text, system_extra=system_extra)
        result = repaired
        decisions = decisions + repair_decisions
        residue = guardrails.japanese_residue_check(list(result.values()))

    # ---- 仍残留 → 落盘机器可读低置信度；仍用它支持的最佳译文继续出图 ----
    low_confidence: list[dict] = []
    if repair_attempted:
        residual_ids = [r["region_id"] for r in canon_items
                        if contains_japanese(result.get(r["region_id"], ""))]
        evidence_pages: list[int] = []
        if residual_ids:
            src_all = [r.get("baberu_text") or r.get("text") or "" for r in canon_items]
            for _entry in workstate.relevant_decisions(work_id, src_all).values():
                for _ev in (_entry.get("evidence") or []):
                    _p = _ev.get("page")
                    if _p is not None and _p not in evidence_pages:
                        evidence_pages.append(_p)
            evidence_pages.sort()
        for rid in residual_ids:
            low_confidence.append({
                "region_id": rid,
                "reason": "residue_after_one_repair",
                "attempted": "region_rewrite_with_residue_hint",
                "evidence_pages": evidence_pages,
            })

    # ---- 记忆写回：本页新决定（幂等，重跑不重复污染） ----
    if decisions and work_id:
        page_no = None
        m = re.search(r"\d+", str(env_page or ""))
        if m:
            page_no = int(m.group())
        workstate.record_decisions(work_id, [
            {**d, "page": page_no, "region_id": d.get("region_id", "")}
            for d in decisions
        ])

    violations: list[str] = []

    out = artifacts.stamp({
        "translations": result,
        "residue": residue,
        "glossary_violations": violations,
        "low_confidence": low_confidence,
        "memory_conflict": ctx.get("memory_conflicts", []),
        "translation_mode": cache_salt,
    }, work_id or "", env_page)
    return out
```

并在 `stage3_minimal.py` 顶部 import 区补：

```python
from amta.common.metrics import contains_japanese
from amta.translation.translate import (
    extract_relevant_terms, get_chat_config, parse_decisions,  # noqa: F401
    repair_with_residue_hint, text_chat, translate_plain_with_decisions,
)
```

- [ ] **Step 3: 运行修复测试**

Run:
```powershell
uv run python -m pytest tests/test_translate_repair.py -q
```
Expected: 4 个全 PASS。`test_residue_triggers_exactly_one_repair` 断言 `len(calls) == 2`；`test_residue_after_one_repair_sets_low_confidence` 断言 `low_confidence[0]["reason"] == "residue_after_one_repair"`。

- [ ] **Step 4: 跑相关既有测试确认没踩坏**

Run:
```powershell
uv run python -m pytest tests/test_translate_station.py tests/test_stage3_minimal.py tests/test_guardrails.py tests/test_artifacts.py -q
```
Expected: PASS。`test_translate_page_minimal_contract` 若因新增键而断言过严，按"新契约"更新它（显式列出改了哪一行）。

- [ ] **Step 5: 提交**

```powershell
git add src/amta/translation/stage3_minimal.py src/amta/stores/artifacts.py tests/test_translate_repair.py
git commit -m "feat(translate): one bounded residue repair with machine-readable low confidence"
```

---

### Task 5: 缓存失效 + 红榜可见

**Files:**
- Modify: `src/amta/orchestrator/pipeline.py:123-131`
- Modify: `src/amta/orchestrator/registry.py:92-116`
- Modify: `src/amta/orchestrator/quality_audit.py:26-107`
- Test: `tests/test_artifact_cache.py`, `tests/test_quality_audit.py`

- [ ] **Step 1: 红测试——改 `work_state.json` 必须让 translate 缓存失效**

在 `tests/test_artifact_cache.py` 新增：

```python
def test_translate_fingerprint_includes_work_state(tmp_path):
    """需求 7：改翻译记忆必须让 translate 产物失效，否则旧译文静默留下。"""
    from amta.orchestrator.context import StationContext
    from amta.orchestrator.pipeline import _stage_input_files
    from amta.orchestrator.registry import get_stage
    from amta.stores.artifact_cache import compute_fingerprint, is_fresh, save_fingerprint

    state = tmp_path / "state"
    state.mkdir()
    ws = state / "work_state.json"
    ws.write_text('{"work_id": "w1", "decisions": {}}', encoding="utf-8")
    canon = tmp_path / "canon.json"
    canon.write_text('{"items": []}', encoding="utf-8")
    raw = tmp_path / "raw.jpg"
    raw.write_bytes(b"x")
    out = tmp_path / "translation.json"
    out.write_text('{"translations": {}}', encoding="utf-8")

    code = [Path(f) for f in get_stage("translate").code_files]
    ctx = StationContext(work_id="w1", page="page_0", page_idx=0, raw_image=raw,
                         artifacts_dir=tmp_path, state_dir=state,
                         inputs={"ocr": canon}, config={})
    inputs = _stage_input_files(ctx)
    assert "work_state" in inputs, "translate 阶段必须把 work_state.json 纳入指纹输入"

    save_fingerprint(out, "translate", "page_0", compute_fingerprint(inputs, code, {}))
    assert is_fresh(out, inputs, code, {}) is True

    ws.write_text('{"work_id": "w1", "decisions": {"x": {"translation": "y"}}}',
                  encoding="utf-8")
    assert is_fresh(out, _stage_input_files(ctx), code, {}) is False
```

Run:
```powershell
uv run python -m pytest tests/test_artifact_cache.py::test_translate_fingerprint_includes_work_state -q
```
Expected: FAIL，`assert "work_state" in inputs` —— 当前 `_stage_input_files` 只回传 `{raw_image, ocr}`。

- [ ] **Step 2: 实现——给 translate 阶段补上 `work_state.json`**

修改 `src/amta/orchestrator/pipeline.py:123-131`：

```python
def _stage_input_files(ctx: StationContext) -> dict[str, Path | str]:
    """收集该阶段的所有输入文件：原始图片 + 上游产物 + 阶段自身的状态产物。

    这些文件的哈希会存入 fingerprint，任何一个变了都会触发重跑。

    translate 额外纳入 state/work_state.json：书内翻译记忆（decisions/terms）变了，
    该页译文必须重算，否则会静默复用旧译文（需求 7：缓存命中不得无声丢失记忆）。
    """
    input_files: dict[str, Path | str] = {"raw_image": ctx.raw_image}
    for dep_name, dep_path in ctx.inputs.items():
        input_files[dep_name] = dep_path
    if ctx.state_dir is not None and ctx.artifacts_dir is not None:
        ws = Path(ctx.state_dir) / "work_state.json"
        if ws.exists():
            input_files["work_state"] = ws
    return input_files
```

- [ ] **Step 3: 补 `registry.code_files`**

修改 `src/amta/orchestrator/registry.py` 的 translate `code_files`（`:98-115`），加入本计划新引入/依赖的模块（`test_artifact_cache.py` 会断言这些文件存在）：

```python
            code_files=[
                "orchestrator/adapters/translate.py",
                "orchestrator/pipeline.py",
                "guards/canon_schema.py",
                "common/config.py",
                "common/metrics.py",
                "common/workstate.py",
                "translation/translate_station.py",
                "translation/translate.py",
                "translation/stage3_minimal.py",
                "guards/guardrails.py",
                "guards/glossary.py",
                "guards/term_dict.py",
                "guards/term_replace.py",
                "guards/pre_scan.py",
                "backends/chat_client.py",
                "stores/artifacts.py",
                "common/paths.py",
            ],
```

- [ ] **Step 4: 红榜可见低置信度**

修改 `src/amta/orchestrator/quality_audit.py`。`PageFlags` 加一个字段（`low_confidence: list[str]`），`audit_page` 里从翻译产物读：

```python
    if t:
        flags.empty_translations = [
            rid for rid, v in t.get("translations", {}).items()
            if not str(v).strip()
        ]
        flags.residues = len([r for r in t.get("residue", []) if str(r).strip()])
        flags.low_confidence = [
            str(e.get("region_id", "?")) for e in (t.get("low_confidence") or [])
        ]
```

`has_flags` 加入 `or self.low_confidence`；`format_redlist` 加入：

```python
        if f.low_confidence:
            parts.append(f"低置信度 {f.low_confidence}（修复后仍残留日文）")
```

在 `tests/test_quality_audit.py` 新增：

```python
def test_audit_lists_low_confidence_regions(tmp_path):
    from amta.orchestrator.quality_audit import audit_page, format_redlist
    art = tmp_path / "translation"
    art.mkdir(parents=True)
    (art / "page_7.json").write_text(
        '{"translations": {"r01": "成瘾菇"}, "residue": ["ヤミツキ茸"],'
        ' "low_confidence": [{"region_id": "r01",'
        ' "reason": "residue_after_one_repair"}]}', encoding="utf-8")
    flags = audit_page(tmp_path, "page_7")
    assert flags.low_confidence == ["r01"]
    assert "低置信度" in format_redlist([flags])
```

- [ ] **Step 5: 运行全部相关测试**

Run:
```powershell
uv run python -m pytest tests/test_artifact_cache.py tests/test_quality_audit.py tests/test_orchestrator_smoke.py tests/test_pipeline_cache_outputs.py -q
```
Expected: PASS

- [ ] **Step 6: 验证需求 6（零硬编码）**

Run:
```powershell
uv run python -c "import subprocess,sys; r=subprocess.run(['git','grep','-n','-e','ヤミツキ茸','-e','迷幻菇','-e','クズ','-e','人渣','--','src/','scripts/'],capture_output=True,text=True,encoding='utf-8'); print(r.stdout or '(no matches)')"
```
Expected: 输出 **`(no matches)`** —— `src/` 与 `scripts/` 生产代码 **零命中**。

再单跑一次 `tests/`，把命中**逐条归类**（预期全部是测试夹具里的假数据，没有任何一处是生产规则）：

```powershell
uv run python -c "import subprocess; r=subprocess.run(['git','grep','-n','-e','ヤミツキ茸','-e','迷幻菇','-e','クズ','-e','人渣','--','tests/'],capture_output=True,text=True,encoding='utf-8'); print(r.stdout or '(no matches)')"
```
Expected: 命中行数应与 Task 1/3 写入的夹具数量一致；报告里逐条说明"这一处是夹具输入/期望值，不是生产规则"。

**不接受笼统豁免**：若出现任何一处位于 `src/` 或 `scripts/` 的命中，即需求 6 不满足，必须改掉再继续。

- [ ] **Step 7: 提交**

```powershell
git add src/amta/orchestrator/pipeline.py src/amta/orchestrator/registry.py src/amta/orchestrator/quality_audit.py tests/test_artifact_cache.py tests/test_quality_audit.py
git commit -m "fix(translate): invalidate cache on memory change and surface low confidence in redlist"
```

---

### Task 6: 真实样本验证（范围 0–15，新 work-id）

**Files:**
- Read-only: `D:\我的汉化\汉化作品\东方\幻想乡居民们的赚钱大法！\原图`
- Write: 被忽略的 `workspace/<new-work-id>/`（**不得**写 `原图`／`新建文件夹`）

- [ ] **Step 1: 先跑便宜的一趟拿语义证据**

Run:
```powershell
uv run python scripts/run_pipeline.py --work-id bookmem-verify --src-dir "D:\我的汉化\汉化作品\东方\幻想乡居民们的赚钱大法！\原图" --start-page 0 --end-page 15 --stages detect,ocr,translate
```
Expected: 16 页跑完，`failed=0`；收尾打印红榜。

- [ ] **Step 2: 断言跨页复用（验收 1–3）**

Run:
```powershell
uv run python scripts/artifact.py query --work-id bookmem-verify --stage translation --format json
```
再读原图 3（管线 page_2）与原图 8（管线 page_7）的产物：

```powershell
uv run python -c "import json,pathlib; d=pathlib.Path('workspace/bookmem-verify/state/work_state.json'); s=json.loads(d.read_text(encoding='utf-8')); print(json.dumps(s.get('decisions',{}), ensure_ascii=False, indent=2))"
uv run python -c "import json,pathlib; print(json.loads(pathlib.Path('workspace/bookmem-verify/artifacts/translation/page_7.json').read_text(encoding='utf-8'))['translations'])"
```
Expected:
- `work_state.json` 的 `decisions` 里存在 `ヤミツキ茸` 的条目，`status="tentative"`，`evidence` 至少含一条 `{page: 2, region_id: ..., surface_seen: "ヤミツキ茸", match: "exact"}`
- `page_7.json` 的 `translations` 里**不再出现片假名 `ヤミツキ茸`**，且所用词 == page_2 那条决定的 `translation`（逐字相同）
- `page_7.json` 的 `residue == []`、`low_confidence == []`

**如实记录**：原图 3 具体选了哪个词（`成瘾菇` / `迷幻菇` / 其他）——**未知且设计上不重要**，只要求一致性。

- [ ] **Step 3: 补全五阶段，证明低置信度不阻塞下游**

Run:
```powershell
uv run python scripts/run_pipeline.py --work-id bookmem-verify --src-dir "D:\我的汉化\汉化作品\东方\幻想乡居民们的赚钱大法！\原图" --start-page 0 --end-page 15 --stages detect,ocr,translate,inpaint,typeset
```
Expected: 全阶段跑完；translate 缓存命中（Step 1 已跑）或按需重算；inpaint/typeset 未被任何低置信度拦住。

- [ ] **Step 4: 生成视觉报告**

Run:
```powershell
uv run python scripts/gen_report.py --work-id bookmem-verify --src-dir "D:\我的汉化\汉化作品\东方\幻想乡居民们的赚钱大法！\原图" --pages 1-16
```
Expected: 报告生成成功；原图 8 对应页面上不再有片假名残留。

- [ ] **Step 5: 断点重跑不污染记忆（需求 7）**

先记录 `decisions` 的 evidence 条数，再重跑同一范围，再比对：

```powershell
uv run python -c "import json,pathlib; s=json.loads(pathlib.Path('workspace/bookmem-verify/state/work_state.json').read_text(encoding='utf-8')); print({k: len(v['evidence']) for k,v in s.get('decisions',{}).items()})"
uv run python scripts/run_pipeline.py --work-id bookmem-verify --src-dir "D:\我的汉化\汉化作品\东方\幻想乡居民们的赚钱大法！\原图" --start-page 0 --end-page 15 --stages detect,ocr,translate
uv run python -c "import json,pathlib; s=json.loads(pathlib.Path('workspace/bookmem-verify/state/work_state.json').read_text(encoding='utf-8')); print({k: len(v['evidence']) for k,v in s.get('decisions',{}).items()})"
```
Expected: 两次输出**完全相同**（evidence 未膨胀）。若第二次全部 cache hit，再 `--force-rerun` 跑一次确认幂等键生效。

- [ ] **Step 6: 记录 before/after 对照**

`workspace/gui-1790591328680` 是 before 基线（page_4 `n_residue=3`、`status=ok`、片假名渲进成品）。**只读**引用它，不修改。把 before 的 `pipeline_log.json` 片段与 after 的 `page_7.json` 并排写进最终报告。

---

### Task 7: 全量门禁 + 收尾

- [ ] **Step 1: 全量 pytest**

Run:
```powershell
uv run python -m pytest -q
```
Expected: 全绿（记录通过/跳过条数）。

- [ ] **Step 2: `npm run check`**

Run:
```powershell
npm run check
```
Expected: 全绿。

- [ ] **Step 3: 收尾（仓库唯一入口）**

Run:
```powershell
uv run python scripts/state.py finish "feat(translate): per-book translation memory with bounded repair"
```
Expected: 内置全量质检通过后提交。**如实报告它实际执行了哪些检查**（不得笼统说"通过了"）。

- [ ] **Step 4: 逐条对应任务书八项结果**

写最终报告，对每一项给出**测试名 / 命令结果 / 产物查询**，无法观察的**标为未知**：

| # | 证据形式 |
|---|---|
| 1 | Task 2 单测 + Task 6 Step 2 的 `work_state.json` `decisions` 片段 |
| 2 | Task 6 Step 2：`page_7.json` 译文与 page_2 决定逐字相同 |
| 3 | Task 2 的 `test_model_judged_variant_records_alias` + evidence 片段 |
| 4 | Task 4 的 `test_residue_after_one_repair_sets_low_confidence` + Task 5 红榜测试 |
| 5 | Task 2 的 `test_revision_keeps_old_evidence` |
| 6 | Task 5 Step 6 的 grep 输出（逐条归类命中） |
| 7 | Task 5 Step 1 的缓存测试 + Task 6 Step 5 的 evidence 条数比对 |
| 8 | 设计不含 PSD 读取；grep 证明无 PSD 反向抽取代码 |

**必须如实标注的未知**：原图 3 在新 work-id 下具体选了哪个词；真实素材上是否出现"修复后仍残留"（若不出现，低置信度分支只能由 Task 4 的注入式测试证明，真实跑证明的是高置信度路径）。

**不得声明**："第 7 页残留被修复"——该症状在本 workspace 未复现（见 spec §1）。

---

## Self-Review

**1. Spec 覆盖**

| Spec 章节 | 落点 |
|---|---|
| §3 组件职责 | 文件结构表 |
| §4.1 `decisions` 形状 | Task 2 Step 1-2 |
| §4.2 terms 优先 + 冲突 | Task 2 Step 2 `relevant_decisions_with_conflicts` + Task 3 Step 3 |
| §4.3 产物新字段 | Task 4 Step 1-2 |
| §5.1 单页流程 | Task 3 + Task 4 |
| §5.2 检索与页距无关 | Task 2 `test_retrieval_ignores_page_distance` + Task 6 Step 2 |
| §5.3 OCR 变体留证 | Task 2 `test_model_judged_variant_records_alias` |
| §5.4 修订不回改旧页 | Task 2 `test_revision_keeps_old_evidence`；Task 6 Step 5 靠 fingerprint 自然重翻 |
| §5.5 低置信度表现 | Task 4 + Task 5 Step 4 |
| §5.6 失败矩阵 | Task 2 `test_corrupt_state_degrades_to_empty_without_raising`；Task 4 修复语义 |
| §6 缓存/重跑 | Task 5 Step 1-2；Task 6 Step 5 |
| §7 验收规则 | Task 6 Step 2 |
| §8 测试策略 | Task 1（先红）+ Task 7（门禁） |
| §9 八项对应 | Task 7 Step 4 |
| §11 未决 | Task 4 明确不修 `contains_japanese`；无 PSD 任务 |
| §2.1 砍掉清单 | 每个 Task 都没有引入被砍掉的机制 |

**2. 占位符扫描**：无 TBD / TODO / "类似 Task N" / "适当处理"。每个改代码的步骤都给了完整代码。

**3. 类型一致性**：`record_decisions(work_id, records)`、`load_decisions(work_id)`、`relevant_decisions(work_id, src_texts)`、`relevant_decisions_with_conflicts(work_id, src_texts) -> (dict, list)`、`translate_plain_with_decisions(...) -> (dict, list, str)`、`repair_with_residue_hint(canon, translations, llm, *, system_extra) -> (dict, list)`、`parse_decisions(raw) -> list[dict]`、`build_prefetch_context(canon, work_state, state_dir, *, work_id=None) -> dict`（返回含 `memory_conflicts`）、`validate_decisions(state) -> list[str]` —— Task 2/3/4/5/6 引用处名称与签名一致。

**4. 既有测试的处置（经核对，结论与初稿相反）**：Task 3 Step 3 给 `build_prefetch_context` 的 `work_id` 参数**必须是可选默认 `None`**，因为 `tests/test_stage3_minimal.py:106` 与 `:123` 都以三个位置参数调用它。保持该默认后，这两个既有测试**无需任何修改**即可继续通过（`work_id=None` ⇒ 无 decisions ⇒ `system_extra` 仍为空）。因此本计划**不修改任何既有断言**，只新增测试。若实现时发现必须改既有断言，停下来先确认是不是引入了非预期行为变更。

**5. 反向契约**：计划显式包含 `test_decisions_do_not_leak_across_work_ids`。书内记忆按 work-id 隔离是本设计的边界；没有这条测试，"一本书内"这个范围就是散文声明而不是可验证契约。
