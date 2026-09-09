"""tickets — needs_review 工单机制（ADR-017，借鉴 CMMS 工单状态机 + 维修手册归档）。

工单生命周期: open → in_progress → resolved / rejected（关闭）
归档闭环: resolved/rejected 时处理结论自动回写判例库（case_law.json）——
"维修手册"逻辑：同类问题下次自动修复/评审可直接参考，越修越聪明。

文件即状态: <state_dir>/tickets.json（每本一个，符合 per-work 结构）
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_RESOLVED = "resolved"
STATUS_REJECTED = "rejected"

KIND_TERM_CONFLICT = "term_conflict"   # 术语表与评审/护栏冲突
KIND_FALSE_POSITIVE = "false_positive"  # 评审误报
KIND_HARD_CASE = "hard_case"           # 难句，自动修复多次未过
KIND_UNKNOWN = "unknown"

KINDS = (KIND_TERM_CONFLICT, KIND_FALSE_POSITIVE, KIND_HARD_CASE, KIND_UNKNOWN)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def classify_kind(reason: str, source: str = "") -> str:
    """从卡点原因粗分类（可后续人工修正）。"""
    blob = f"{reason} {source}"
    if any(k in blob for k in ("术语", "护栏", "canon", "glossary", "consistent")):
        return KIND_TERM_CONFLICT
    if any(k in blob for k in ("误报", "语境", "编造", "补全")):
        return KIND_FALSE_POSITIVE
    return KIND_HARD_CASE


class TicketStore:
    """JSON 文件即状态：create / set_status / resolve / reject / list_open。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._data: dict[str, Any] = {"tickets": []}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {"tickets": []}
        self._data.setdefault("tickets", [])

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    def create(self, work_id: str, region_id: str, *, reason: str,
               auto_rounds: int, source: str = "", translation: str = "",
               kind: str | None = None) -> dict:
        """自动修复层开单。返回工单 dict。"""
        ticket = {
            "id": uuid.uuid4().hex[:12],
            "work_id": work_id,
            "region_id": region_id,
            "kind": kind or classify_kind(reason, source),
            "source": source,
            "translation": translation,
            "reason": reason,
            "auto_rounds": auto_rounds,
            "status": STATUS_OPEN,
            "created_at": _now(),
            "updated_at": _now(),
            "action": None,
            "resolution": None,
        }
        self._data["tickets"].append(ticket)
        self._save()
        return ticket

    def get(self, ticket_id: str) -> dict | None:
        return next((t for t in self._data["tickets"] if t["id"] == ticket_id), None)

    def list_open(self) -> list[dict]:
        return [t for t in self._data["tickets"]
                if t["status"] in (STATUS_OPEN, STATUS_IN_PROGRESS)]

    def set_status(self, ticket_id: str, status: str, *,
                   action: str | None = None, resolution: str | None = None) -> dict:
        """流转状态（in_progress / resolved / rejected 等）。"""
        t = self.get(ticket_id)
        if t is None:
            raise KeyError(f"ticket not found: {ticket_id}")
        t["status"] = status
        t["updated_at"] = _now()
        if action:
            t["action"] = action
        if resolution:
            t["resolution"] = resolution
        self._save()
        return t

    def _append_case_law(self, case_law_path: Path | None, *, region_id: str,
                         source: str, translation: str, verdict: str,
                         reason: str, lesson: str) -> None:
        """归档闭环：处理结论回写判例库（维修手册逻辑）。"""
        if case_law_path is None:
            return
        doc: dict[str, Any] = {"cases": []}
        if case_law_path.exists():
            try:
                doc = json.loads(case_law_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                doc = {"cases": []}
        doc.setdefault("cases", [])
        entry = {
            "region_id": region_id,
            "source": source,
            "translation": translation,
            "verdict": verdict,
            "scores": {},
            "reason": reason,
            "suggestion": "",
            "lesson": lesson,
            "ticket_id": region_id,
        }
        idx = next((i for i, c in enumerate(doc["cases"])
                    if c.get("region_id") == region_id), None)
        if idx is not None:
            doc["cases"][idx] = entry
        else:
            doc["cases"].append(entry)
        case_law_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    def resolve(self, ticket_id: str, *, action: str, resolution: str,
                case_law_path: Path | None = None) -> dict:
        """导演处理完成：标记 resolved 并归档回写判例库（verdict=pass）。"""
        t = self.set_status(ticket_id, STATUS_RESOLVED, action=action, resolution=resolution)
        self._append_case_law(case_law_path, region_id=t["region_id"],
                              source=t.get("source", ""), translation=t.get("translation", ""),
                              verdict="pass", reason=resolution,
                              lesson=f"工单 {ticket_id}（{t['kind']}）：{action} → {resolution}")
        return t

    def reject(self, ticket_id: str, *, reason: str,
               case_law_path: Path | None = None) -> dict:
        """导演驳回（评审误报）：标记 rejected 并归档回写判例库（verdict=pass，lesson=误报）。"""
        t = self.set_status(ticket_id, STATUS_REJECTED, action="驳回",
                            resolution=reason)
        self._append_case_law(case_law_path, region_id=t["region_id"],
                              source=t.get("source", ""), translation=t.get("translation", ""),
                              verdict="pass", reason=reason,
                              lesson=f"工单 {ticket_id}（{t['kind']}）：评审误报驳回，维持原译")
        return t
