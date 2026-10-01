"""per-work workspace + work_state — 产物结构 rebaseline（ADR-013）。

每本同人志一个工作区，文件即状态：

    workspace/<work_id>/
    ├── raw/                       # 源页图（未翻译原图）
    ├── artifacts/                 # 单页/整本确定性产物
    └── state/
        ├── touhou_knowledge.json  # 共享 canon prior（curated，跨本子复用）
        ├── work_state.json        # 当前本子状态（逐页生长）
        └── open_questions.json    # 未决问题

语义（参考 first-principles/DIKW 设计）：
- 三层上下文分离：canon prior（stable）≠ work_state（可变，本子真相优先于 canon）。
- work_state 逐页生长，不从开局构建完美世界模型。
- Evidence tracking：条目带 status∈{confirmed,inferred,candidate} + source（页码）。
- 新证据可修正旧状态；单页可运行。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from amta.common.paths import ROOT

# workspace 根目录（gitignored 大产物 + 入库的 state JSON）
WORKSPACE = ROOT / "workspace"

# 证据状态枚举（ADR-016 四层：observed/confirmed/inferred/candidate）
STATUS_OBSERVED = "observed"
STATUS_CONFIRMED = "confirmed"
STATUS_INFERRED = "inferred"
STATUS_CANDIDATE = "candidate"
STATUSES = (STATUS_CONFIRMED, STATUS_INFERRED, STATUS_CANDIDATE, STATUS_OBSERVED)

# 文本类型
TEXT_CLASSES = ["dialogue_in", "dialogue_out", "sfx", "bg_text"]

# 三个 state 文件的空 schema（首版不做 Character/Relationship DB、Event Graph、Vector DB）
TEMPLATE_KNOWLEDGE: dict[str, Any] = {
    "work_id": "",
    "characters": {},   # {名字: {canon_desc, aliases, speech_style}}
    "locations": {},    # {名: {canon_desc}}
    "terms": {},        # {术语: {canon_translation, notes}}
}
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
TEMPLATE_OPEN_QUESTIONS: dict[str, Any] = {
    "work_id": "",
    "questions": [],   # [{id, question, status, raised_page, resolved_by?, resolution?}]
}

ARTIFACT_NAMES = (
    "detection.json", "ocr_candidates.json", "canon_text.json",
    "translation.json", "mask.png", "cleaned.png", "final.png",
)
STATE_FILES = ("touhou_knowledge.json", "work_state.json", "open_questions.json")


def work_dir(work_id: str, *, tmp_workspace_root: Path | str | None = None) -> Path:
    """返回该本子工作区根目录。

    Args:
        work_id: 工作区 ID。
        tmp_workspace_root: 临时/试验工作区的根。**跑探针、benchmark、任何会
            生成一次性 work_id 的代码必须传它**——否则会往中央 workspace/ 里
            留下空壳目录（2026-09-10 体检实测积了 2164 个，零个有真实产物）。
    """
    base = Path(tmp_workspace_root) if tmp_workspace_root is not None else WORKSPACE
    return base / work_id


def ensure_workspace(work_id: str, *, tmp_workspace_root: Path | str | None = None) -> Path:
    """创建该本子的 raw/ artifacts/ state/ 目录，返回工作区根目录。

    见 `work_dir` 关于 `tmp_workspace_root` 的说明。
    """
    root = work_dir(work_id, tmp_workspace_root=tmp_workspace_root)
    for sub in ("raw", "artifacts", "state"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def empty_state() -> dict[str, dict[str, Any]]:
    """返回三个 state 文件的空 schema（deep-copy，避免共享可变对象）。"""
    import copy
    return {name: copy.deepcopy(TEMPLATE) for name, TEMPLATE in (
        ("touhou_knowledge.json", TEMPLATE_KNOWLEDGE),
        ("work_state.json", TEMPLATE_WORK_STATE),
        ("open_questions.json", TEMPLATE_OPEN_QUESTIONS),
    )}


def init_workspace(work_id: str, *, tmp_workspace_root: Path | str | None = None) -> Path:
    """创建工作区目录 + 写入三个空 state 文件，返回工作区根目录。

    幂等：文件已存在则不覆盖（保留既有状态）。
    """
    root = ensure_workspace(work_id, tmp_workspace_root=tmp_workspace_root)
    for name, template in (
        ("touhou_knowledge.json", TEMPLATE_KNOWLEDGE),
        ("work_state.json", TEMPLATE_WORK_STATE),
        ("open_questions.json", TEMPLATE_OPEN_QUESTIONS),
    ):
        p = root / "state" / name
        if not p.exists():
            doc = dict(template, work_id=work_id)
            from amta.common.paths import write_json
            write_json(p, doc)
    return root


def load_state(work_id: str) -> dict[str, Any]:
    """读 work_state.json；缺失则返回空模板。"""
    p = work_dir(work_id) / "state" / "work_state.json"
    if not p.exists():
        return dict(TEMPLATE_WORK_STATE, work_id=work_id)
    from amta.common.paths import read_json
    return read_json(p)


def save_state(work_id: str, state: dict[str, Any]) -> Path:
    """写回 work_state.json。"""
    from amta.common.paths import write_json
    return write_json(work_dir(work_id) / "state" / "work_state.json", state)


def add_evidence_fact(work_id: str, fact: str, *, status: str, source: str,
                      confidence: float | None = None) -> dict[str, Any]:
    """向 work_state.recent_context 追加一条带证据状态的事实条目。"""
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    state = load_state(work_id)
    entry: dict[str, Any] = {"fact": fact, "status": status, "source": source}
    if confidence is not None:
        entry["confidence"] = confidence
    state.setdefault("recent_context", []).append(entry)
    save_state(work_id, state)
    return entry


def update_character(work_id: str, name: str, *, status: str = STATUS_CONFIRMED,
                     source: str = "", aliases: list[str] | None = None,
                     role: str = "", notes: str = "", confidence: float | None = None) -> dict[str, Any]:
    """新增或更新一个角色条目（evidence tracking）。"""
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    state = load_state(work_id)
    chars = state.setdefault("characters", {})
    entry = chars.get(name) or {}
    entry.update({"name": name, "status": status, "source": source, "role": role, "notes": notes})
    if aliases is not None:
        entry["aliases"] = aliases
    if confidence is not None:
        entry["confidence"] = confidence
    chars[name] = entry
    save_state(work_id, state)
    return entry


def add_open_question(work_id: str, question: str, *, raised_page: int) -> dict[str, Any]:
    """新增一个未决问题（open_questions.json）。"""
    p = work_dir(work_id) / "state" / "open_questions.json"
    from amta.common.paths import read_json, write_json
    doc = read_json(p) if p.exists() else dict(TEMPLATE_OPEN_QUESTIONS, work_id=work_id)
    qid = f"q{len(doc['questions']) + 1}"
    entry = {"id": qid, "question": question, "status": "open", "raised_page": raised_page}
    doc.setdefault("questions", []).append(entry)
    write_json(p, doc)
    return entry


def validate_state(state: dict[str, Any]) -> list[str]:
    """检查 work_state 结构合法性，返回问题列表（空=合法）。"""
    problems: list[str] = []
    if not state.get("work_id"):
        problems.append("missing work_id")
    for key in ("characters", "terms", "recent_context"):
        if not isinstance(state.get(key, {}), (dict, list)):
            problems.append(f"field {key!r} must be dict/list")
    for name, c in state.get("characters", {}).items():
        if c.get("status") not in STATUSES:
            problems.append(f"character {name!r} invalid status {c.get('status')!r}")
    return problems


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
        surface = str(entry.get("surface") or "")
        if not surface:
            continue
        candidates = [surface] + [str(a) for a in (entry.get("aliases") or [])]
        for cand in candidates:
            ncand = norm(cand)
            if ncand and ncand in ntext:
                hits[surface] = entry
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
    同名同词 → terms 的译名生效（两条都保留在盘上）。
    同名不同译名 → 同样 terms 生效，并返回冲突条目（供产物落盘），**不覆盖任何一方**。

    匹配用规范化后的**相等**判断，不做子串包含——子串包含会让「ヤミツキ」这种
    短别名误吞别的词条，是误绑的来源。
    """
    from amta.common.metrics import norm

    hits = relevant_decisions(work_id, src_texts)
    terms = load_state(work_id).get("terms", {}) or {}

    # 只索引本页原文里真实出现过的 terms
    norm_text = norm(" ".join(t or "" for t in src_texts))
    present_terms: dict[str, tuple[str, dict]] = {}
    for t_surface, t_meta in terms.items():
        nt = norm(t_surface)
        if nt and nt in norm_text:
            present_terms[nt] = (t_surface, t_meta or {})

    resolved: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for surface, entry in hits.items():
        # 该决定自身的所有表面形（原文 + 见过的别名），规范化后找 terms 命中
        cands = [str(entry.get("surface") or "")] + [
            str(a) for a in (entry.get("aliases") or [])
        ]
        term_hit = None
        for cand in cands:
            ncand = norm(cand)
            if ncand and ncand in present_terms:
                term_hit = present_terms[ncand]
                break
        if term_hit is None:
            resolved[surface] = entry
            continue
        t_surface, t_meta = term_hit
        t_trans = t_meta.get("translation") or t_meta.get("canon_translation")
        if t_trans and t_trans != entry.get("translation"):
            conflicts.append({
                "surface": surface,
                "terms_surface": t_surface,
                "terms_translation": t_trans,
                "decision_translation": entry.get("translation"),
            })
        resolved[t_surface] = {
            "surface": t_surface,
            "translation": t_trans,
            "aliases": list(entry.get("aliases") or []),
            "evidence": list(entry.get("evidence") or []),
        }
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
