"""apply_revisions — 导演语义 loop 的修订落盘（ADR-016）。

读 translation.json + revisions 列表（region_id/revised/reason/source），
应用修订写回 translations，revisions 存档到 translation.json.revisions 字段。
用法: python scripts/apply_revisions.py --trans translation.json --revisions revs.json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.artifacts import load_translation  # noqa: E402


def apply(trans: dict[str, str], revisions: list[dict]) -> tuple[dict, dict]:
    log: dict[str, str] = {}
    for r in revisions:
        rid = r.get("region_id")
        if rid not in trans:
            continue
        if "revised" in r and r["revised"]:
            log[rid] = trans[rid]
            trans[rid] = r["revised"].strip()
    return trans, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trans", type=Path, required=True)
    ap.add_argument("--revisions", type=Path, required=True)
    a = ap.parse_args()
    doc = load_translation(a.trans)  # 契约层读取
    revs = json.loads(a.revisions.read_text(encoding="utf-8"))
    trans = doc.setdefault("translations", {})
    _, log = apply(trans, revs)
    doc["revisions"] = doc.get("revisions", []) + revs
    a.trans.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[apply_revisions] applied {len(log)} revisions -> {a.trans}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
