"""Revise flagged translations through a strict, page-independent review contract."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from amta.common.config import get_chat_config
from amta.common.paths import read_json, write_json
from amta.stores.artifacts import artifact_paths
from amta.translation.translate import text_chat

SYSTEM = """你是日中漫画副文本审校员。根据日文源文、当前中文和视觉审校意见修订中文。
审校意见可能包含不适合中文本地化的建议；只修正有源文证据、能让中文更准确自然的问题。
专名、社团名可保留日文；中文通常省略日语敬称。保留日期、邮箱、账号和有意义的换行。
不要改动未列出的区域。输出严格 JSON：{"revisions":{"r00":"修订译文"}}，键集合必须完全一致。"""


def parse_revisions(raw: str, expected: set[str]) -> dict[str, str]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(text)
    revisions = data.get("revisions") if isinstance(data, dict) else None
    if not isinstance(revisions, dict) or set(revisions) != expected:
        raise ValueError("revision coverage mismatch")
    result = {str(k): str(v).strip() for k, v in revisions.items()}
    if any(not value for value in result.values()):
        raise ValueError("empty revision")
    return result


def revise(work_id: str, page: int) -> dict:
    art = ROOT / "workspace" / work_id / "artifacts"
    paths = artifact_paths(art, f"page_{page}")
    canon = read_json(paths["canon"])
    translation = read_json(paths["translation"])
    review = read_json(art / "review" / f"page_{page}.json")
    issues = [issue for issue in review.get("issues", []) if issue.get("kind") == "translation"]
    region_ids = {str(issue["region_id"]) for issue in issues}
    if not region_ids:
        return translation
    source = {item["region_id"]: item.get("text") or item.get("baberu_text", "")
              for item in canon["items"] if item["region_id"] in region_ids}
    current = {rid: translation["translations"][rid] for rid in region_ids}
    payload = {"source": source, "current": current, "review_issues": issues}
    cfg = get_chat_config()
    raw = text_chat(cfg["base_url"], cfg["model"], [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], api_key=cfg["api_key"], timeout=240, temperature=0.1,
        response_format={"type": "json_object"})
    revisions = parse_revisions(raw, region_ids)
    translation["translations"].update(revisions)
    translation.setdefault("review_revisions", []).append({"issues": issues, "revisions": revisions})
    write_json(paths["translation"], translation)
    return translation


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--pages", required=True)
    args = ap.parse_args()
    for page in map(int, args.pages.split(",")):
        result = revise(args.work_id, page)
        print(page, json.dumps(result.get("review_revisions", [])[-1:], ensure_ascii=False), flush=True)
