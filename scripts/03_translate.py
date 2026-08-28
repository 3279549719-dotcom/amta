"""03_translate 工位 — 读 canon_text.json → DeepSeek 翻译 → translation.json + suggestions.json。

用法: python scripts/03_translate.py --canon <canon_text.json> --out <translation.json> [--work-id ID] [--state-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta import paths, translate  # noqa: E402
from amta.canon_schema import validate_canon  # noqa: E402
from amta.glossary import check_glossary  # noqa: E402
from amta.workstate import load_state  # noqa: E402
from amta.stage3_planner import run_plan_loop, translate_with_plan, validate_plan  # noqa: E402
try:
    from amta.stage3_planner_vision import run_plan_loop_vision  # noqa: E402
except ImportError:
    run_plan_loop_vision = None


def _load_open_questions(state_dir: str | Path | None) -> list[dict] | None:
    """从 state/open_questions.json 读未决问题列表；无则 None。"""
    if not state_dir:
        return None
    p = Path(state_dir) / "open_questions.json"
    if not p.exists():
        return None
    doc = paths.read_json(p)
    return doc.get("questions", [])


def run(canon_path: str | Path, out_path: str | Path, *,
        work_id: str | None = None, state_dir: str | Path | None = None,
        trace_path: str | Path | None = None,
        with_plan: bool = False, with_vision_plan: bool = False) -> dict:
    canon = paths.read_json(canon_path)
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

    # 规划阶段（可选）：翻译前让 LLM 扫描全页，标记 invalid/duplicate 框
    plan = None
    plan_elapsed = 0.0
    if with_vision_plan and run_plan_loop_vision is not None:
        page_num = canon[0].get('page') if canon else None
        t_plan_start = time.time()
        plan = run_plan_loop_vision(canon, None, page=page_num)  # vision规划用DashScope VLM，翻译仍用DeepSeek
    elif with_plan:
        t_plan_start = time.time()
        plan = run_plan_loop(canon, llm)
        plan_elapsed = time.time() - t_plan_start
        plan_errors = validate_plan(plan, canon)
        if plan_errors:
            print(f"[03_translate][plan] 护栏警告: {'; '.join(plan_errors[:3])}")

    # 真 function calling：模型按需调 lookup_term / get_context（Patrick 裁决，2026-08-26）
    t_translate_start = time.time()
    if (with_plan or with_vision_plan) and plan is not None:
        result = translate_with_plan(canon, llm, plan=plan, work_state=ws,
                                     open_questions=open_questions,
                                     tools=translate.TOOLS_SCHEMA, state_dir=state_dir)
    else:
        result = translate.translate_with_retry(canon, llm, work_state=ws, open_questions=open_questions,
                                                tools=translate.TOOLS_SCHEMA, state_dir=state_dir)
    translate_elapsed = time.time() - t_translate_start

    # Front3 Stage 3 trace: 每区域双引擎文本 + 最终译文，供后续分析 LLM 选择了哪个引擎
    page_name = canon[0].get("page", "unknown") if canon else "unknown"
    stage3_trace = {
        "page": str(page_name),
        "model": cfg.get("model", ""),
        "n_regions": len(canon),
        "translate_elapsed": round(translate_elapsed, 2),
        "regions": [
            {
                "region_id": r.get("region_id"),
                "baberu_text": r.get("baberu_text"),
                "vlm_text": r.get("vlm_text"),
                "vlm_status": r.get("vlm_status"),
                "contained_in": r.get("contained_in"),
                "translation": result.get(r.get("region_id", ""), ""),
                "plan_status": (
                    "invalid" if plan and r.get("region_id") in plan.invalids
                    else f"duplicate_of:{plan.duplicates[r.get('region_id')]}" if plan and r.get("region_id") in plan.duplicates
                    else "valid"
                ),
            }
            for r in canon
        ],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if (with_plan or with_vision_plan) and plan is not None:
        stage3_trace["plan"] = {
            "elapsed": round(plan_elapsed, 2),
            "n_invalid": len(plan.invalids),
            "n_duplicate": len(plan.duplicates),
            "n_valid": len(plan.valid_regions),
            "invalids": plan.invalids,
            "duplicates": plan.duplicates,
        }
    stage3_trace_path = Path(out_path).parent / f"{page_name}_03_translate_trace.json"
    paths.write_json(stage3_trace_path, stage3_trace)

    residue = translate.japanese_residue_check(list(result.values()))
    violations = check_glossary(canon, result, ws)
    out = {"work_id": work_id or "", "translations": result, "residue": residue,
           "glossary_violations": violations}
    paths.write_json(out_path, out)

    # on-failure 结构化记录（ADR-016）：残留/术语违例/空译文 → failure_log.json 供断点重跑
    if state_dir:
        problems = [{"region_id": rid, "kind": "residue", "text": t}
                    for rid, t in result.items() if t in residue]
        problems += [{"region_id": rid, "kind": "glossary", "detail": v}
                     for rid, v in violations]
        if problems:
            translate.record_failure(Path(state_dir) / "failure_log.json",
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
    ap.add_argument("--with-plan", action="store_true",
                    help="开启规划阶段：翻译前 LLM 扫描全页，自动标记 invalid/duplicate 框")
    ap.add_argument("--with-vision-plan", action="store_true",
                    help="翻译前跑VLM规划阶段，带整页图，标记 invalid/duplicate 框")
    a = ap.parse_args()
    run(a.canon, a.out, work_id=a.work_id, state_dir=a.state_dir, trace_path=a.trace,
        with_plan=a.with_plan, with_vision_plan=a.with_vision_plan)
    print(f"[03_translate] -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
