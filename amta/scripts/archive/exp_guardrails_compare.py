"""护栏方案对比实验：规则过滤 vs 规则过滤+VLM筛选。

用法:
  python scripts/exp_guardrails_compare.py --mode vlm-filter
  python scripts/exp_guardrails_compare.py --mode rule-only

流程:
  1. 从 detect_full/results.json 加载 10 页样本的检测框 + OCR 文本
  2. 规则过滤（mechanical guard rails）：纯标点、纯数字、贴页边、极端宽高比
  3. [vlm-filter 模式] VLM 全页筛选：标记 invalid 框（排线被识别成文字等）
  4. LM 翻译（DeepSeek Flash）
  5. 输出对比报告

样本页: [0, 1, 2, 5, 6, 11, 12, 14, 18, 32]
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
OUT_DIR = ROOT / "output" / "data" / "guardrails_exp"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_PAGES = [0, 1, 2, 5, 6, 11, 12, 14, 18, 32]

# === API 配置（从项目 config 读取）===
_chat_cfg = get_chat_config()
LM_BASE = _chat_cfg["base_url"]       # https://api.deepseek.com
LM_MODEL = _chat_cfg["model"]          # deepseek-v4-flash
LM_KEY = _chat_cfg["api_key"]

VLM_BASE = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
VLM_MODEL = os.environ.get("VISION_MODEL", "qwen3.5-omni-plus")
VLM_KEY = get_dashscope_key()

# === 规则过滤 ===
PUNCT_CHARS = set("．。・〜~…—-「」『』、！？!?　 \t\n.,;:!?\"'()[]{}<>/\\|@#$%^&*_+=`~")


def is_pure_punct(text: str) -> bool:
    """纯标点（含全角半角），没有任何字母/数字/假名/汉字。"""
    if not text:
        return True
    return all(ch in PUNCT_CHARS or not ch.isalnum() and not _is_cjk(ch) for ch in text)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (0x3040 <= cp <= 0x30FF) or (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF)


def is_pure_number(text: str) -> bool:
    """纯数字（页码等），没有假名/汉字/字母。"""
    if not text:
        return False
    has_digit = any(ch.isdigit() for ch in text)
    has_cjk_or_alpha = any(_is_cjk(ch) or ch.isalpha() for ch in text)
    return has_digit and not has_cjk_or_alpha


def is_edge_box(bbox: list, img_w: int, img_h: int, margin: int = 8) -> bool:
    """贴页边的框（大概率误报）。"""
    x1, y1, x2, y2 = bbox
    return (x1 <= margin) or (y1 <= margin) or (x2 >= img_w - margin) or (y2 >= img_h - margin)


def is_extreme_aspect(bbox: list, max_ratio: float = 8.0) -> bool:
    """极端宽高比（扁条或竖条，大概率是排线/分割线）。"""
    x1, y1, x2, y2 = bbox
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    return (w / h > max_ratio) or (h / w > max_ratio)


def rule_filter(blocks: list[dict], img_w: int, img_h: int) -> tuple[list[dict], list[dict]]:
    """规则过滤，返回 (kept, removed)。"""
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


# === VLM 筛选 ===
VLM_SYSTEM = """You are a manga text validation engine. Given a full manga page image and a list of OCR text regions with coordinates, determine which regions contain REAL text that exists on the page, and which are NOISE (patterns, lines, decorations, screentone, or blank areas that OCR misrecognized as text).

Output STRICT JSON:
{
  "invalid_regions": ["r01", "r03", ...],
  "invalid_reasons": {"r01": "screentone pattern misread as text", ...}
}

Rules:
- ONLY mark a region invalid if you are CONFIDENT the text does NOT exist on the page at that location.
- Do NOT mark short text as invalid just because it is short — SFX, onomatopoeia, and single characters are legitimate manga text.
- Do NOT mark text as invalid if you can see any characters in that region, even if OCR got some wrong.
- Mark regions invalid when: the area is clearly blank, a screentone/hatching pattern, a speed line, a border/decoration, or an illustration detail with no text.
- Output ONLY valid JSON. No markdown, no explanation."""


def vlm_filter(image_path: Path, blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    """VLM 全页筛选，返回 (kept, removed)。"""
    if not blocks:
        return [], []
    if not VLM_KEY:
        print("  [vlm] WARNING: no API key, skipping VLM filter (all kept)")
        return blocks, []

    img_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    img_url = f"data:image/jpeg;base64,{img_b64}"

    lines = ["OCR text regions (region_id: text [bbox]):"]
    for i, b in enumerate(blocks):
        rid = f"r{i:02d}"
        b["_rid"] = rid
        lines.append(f"{rid}: {b.get('text', '')[:80]} [bbox: {[round(v) for v in b['bbox']]}]")
    user_prompt = "\n".join(lines)

    messages = [
        {"role": "system", "content": VLM_SYSTEM},
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
        print(f"  [vlm] ERROR: {e}, all kept")
        return blocks, []
    elapsed = time.perf_counter() - t0

    parsed = _parse_json_safe(raw)
    invalid_ids = set(parsed.get("invalid_regions", [])) if parsed else set()
    invalid_reasons = parsed.get("invalid_reasons", {}) if parsed else {}

    kept, removed = [], []
    for b in blocks:
        if b.get("_rid") in invalid_ids:
            b["filter_reason"] = f"vlm:{invalid_reasons.get(b['_rid'], 'invalid')}"
            removed.append(b)
        else:
            kept.append(b)
    print(f"  [vlm] {elapsed:.1f}s, kept {len(kept)}/{len(blocks)}, removed {len(removed)}")
    return kept, removed


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


# === LM 翻译 ===
LM_SYSTEM = """You are a professional manga translator. Translate Japanese manga text to natural, fluent Simplified Chinese. Keep the tone appropriate for the context (casual dialogue, formal narration, SFX, etc.). Output STRICT JSON mapping input keys to translations:
{"r01": "翻译", "r02": "翻译", ...}
Rules:
- Translate ALL provided text blocks.
- For SFX/onomatopoeia, use Chinese onomatopoeia or keep the original if no good equivalent.
- Output ONLY valid JSON. No markdown, no explanation."""


def lm_translate(blocks: list[dict]) -> list[dict]:
    """LM 批量翻译。"""
    if not blocks:
        return blocks
    if not LM_KEY:
        print("  [lm] WARNING: no API key, skipping translation")
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
def run_experiment(mode: str):
    print(f"=== Guardrails Experiment — mode={mode} ===")
    print(f"Sample pages: {SAMPLE_PAGES}")
    print(f"VLM: {VLM_MODEL} @ {VLM_BASE}")
    print(f"LM:  {LM_MODEL} @ {LM_BASE}")
    print(f"VLM key: {'set' if VLM_KEY else 'NOT SET'}, LM key: {'set' if LM_KEY else 'NOT SET'}\n")

    with open(RESULTS_JSON, "r", encoding="utf-8") as f:
        full_data = json.load(f)

    page_map = {p["page"]: p for p in full_data["per_page"] if "error" not in p}
    all_results = []
    total_original = total_rule_removed = total_vlm_removed = total_final = 0

    for page_num in SAMPLE_PAGES:
        if page_num not in page_map:
            print(f"page_{page_num:02d}: NOT FOUND in results, skip")
            continue
        pdata = page_map[page_num]
        img_w, img_h = pdata["image_size"]
        raw_path = RAW_DIR / f"{page_num}.jpg"
        if not raw_path.exists():
            print(f"page_{page_num:02d}: raw image not found, skip")
            continue

        # 构建 block 列表
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

        # Step 2: VLM 筛选（仅 vlm-filter 模式）
        vlm_removed = []
        if mode == "vlm-filter" and kept:
            kept, vlm_removed = vlm_filter(raw_path, kept)
            total_vlm_removed += len(vlm_removed)

        # Step 3: LM 翻译
        kept = lm_translate(kept)
        total_final += len(kept)

        # 记录结果
        all_results.append({
            "page": page_num,
            "image_size": [img_w, img_h],
            "original_count": len(blocks),
            "rule_removed": [{"text": b["text"][:60], "reason": b["filter_reason"]} for b in rule_removed],
            "vlm_removed": [{"text": b["text"][:60], "reason": b["filter_reason"]} for b in vlm_removed],
            "final_blocks": [
                {"bbox": b["bbox"], "text": b["text"][:80], "translation": b.get("translation", "")[:80]}
                for b in kept
            ],
            "final_count": len(kept),
        })

    # 汇总
    summary = {
        "mode": mode,
        "sample_pages": SAMPLE_PAGES,
        "vlm_model": VLM_MODEL,
        "lm_model": LM_MODEL,
        "total_original": total_original,
        "total_rule_removed": total_rule_removed,
        "total_vlm_removed": total_vlm_removed,
        "total_final": total_final,
        "rule_removal_rate": round(total_rule_removed / max(1, total_original), 3),
        "vlm_removal_rate": round(total_vlm_removed / max(1, total_original - total_rule_removed), 3),
        "overall_removal_rate": round((total_rule_removed + total_vlm_removed) / max(1, total_original), 3),
        "per_page": all_results,
    }

    out_path = OUT_DIR / f"result_{mode}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"=== SUMMARY (mode={mode}) ===")
    print(f"  Original blocks:     {total_original}")
    print(f"  Rule removed:        {total_rule_removed} ({summary['rule_removal_rate']:.1%})")
    print(f"  VLM removed:         {total_vlm_removed} ({summary['vlm_removal_rate']:.1%})")
    print(f"  Final translated:    {total_final}")
    print(f"  Overall removal:     {summary['overall_removal_rate']:.1%}")
    print(f"  -> {out_path}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["vlm-filter", "rule-only"], required=True)
    args = ap.parse_args()
    run_experiment(args.mode)


if __name__ == "__main__":
    main()
