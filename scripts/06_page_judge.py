"""06_page_judge — 单页 AI 质量判断 CLI（Stage 1 半自主循环）。

用法:
  python scripts/06_page_judge.py \
      --canon artifacts/page_10_canon.json \
      --trans artifacts/page_10_translation.json \
      --sem   artifacts/page_10_semantic.json \
      --out   artifacts/page_10_judge.json

读 .env CHAT_* 配置（与 03_translate 共用）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.page_judge import judge_page, save_decision  # noqa: E402
from amta.chat_config import get_chat_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="06_page_judge: AI 质量判断")
    ap.add_argument("--canon", required=True, type=Path)
    ap.add_argument("--trans", required=True, type=Path)
    ap.add_argument("--sem", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    cfg = get_chat_config()
    decision = judge_page(
        a.canon, a.trans, a.sem,
        base_url=cfg["base_url"], model=cfg["model"], api_key=cfg["api_key"],
    )
    save_decision(a.out, decision)

    n = len(decision["decisions"])
    print(f"[06_page_judge] {n} decisions → {a.out}")
    for d in decision["decisions"]:
        print(f"  - {d['tool']}: {d['args']}")
    if decision.get("summary"):
        print(f"  summary: {decision['summary'][:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
