"""pipeline_log — 流水线 step-level tracing(借鉴 OTel span 思想,零依赖,ADR-018)。

每次运行一个 run 对象:
  {run_id, git_head, started_at, trigger, steps: [span...], failed_step, ended_at}
每步一条 span(append 不覆盖):
  {step, page, status, input, output, detail, duration_s}
文件即状态:<state_dir>/pipeline_log.json(每本一个)
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amta.common.encoding import run_text_or
from amta.common.paths import ROOT


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def git_head() -> str:
    """当前代码版本(commit 短 hash);失败返回 unknown。"""
    return run_text_or(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, timeout=5).strip() or "unknown"


class PipelineLog:
    """pipeline_log.json 读写:start_run / span / fail_run。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._data: dict[str, Any] = {"runs": []}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {"runs": []}
        self._data.setdefault("runs", [])

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    def start_run(self, trigger: str) -> str:
        """开新 run,返回 run_id。"""
        run_id = uuid.uuid4().hex[:12]
        self._data["runs"].append({
            "run_id": run_id,
            "git_head": git_head(),
            "started_at": _now(),
            "trigger": trigger,
            "steps": [],
            "failed_step": None,
            "ended_at": None,
        })
        self._save()
        return run_id

    def add_span(self, run_id: str, *, step: str, page: str, status: str,
                 input: str = "", output: str = "", detail: dict | None = None,
                 duration_s: float = 0.0) -> None:
        """记录一步。status: ok / fail / skipped。"""
        run = next((r for r in self._data["runs"] if r["run_id"] == run_id), None)
        if run is None:
            return
        run["steps"].append({
            "step": step, "page": page, "status": status,
            "input": input, "output": output,
            "detail": detail or {}, "duration_s": round(duration_s, 2),
            "at": _now(),
        })
        self._save()

    def fail_run(self, run_id: str, *, step: str, page: str, reason: str) -> None:
        """失败锚点:哪一步、哪一页、违反什么(reason),配合工单定位。"""
        run = next((r for r in self._data["runs"] if r["run_id"] == run_id), None)
        if run is None:
            return
        run["failed_step"] = {"step": step, "page": page, "reason": reason}
        run["ended_at"] = _now()
        self._save()

    def end_run(self, run_id: str) -> None:
        run = next((r for r in self._data["runs"] if r["run_id"] == run_id), None)
        if run is not None:
            run["ended_at"] = _now()
            self._save()

    def last_runs(self, n: int = 5) -> list[dict]:
        return self._data["runs"][-n:]

    def find_failed(self) -> list[dict]:
        return [r for r in self._data["runs"] if r.get("failed_step")]
