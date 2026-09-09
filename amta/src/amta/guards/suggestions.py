"""suggestions 机制唯一归属（修 F5）：片假名术语提取 → 追加落盘 → 跨页合并。

- SuggestionsExtractor：ADR-016 收紧版（只提片假名专有名词段），自 translate.py 迁入
- append_suggestions：原 03_translate.py 内联读写合并段收编（4fc5037 曾因内联出冲突标记 bug）
- merge_into_state：scripts/merge_suggestions.py 的 merge 收编（≥2 页且译名一致 → confirmed）
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from amta.common.paths import write_json

# 片假名词段 = 专有名词/外来语特征最强（サグメ）；汉字人名难自动判别，留导演批（ADR-016）
_KATAKANA_TERM = re.compile(r"[\u30a0-\u30ff]{2,}")
# 过滤常见语法片假名（>=2 字仍会误抓），黑名单
_KATAKANA_STOP = {
    "カラ", "デス", "マス", "タリ", "シテ", "トモ", "ノニ", "コト",
    "トキ", "ヒト", "モノ", "コレ", "ソレ", "アレ", "コノ", "ソノ",
    "アイテ", "デモ", "ナノ", "ノデ", "トイウ", "トシテ",
}


class SuggestionsExtractor:
    """从译文里发现疑似新角色/专有名词 → suggestions（导演自动合并）。

    借鉴自 comic-translate 的 extra_context/术语演进设计 + ADR-014 suggestions 机制。
    ADR-016 收紧：只提片假名专有名词段，不整段日文，防污染 work_state 术语表。
    """

    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or set()

    def extract(self, canon: list[dict], translations: dict[str, str]) -> list[dict]:
        suggestions = []
        for r in canon:
            # Front3 双引擎格式（ADR-023）：text 缺失时回退 baberu_text
            text = r.get("text") or r.get("baberu_text") or ""
            for m in _KATAKANA_TERM.finditer(text):
                term = m.group(0)
                if term in self.existing or term in _KATAKANA_STOP:
                    continue
                suggestions.append({
                    "term": term,
                    "source": r.get("region_id", ""),
                    "page": r.get("page", 0),
                    "translation": translations.get(r["region_id"], ""),
                    "status": "candidate",
                })
        return suggestions


def append_suggestions(state_dir: Path, work_id: str, sugg: list[dict]) -> Path:
    """追加写入 state/suggestions.json（读-并-写整体在此，调用方不再手搓 JSON）。"""
    sugg_path = Path(state_dir) / "suggestions.json"
    prev = (json.loads(sugg_path.read_text(encoding="utf-8"))
            if sugg_path.exists() else {"work_id": work_id, "suggestions": []})
    prev.setdefault("suggestions", []).extend(sugg)
    return write_json(sugg_path, prev)


def merge_into_state(state: dict, suggestions: list[dict]) -> dict:
    """suggestions → work_state.terms 合并（原 merge_suggestions.merge 逐行搬入）。"""
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
