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

from amta.paths import ROOT

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
    "terms": {},        # {术语: {translation, status, source}}
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


def work_dir(work_id: str) -> Path:
    """返回该本子工作区根目录。"""
    return WORKSPACE / work_id


def ensure_workspace(work_id: str) -> Path:
    """创建该本子的 raw/ artifacts/ state/ 目录，返回工作区根目录。"""
    root = work_dir(work_id)
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


def init_workspace(work_id: str) -> Path:
    """创建工作区目录 + 写入三个空 state 文件，返回工作区根目录。

    幂等：文件已存在则不覆盖（保留既有状态）。
    """
    root = ensure_workspace(work_id)
    for name, template in (
        ("touhou_knowledge.json", TEMPLATE_KNOWLEDGE),
        ("work_state.json", TEMPLATE_WORK_STATE),
        ("open_questions.json", TEMPLATE_OPEN_QUESTIONS),
    ):
        p = root / "state" / name
        if not p.exists():
            doc = dict(template, work_id=work_id)
            from amta.paths import write_json
            write_json(p, doc)
    return root


def load_state(work_id: str) -> dict[str, Any]:
    """读 work_state.json；缺失则返回空模板。"""
    p = work_dir(work_id) / "state" / "work_state.json"
    if not p.exists():
        return dict(TEMPLATE_WORK_STATE, work_id=work_id)
    from amta.paths import read_json
    return read_json(p)


def save_state(work_id: str, state: dict[str, Any]) -> Path:
    """写回 work_state.json。"""
    from amta.paths import write_json
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
    from amta.paths import read_json, write_json
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
