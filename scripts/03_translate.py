"""03_translate 工位 — 读 canon_text.json → DeepSeek 翻译 → translation.json + suggestions.json。

用法: python scripts/03_translate.py --canon <canon_text.json> --out <translation.json> [--work-id ID] [--state-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta import paths, translate  # noqa: E402
from amta.workstate import load_state  # noqa: E402


def _load_open_questions(state_dir: str | Path | None) -> list[dict] | None:
    """从 state/open_questions.json 读未决问题列表；无则 None。"""
    if not state_dir:
        return None
    p = Path(state_dir) / "open_questions.json"
    if not p.exists():
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    return doc.get("questions", [])


def run(canon_path: str | Path, out_path: str | Path, *,
        work_id: str | None = None, state_dir: str | Path | None = None,
        trace_path: str | Path | None = None) -> dict:
    canon = paths.read_json(canon_path)
    from amta.canon_schema import validate_canon
    problems = validate_canon(canon)
    if problems:
        raise ValueError(f"canon input schema failed: {'; '.join(problems[:5])}")
    cfg = translate.get_chat_config()
    ws = load_state(work_id) if work_id else {}
    open_questions = _load_open_questions(state_dir)

    trace: list[dict] = []

    def llm(messages, tools=None):
        resp = translate.chat_with_tools(cfg["base_url"], cfg["model"], messages,
                                         tools=tools, api_key=cfg["api_key"])
        if trace_path:
            trace.append({
                "roles": [m["role"] for m in messages],
                "tool_calls": [{"name": c.get("function", {}).get("name"),
                                 "args": c.get("function", {}).get("arguments")}
                                for c in (resp.get("tool_calls") or [])],
                "content": (resp.get("content") or "")[:200],
            })
        return resp

    # 真 function calling：模型按需调 lookup_term / get_context（Patrick 裁决，2026-08-26）
    result = translate.translate_with_retry(canon, llm, work_state=ws, open_questions=open_questions,
                                            tools=translate.TOOLS_SCHEMA, state_dir=state_dir)

    residue = translate.japanese_residue_check(list(result.values()))
    from amta.glossary import check_glossary
    violations = check_glossary(canon, result, ws)
    out = {"work_id": work_id or "", "translations": result, "residue": residue,
           "glossary_violations": violations}
    paths.write_json(out_path, out)

    # on-failure 结构化记录（ADR-016）：残留/术语违例/空译文 → failure_log.json 供断点重跑
    if state_dir:
        from pathlib import Path as _Path
        problems = [{"region_id": rid, "kind": "residue", "text": t}
                    for rid, t in result.items() if t in residue]
        problems += [{"region_id": rid, "kind": "glossary", "detail": v}
                     for rid, v in violations]
        if problems:
            translate.record_failure(_Path(state_dir) / "failure_log.json",
                                     {"work_id": work_id or "", "problems": problems})

    if trace_path and trace:
        paths.write_json(trace_path, {"work_id": work_id or "", "trace": trace})

    if work_id and state_dir:
        ex = translate.SuggestionsExtractor(existing=set(ws.get("characters", {})) | set(ws.get("terms", {})))
        sugg = ex.extract(canon, result)
        if sugg:
            sugg_path = Path(state_dir) / "suggestions.json"
            prev = json.loads(sugg_path.read_text(encoding="utf-8")) if sugg_path.exists() else {"work_id": work_id, "suggestions": []}
            prev.setdefault("suggestions", []).extend(sugg)
            paths.write_json(sugg_path, prev)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canon", required=True, help="canon_text.json 路径")
    ap.add_argument("--out", required=True, help="输出 translation.json 路径")
    ap.add_argument("--work-id", default=None)
    ap.add_argument("--state-dir", default=None)
    ap.add_argument("--trace", default=None, help="LLM/工具调用观测落盘路径(可选)")
    a = ap.parse_args()
    run(a.canon, a.out, work_id=a.work_id, state_dir=a.state_dir, trace_path=a.trace)
    print(f"[03_translate] -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
