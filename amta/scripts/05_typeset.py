"""05_typeset 工位 CLI — clean 图 + canon + translation + detection → final.png（薄包装）。

实现已移至 src/amta/typeset_station.py，本脚本只保留 CLI 入口。
用法: python scripts/05_typeset.py --work-id <id> --canon <canon.json> --trans <translation.json>
      --det <detection.json> --clean <clean.png> --out <page>_typeset.json --final <final.png>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.typeset_station import run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="05_typeset 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--canon", required=True, type=Path)
    ap.add_argument("--trans", required=True, type=Path)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--clean", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--final", required=True, type=Path)
    a = ap.parse_args()
    doc = run(a.work_id, a.canon, a.trans, a.det, a.clean, a.out, a.final)
    print(f"[05_typeset] {doc['page']}: rendered={doc['checks']['rendered']} "
          f"coverage={doc['checks']['coverage_complete']} "
          f"overflow={len(doc['checks']['overflow'])} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
