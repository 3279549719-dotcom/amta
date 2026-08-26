"""merge_suggestions — suggestions.json → work_state 合并。

跨页一致（同一 term ≥2 页且译名一致）→ confirmed 自动升；否则保持 candidate。
导演可随后手工改 work_state.status 降级（新证据可修正旧状态，ADR-016）。
写回 work_state.json。
用法: python scripts/merge_suggestions.py --work-id ID [--suggestions PATH]
"""
from __future__ import annotations
import argparse
import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta import paths, workstate  # noqa: E402


def merge(state: dict, suggestions: list[dict]) -> dict:
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
