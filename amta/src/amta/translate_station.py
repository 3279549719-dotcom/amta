"""Stage 3 翻译工位 — canon → TranslationArtifact（深模块，修 F8 宽接口 / F5 内联）。

藏匿：chat config、llm 闭包+观测 trace、plan 双模式（text/vision）、
translate_with_retry / translate_with_plan、残留+术语护栏、failure log
（ADR-016）、suggestions 提取+追加（amta.suggestions）。接缝：llm 函数注入
（与既有测试同款 fake 模式）。脚本 03_translate.py 只剩 CLI。
"""
from __future__ import annotations

from pathlib import Path

from amta import artifacts, paths, suggestions, workstate
from amta.canon_schema import validate_canon
from amta.glossary import check_glossary
from amta.stage3_planner import run_plan_loop, translate_with_plan, validate_plan
from amta import translate

try:
    from amta.stage3_planner_vision import run_plan_loop_vision
except ImportError:  # pragma: no cover
    run_plan_loop_vision = None


def _load_open_questions(state_dir: Path | None) -> list[dict] | None:
    if not state_dir:
        return None
    p = Path(state_dir) / "open_questions.json"
    if not p.exists():
        return None
    return paths.read_json(p).get("questions", [])


def translate_page(work_id: str, canon, *, state_dir: Path | str | None = None,
                   page: str | None = None, with_plan: bool = False,
                   with_vision_plan: bool = False, trace_enabled: bool = False,
                   crop_dir: Path | str | None = None, llm=None) -> dict:
    """一页 canon → 翻译产物（含护栏/失败记录/suggestions）。返回信封 doc。"""
    if isinstance(canon, dict):  # 接受 CanonArtifact 或裸 items list
        canon = canon.get("items", [])
    problems = validate_canon(canon)
    if problems:
        raise ValueError(f"canon input schema failed: {'; '.join(problems[:5])}")

    cfg = translate.get_chat_config()
    ws = workstate.load_state(work_id) if work_id else {}
    open_questions = _load_open_questions(Path(state_dir) if state_dir else None)
    vlm_api_key = cfg.get("api_key")
    trace: list[dict] = []

    if llm is None:
        def _default_llm(messages, tools=None):  # 默认闭包（生产路径）
            resp = translate.chat_with_tools(cfg["base_url"], cfg["model"], messages,
                                             tools=tools, api_key=cfg["api_key"])
            if trace_enabled:
                trace.append({
                    "roles": [m["role"] for m in messages],
                    "tool_calls": [{"name": c.get("function", {}).get("name"),
                                    "args": c.get("function", {}).get("arguments")}
                                   for c in (resp.get("tool_calls") or [])],
                    "content": (resp.get("content") or "")[:200],
                })
            return resp
        llm = _default_llm

    plan = None
    if with_vision_plan and run_plan_loop_vision is not None:
        page_num = canon[0].get("page") if canon else None
        plan = run_plan_loop_vision(canon, None, page=page_num)
    elif with_plan:
        plan = run_plan_loop(canon, llm)
        plan_errors = validate_plan(plan, canon)
        if plan_errors:
            print(f"[03_translate][plan] 护栏警告: {'; '.join(plan_errors[:3])}")

    if plan is not None:
        result = translate_with_plan(canon, llm, plan=plan, work_state=ws,
                                     open_questions=open_questions,
                                     tools=translate.TOOLS_SCHEMA, state_dir=state_dir)
    else:
        result = translate.translate_with_retry(
            canon, llm, work_state=ws, open_questions=open_questions,
            tools=translate.TOOLS_SCHEMA, state_dir=state_dir,
            crop_dir=crop_dir, vlm_api_key=vlm_api_key)

    residue = translate.japanese_residue_check(list(result.values()))
    violations = check_glossary(canon, result, ws)
    env_page = page or (artifacts.page_key(canon[0]["page"]) if canon else "")
    out = artifacts.stamp({"translations": result, "residue": residue,
                           "glossary_violations": violations}, work_id or "", env_page)

    if state_dir:  # on-failure 结构化记录（ADR-016），原 03 内联段收编
        failure_problems = [{"region_id": rid, "kind": "residue", "text": t}
                            for rid, t in result.items() if t in residue]
        failure_problems += [{"region_id": rid, "kind": "glossary", "detail": v}
                             for rid, v in violations]
        if failure_problems:
            translate.record_failure(Path(state_dir) / "failure_log.json",
                                     {"work_id": work_id or "", "problems": failure_problems})

    if work_id and state_dir:  # suggestions 提取+追加（原 03 内联段收编，修 F5）
        ex = suggestions.SuggestionsExtractor(
            existing=set(ws.get("characters", {})) | set(ws.get("terms", {})))
        sugg = ex.extract(canon, result)
        if sugg:
            suggestions.append_suggestions(Path(state_dir), work_id, sugg)

    if trace_enabled and trace:
        out["_trace"] = trace  # 观测随返回值走，CLI 负责落盘（--trace 语义保留）
    return out
