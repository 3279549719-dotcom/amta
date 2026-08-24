"""评测聚合工具 — 统一 CER/EM 逐行计算与按类型汇总（ocr_eval / eval_86 / ocr_score 共用）。"""
from __future__ import annotations

import os
from typing import Any

from amta.metrics import cer

TEXT_CLASSES = ["dialogue_in", "dialogue_out", "sfx", "bg_text"]


def basename_key(path) -> str:
    """crop 匹配键：只取 basename，容忍相对/绝对路径差异。"""
    return os.path.basename(str(path))


def eval_rows(meta: list[dict], preds: list[dict]) -> tuple[list[dict], dict]:
    """meta: [{crop, content, type, ...}]; preds: [{crop, ocr}] → (rows, summary)。

    rows 每条含 crop/type/gt/pred/cer/em；summary 按 TEXT_CLASSES + ALL 聚合。
    """
    by_crop = {basename_key(p["crop"]): (p.get("ocr") or "") for p in preds}
    rows = []
    for m in meta:
        pred = by_crop.get(basename_key(m["crop"]), "")
        c = cer(m["content"], pred)
        rows.append({"crop": m["crop"], "type": m["type"], "gt": m["content"],
                     "pred": pred, "cer": c, "em": 1 if c == 0.0 else 0})
    return rows, summarize_rows(rows)


def summarize_rows(rows: list[dict], classes: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """按 type 聚合 CER/EM（n/cer/em），末尾追加 ALL。"""
    classes = classes or TEXT_CLASSES
    summary: dict[str, dict[str, Any]] = {}
    for t in classes + ["ALL"]:
        sub = rows if t == "ALL" else [r for r in rows if r["type"] == t]
        n = len(sub)
        summary[t] = {
            "n": n,
            "cer": round(sum(r["cer"] for r in sub) / n, 4) if n else 0.0,
            "em": round(sum(r["em"] for r in sub) / n, 4) if n else 0.0,
        }
    return summary
