"""repair_failed — 自动修复层（蓝图 Loop 的 DeepSeek 自修复环节，Patrick 裁决 2026-08-26）。

对 semantic_check 的 failed 列表逐条：
  1. 构造修复 prompt：原文 + 旧译文 + 评审意见(reason) + 请重译
  2. 调 DeepSeek（deepseek-v4-pro，可带 lookup_term/get_context 工具）重译
  3. 机械护栏（结构/残留/glossary）检查，不过则下一轮
  4. 通过 → 写 revisions（复用 apply_revisions 语义：写回 translation + 历史）→ --only 重评审
  5. 重评审未过 → 带新评审意见下一轮（max_rounds 上限，蓝图 bounded retry）
  6. 仍失败 → needs_review 落盘（导演终审队列；外部只碰这里，日常修复全自动）

用法:
  python scripts/repair_failed.py --canon canon.json --trans translation.json \
      --semantic semantic_check.json --crops crops_dir [--state-dir state_dir] \
      [--max-rounds 3] [--only r1,r2] [--out-review needs_review.json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta import translate  # noqa: E402

REPAIR_SYSTEM = (
    "你是专业日文→中文漫画翻译专家。以下是评审对你上次译文的意见，"
    "请根据意见重新翻译该句，输出严格 JSON：{{\"{rid}\": \"修正译文\"}}，"
    "不要输出任何额外文字。"
)


def build_repair_prompt(rid: str, source: str, old: str, reason: str) -> list[dict]:
    """构造修复消息：system（带输出格式约束）+ user（原文/旧译文/评审意见）。"""
    return [
        {"role": "system", "content": REPAIR_SYSTEM.format(rid=rid)},
        {"role": "user", "content": (
            f"原文(OCR): {source}\n"
            f"你上次的译文: {old}\n"
            f"评审意见: {reason}\n"
            f"请重新翻译「{rid}」。"
        )},
    ]


def repair_one(cfg: dict, rid: str, source: str, old: str, reason: str,
               *, work_state: dict, state_dir: Path | None, llm=None) -> str:
    """单条修复：调 DeepSeek（带工具）重译，返回修正译文；失败返回空串。"""
    messages = build_repair_prompt(rid, source, old, reason)
    if llm is None:
        def llm(msgs, tools=None):
            return translate.chat_with_tools(cfg["base_url"], cfg["model"], msgs,
                                             tools=tools, api_key=cfg["api_key"])
    budgets = {"lookup_term": 3, "get_context": 1}
    for _round in range(translate.MAX_TOOL_ROUNDS):
        resp = llm(messages, tools=translate.TOOLS_SCHEMA)
        if isinstance(resp, str):
            raw = resp
            break
        calls = resp.get("tool_calls") or []
        if not calls:
            raw = resp.get("content") or ""
            break
        messages.append({"role": "assistant", "content": resp.get("content") or None,
                         "tool_calls": calls})
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if budgets.get(name, 0) <= 0:
                result = f"工具「{name}」本次调用预算已耗尽，请基于现有信息继续翻译"
            else:
                budgets[name] -= 1
                result = translate.execute_tool(name, args, work_state, None, state_dir)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                             "content": result})
    else:
        raw = ""
    parsed = translate.parse_translation_response(raw, [rid])
    return parsed.get(rid, "")


def _rerun_judge(trans_path: Path, canon_path: Path, crops: Path, rid: str,
                 tmp_out: Path) -> str:
    """重评审单 region（--only），返回 verdict: pass/fail/inconclusive。"""
    cmd = [
        sys.executable, str(Path(__file__).resolve().parent / "translate_semantic_check.py"),
        "--canon", str(canon_path), "--trans", str(trans_path),
        "--crops", str(crops), "--out", str(tmp_out), "--only", rid,
    ]
    subprocess.run(cmd, check=False)
    if not tmp_out.exists():
        return "inconclusive"
    doc = json.loads(tmp_out.read_text(encoding="utf-8"))
    if doc.get("failed"):
        return "fail"
    return "pass"


def run(canon_path: Path, trans_path: Path, semantic_path: Path, crops: Path,
        *, state_dir: Path | None = None, max_rounds: int = 3,
        only: list[str] | None = None, out_review: Path | None = None) -> dict:
    """自动修复主流程。返回 {repaired: [...], needs_review: [...], rounds: {...}}"""
    cfg = translate.get_chat_config()
    canon = json.loads(canon_path.read_text(encoding="utf-8"))
    trans_doc = json.loads(trans_path.read_text(encoding="utf-8"))
    trans = trans_doc.setdefault("translations", {})
    sem = json.loads(semantic_path.read_text(encoding="utf-8"))
    failed = sem.get("failed", [])
    if only:
        only_set = set(only)
        failed = [f for f in failed if f["region_id"] in only_set]

    work_state = {}
    if state_dir is not None and (state_dir / "work_state.json").exists():
        work_state = json.loads((state_dir / "work_state.json").read_text(encoding="utf-8"))

    repaired: list[dict] = []
    needs_review: list[dict] = []
    rounds: dict[str, int] = {}

    for f in failed:
        rid = f["region_id"]
        source = f.get("source") or ""
        old = f.get("translation") or ""
        reason = f.get("reason") or "译文不合格，请重译"
        fixed = False
        for rnd in range(1, max_rounds + 1):
            rounds[rid] = rnd
            new = repair_one(cfg, rid, source, old, reason,
                             work_state=work_state, state_dir=state_dir)
            if not new or translate.japanese_residue_check([new]):
                reason = f"第{rnd}轮修复译文仍不合格（残留日文/空译文）：{new or '（空）'}"
                continue
            # 机械护栏（结构）
            canon_item = next((r for r in canon if r["region_id"] == rid), None)
            if canon_item is not None:
                from amta.glossary import check_glossary
                probs = translate.mechanical_guardrails([canon_item], {rid: new})
                probs += check_glossary([canon_item], {rid: new}, work_state)
                if probs:
                    reason = f"第{rnd}轮修复违反机械护栏：{'；'.join(probs[:2])}"
                    continue
            # 落盘修订
            trans[rid] = new
            trans_doc.setdefault("revisions", []).append({
                "region_id": rid, "revised": new, "reason": reason, "source": "auto-repair",
            })
            trans_path.write_text(json.dumps(trans_doc, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
            # 重评审
            tmp_out = trans_path.parent / f"_rerun_{rid}.json"
            verdict = _rerun_judge(trans_path, canon_path, crops, rid, tmp_out)
            tmp_out.unlink(missing_ok=True)
            if verdict == "pass":
                repaired.append({"region_id": rid, "revised": new, "rounds": rnd})
                fixed = True
                break
            reason = f"第{rnd}轮修复后重评审未过，请继续修正（最新评审意见见下）"
            old = new
        if not fixed:
            needs_review.append({
                "region_id": rid, "source": source,
                "translation": trans.get(rid, ""), "reason": reason, "rounds": max_rounds,
            })

    if out_review is not None:
        out_review.write_text(json.dumps({"needs_review": needs_review},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
    return {"repaired": repaired, "needs_review": needs_review, "rounds": rounds}


def main() -> int:
    ap = argparse.ArgumentParser(description="自动修复层：FAILED 带评审意见喂回 DeepSeek 重译")
    ap.add_argument("--canon", required=True, type=Path)
    ap.add_argument("--trans", required=True, type=Path)
    ap.add_argument("--semantic", required=True, type=Path)
    ap.add_argument("--crops", required=True, type=Path)
    ap.add_argument("--state-dir", type=Path, default=None)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--only", type=str, default=None)
    ap.add_argument("--out-review", type=Path, default=None)
    a = ap.parse_args()
    only = a.only.split(",") if a.only else None
    res = run(a.canon, a.trans, a.semantic, a.crops, state_dir=a.state_dir,
              max_rounds=a.max_rounds, only=only, out_review=a.out_review)
    print(f"[repair_failed] repaired={len(res['repaired'])} "
          f"needs_review={len(res['needs_review'])} rounds={res['rounds']}")
    for r in res["repaired"]:
        print("  REPAIRED:", r["region_id"], f"(round {r['rounds']}) ->", r["revised"][:40])
    for r in res["needs_review"]:
        print("  REVIEW:", r["region_id"], "|", (r.get("reason") or "")[:70])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
