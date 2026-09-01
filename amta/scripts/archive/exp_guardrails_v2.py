"""护栏方案 v2 实验 — 三态 VLM（keep/fix/drop）+ 规则过滤。

v1 的问题：VLM 只有"丢弃"权力，没有"修正"权力，导致 4 个 OCR 识别错误的框被误杀。
v2 改进：VLM 输出三态 — keep(保留) / fix(修正,给出正确文本) / drop(丢弃,无文本)。

用法: python scripts/exp_guardrails_v2.py
输出: output/data/guardrails_exp_v2/result_v2_tri-state.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))

import requests  # noqa: E402
from amta.chat_client import chat  # noqa: E402
from amta.config import get_chat_config, get_vlm_api_key, get_dashscope_key  # noqa: E402

RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
RESULTS_JSON = ROOT / "output" / "data" / "detect_full" / "results.json"
OUT_DIR = ROOT / "output" / "data" / "guardrails_exp_v2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_PAGES = [0, 1, 2, 5, 6, 11, 12, 14, 18, 32]

# === API 配置 ===
_chat_cfg = get_chat_config()
LM_BASE = _chat_cfg["base_url"]
LM_MODEL = _chat_cfg["model"]
LM_KEY = _chat_cfg["api_key"]

VLM_BASE = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
VLM_MODEL = os.environ.get("VISION_MODEL", "qwen3.5-omni-plus")
VLM_KEY = get_dashscope_key()

# === 规则过滤（与 v1 相同）===
PUNCT_CHARS = set("．。・〜~…—-「」『』、！？!?　 \t\n.,;:!?\"'()[]{}<>/\\|@#$%^&*_+=`~")


def is_pure_punct(text: str) -> bool:
    if not text:
        return True
    return all(ch in PUNCT_CHARS or (not ch.isalnum() and not _is_cjk(ch)) for ch in text)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (0x3040 <= cp <= 0x30FF) or (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF)


def is_pure_number(text: str) -> bool:
    if not text:
        return False
    has_digit = any(ch.isdigit() for ch in text)
    has_cjk_or_alpha = any(_is_cjk(ch) or ch.isalpha() for ch in text)
    return has_digit and not has_cjk_or_alpha


def is_edge_box(bbox: list, img_w: int, img_h: int, margin: int = 8) -> bool:
    x1, y1, x2, y2 = bbox
    return (x1 <= margin) or (y1 <= margin) or (x2 >= img_w - margin) or (y2 >= img_h - margin)


def is_extreme_aspect(bbox: list, max_ratio: float = 8.0) -> bool:
    x1, y1, x2, y2 = bbox
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    return (w / h > max_ratio) or (h / w > max_ratio)


def rule_filter(blocks: list[dict], img_w: int, img_h: int) -> tuple[list[dict], list[dict]]:
    kept, removed = [], []
    for b in blocks:
        text = b.get("text", "")
        bbox = b.get("bbox", [0, 0, 0, 0])
        reason = None
        if is_pure_punct(text):
            reason = "pure_punct"
        elif is_pure_number(text):
            reason = "pure_number"
        elif is_extreme_aspect(bbox):
            reason = "extreme_aspect"
        elif is_edge_box(bbox, img_w, img_h):
            reason = "edge_box"
        if reason:
            b["filter_reason"] = reason
            removed.append(b)
        else:
            kept.append(b)
    return kept, removed


# === v2 三态 VLM ===
VLM_V2_SYSTEM = """You are a manga text validation and correction engine. Given a full manga page image and a list of OCR text regions with coordinates, classify each region into ONE of three categories:

1. "keep" — The OCR text is correct and the region contains real text. Keep as-is.
2. "fix" — The region DOES contain real text, but the OCR text is wrong/incomplete. Provide the corrected text.
3. "drop" — The region contains NO text (blank area, screentone, hatching, speed lines, illustration detail, page border, or binding edge). The OCR output is a hallucination.

Output STRICT JSON:
{
  "keep": ["r01", "r02", ...],
  "fix": {"r03": "corrected Japanese text here", ...},
  "drop": ["r04", "r05", ...],
  "reasons": {"r03": "OCR misread 蓬莱山 as 落菜", "r04": "blank background area", ...}
}

Rules:
- For "fix": you MUST provide the corrected Japanese text exactly as it appears on the page. Look carefully at the image region.
- For "drop": only mark drop if you are confident there is NO text in that region.
- For "keep": OCR is correct, no change needed.
- Every region_id must appear in exactly ONE of keep/fix/drop.
- Short text (SFX, onomatopoeia, single characters) is legitimate — do not drop just because it is short.
- Output ONLY valid JSON. No markdown, no explanation."""


def vlm_filter_v2(image_path: Path, blocks: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """三态 VLM 筛选，返回 (kept, fixed, dropped)。
    kept: OCR 正确，保留原文本
    fixed: OCR 错误，已修正文本
    dropped: 无文本，丢弃
    """
    if not blocks:
        return [], [], []
    if not VLM_KEY:
        print("  [vlm-v2] WARNING: no API key, all kept")
        return blocks, [], []

    img_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    img_url = f"data:image/jpeg;base64,{img_b64}"

    lines = ["OCR text regions (region_id: text [bbox]):"]
    for i, b in enumerate(blocks):
        rid = f"r{i:02d}"
        b["_rid"] = rid
        lines.append(f"{rid}: {b.get('text', '')[:80]} [bbox: {[round(v) for v in b['bbox']]}]")
    user_prompt = "\n".join(lines)

    messages = [
        {"role": "system", "content": VLM_V2_SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": img_url}},
        ]},
    ]

    t0 = time.perf_counter()
    try:
        resp = chat(VLM_BASE, VLM_MODEL, messages, api_key=VLM_KEY, timeout=120)
        raw = resp.get("content", "")
    except Exception as e:
        print(f"  [vlm-v2] ERROR: {e}, all kept")
        return blocks, [], []
    elapsed = time.perf_counter() - t0

    parsed = _parse_json_safe(raw)
    if not parsed:
        print(f"  [vlm-v2] WARNING: JSON parse failed, all kept. raw[:200]={raw[:200]}")
        return blocks, [], []

    keep_ids = set(parsed.get("keep", []))
    fix_dict = parsed.get("fix", {})
    drop_ids = set(parsed.get("drop", []))
    reasons = parsed.get("reasons", {})

    kept, fixed, dropped = [], [], []
    for b in blocks:
        rid = b.get("_rid", "")
        if rid in drop_ids:
            b["filter_reason"] = f"vlm-drop:{reasons.get(rid, 'no text')}"
            dropped.append(b)
        elif rid in fix_dict:
            original = b.get("text", "")
            corrected = fix_dict[rid]
            b["original_text"] = original
            b["text"] = corrected
            b["filter_reason"] = f"vlm-fix:{reasons.get(rid, 'OCR corrected')}"
            fixed.append(b)
        else:  # keep_ids 或未分类（默认保留）
            kept.append(b)

    print(f"  [vlm-v2] {elapsed:.1f}s, keep={len(kept)}, fix={len(fixed)}, drop={len(dropped)}")
    if fixed:
        for b in fixed:
            print(f"    FIX: \"{b.get('original_text','')[:40]}\" -> \"{b.get('text','')[:40]}\"")
    return kept, fixed, dropped


def _parse_json_safe(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


# === LM 翻译（与 v1 相同）===
LM_SYSTEM = """You are a professional manga translator. Translate Japanese manga text to natural, fluent Simplified Chinese. Keep the tone appropriate for the context. Output STRICT JSON mapping input keys to translations:
{"r01": "翻译", "r02": "翻译", ...}
Output ONLY valid JSON. No markdown, no explanation."""


def lm_translate(blocks: list[dict]) -> list[dict]:
    if not blocks:
        return blocks
    if not LM_KEY:
        print("  [lm] WARNING: no API key, skipping")
        for b in blocks:
            b["translation"] = ""
        return blocks

    items = {}
    for i, b in enumerate(blocks):
        rid = b.get("_rid", f"r{i:02d}")
        items[rid] = b.get("text", "")

    user_prompt = "Text to translate (Japanese -> Simplified Chinese):\n" + json.dumps(items, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": LM_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    t0 = time.perf_counter()
    try:
        resp = chat(LM_BASE, LM_MODEL, messages, api_key=LM_KEY, timeout=120)
        raw = resp.get("content", "")
    except Exception as e:
        print(f"  [lm] ERROR: {e}")
        for b in blocks:
            b["translation"] = ""
        return blocks
    elapsed = time.perf_counter() - t0

    parsed = _parse_json_safe(raw)
    for i, b in enumerate(blocks):
        rid = b.get("_rid", f"r{i:02d}")
        b["translation"] = parsed.get(rid, "") if parsed else ""
    print(f"  [lm] {elapsed:.1f}s, translated {len(blocks)} blocks")
    return blocks


# === 主流程 ===
def run_experiment():
    print(f"=== Guardrails v2 Experiment — 三态 VLM (keep/fix/drop) ===")
    print(f"Sample pages: {SAMPLE_PAGES}")
    print(f"VLM: {VLM_MODEL} @ {VLM_BASE}")
    print(f"LM:  {LM_MODEL} @ {LM_BASE}\n")

    with open(RESULTS_JSON, "r", encoding="utf-8") as f:
        full_data = json.load(f)

    page_map = {p["page"]: p for p in full_data["per_page"] if "error" not in p}
    all_results = []
    total_original = total_rule_removed = 0
    total_vlm_keep = total_vlm_fix = total_vlm_drop = 0
    total_final = 0

    for page_num in SAMPLE_PAGES:
        if page_num not in page_map:
            print(f"page_{page_num:02d}: NOT FOUND, skip")
            continue
        pdata = page_map[page_num]
        img_w, img_h = pdata["image_size"]
        raw_path = RAW_DIR / f"{page_num}.jpg"
        if not raw_path.exists():
            print(f"page_{page_num:02d}: raw image not found, skip")
            continue

        blocks = []
        for i, r in enumerate(pdata.get("ocr_results", [])):
            blocks.append({"bbox": r["bbox"], "text": r["text"], "_idx": i})

        print(f"page_{page_num:02d}: {len(blocks)} blocks, {img_w}x{img_h}")
        total_original += len(blocks)

        # Step 1: 规则过滤
        kept, rule_removed = rule_filter(blocks, img_w, img_h)
        total_rule_removed += len(rule_removed)
        print(f"  rule: kept {len(kept)}, removed {len(rule_removed)} "
              f"({[b['filter_reason'] for b in rule_removed]})")

        # Step 2: 三态 VLM
        vlm_kept, vlm_fixed, vlm_dropped = vlm_filter_v2(raw_path, kept)
        total_vlm_keep += len(vlm_kept)
        total_vlm_fix += len(vlm_fixed)
        total_vlm_drop += len(vlm_dropped)

        # 合并 keep + fix（都送翻译，fix 已修正文本）
        final_blocks = vlm_kept + vlm_fixed

        # Step 3: LM 翻译
        final_blocks = lm_translate(final_blocks)
        total_final += len(final_blocks)

        # 记录结果
        all_results.append({
            "page": page_num,
            "image_size": [img_w, img_h],
            "original_count": len(blocks),
            "rule_removed": [{"text": b["text"][:60], "reason": b["filter_reason"]} for b in rule_removed],
            "vlm_keep": len(vlm_kept),
            "vlm_fixed": [{"original": b.get("original_text", "")[:60], "corrected": b["text"][:60], "reason": b["filter_reason"]} for b in vlm_fixed],
            "vlm_dropped": [{"text": b["text"][:60], "reason": b["filter_reason"]} for b in vlm_dropped],
            "final_blocks": [
                {"bbox": b["bbox"], "text": b["text"][:80], "original_text": b.get("original_text", ""), "translation": b.get("translation", "")[:80], "vlm_state": "fixed" if "original_text" in b else "keep"}
                for b in final_blocks
            ],
            "final_count": len(final_blocks),
        })

    # 汇总
    summary = {
        "version": "v2-tri-state",
        "sample_pages": SAMPLE_PAGES,
        "vlm_model": VLM_MODEL,
        "lm_model": LM_MODEL,
        "total_original": total_original,
        "total_rule_removed": total_rule_removed,
        "total_vlm_keep": total_vlm_keep,
        "total_vlm_fix": total_vlm_fix,
        "total_vlm_drop": total_vlm_drop,
        "total_final": total_final,
        "rule_removal_rate": round(total_rule_removed / max(1, total_original), 3),
        "vlm_drop_rate": round(total_vlm_drop / max(1, total_original - total_rule_removed), 3),
        "vlm_fix_rate": round(total_vlm_fix / max(1, total_original - total_rule_removed), 3),
        "overall_removal_rate": round((total_rule_removed + total_vlm_drop) / max(1, total_original), 3),
        "per_page": all_results,
    }

    out_path = OUT_DIR / "result_v2_tri-state.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"=== v2 SUMMARY (三态 VLM) ===")
    print(f"  Original:            {total_original}")
    print(f"  Rule removed:        {total_rule_removed} ({summary['rule_removal_rate']:.1%})")
    print(f"  VLM keep:            {total_vlm_keep}")
    print(f"  VLM fix:             {total_vlm_fix} ({summary['vlm_fix_rate']:.1%} of rule-kept)")
    print(f"  VLM drop:            {total_vlm_drop} ({summary['vlm_drop_rate']:.1%} of rule-kept)")
    print(f"  Final translated:    {total_final}")
    print(f"  Overall removal:     {summary['overall_removal_rate']:.1%}")
    print(f"  -> {out_path}")
    return summary


if __name__ == "__main__":
    run_experiment()
