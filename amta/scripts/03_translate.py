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


def run(canon_path: str | Path, out_path: str | Path, *,
        work_id: str | None = None, state_dir: str | Path | None = None) -> dict:
    canon = paths.read_json(canon_path)
    cfg = translate.get_chat_config()
    ws = load_state(work_id) if work_id else {}

    def llm(messages):
        return translate.text_chat(cfg["base_url"], cfg["model"], messages, api_key=cfg["api_key"])

    result = translate.translate_with_retry(canon, llm)

    residue = translate.japanese_residue_check(list(result.values()))
    out = {"work_id": work_id or "", "translations": result, "residue": residue}
    paths.write_json(out_path, out)

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
    a = ap.parse_args()
    run(a.canon, a.out, work_id=a.work_id, state_dir=a.state_dir)
    print(f"[03_translate] -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
